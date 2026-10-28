"""Read side of the properties context (CQRS-lite, Cosmic Python ch. 12).

The admin list and the owner portal ask the domain, not a copy of its rules: rows are mapped to
aggregates and the aggregates answer what is missing. Nothing here changes anything.
"""

from dataclasses import dataclass
from uuid import UUID

from django.db.models.fields.files import FieldFile

from kospm.properties import models
from kospm.properties.adapters.repository import owner_to_domain, property_to_domain
from kospm.properties.domain.checklist import ActivationRequirement, ProfileItem
from kospm.properties.domain.owner import BankAccountStatus, PayeeCheckResult
from kospm.properties.domain.property import Property, PropertyStatus


def missing_for_activation(row: models.Property) -> list[ActivationRequirement]:
    """Checklist items the property still misses (needs `owner` loaded: select_related)."""
    verified = owner_to_domain(row.owner).bank_account_verified
    return property_to_domain(row).missing_for_activation(owner_bank_account_verified=verified)


def profile_gaps(row: models.Property) -> list[ProfileItem]:
    return property_to_domain(row).profile_gaps()


# --- the owner portal (DOMAIN §5, owner portal) --------------------------------------------------


@dataclass(frozen=True)
class BankOverview:
    iban: str  # grouped by four, as banks print it
    holder_name: str
    status: BankAccountStatus
    payee_check: PayeeCheckResult | None


@dataclass(frozen=True)
class PropertySummary:
    code: str
    name: str
    status: PropertyStatus
    missing: tuple[ActivationRequirement, ...]

    @property
    def ready(self) -> int:
        """How many checklist items are done."""
        return len(ActivationRequirement) - len(self.missing)

    @property
    def total(self) -> int:
        return len(ActivationRequirement)


@dataclass(frozen=True)
class OwnerOverview:
    """What an owner sees about themself: details, bank account and properties."""

    owner_id: UUID
    name: str
    email: str
    phone: str
    afm: str
    version: int  # forms carry it (ADR 0016)
    bank: BankOverview
    properties: tuple[PropertySummary, ...]


def owner_overview(owner_id: UUID) -> OwnerOverview | None:
    """The owner's overview, or None while the owner has not registered (onboarding step 1)."""
    row = models.Owner.objects.filter(pk=owner_id).first()
    if row is None:
        return None
    owner = owner_to_domain(row)
    account = owner.bank_account
    verified = owner.bank_account_verified
    properties = tuple(
        PropertySummary(
            code=prop.code.value,
            name=prop.name,
            status=prop.status,
            missing=tuple(prop.missing_for_activation(owner_bank_account_verified=verified)),
        )
        for prop in map(property_to_domain, row.properties.order_by("code"))
    )
    return OwnerOverview(
        owner_id=owner.id,
        name=owner.name,
        email=owner.email.value,
        phone=owner.phone,
        afm=owner.afm.value,
        version=row.version,
        bank=BankOverview(
            iban=account.iban.formatted(),
            holder_name=account.holder_name.value,
            status=account.status,
            payee_check=account.payee_check.result if account.payee_check else None,
        ),
        properties=properties,
    )


@dataclass(frozen=True)
class OwnerProperty:
    """One of the owner's properties, for its pages.

    `prop` is an unsaved copy of the aggregate: the pages show it and preview a change on
    it (as the admin forms do), the commands change the real one.
    """

    prop: Property
    version: int
    bank_account_verified: bool

    @property
    def missing(self) -> list[ActivationRequirement]:
        return self.prop.missing_for_activation(
            owner_bank_account_verified=self.bank_account_verified
        )


def owner_property(owner_id: UUID, code: str) -> OwnerProperty | None:
    """The property with this code, if it is this owner's (another owner's is "not found")."""
    row = (
        models.Property.objects.select_related("owner")
        .filter(owner_id=owner_id, code=code.strip().upper())
        .first()
    )
    if row is None:
        return None
    return OwnerProperty(
        prop=property_to_domain(row),
        version=row.version,
        bank_account_verified=owner_to_domain(row.owner).bank_account_verified,
    )


def owner_property_code(owner_id: UUID, property_id: UUID) -> str | None:
    code: str | None = (
        models.Property.objects.filter(owner_id=owner_id, pk=property_id)
        .values_list("code", flat=True)
        .first()
    )
    return code


def owner_file(owner_id: UUID, code: str, kind: str) -> FieldFile | None:
    """An uploaded file of the owner's property (photos, contracts), or None (DOMAIN §5: files
    are visible only to their owner and the admin)."""
    if kind not in OWNER_FILES:
        return None
    row = models.Property.objects.filter(owner_id=owner_id, code=code.strip().upper()).first()
    if row is None:
        return None
    file: FieldFile = getattr(row, kind)
    return file if file else None


# The files an owner may open: their own uploads and the contract the IKE offered them.
OWNER_FILES = frozenset(
    {"exterior_photo", "lockbox_photo", "contract_draft_document", "contract_document"}
)
