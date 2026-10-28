"""The Property aggregate: profile, legal steps, activation checklist and states (DOMAIN §5).

States: ONBOARDING → ACTIVE ⇄ INACTIVE, and any state → OFFBOARDED (final). A property becomes
ACTIVE only when its checklist is complete; the checklist items can be done in any order. While
it is ACTIVE its profile must stay complete, so the invariant keeps holding after activation; an
INACTIVE property may have gaps, and its checklist is checked again when it is reactivated.

The owner's bank account belongs to another aggregate (Owner), so `activate()` takes whether it
is verified as an argument; the handler reads it. Only this aggregate changes in that unit.
"""

from collections.abc import Iterable
from datetime import datetime, time
from enum import StrEnum
from typing import Self
from uuid import UUID

from kospm.properties.domain.checklist import ActivationRequirement, ProfileItem
from kospm.properties.domain.defaults import PropertyDefaults
from kospm.properties.domain.errors import (
    ChangeThroughTheIke,
    InvalidStatusTransition,
    InvalidValue,
    NoContractToSign,
    ProfileMustStayComplete,
    PropertyNotFound,
    PropertyNotReadyForActivation,
)
from kospm.properties.domain.events import (
    AmaAssigned,
    ContractOffered,
    ContractSigned,
    PropertyActivated,
    PropertyDeactivated,
    PropertyOffboarded,
    PropertyProfileCompleted,
    PropertyReactivated,
    SubleaseDeclared,
)
from kospm.properties.domain.value_objects import (
    Amenities,
    CheckInGuide,
    Contract,
    ContractDraft,
    GeoPoint,
    IcalFeed,
    PropertyCode,
)
from kospm.shared.domain import Aggregate


class PropertyStatus(StrEnum):
    ONBOARDING = "onboarding"  # Σε εξέλιξη
    ACTIVE = "active"  # Ενεργό
    INACTIVE = "inactive"  # Ανενεργό
    OFFBOARDED = "offboarded"  # Αποχώρησε (final)


