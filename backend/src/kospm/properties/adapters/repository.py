"""Django repositories of the properties context (Repository pattern, Cosmic Python Appendix D).

`*_to_domain` builds an aggregate from a row; `*_values` gives the column values of an aggregate.
Repositories return domain objects only, and write back the changed ones on commit with the
version check of ADR 0016 (VersionedDjangoRepository).
"""

from typing import Any
from uuid import UUID

from django.db import IntegrityError

from kospm.properties import models
from kospm.properties.domain.errors import (
    OwnerAlreadyRegistered,
    OwnerNotFound,
    PropertyCodeTaken,
    PropertyNotFound,
)
from kospm.properties.domain.owner import (
    BankAccount,
    BankAccountStatus,
    Owner,
    PayeeCheck,
    PayeeCheckResult,
)
from kospm.properties.domain.property import Property, PropertyStatus
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
from kospm.properties.service_layer.unit_of_work import OwnerRepository, PropertyRepository
from kospm.shared.adapters.versioned_repository import (
    VersionedDjangoRepository,
    violated_constraint,
)
from kospm.shared.domain import Money

# --- owners --------------------------------------------------------------------------------------


def owner_to_domain(row: models.Owner) -> Owner:
    return Owner(
        row.id,
        name=row.name,
        email=Email(row.email),
        phone=row.phone,
        afm=Afm(row.afm),
        bank_account=BankAccount(
            Iban(row.iban),
            AccountHolderName(row.bank_holder_name),
            status=BankAccountStatus(row.bank_account_status),
            verification_code=row.bank_verification_code,
            failed_attempts=row.bank_verification_failed_attempts,
            payee_check=_payee_check(row),
        ),
        show_on_website=row.show_on_website,
        website_consent_requested=row.website_consent_requested,
    )


def _payee_check(row: models.Owner) -> PayeeCheck | None:
    if not row.bank_payee_check:
        return None
    bank_name = row.bank_payee_check_name
    return PayeeCheck(
        PayeeCheckResult(row.bank_payee_check),
        AccountHolderName(bank_name) if bank_name else None,
    )


def owner_values(owner: Owner) -> dict[str, Any]:
    account = owner.bank_account
    check = account.payee_check
    return {
        "name": owner.name,
        "email": owner.email.value,
        "phone": owner.phone,
        "afm": owner.afm.value,
        "iban": account.iban.value,
        "bank_holder_name": account.holder_name.value,
        "bank_payee_check": check.result.value if check else "",
        "bank_payee_check_name": check.bank_name.value if check and check.bank_name else "",
        "bank_account_status": account.status.value,
        "bank_verification_code": account.verification_code,
        "bank_verification_failed_attempts": account.failed_attempts,
        "show_on_website": owner.show_on_website,
        "website_consent_requested": owner.website_consent_requested,
    }


class DjangoOwnerRepository(VersionedDjangoRepository[Owner], OwnerRepository):
    model = models.Owner

    def get(self, owner_id: UUID, *, expected_version: int | None = None) -> Owner:
        try:
            row = models.Owner.objects.using(self.using).get(pk=owner_id)
        except models.Owner.DoesNotExist:
            raise OwnerNotFound(f"no owner has id {owner_id}") from None
        return self._load(owner_to_domain(row), row.version, expected_version=expected_version)

    def find_by_afm(self, afm: Afm) -> Owner | None:
        row = models.Owner.objects.using(self.using).filter(afm=afm.value).first()
        return None if row is None else self._load(owner_to_domain(row), row.version)

    def find_by_email(self, email: Email) -> Owner | None:
        row = models.Owner.objects.using(self.using).filter(email=email.value).first()
        return None if row is None else self._load(owner_to_domain(row), row.version)

    def _values(self, owner: Owner) -> dict[str, Any]:
        return owner_values(owner)

    def _duplicate(self, owner: Owner, error: IntegrityError) -> Exception:
        # Another unit took the same ΑΦΜ or email between the handler's check and the write.
        constraint = violated_constraint(error)
        for field in ("afm", "email"):
            if f"_{field}_" in constraint:
                return OwnerAlreadyRegistered(field)
        return error


# --- properties ----------------------------------------------------------------------------------


