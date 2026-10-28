"""CalendarDiff: what one feed changes in the stored reservations of its channel (DOMAIN §6).

A pure function: stored reservations and imported events in, changes out.
"""

from kospm.reservations.domain.diff import calendar_diff
from kospm.reservations.domain.reservation import Reservation
from kospm.reservations.domain.value_objects import Channel, ImportedCalendarEvent
from kospm.shared.domain import new_id
from tests.unit.reservations.builders import DETAILS, TODAY, event, stay


def stored(uid: str, check_in: str, check_out: str) -> Reservation:
    return Reservation(
        new_id(),
        channel=Channel.AIRBNB,
        dates=stay(check_in, check_out),
        check_in_time=DETAILS.check_in_time,
        check_out_time=DETAILS.check_out_time,
        external_uid=uid,
    )


def uids(events: tuple[ImportedCalendarEvent, ...]) -> list[str]:
    return [imported.uid for imported in events]


def test_the_first_import_creates_every_reservation() -> None:
    changes = calendar_diff(
        [], [event("a", "07-12", "07-15"), event("b", "07-20", "07-22")], today=TODAY
    )
    assert uids(changes.new) == ["a", "b"]
    assert (changes.rescheduled, changes.cancelled) == ((), ())


def test_the_same_feed_again_changes_nothing() -> None:
    reservations = [stored("a", "07-12", "07-15"), stored("b", "07-20", "07-22")]
    changes = calendar_diff(
        reservations, [event("a", "07-12", "07-15"), event("b", "07-20", "07-22")], today=TODAY
    )
    assert changes.empty


def test_changed_dates_reschedule_the_reservation() -> None:
    reservation = stored("a", "07-12", "07-15")
    changes = calendar_diff([reservation], [event("a", "07-12", "07-16")], today=TODAY)
    ((rescheduled, imported),) = changes.rescheduled
    assert rescheduled is reservation
    assert imported.dates == stay("07-12", "07-16")
    assert (changes.new, changes.cancelled) == ((), ())


def test_a_stay_in_progress_still_follows_its_feed() -> None:
    reservation = stored("a", "07-08", "07-14")  # the guests leave early
    changes = calendar_diff([reservation], [event("a", "07-08", "07-11")], today=TODAY)
    assert [pair[0] for pair in changes.rescheduled] == [reservation]


def test_a_stay_that_has_ended_never_changes() -> None:
    reservation = stored("a", "07-01", "07-05")
    changes = calendar_diff([reservation], [event("a", "07-01", "07-06")], today=TODAY)
    assert changes.empty


def test_a_removed_future_reservation_is_cancelled() -> None:
    reservation = stored("a", "07-12", "07-15")
    changes = calendar_diff(
        [reservation, stored("b", "07-20", "07-22")], [event("b", "07-20", "07-22")], today=TODAY
    )
    assert changes.cancelled == (reservation,)


def test_a_removed_past_or_current_reservation_is_not_cancelled() -> None:
    reservations = [
        stored("past", "07-01", "07-05"),
        stored("in-progress", "07-08", "07-12"),
        stored("starting-today", "07-10", "07-13"),
    ]
    assert calendar_diff(reservations, [], today=TODAY).empty


def test_a_uid_listed_twice_counts_once() -> None:
    changes = calendar_diff(
        [], [event("a", "07-12", "07-15"), event("a", "07-12", "07-15")], today=TODAY
    )
    assert uids(changes.new) == ["a"]


def test_stored_reservations_without_a_uid_are_not_the_feeds() -> None:
    direct = Reservation(
        new_id(),
        channel=Channel.DIRECT,
        dates=stay("07-12", "07-15"),
        check_in_time=DETAILS.check_in_time,
        check_out_time=DETAILS.check_out_time,
    )
    assert calendar_diff([direct], [], today=TODAY).empty