class Property(Aggregate[UUID]):
    """A rentable unit managed by the IKE. Its code is fixed for life (guests quote it)."""

    def __init__(
        self,
        id: UUID,
        *,
        owner_id: UUID,
        code: PropertyCode,
        name: str,
        default_check_in_time: time,
        default_check_out_time: time,
        linen_par_level: int,
        status: PropertyStatus = PropertyStatus.ONBOARDING,
        address: str = "",
        location: GeoPoint | None = None,
        preferred_cleaner_id: UUID | None = None,
        check_in_guide: CheckInGuide | None = None,
        amenities: Amenities | None = None,
        ical_feeds: tuple[IcalFeed, ...] = (),
        contract_draft: ContractDraft | None = None,
        contract: Contract | None = None,
        sublease_declaration_number: str = "",
        ama_number: str = "",
    ) -> None:
        super().__init__(id)
        self.owner_id = owner_id
        self.code = code
        self.name = name
        self.status = status
        self.address = address
        self.location = location
        self.default_check_in_time = default_check_in_time
        self.default_check_out_time = default_check_out_time
        self.linen_par_level = linen_par_level
        self.preferred_cleaner_id = preferred_cleaner_id
        self.check_in_guide = check_in_guide or CheckInGuide()
        self.amenities = amenities or Amenities()
        self.ical_feeds = ical_feeds
        self.contract_draft = contract_draft
        self.contract = contract
        self.sublease_declaration_number = sublease_declaration_number
        self.ama_number = ama_number

    @classmethod
    def create(
        cls,
        *,
        property_id: UUID,
        owner_id: UUID,
        code: PropertyCode,
        name: str,
        defaults: PropertyDefaults,
    ) -> Self:
        """A new property of an owner, onboarding, with the configured defaults."""
        return cls(
            property_id,
            owner_id=owner_id,
            code=code,
            name=_required(name, "name"),
            default_check_in_time=defaults.check_in_time,
            default_check_out_time=defaults.check_out_time,
            linen_par_level=defaults.linen_par_level,
        )

    # --- profile ----------------------------------------------------------------------------

    def update_profile(
        self,
        *,
        name: str,
        address: str,
        location: GeoPoint | None,
        check_in_guide: CheckInGuide,
        amenities: Amenities,
        ical_feeds: Iterable[IcalFeed],
        default_check_in_time: time,
        default_check_out_time: time,
        linen_par_level: int,
        preferred_cleaner_id: UUID | None,
    ) -> None:
        """Replace the whole profile (onboarding step 2), as one form or wizard sends it."""
        self._refuse_if_offboarded("change the profile of")
        name = _required(name, "name")
        address = address.strip()
        feeds = tuple(ical_feeds)
        _check_one_feed_per_channel(feeds)
        if linen_par_level < 1:
            raise InvalidValue("the linen par level is at least one set", field="linen_par_level")

        gaps = _profile_gaps(address, location, check_in_guide, amenities)
        if gaps and self.status is PropertyStatus.ACTIVE:
            raise ProfileMustStayComplete(gaps)
        was_complete = not self.profile_gaps()

        self.name = name
        self.address = address
        self.location = location
        self.check_in_guide = check_in_guide
        self.amenities = amenities
        self.ical_feeds = feeds
        self.default_check_in_time = default_check_in_time
        self.default_check_out_time = default_check_out_time
        self.linen_par_level = linen_par_level
        self.preferred_cleaner_id = preferred_cleaner_id

        if not gaps and not was_complete:
            self.events.append(PropertyProfileCompleted(property_id=self.id))

    def profile_gaps(self) -> list[ProfileItem]:
        """Parts of the profile still missing, in checklist order."""
        return _profile_gaps(self.address, self.location, self.check_in_guide, self.amenities)

    # --- legal steps ---------------------------------------------------------------------------

    def offer_contract(self, draft: ContractDraft) -> None:
        """Onboarding step 3, first half: the IKE uploads the contract to sign, with its terms.
        A new draft replaces the previous one; it does not undo a signed contract."""
        self._refuse_if_offboarded("offer a contract for")
        if draft != self.contract_draft:
            self.contract_draft = draft
            self.events.append(ContractOffered(property_id=self.id))

    def sign_offered_contract(self, document: str, *, signed_at: datetime) -> None:
        """The owner uploads the draft, signed by them: the contract has the draft's terms."""
        if self.contract_draft is None:
            raise NoContractToSign("the IKE has not offered a contract for this property yet")
        self.sign_contract(
            Contract(
                commission_rate=self.contract_draft.commission_rate,
                owner_cleaning_charge=self.contract_draft.owner_cleaning_charge,
                signed_at=signed_at,
                document=document,
            )
        )

    def sign_contract(self, contract: Contract) -> None:
        """Onboarding step 3: the signed contract (its PDF) is recorded."""
        self._refuse_if_offboarded("sign a contract for")
        if contract != self.contract:
            self.contract = contract
            self.events.append(ContractSigned(property_id=self.id))

    def record_sublease_declaration(self, number: str) -> None:
        """Onboarding step 4: the number of the owner's sublease declaration at AADE."""
        self._refuse_if_offboarded("record a sublease declaration for")
        number = _required(number, "sublease_declaration_number")
        if number != self.sublease_declaration_number:
            self.sublease_declaration_number = number
            self.events.append(SubleaseDeclared(property_id=self.id, number=number))

    def assign_ama(self, ama_number: str) -> None:
        """Onboarding step 5: the AMA number of the short-term rental registry."""
        self._refuse_if_offboarded("assign an AMA number to")
        ama_number = _required(ama_number, "ama_number")
        if ama_number != self.ama_number:
            self.ama_number = ama_number
            self.events.append(AmaAssigned(property_id=self.id, ama_number=ama_number))

    # --- checklist and states ------------------------------------------------------------------

    def missing_for_activation(
        self, *, owner_bank_account_verified: bool
    ) -> list[ActivationRequirement]:
        """The checklist items still missing, in checklist order (DOMAIN §5 invariant)."""
        missing: list[ActivationRequirement] = []
        if self.contract is None:
            missing.append(ActivationRequirement.CONTRACT_SIGNED)
        if not self.sublease_declaration_number:
            missing.append(ActivationRequirement.SUBLEASE_DECLARATION)
        if not self.ama_number:
            missing.append(ActivationRequirement.AMA)
        if self.profile_gaps():
            missing.append(ActivationRequirement.PROFILE_COMPLETE)
        if not owner_bank_account_verified:
            missing.append(ActivationRequirement.BANK_ACCOUNT_VERIFIED)
        return missing

    def activate(self, *, owner_bank_account_verified: bool) -> None:
        """First activation (from ONBOARDING) or return from INACTIVE; the checklist must hold."""
        if self.status not in (PropertyStatus.ONBOARDING, PropertyStatus.INACTIVE):
            raise InvalidStatusTransition(self.status.value, "activate")
        missing = self.missing_for_activation(
            owner_bank_account_verified=owner_bank_account_verified
        )
        if missing:
            raise PropertyNotReadyForActivation(missing)
        if self.status is PropertyStatus.ONBOARDING:
            self.events.append(
                PropertyActivated(property_id=self.id, owner_id=self.owner_id, code=self.code.value)
            )
        else:
            self.events.append(PropertyReactivated(property_id=self.id))
        self.status = PropertyStatus.ACTIVE

    def deactivate(self) -> None:
        """Pause an active property (Ανενεργό). It can be activated again."""
        if self.status is not PropertyStatus.ACTIVE:
            raise InvalidStatusTransition(self.status.value, "deactivate")
        self.status = PropertyStatus.INACTIVE
        self.events.append(PropertyDeactivated(property_id=self.id))

    def offboard(self) -> None:
        """The property leaves the IKE's management. Final."""
        self._refuse_if_offboarded("offboard")
        self.status = PropertyStatus.OFFBOARDED
        self.events.append(PropertyOffboarded(property_id=self.id))

    # --- the owner portal ----------------------------------------------------------------------

    def check_owner_may_change(self, owner_id: UUID) -> None:
        """An owner changes only their own property, and only while it is being set up
        (DOMAIN §5, owner portal); after that, changes go through the IKE. Another owner's
        property is "not found", so the portal never tells that it exists."""
        if owner_id != self.owner_id:
            raise PropertyNotFound(f"no property has id {self.id}")
        if self.status is not PropertyStatus.ONBOARDING:
            raise ChangeThroughTheIke("property")

    def _refuse_if_offboarded(self, action: str) -> None:
        if self.status is PropertyStatus.OFFBOARDED:
            raise InvalidStatusTransition(self.status.value, action)


