"""Command and event handlers of the properties context (Cosmic Python ch. 10).

Each handler runs one Unit of Work and changes one aggregate. Commands carry plain values; the
handlers turn them into value objects before opening the unit, so a malformed ΑΦΜ or IBAN is
refused before anything is loaded. Dependencies besides `uow` and `clock` are injected by
bootstrap by name: `property_defaults`, `bank_verification` (policy) and `bank_account_verifier`.

Commands sent from a form carry the `expected_version` the form was rendered with: if someone
else saved the aggregate since, the handler refuses with ConcurrencyError (ADR 0016), instead of
applying a stale form over their change.
"""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import assert_never
from uuid import UUID

from kospm.properties.domain.codes import PropertyCodeSeries
from kospm.properties.domain.commands import (
    ActivateProperty,
    AssignAma,
    ChangeBankAccount,
    ConfirmBankAccount,
    CreateProperty,
    DeactivateProperty,
    OffboardProperty,
    OfferContract,
    RecordSubleaseDeclaration,
    RecordTestTransfer,
    RegisterOwner,
    SignContract,
    StartBankAccountVerification,
    UpdateOwnerDetails,
    UpdatePropertyProfile,
)
from kospm.properties.domain.defaults import BankVerificationPolicy, PropertyDefaults
from kospm.properties.domain.errors import (
    ChangeThroughTheIke,
    InvalidValue,
    OwnerAlreadyRegistered,
    OwnerNotFound,
    PropertyCodeTaken,
    WrongVerificationCode,
)
from kospm.properties.domain.events import PropertyActivated
from kospm.properties.domain.owner import Owner, PayeeCheck, PayeeCheckResult
from kospm.properties.domain.property import Property
from kospm.properties.domain.value_objects import (
    AccountHolderName,
    Afm,
    Amenities,
    CheckInGuide,
    Contract,
    ContractDraft,
    Email,
    GeoPoint,
    Iban,
    IcalChannel,
    IcalFeed,
    PropertyCode,
)
from kospm.properties.service_layer.ports import BankAccountVerifier
from kospm.properties.service_layer.unit_of_work import PropertiesUnitOfWork
from kospm.shared.clock import Clock
from kospm.shared.domain import Command, DomainEvent, Money

# --- owners --------------------------------------------------------------------------------------


def register_owner(cmd: RegisterOwner, uow: PropertiesUnitOfWork) -> None:
    email, afm, iban = Email(cmd.email), Afm(cmd.afm), Iban(cmd.iban)
    holder_name = AccountHolderName(cmd.holder_name)
    with uow:
        if uow.owners.find_by_afm(afm) is not None:
            raise OwnerAlreadyRegistered("afm")
        if uow.owners.find_by_email(email) is not None:
            raise OwnerAlreadyRegistered("email")
        uow.owners.add(
            Owner.register(
                owner_id=cmd.owner_id,
                name=cmd.name,
                email=email,
                phone=cmd.phone,
                afm=afm,
                iban=iban,
                holder_name=holder_name,
            )
        )
        uow.commit()


def update_owner_details(cmd: UpdateOwnerDetails, uow: PropertiesUnitOfWork) -> None:
    email = Email(cmd.email)
    with uow:
        owner = _owner(uow, cmd.owner_id, cmd.acting_owner_id, cmd.expected_version)
        if cmd.acting_owner_id is not None and email != owner.email:
            raise ChangeThroughTheIke("email")  # the owner's email is their login
        holder = uow.owners.find_by_email(email)
        if holder is not None and holder.id != owner.id:
            raise OwnerAlreadyRegistered("email")
        owner.update_details(name=cmd.name, email=email, phone=cmd.phone)
        uow.commit()


def change_bank_account(cmd: ChangeBankAccount, uow: PropertiesUnitOfWork) -> None:
    iban, holder_name = Iban(cmd.iban), AccountHolderName(cmd.holder_name)
    with uow:
        owner = _owner(uow, cmd.owner_id, cmd.acting_owner_id, cmd.expected_version)
        if cmd.acting_owner_id is None:
            owner.change_bank_account(iban, holder_name)
        else:
            owner.change_own_bank_account(iban, holder_name)
        uow.commit()


