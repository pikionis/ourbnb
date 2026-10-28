"""Value objects of the reservations context (DOMAIN §6)."""

import pytest

from kospm.reservations.domain.errors import InvalidValue
from kospm.reservations.domain.value_objects import EventKind, ImportedCalendarEvent
from tests.unit.reservations.builders import TODAY, day, stay


class TestStayDates:
    def test_counts_the_nights(self) -> None:
        assert stay("07-12", "07-15").nights == 3

    def test_one_night_is_a_stay(self) -> None:
        assert stay("07-12", "07-13").nights == 1  # no minimum stay is assumed (DOMAIN §6)

    @pytest.mark.parametrize(("check_in", "check_out"), [("07-12", "07-12"), ("07-12", "07-11")])
    def test_a_stay_ends_after_it_starts(self, check_in: str, check_out: str) -> None:
        with pytest.raises(InvalidValue) as refused:
            stay(check_in, check_out)
        assert refused.value.field == "dates"

    def test_the_check_out_day_may_be_the_next_check_in_day(self) -> None:
        assert not stay("07-12", "07-15").overlaps(stay("07-15", "07-18"))
        assert not stay("07-15", "07-18").overlaps(stay("07-12", "07-15"))

    @pytest.mark.parametrize(
        "other",
        [("07-14", "07-16"), ("07-10", "07-13"), ("07-13", "07-14"), ("07-11", "07-20")],
    )
    def test_stays_that_share_a_night_overlap(self, other: tuple[str, str]) -> None:
        assert stay("07-12", "07-15").overlaps(stay(*other))
        assert stay(*other).overlaps(stay("07-12", "07-15"))

    def test_a_stay_has_ended_once_its_check_out_day_is_past(self) -> None:
        assert stay("07-05", "07-09").has_ended(TODAY)
        assert not stay("07-05", "07-10").has_ended(TODAY)  # leaving today: not yet ended

    def test_starts_after_today(self) -> None:
        assert stay("07-11", "07-12").starts_after(TODAY)
        assert not stay("07-10", "07-12").starts_after(TODAY)  # starting today


class TestImportedCalendarEvent:
    def test_has_a_uid(self) -> None:
        with pytest.raises(InvalidValue) as refused:
            ImportedCalendarEvent(uid=" ", dates=stay("07-12", "07-15"), kind=EventKind.BLOCK)
        assert refused.value.field == "uid"

    def test_keeps_only_what_the_sync_needs(self) -> None:
        imported = ImportedCalendarEvent(
            uid="abc@airbnb.com",
            dates=stay("07-12", "07-15"),
            kind=EventKind.RESERVATION,
            confirmation_code="HMABC123",
        )
        assert (imported.dates.check_in, imported.confirmation_code) == (day("07-12"), "HMABC123")