def property_to_domain(row: models.Property) -> Property:
    location = (
        GeoPoint(lat=row.lat, lng=row.lng) if row.lat is not None and row.lng is not None else None
    )
    contract = (
        Contract(
            commission_rate=row.contract_commission_rate,
            owner_cleaning_charge=Money(row.contract_owner_cleaning_charge),
            signed_at=row.contract_signed_at,
            document=row.contract_document.name or "",
        )
        if row.contract_signed_at is not None
        and row.contract_commission_rate is not None
        and row.contract_owner_cleaning_charge is not None
        else None
    )
    draft = (
        ContractDraft(
            document=row.contract_draft_document.name,
            commission_rate=row.contract_draft_commission_rate,
            owner_cleaning_charge=Money(row.contract_draft_owner_cleaning_charge),
        )
        if row.contract_draft_document
        and row.contract_draft_commission_rate is not None
        and row.contract_draft_owner_cleaning_charge is not None
        else None
    )
    return Property(
        row.id,
        owner_id=row.owner_id,
        code=PropertyCode(row.code),
        name=row.name,
        status=PropertyStatus(row.status),
        address=row.address,
        location=location,
        default_check_in_time=row.default_check_in_time,
        default_check_out_time=row.default_check_out_time,
        linen_par_level=row.linen_par_level,
        preferred_cleaner_id=row.preferred_cleaner_id,
        check_in_guide=CheckInGuide(
            directions_el=row.directions_el,
            directions_en=row.directions_en,
            map_url=row.map_url,
            exterior_photo=row.exterior_photo.name or "",
            lockbox_photo=row.lockbox_photo.name or "",
            guest_lockbox_code=row.guest_lockbox_code or "",
            cleaner_lockbox_code=row.cleaner_lockbox_code or "",
        ),
        amenities=Amenities(
            included=tuple(row.amenities_included),
            not_included=tuple(row.amenities_not_included),
        ),
        ical_feeds=tuple(
            IcalFeed(channel=IcalChannel(feed["channel"]), url=feed["url"])
            for feed in row.ical_feeds
        ),
        contract_draft=draft,
        contract=contract,
        sublease_declaration_number=row.sublease_declaration_number,
        ama_number=row.ama_number,
    )


def property_values(prop: Property) -> dict[str, Any]:
    guide = prop.check_in_guide
    contract = prop.contract
    draft = prop.contract_draft
    return {
        "owner_id": prop.owner_id,
        "code": prop.code.value,
        "name": prop.name,
        "status": prop.status.value,
        "address": prop.address,
        "lat": None if prop.location is None else prop.location.lat,
        "lng": None if prop.location is None else prop.location.lng,
        "default_check_in_time": prop.default_check_in_time,
        "default_check_out_time": prop.default_check_out_time,
        "linen_par_level": prop.linen_par_level,
        "preferred_cleaner_id": prop.preferred_cleaner_id,
        "directions_el": guide.directions_el,
        "directions_en": guide.directions_en,
        "map_url": guide.map_url,
        "exterior_photo": guide.exterior_photo,
        "lockbox_photo": guide.lockbox_photo,
        "guest_lockbox_code": guide.guest_lockbox_code or None,
        "cleaner_lockbox_code": guide.cleaner_lockbox_code or None,
        "amenities_included": list(prop.amenities.included),
        "amenities_not_included": list(prop.amenities.not_included),
        "ical_feeds": [{"channel": f.channel.value, "url": f.url} for f in prop.ical_feeds],
        "contract_commission_rate": None if contract is None else contract.commission_rate,
        "contract_owner_cleaning_charge": (
            None if contract is None else contract.owner_cleaning_charge.amount
        ),
        "contract_signed_at": None if contract is None else contract.signed_at,
        "contract_document": "" if contract is None else contract.document,
        "contract_draft_document": "" if draft is None else draft.document,
        "contract_draft_commission_rate": None if draft is None else draft.commission_rate,
        "contract_draft_owner_cleaning_charge": (
            None if draft is None else draft.owner_cleaning_charge.amount
        ),
        "sublease_declaration_number": prop.sublease_declaration_number,
        "ama_number": prop.ama_number,
    }


class DjangoPropertyRepository(VersionedDjangoRepository[Property], PropertyRepository):
    model = models.Property

    def get(self, property_id: UUID, *, expected_version: int | None = None) -> Property:
        try:
            row = models.Property.objects.using(self.using).get(pk=property_id)
        except models.Property.DoesNotExist:
            raise PropertyNotFound(f"no property has id {property_id}") from None
        return self._load(property_to_domain(row), row.version, expected_version=expected_version)

    def find_by_code(self, code: PropertyCode) -> Property | None:
        row = models.Property.objects.using(self.using).filter(code=code.value).first()
        return None if row is None else self._load(property_to_domain(row), row.version)

    def list_by_owner(self, owner_id: UUID) -> list[Property]:
        rows = models.Property.objects.using(self.using).filter(owner_id=owner_id)
        return [self._load(property_to_domain(row), row.version) for row in rows]

    def codes_with_prefix(self, prefix: str) -> list[PropertyCode]:
        codes = models.Property.objects.using(self.using).filter(code__startswith=f"{prefix}-")
        return [PropertyCode(code) for code in codes.values_list("code", flat=True)]

    def _values(self, prop: Property) -> dict[str, Any]:
        return property_values(prop)

    def _duplicate(self, prop: Property, error: IntegrityError) -> Exception:
        # Another unit took the same code between the handler's check and the write.
        if "_code_" in violated_constraint(error):
            return PropertyCodeTaken(prop.code.value)
        return error