def start_bank_account_verification(
    cmd: StartBankAccountVerification,
    uow: PropertiesUnitOfWork,
    bank_account_verifier: BankAccountVerifier,
) -> None:
    """A €0.01 test transfer is to be sent with a fresh code in its reference (DOMAIN §5)."""
    code = bank_account_verifier.new_code()
    with uow:
        owner = _owner(uow, cmd.owner_id, cmd.acting_owner_id)
        owner.start_bank_verification(code)
        bank_account_verifier.request_test_transfer(
            owner_id=owner.id,
            iban=owner.bank_account.iban,
            holder_name=owner.bank_account.holder_name,
            code=code,
            outbox=uow.outbox,
        )
        uow.commit()


def record_test_transfer(cmd: RecordTestTransfer, uow: PropertiesUnitOfWork) -> None:
    """The admin records the test transfer and the bank's payee check (ADR 0018)."""
    check = _payee_check(cmd.result, cmd.bank_name)
    with uow:
        uow.owners.get(cmd.owner_id).record_test_transfer(check)
        uow.commit()


def confirm_bank_account(
    cmd: ConfirmBankAccount, uow: PropertiesUnitOfWork, bank_verification: BankVerificationPolicy
) -> None:
    with uow:
        owner = _owner(uow, cmd.owner_id, cmd.acting_owner_id)
        outcome = owner.confirm_bank_account(cmd.code, bank_verification)
        uow.commit()  # a wrong attempt counts, so it is saved before the error is reported
    if not outcome.verified:
        raise WrongVerificationCode(outcome.attempts_left)


def _owner(
    uow: PropertiesUnitOfWork,
    owner_id: UUID,
    acting_owner_id: UUID | None,
    expected_version: int | None = None,
) -> Owner:
    """The owner a command is about. From the portal, only the acting owner's own (ADR 0017):
    anyone else's is "not found", so the portal never tells that it exists."""
    if acting_owner_id is not None and acting_owner_id != owner_id:
        raise OwnerNotFound(f"no owner has id {owner_id}")
    return uow.owners.get(owner_id, expected_version=expected_version)


def _payee_check(result: str, bank_name: str) -> PayeeCheck:
    try:
        kind = PayeeCheckResult(result)
    except ValueError as error:
        raise InvalidValue(f"{result!r} is not a payee check", field="payee_check") from error
    return PayeeCheck(kind, AccountHolderName(bank_name) if bank_name.strip() else None)


# --- properties ----------------------------------------------------------------------------------


def create_property(
    cmd: CreateProperty,
    uow: PropertiesUnitOfWork,
    property_defaults: PropertyDefaults,
    property_codes: PropertyCodeSeries,
) -> None:
    """A new property of an owner. Without a code (the owner portal), it gets the next code of
    the series (DOMAIN §5, owner portal)."""
    with uow:
        _owner(uow, cmd.owner_id, cmd.acting_owner_id)  # must exist; read only, not written
        if cmd.code is None:
            code = property_codes.next_code(uow.properties.codes_with_prefix(property_codes.prefix))
        else:
            code = PropertyCode(cmd.code)
        if uow.properties.find_by_code(code) is not None:
            raise PropertyCodeTaken(code.value)
        uow.properties.add(
            Property.create(
                property_id=cmd.property_id,
                owner_id=cmd.owner_id,
                code=code,
                name=cmd.name,
                defaults=property_defaults,
            )
        )
        uow.commit()


def update_property_profile(cmd: UpdatePropertyProfile, uow: PropertiesUnitOfWork) -> None:
    with uow:
        apply_profile(
            uow.properties.get(cmd.property_id, expected_version=cmd.expected_version), cmd
        )
        uow.commit()


