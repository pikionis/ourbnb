"""Value objects of the properties context: validated when created, compared by value."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from kospm.properties.domain.errors import InvalidValue
from kospm.properties.domain.value_objects import (
    Afm,
    Amenities,
    Contract,
    Email,
    GeoPoint,
    Iban,
    IcalChannel,
    IcalFeed,
    PropertyCode,
)
from kospm.shared.domain import Money
from tests.unit.properties.builders import (
    OTHER_VALID_AFM,
    VALID_AFM,
    VALID_IBAN,
    complete_guide,
    signed_contract,
)


class TestPropertyCode:
    def test_is_normalised_to_upper_case(self) -> None:
        assert PropertyCode(" kos-a1 ").value == "KOS-A1"
        assert PropertyCode("kos-a1") == PropertyCode("KOS-A1")

    @pytest.mark.parametrize(
        "raw", ["", "A", "KOS A1", "KOS--A1", "-KOS", "KOS-", "KOS_A1", "ΚΩΣ-1", "A" * 17]
    )
    def test_rejects_malformed_codes(self, raw: str) -> None:
        with pytest.raises(InvalidValue):
            PropertyCode(raw)


class TestAfm:
    @pytest.mark.parametrize("raw", [VALID_AFM, OTHER_VALID_AFM, " 090 000 045 "])
    def test_accepts_nine_digits_with_a_valid_check_digit(self, raw: str) -> None:
        assert len(Afm(raw).value) == 9

    @pytest.mark.parametrize(
        "raw", ["", "123456789", "12345678", "0900000450", "09000004A", "000000000"]
    )
    def test_rejects_anything_else(self, raw: str) -> None:
        with pytest.raises(InvalidValue):
            Afm(raw)


class TestEmail:
    def test_is_normalised(self) -> None:
        assert Email("  Maria@Example.COM ").value == "maria@example.com"

    @pytest.mark.parametrize(
        "raw", ["", "maria", "maria@", "@example.com", "ma ria@example.com", "maria@example"]
    )
    def test_rejects_malformed_addresses(self, raw: str) -> None:
        with pytest.raises(InvalidValue):
            Email(raw)


class TestIban:
    def test_accepts_a_valid_iban_written_with_spaces_or_lower_case(self) -> None:
        assert Iban(VALID_IBAN).value == "GR1601101250000000012300695"
        assert Iban(VALID_IBAN.lower()) == Iban(VALID_IBAN)

    def test_formats_in_groups_of_four(self) -> None:
        assert Iban(VALID_IBAN).formatted() == "GR16 0110 1250 0000 0001 2300 695"

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "GR16",
            "GR16 0110 1250 0000 0001 2300 696",  # one digit off: the mod-97 check fails
            "16GR 0110 1250 0000 0001 2300 695",
            "GR16-0110-1250-0000-0001-2300-695",
        ],
    )
    def test_rejects_an_invalid_iban(self, raw: str) -> None:
        with pytest.raises(InvalidValue):
            Iban(raw)


class TestGeoPoint:
    def test_holds_decimal_coordinates(self) -> None:
        point = GeoPoint(lat=Decimal("36.8933"), lng=Decimal("27.2889"))
        assert point.lat == Decimal("36.8933")

    @pytest.mark.parametrize(("lat", "lng"), [("90.1", "27"), ("-90.1", "27"), ("36", "180.5")])
    def test_rejects_coordinates_off_the_globe(self, lat: str, lng: str) -> None:
        with pytest.raises(InvalidValue):
            GeoPoint(lat=Decimal(lat), lng=Decimal(lng))

    def test_rejects_floats(self) -> None:
        with pytest.raises(TypeError):
            GeoPoint(lat=36.8933, lng=Decimal("27.2889"))  # type: ignore[arg-type]


class TestIcalFeed:
    def test_takes_the_channel_by_name(self) -> None:
        feed = IcalFeed(channel="booking", url="https://admin.booking.com/ical/1.ics")  # type: ignore[arg-type]
        assert feed.channel is IcalChannel.BOOKING

    @pytest.mark.parametrize(
        "url", ["", "http://www.airbnb.com/calendar/ical/1.ics", "airbnb.com/1.ics", "https://a b"]
    )
    def test_accepts_only_https_urls(self, url: str) -> None:
        with pytest.raises(InvalidValue):
            IcalFeed(channel=IcalChannel.AIRBNB, url=url)


class TestAmenities:
    def test_trims_drops_blanks_and_duplicates_keeping_order(self) -> None:
        amenities = Amenities(included=(" Wi-Fi ", "", "Wi-Fi", "Κλιματισμός"))
        assert amenities.included == ("Wi-Fi", "Κλιματισμός")

    def test_an_item_cannot_be_both_included_and_not_included(self) -> None:
        with pytest.raises(InvalidValue):
            Amenities(included=("Πισίνα",), not_included=("Πισίνα",))


class TestCheckInGuide:
    def test_never_shows_lockbox_codes_in_its_repr(self) -> None:
        guide = complete_guide(guest_lockbox_code="4711", cleaner_lockbox_code="9090")
        assert "4711" not in repr(guide)
        assert "9090" not in repr(guide)

    def test_cleaners_use_the_guests_code_unless_they_have_their_own(self) -> None:
        assert complete_guide(guest_lockbox_code="4711").cleaners_lockbox_code == "4711"
        assert (
            complete_guide(
                guest_lockbox_code="4711", cleaner_lockbox_code="9090"
            ).cleaners_lockbox_code
            == "9090"
        )

    @pytest.mark.parametrize("name", ["photos/door.JPG", "photos/door.jpeg", "door.png", "a.heic"])
    def test_photos_are_images(self, name: str) -> None:
        assert complete_guide(exterior_photo=name, lockbox_photo=name).exterior_photo == name

    @pytest.mark.parametrize("field", ["exterior_photo", "lockbox_photo"])
    def test_a_photo_that_is_not_an_image_is_refused(self, field: str) -> None:
        with pytest.raises(InvalidValue) as refused:
            complete_guide(**{field: "photos/door.pdf"})
        assert refused.value.field == field


class TestContract:
    def test_a_signed_contract_needs_the_signed_document(self) -> None:
        with pytest.raises(InvalidValue):
            signed_contract(document="")

    @pytest.mark.parametrize("document", ["contracts/signed.docx", "contracts/signed", "a.pdf.exe"])
    def test_the_signed_document_is_a_pdf(self, document: str) -> None:
        with pytest.raises(InvalidValue) as refused:
            signed_contract(document=document)
        assert refused.value.field == "contract_document"
        assert signed_contract(document="contracts/Signed.PDF").document == "contracts/Signed.PDF"

    @pytest.mark.parametrize("rate", [Decimal("-0.01"), Decimal("1"), Decimal("1.5")])
    def test_the_commission_rate_is_a_fraction_below_one(self, rate: Decimal) -> None:
        with pytest.raises(InvalidValue):
            signed_contract(commission_rate=rate)

    def test_the_commission_rate_is_never_a_float(self) -> None:
        with pytest.raises(TypeError):
            signed_contract(commission_rate=0.15)

    @pytest.mark.parametrize("charge", [Money("-1.00"), Money("40.005")])
    def test_the_cleaning_charge_is_a_non_negative_amount_in_cents(self, charge: Money) -> None:
        with pytest.raises(InvalidValue):
            signed_contract(owner_cleaning_charge=charge)

    def test_the_signing_time_is_timezone_aware(self) -> None:
        with pytest.raises(InvalidValue):
            signed_contract(signed_at=datetime(2026, 10, 20, 9, 30))  # noqa: DTZ001

    def test_is_a_value(self) -> None:
        assert signed_contract() == signed_contract()
        assert Contract(
            commission_rate=Decimal("0.15"),
            owner_cleaning_charge=Money("40.00"),
            signed_at=datetime(2026, 10, 20, 9, 30, tzinfo=UTC),
            document="contracts/a.pdf",
        ) != signed_contract(document="contracts/b.pdf")


def test_stored_precision_is_never_silently_rounded() -> None:
    with pytest.raises(InvalidValue) as rate:
        signed_contract(commission_rate=Decimal("0.15005"))
    with pytest.raises(InvalidValue) as point:
        GeoPoint(lat=Decimal("36.8933001"), lng=Decimal("27.2889"))
    assert (rate.value.field, point.value.field) == ("commission_rate", "location")
    assert signed_contract(commission_rate=Decimal("0.15000")).commission_rate == Decimal("0.15")


@pytest.mark.parametrize(
    ("make", "field"),
    [
        (lambda: PropertyCode("K"), "code"),
        (lambda: Afm("123456789"), "afm"),
        (lambda: Email("x"), "email"),
        (lambda: Iban("GR16"), "iban"),
        (lambda: IcalFeed(channel=IcalChannel.AIRBNB, url="http://x.y"), "ical_feeds"),
        (lambda: Amenities(included=("A",), not_included=("A",)), "amenities"),
        (lambda: signed_contract(document=" "), "contract_document"),
    ],
)
def test_invalid_values_name_their_field(make: Any, field: str) -> None:
    with pytest.raises(InvalidValue) as refused:
        make()
    assert refused.value.field == field
