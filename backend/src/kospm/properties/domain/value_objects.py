"""Value objects of the properties context (Cosmic Python ch. 1).

Each one validates itself when created, so an invalid ΑΦΜ, IBAN or property code cannot exist in
the domain at all. They are immutable and compared by value. Text is normalised on the way in
(trimmed, upper- or lower-cased) so that equal values compare equal.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from kospm.properties.domain.errors import InvalidValue
from kospm.shared.domain import Money, require_aware

_PROPERTY_CODE = re.compile(r"[A-Z0-9]+(?:-[A-Z0-9]+)*")
_AFM = re.compile(r"[0-9]{9}")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_IBAN = re.compile(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}")
_HTTPS_URL = re.compile(r"https://\S+\.\S+")
_MICRODEGREE = Decimal("0.000001")  # coordinates are stored with 6 decimal places
_RATE_STEP = Decimal("0.0001")  # commission rates are stored with 4 decimal places
# Uploads are judged by the extension of their storage name (DOMAIN §5, validation details).
_PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".heic")
_CONTRACT_SUFFIX = ".pdf"


def _set(instance: object, name: str, value: object) -> None:
    """Normalise a field of a frozen dataclass in __post_init__."""
    object.__setattr__(instance, name, value)


@dataclass(frozen=True)
class PropertyCode:
    """Short public code of a property, e.g. KOS-A1. Guests quote it on WhatsApp (DOMAIN §7)."""

    value: str

    def __post_init__(self) -> None:
        code = self.value.strip().upper()
        if not (2 <= len(code) <= 16 and _PROPERTY_CODE.fullmatch(code)):
            raise InvalidValue(
                f"{self.value!r} is not a property code: 2-16 Latin letters or digits, "
                "in groups joined by single hyphens (e.g. KOS-A1)",
                field="code",
            )
        _set(self, "value", code)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Afm:
    """Greek tax number (ΑΦΜ): nine digits, the last one a check digit."""

    value: str

    def __post_init__(self) -> None:
        afm = "".join(self.value.split())
        if not _AFM.fullmatch(afm) or afm == "000000000" or not _afm_check_digit_ok(afm):
            raise InvalidValue(f"{self.value!r} is not a valid ΑΦΜ", field="afm")
        _set(self, "value", afm)

    def __str__(self) -> str:
        return self.value


def _afm_check_digit_ok(afm: str) -> bool:
    digits = [int(char) for char in afm]
    weighted = sum(digit << (8 - position) for position, digit in enumerate(digits[:8]))
    return weighted % 11 % 10 == digits[8]


@dataclass(frozen=True)
class Email:
    """An email address, lower-cased so that the same address is never registered twice."""

    value: str

    def __post_init__(self) -> None:
        email = self.value.strip().lower()
        if not _EMAIL.fullmatch(email):
            raise InvalidValue(f"{self.value!r} is not an email address", field="email")
        _set(self, "value", email)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Iban:
    """International bank account number, checked with the ISO 13616 mod-97 rule."""

    value: str

    def __post_init__(self) -> None:
        iban = "".join(self.value.split()).upper()
        if not _IBAN.fullmatch(iban) or not _iban_checksum_ok(iban):
            raise InvalidValue(f"{self.value!r} is not a valid IBAN", field="iban")
        _set(self, "value", iban)

    def formatted(self) -> str:
        """Groups of four characters, as banks print it."""
        return " ".join(self.value[start : start + 4] for start in range(0, len(self.value), 4))

    def __str__(self) -> str:
        return self.value


def _iban_checksum_ok(iban: str) -> bool:
    rearranged = iban[4:] + iban[:4]
    return int("".join(str(int(char, 36)) for char in rearranged)) % 97 == 1


@dataclass(frozen=True)
class GeoPoint:
    """Coordinates of a property, in decimal degrees (routing of the linen restock, DOMAIN §9)."""

    lat: Decimal
    lng: Decimal

    def __post_init__(self) -> None:
        for name, limit in (("lat", 90), ("lng", 180)):
            value = getattr(self, name)
            if not isinstance(value, Decimal):
                raise TypeError(f"{name} must be a Decimal, got {type(value).__name__}")
            if not value.is_finite() or not -limit <= value <= limit:
                raise InvalidValue(f"{name}={value} is outside -{limit}..{limit}", field="location")
            if value != value.quantize(_MICRODEGREE):
                raise InvalidValue(
                    f"{name}={value} has more than 6 decimal places", field="location"
                )


class IcalChannel(StrEnum):
    """The platforms whose calendars are imported (DOMAIN §6)."""

    AIRBNB = "airbnb"
    BOOKING = "booking"


@dataclass(frozen=True)
class IcalFeed:
    """The calendar export of one channel's listing. https only (DOMAIN §2.1: iCal is allowed)."""

    channel: IcalChannel
    url: str

    def __post_init__(self) -> None:
        try:
            _set(self, "channel", IcalChannel(self.channel))
        except ValueError as error:
            raise InvalidValue(
                f"{self.channel!r} is not a calendar channel", field="ical_feeds"
            ) from error
        url = self.url.strip()
        if not _HTTPS_URL.fullmatch(url):
            raise InvalidValue(f"{self.url!r} is not an https address", field="ical_feeds")
        _set(self, "url", url)