def apply_profile(prop: Property, cmd: UpdatePropertyProfile) -> None:
    """Apply a profile command to a property: the handler's work, without a Unit of Work."""
    if cmd.acting_owner_id is not None:
        prop.check_owner_may_change(cmd.acting_owner_id)
        _refuse_what_the_ike_sets(prop, cmd)
    location = _location(cmd.lat, cmd.lng)
    amenities = Amenities(included=cmd.amenities_included, not_included=cmd.amenities_not_included)
    feeds = tuple(IcalFeed(channel=_channel(name), url=url) for name, url in cmd.ical_feeds)
    stored = prop.check_in_guide
    guide = CheckInGuide(
        directions_el=cmd.directions_el,
        directions_en=cmd.directions_en,
        map_url=cmd.map_url,
        exterior_photo=cmd.exterior_photo,
        lockbox_photo=cmd.lockbox_photo,
        guest_lockbox_code=_keep_if_none(cmd.guest_lockbox_code, stored.guest_lockbox_code),
        cleaner_lockbox_code=_keep_if_none(cmd.cleaner_lockbox_code, stored.cleaner_lockbox_code),
    )
    prop.update_profile(
        name=cmd.name,
        address=cmd.address,
        location=location,
        check_in_guide=guide,
        amenities=amenities,
        ical_feeds=feeds,
        default_check_in_time=cmd.default_check_in_time,
        default_check_out_time=cmd.default_check_out_time,
        linen_par_level=cmd.linen_par_level,
        preferred_cleaner_id=cmd.preferred_cleaner_id,
    )


def sign_contract(
    cmd: SignContract,
    uow: PropertiesUnitOfWork,
    clock: Clock,
    property_defaults: PropertyDefaults,
) -> None:
    now = clock.now()
    with uow:
        prop = uow.properties.get(cmd.property_id, expected_version=cmd.expected_version)
        apply_edit(prop, cmd, property_defaults=property_defaults, now=now)
        uow.commit()


def offer_contract(
    cmd: OfferContract,
    uow: PropertiesUnitOfWork,
    clock: Clock,
    property_defaults: PropertyDefaults,
) -> None:
    with uow:
        prop = uow.properties.get(cmd.property_id, expected_version=cmd.expected_version)
        apply_edit(prop, cmd, property_defaults=property_defaults, now=clock.now())
        uow.commit()


def build_draft(cmd: OfferContract, defaults: PropertyDefaults) -> ContractDraft:
    """The contract to sign an OfferContract command records: terms it omits take the defaults."""
    return ContractDraft(
        document=cmd.document,
        commission_rate=(
            defaults.commission_rate if cmd.commission_rate is None else cmd.commission_rate
        ),
        owner_cleaning_charge=(
            defaults.owner_cleaning_charge
            if cmd.owner_cleaning_charge is None
            else Money(cmd.owner_cleaning_charge)
        ),
    )


def build_contract(cmd: SignContract, defaults: PropertyDefaults, *, now: datetime) -> Contract:
    """The contract a SignContract command records: terms it omits take the defaults."""
    return Contract(
        commission_rate=(
            defaults.commission_rate if cmd.commission_rate is None else cmd.commission_rate
        ),
        owner_cleaning_charge=(
            defaults.owner_cleaning_charge
            if cmd.owner_cleaning_charge is None
            else Money(cmd.owner_cleaning_charge)
        ),
        signed_at=now if cmd.signed_at is None else cmd.signed_at,
        document=cmd.document,
    )


# The commands a property form sends after the property exists (onboarding steps 2-5).
type PropertyEdit = (
    UpdatePropertyProfile | OfferContract | SignContract | RecordSubleaseDeclaration | AssignAma
)


def apply_edit(
    prop: Property, cmd: PropertyEdit, *, property_defaults: PropertyDefaults, now: datetime
) -> None:
    """Apply one edit to a property as its handler does, without a Unit of Work.

    Forms call it on an unsaved copy of the aggregate, for every command a save would send, to
    show the domain's verdict as a form error before anything is saved.
    """
    match cmd:
        case UpdatePropertyProfile():
            apply_profile(prop, cmd)
        case OfferContract():
            prop.offer_contract(build_draft(cmd, property_defaults))
        case SignContract() if cmd.acting_owner_id is not None:
            # The owner signs the draft the IKE offered, with its terms (DOMAIN §5).
            prop.check_owner_may_change(cmd.acting_owner_id)
            prop.sign_offered_contract(cmd.document, signed_at=now)
        case SignContract():
            prop.sign_contract(build_contract(cmd, property_defaults, now=now))
        case RecordSubleaseDeclaration():
            if cmd.acting_owner_id is not None:
                prop.check_owner_may_change(cmd.acting_owner_id)
            prop.record_sublease_declaration(cmd.number)
        case AssignAma():
            prop.assign_ama(cmd.ama_number)
        case _:
            assert_never(cmd)


