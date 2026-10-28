"""Commands of the properties context (Cosmic Python ch. 10).

Commands carry plain values, as a form or an API sends them; the handlers turn them into value
objects, so validation lives in one place (the domain). The admin and the owner portal send the
same commands.

`acting_owner_id` names the owner who sends a command from the owner portal (ADR 0017); None
means the IKE (the admin). The handler then refuses another owner's data and what DOMAIN §5
keeps for the IKE.

`expected_version` (on commands sent from a form) is the version the form was rendered with: the
handler refuses with ConcurrencyError if someone saved the aggregate since (ADR 0016). Secrets
(lockbox and verification codes) are kept out of repr, so they never reach logs or tracebacks.
"""

from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal
from uuid import UUID

from kospm.shared.domain import Command


@dataclass(frozen=True, kw_only=True)
class RegisterOwner(Command):
    owner_id: UUID
    name: str
    email: str
    phone: str
    afm: str
    iban: str
    holder_name: str


@dataclass(frozen=True, kw_only=True)
class UpdateOwnerDetails(Command):
    owner_id: UUID
    name: str
    email: str
    phone: str
    expected_version: int | None = None
    acting_owner_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class ChangeBankAccount(Command):
    """A new IBAN or account holder name; either must be verified again."""

    owner_id: UUID
    iban: str
    holder_name: str
    expected_version: int | None = None
    acting_owner_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class StartBankAccountVerification(Command):
    """Prepare the €0.01 test transfer: the handler creates the code to put in its reference."""

    owner_id: UUID
    acting_owner_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class RecordTestTransfer(Command):
    """The admin sent the test transfer (or not: no_match) and records the bank's payee check:
    match, close_match (with the name the bank returned), not_possible or no_match."""

    owner_id: UUID
    result: str
    bank_name: str = ""


@dataclass(frozen=True, kw_only=True)
class ConfirmBankAccount(Command):
    owner_id: UUID
    code: str = field(repr=False)
    acting_owner_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class CreateProperty(Command):
    """A new property. Without a code (the owner portal), it gets the next one of the series."""

    property_id: UUID
    owner_id: UUID
    name: str
    code: str | None = None
    acting_owner_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class UpdatePropertyProfile(Command):
    """The whole profile as edited in a form. A lockbox code of None keeps the stored one."""

    property_id: UUID
    name: str
    address: str
    lat: Decimal | None
    lng: Decimal | None
    directions_el: str
    directions_en: str
    map_url: str
    exterior_photo: str
    lockbox_photo: str
    guest_lockbox_code: str | None = field(repr=False)
    cleaner_lockbox_code: str | None = field(repr=False)
    amenities_included: tuple[str, ...]
    amenities_not_included: tuple[str, ...]
    ical_feeds: tuple[tuple[str, str], ...]  # (channel, url)
    default_check_in_time: time
    default_check_out_time: time
    linen_par_level: int
    preferred_cleaner_id: UUID | None
    expected_version: int | None = None
    acting_owner_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class OfferContract(Command):
    """The IKE uploads the contract to sign (its PDF). Missing terms take the defaults."""

    property_id: UUID
    document: str
    commission_rate: Decimal | None = None
    owner_cleaning_charge: Decimal | None = None
    expected_version: int | None = None


@dataclass(frozen=True, kw_only=True)
class SignContract(Command):
    """Record the signed contract. Missing terms take the configured defaults; an owner (the
    portal) signs the offered draft, whose terms the contract takes."""

    property_id: UUID
    document: str
    signed_at: datetime | None = None  # None: now
    commission_rate: Decimal | None = None
    owner_cleaning_charge: Decimal | None = None
    expected_version: int | None = None
    acting_owner_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class RecordSubleaseDeclaration(Command):
    property_id: UUID
    number: str
    expected_version: int | None = None
    acting_owner_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class AssignAma(Command):
    property_id: UUID
    ama_number: str
    expected_version: int | None = None


@dataclass(frozen=True, kw_only=True)
class ActivateProperty(Command):
    """Activate an onboarding property, or bring an inactive one back."""

    property_id: UUID


@dataclass(frozen=True, kw_only=True)
class DeactivateProperty(Command):
    property_id: UUID


@dataclass(frozen=True, kw_only=True)
class OffboardProperty(Command):
    property_id: UUID