@dataclass(frozen=True)
class Amenities:
    """What a property offers and what it does not; the AI answers guests from it (DOMAIN §5)."""

    included: tuple[str, ...] = ()
    not_included: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        included = _distinct(self.included)
        not_included = _distinct(self.not_included)
        both = set(included) & set(not_included)
        if both:
            raise InvalidValue(
                "an amenity cannot be both included and not included: " + ", ".join(sorted(both)),
                field="amenities",
            )
        _set(self, "included", included)
        _set(self, "not_included", not_included)


def _distinct(items: tuple[str, ...]) -> tuple[str, ...]:
    """Trimmed, without blanks or repeats, in their original order."""
    return tuple(dict.fromkeys(item.strip() for item in items if item.strip()))


@dataclass(frozen=True)
class CheckInGuide:
    """How a guest finds and enters the property (DOMAIN §5).

    Photos are storage paths. Lockbox codes are secrets (DOMAIN §2.3): encrypted at rest by the
    adapter and kept out of repr, so they never reach a log. Empty text means "not filled in yet".
    """

    directions_el: str = ""
    directions_en: str = ""
    map_url: str = ""
    exterior_photo: str = ""
    lockbox_photo: str = ""
    guest_lockbox_code: str = field(default="", repr=False)
    cleaner_lockbox_code: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        for name in (
            "directions_el",
            "directions_en",
            "map_url",
            "exterior_photo",
            "lockbox_photo",
            "guest_lockbox_code",
            "cleaner_lockbox_code",
        ):
            _set(self, name, getattr(self, name).strip())
        if self.map_url and not _HTTPS_URL.fullmatch(self.map_url):
            raise InvalidValue(f"{self.map_url!r} is not an https address", field="map_url")
        if not _is_photo(self.exterior_photo):
            raise InvalidValue(f"{self.exterior_photo!r} is not a photo", field="exterior_photo")
        if not _is_photo(self.lockbox_photo):
            raise InvalidValue(f"{self.lockbox_photo!r} is not a photo", field="lockbox_photo")

    @property
    def cleaners_lockbox_code(self) -> str:
        """The cleaners' code: their own, or the guests' code when they share one."""
        return self.cleaner_lockbox_code or self.guest_lockbox_code


@dataclass(frozen=True)
class Contract:
    """The signed agreement between the IKE and the owner for one property (DOMAIN §5, §10)."""

    commission_rate: Decimal
    owner_cleaning_charge: Money
    signed_at: datetime
    document: str

    def __post_init__(self) -> None:
        if not isinstance(self.commission_rate, Decimal):
            raise TypeError(
                f"commission_rate must be a Decimal, got {type(self.commission_rate).__name__}"
            )
        if not Decimal(0) <= self.commission_rate < Decimal(1):
            raise InvalidValue(
                f"the commission rate {self.commission_rate} is not in 0..1",
                field="commission_rate",
            )
        if self.commission_rate != self.commission_rate.quantize(_RATE_STEP):
            raise InvalidValue(
                f"the commission rate {self.commission_rate} has more than 4 decimal places",
                field="commission_rate",
            )
        if not isinstance(self.owner_cleaning_charge, Money):
            raise TypeError("owner_cleaning_charge must be Money")
        if self.owner_cleaning_charge < Money.zero() or not self.owner_cleaning_charge.is_rounded:
            raise InvalidValue(
                f"the cleaning charge {self.owner_cleaning_charge} must be a non-negative "
                "amount in whole cents",
                field="owner_cleaning_charge",
            )
        try:
            require_aware(self.signed_at)
        except ValueError as error:
            raise InvalidValue(
                "the signing time must be timezone-aware", field="signed_at"
            ) from error
        document = self.document.strip()
        if not document.lower().endswith(_CONTRACT_SUFFIX):
            raise InvalidValue(
                f"a signed contract needs its signed PDF, not {document!r}",
                field="contract_document",
            )
        _set(self, "document", document)


def _is_photo(path: str) -> bool:
    """Empty (not uploaded yet) or an image by its extension."""
    return not path or path.lower().endswith(_PHOTO_SUFFIXES)