def record_sublease_declaration(
    cmd: RecordSubleaseDeclaration,
    uow: PropertiesUnitOfWork,
    clock: Clock,
    property_defaults: PropertyDefaults,
) -> None:
    with uow:
        prop = uow.properties.get(cmd.property_id, expected_version=cmd.expected_version)
        apply_edit(prop, cmd, property_defaults=property_defaults, now=clock.now())
        uow.commit()


def assign_ama(cmd: AssignAma, uow: PropertiesUnitOfWork) -> None:
    with uow:
        prop = uow.properties.get(cmd.property_id, expected_version=cmd.expected_version)
        prop.assign_ama(cmd.ama_number)
        uow.commit()


def activate_property(cmd: ActivateProperty, uow: PropertiesUnitOfWork) -> None:
    with uow:
        prop = uow.properties.get(cmd.property_id)
        owner = uow.owners.get(prop.owner_id)  # read only: the bank account is on the checklist
        prop.activate(owner_bank_account_verified=owner.bank_account_verified)
        uow.commit()


def deactivate_property(cmd: DeactivateProperty, uow: PropertiesUnitOfWork) -> None:
    with uow:
        uow.properties.get(cmd.property_id).deactivate()
        uow.commit()


def offboard_property(cmd: OffboardProperty, uow: PropertiesUnitOfWork) -> None:
    with uow:
        uow.properties.get(cmd.property_id).offboard()
        uow.commit()


# --- events --------------------------------------------------------------------------------------


def request_website_consent(event: PropertyActivated, uow: PropertiesUnitOfWork) -> None:
    """After a first activation the owner is asked about the public website (DOMAIN §5).

    A separate unit from the activation: one handler, one aggregate changed (Cosmic Python ch. 7).
    """
    with uow:
        uow.owners.get(event.owner_id).request_website_consent()
        uow.commit()


# --- helpers -------------------------------------------------------------------------------------


def _location(lat: Decimal | None, lng: Decimal | None) -> GeoPoint | None:
    if lat is None and lng is None:
        return None
    if lat is None or lng is None:
        raise InvalidValue("latitude and longitude are given together", field="location")
    return GeoPoint(lat=lat, lng=lng)


def _channel(name: str) -> IcalChannel:
    try:
        return IcalChannel(name)
    except ValueError as error:
        raise InvalidValue(f"{name!r} is not a calendar channel", field="ical_feeds") from error


def _keep_if_none(new: str | None, stored: str) -> str:
    return stored if new is None else new


def _refuse_what_the_ike_sets(prop: Property, cmd: UpdatePropertyProfile) -> None:
    """An owner's profile carries the IKE's settings unchanged: calendar feeds, preferred
    cleaner, linen sets, check-in/out times (DOMAIN §5, owner portal)."""
    sent = (
        {(channel, url.strip()) for channel, url in cmd.ical_feeds},
        cmd.preferred_cleaner_id,
        cmd.linen_par_level,
        cmd.default_check_in_time,
        cmd.default_check_out_time,
    )
    stored = (
        {(feed.channel.value, feed.url) for feed in prop.ical_feeds},
        prop.preferred_cleaner_id,
        prop.linen_par_level,
        prop.default_check_in_time,
        prop.default_check_out_time,
    )
    if sent != stored:
        raise ChangeThroughTheIke("property")


COMMAND_HANDLERS: dict[type[Command], Callable[..., None]] = {
    RegisterOwner: register_owner,
    UpdateOwnerDetails: update_owner_details,
    ChangeBankAccount: change_bank_account,
    StartBankAccountVerification: start_bank_account_verification,
    RecordTestTransfer: record_test_transfer,
    ConfirmBankAccount: confirm_bank_account,
    CreateProperty: create_property,
    UpdatePropertyProfile: update_property_profile,
    OfferContract: offer_contract,
    SignContract: sign_contract,
    RecordSubleaseDeclaration: record_sublease_declaration,
    AssignAma: assign_ama,
    ActivateProperty: activate_property,
    DeactivateProperty: deactivate_property,
    OffboardProperty: offboard_property,
}

EVENT_HANDLERS: dict[type[DomainEvent], list[Callable[..., None]]] = {
    PropertyActivated: [request_website_consent],
}