def _profile_gaps(
    address: str, location: GeoPoint | None, guide: CheckInGuide, amenities: Amenities
) -> list[ProfileItem]:
    filled = {
        ProfileItem.ADDRESS: bool(address),
        ProfileItem.LOCATION: location is not None,
        ProfileItem.DIRECTIONS_EL: bool(guide.directions_el),
        ProfileItem.DIRECTIONS_EN: bool(guide.directions_en),
        ProfileItem.EXTERIOR_PHOTO: bool(guide.exterior_photo),
        ProfileItem.LOCKBOX_PHOTO: bool(guide.lockbox_photo),
        ProfileItem.LOCKBOX_CODE: bool(guide.guest_lockbox_code),
        ProfileItem.AMENITIES: bool(amenities.included),
    }
    return [item for item in ProfileItem if not filled[item]]


def _check_one_feed_per_channel(feeds: tuple[IcalFeed, ...]) -> None:
    channels = [feed.channel for feed in feeds]
    if len(set(channels)) != len(channels):
        raise InvalidValue("a property has one calendar feed per channel", field="ical_feeds")


def _required(text: str, field: str) -> str:
    value = text.strip()
    if not value:
        label = field.replace("_", " ")
        raise InvalidValue(f"the property's {label} is required", field=field)
    return value
