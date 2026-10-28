"""Builders for properties-context tests: valid objects at each step of the checklist (DOMAIN §5).

Each builder returns a fresh object; tests override only what they are about.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from kospm.properties.domain.defaults import PropertyDefaults
from kospm.properties.domain.owner import Owner
from kospm.properties.domain.property import Property
from kospm.properties.domain.value_objects import (
    AccountHolderName,
    Afm,
    Amenities,
    CheckInGuide,
    Contract,
    Email,
    GeoPoint,
    Iban,
    IcalChannel,
    IcalFeed,
    PropertyCode,
)
from kospm.shared.domain import Money, new_id

VALID_AFM = "090000045"
OTHER_VALID_AFM = "123456783"
VALID_IBAN = "GR16 0110 1250 0000 0001 2300 695"
OTHER_VALID_IBAN = "DE89 3704 0044 0532 0130 00"
HOLDER = AccountHolderName("PAPADOPOULOU MARIA")
KOS_TOWN = GeoPoint(lat=Decimal("36.893300"), lng=Decimal("27.288900"))
SIGNED_AT = datetime(2026, 10, 20, 9, 30, tzinfo=UTC)


def owner(
    *, owner_id: UUID | None = None, email: str = "maria@example.com", afm: str = VALID_AFM
) -> Owner:
    registered = Owner.register(
        owner_id=owner_id or new_id(),
        name="Μαρία Παπαδοπούλου",
        email=Email(email),
        phone="+30 6900000000",
        afm=Afm(afm),
        iban=Iban(VALID_IBAN),
        holder_name=HOLDER,
    )
    registered.events.clear()
    return registered


def complete_guide(**overrides: Any) -> CheckInGuide:
    values: dict[str, Any] = {
        "directions_el": "Από το λιμάνι, δεύτερο στενό δεξιά.",
        "directions_en": "From the harbour, second street on the right.",
        "map_url": "https://maps.google.com/?q=36.8933,27.2889",
        "exterior_photo": "properties/photos/kos-a1-exterior.jpg",
        "lockbox_photo": "properties/photos/kos-a1-lockbox.jpg",
        "guest_lockbox_code": "4711",
        "cleaner_lockbox_code": "",
    }
    values.update(overrides)
    return CheckInGuide(**values)


def complete_profile(**overrides: Any) -> dict[str, Any]:
    """Keyword arguments for Property.update_profile that leave no profile gap."""
    values: dict[str, Any] = {
        "name": "Σπίτι Αιγαίου",
        "address": "Βασιλέως Παύλου 12, Κως 853 00",
        "location": KOS_TOWN,
        "check_in_guide": complete_guide(),
        "amenities": Amenities(included=("Wi-Fi", "Κλιματισμός"), not_included=("Πισίνα",)),
        "ical_feeds": (),
        "default_check_in_time": PropertyDefaults().check_in_time,
        "default_check_out_time": PropertyDefaults().check_out_time,
        "linen_par_level": 3,
        "preferred_cleaner_id": None,
    }
    values.update(overrides)
    return values


def signed_contract(**overrides: Any) -> Contract:
    values: dict[str, Any] = {
        "commission_rate": Decimal("0.15"),
        "owner_cleaning_charge": Money("40.00"),
        "signed_at": SIGNED_AT,
        "document": "contracts/kos-a1-signed.pdf",
    }
    values.update(overrides)
    return Contract(**values)


def airbnb_feed() -> IcalFeed:
    return IcalFeed(channel=IcalChannel.AIRBNB, url="https://www.airbnb.com/calendar/ical/1.ics")


def new_property(
    *, property_id: UUID | None = None, owner_id: UUID | None = None, code: str = "KOS-A1"
) -> Property:
    return Property.create(
        property_id=property_id or new_id(),
        owner_id=owner_id or new_id(),
        code=PropertyCode(code),
        name="Σπίτι Αιγαίου",
        defaults=PropertyDefaults(),
    )


def ready_property(*, owner_id: UUID | None = None, code: str = "KOS-A1") -> Property:
    """A property whose own checklist items are all done (the bank account is the owner's)."""
    prop = new_property(owner_id=owner_id, code=code)
    prop.update_profile(**complete_profile())
    prop.sign_contract(signed_contract())
    prop.record_sublease_declaration("ΔΥ-2026-000123")
    prop.assign_ama("00001234567")
    prop.events.clear()
    return prop
