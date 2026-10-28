"""The ReservationCalendar aggregate: a property's reservations and its feeds (DOMAIN §6)."""

from dataclasses import replace
from datetime import date, datetime, time, timedelta

import pytest

from kospm.reservations.domain.calendar import (
    Feed,
    ReservationCalendar,
    ReviewReason,
    WaitingEvent,
)
from kospm.reservations.domain.errors import (
    CalendarEventNotWaiting,
    ChangeOnThePlatform,
    FeedNotConfigured,
    InvalidValue,
    OverlappingReservation,
    ReservationNotFound,
)
from kospm.reservations.domain.events import (
    CalendarEventNeedsReview,
    CalendarFeedFailing,
    ReservationCancelled,
    ReservationImported,
    ReservationRescheduled,
    StayEnded,
)
from kospm.reservations.domain.reservation import Reservation
from kospm.reservations.domain.value_objects import (
    Channel,
    EventKind,
    ImportedCalendarEvent,
    StayDates,
)
from kospm.shared.domain import DomainEvent, new_id
from tests.unit.reservations.builders import (
    AIRBNB_URL,
    DETAILS,
    NOW,
    POLICY,
    PROPERTY_ID,
    TODAY,
    calendar,
    day,
    event,
    stay,
)

AIRBNB, BOOKING = Channel.AIRBNB, Channel.BOOKING
UNKNOWN, BLOCK = EventKind.UNKNOWN, EventKind.BLOCK


def read(
    subject: ReservationCalendar,
    channel: Channel,
    *events: ImportedCalendarEvent,
    today: date = TODAY,
    now: datetime = NOW,
    etag: str = "",
) -> list[DomainEvent]:
    """One accepted read of a feed; returns the events it raised."""
    subject.events.clear()
    subject.read_feed(channel, events, today=today, now=now, policy=POLICY, etag=etag)
    return list(subject.events)


def by_uid(subject: ReservationCalendar) -> dict[str, StayDates]:
    """The confirmed reservations from feeds, by event UID."""
    return {
        reservation.external_uid: reservation.dates
        for reservation in subject.reservations
        if reservation.confirmed and reservation.external_uid
    }


def the(subject: ReservationCalendar, uid: str) -> Reservation:
    return next(r for r in subject.reservations if r.external_uid == uid and r.confirmed)


class TestImport:
    def test_the_first_import_creates_reservations_with_the_property_times(self) -> None:
        subject = calendar()

        raised = read(subject, AIRBNB, event("a", "07-12", "07-15", code="HMAAA111"))

        reservation = the(subject, "a")
        assert (reservation.dates, reservation.channel) == (stay("07-12", "07-15"), AIRBNB)
        assert (reservation.check_in_time, reservation.check_out_time) == (time(15), time(11))
        assert reservation.confirmation_code == "HMAAA111"
        assert raised == [
            ReservationImported(
                reservation_id=reservation.id,
                property_id=PROPERTY_ID,
                channel="airbnb",
                check_in_date=day("07-12"),
                check_out_date=day("07-15"),
                check_in_time=time(15),
                check_out_time=time(11),
            )
        ]

    def test_the_same_feed_twice_raises_nothing(self) -> None:
        subject = calendar()
        feed = (event("a", "07-12", "07-15"), event("b", "07-20", "07-22"))
        read(subject, AIRBNB, *feed)
        assert read(subject, AIRBNB, *feed) == []
        assert len(subject.reservations) == 2

    def test_changed_dates_reschedule_the_reservation(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-12", "07-15"))

        raised = read(subject, AIRBNB, event("a", "07-13", "07-16"))

        reservation = the(subject, "a")
        assert reservation.dates == stay("07-13", "07-16")
        assert raised == [
            ReservationRescheduled(
                reservation_id=reservation.id,
                property_id=PROPERTY_ID,
                previous_check_in_date=day("07-12"),
                previous_check_out_date=day("07-15"),
                previous_check_in_time=time(15),
                previous_check_out_time=time(11),
                check_in_date=day("07-13"),
                check_out_date=day("07-16"),
                check_in_time=time(15),
                check_out_time=time(11),
            )
        ]

    def test_a_removed_future_reservation_is_cancelled(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-12", "07-15"), event("b", "07-20", "07-22"))
        cancelled = the(subject, "a")

        raised = read(subject, AIRBNB, event("b", "07-20", "07-22"))

        assert not cancelled.confirmed
        assert raised == [
            ReservationCancelled(
                reservation_id=cancelled.id,
                property_id=PROPERTY_ID,
                check_in_date=day("07-12"),
                check_out_date=day("07-15"),
            )
        ]

    def test_a_removed_stay_in_progress_or_starting_today_is_kept(self) -> None:
        subject = calendar()
        read(
            subject,
            AIRBNB,
            event("leaving-today", "07-08", "07-10"),
            event("arriving-today", "07-10", "07-12"),
            event("later", "07-20", "07-22"),
            today=day("07-07"),
        )
        assert read(subject, AIRBNB, event("later", "07-20", "07-22")) == []
        assert set(by_uid(subject)) == {"leaving-today", "arriving-today", "later"}

    def test_blocks_are_ignored(self) -> None:
        subject = calendar()
        assert read(subject, AIRBNB, event("x", "07-12", "07-15", kind=BLOCK)) == []
        assert subject.reservations == ()

    def test_one_night_and_a_booking_for_today_are_imported(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("one-night", "07-20", "07-21"), event("now", "07-10", "07-12"))
        assert set(by_uid(subject)) == {"one-night", "now"}

    def test_a_stay_first_seen_after_it_ended_is_recorded_without_an_event(self) -> None:
        subject = calendar()
        assert read(subject, AIRBNB, event("old", "07-01", "07-05")) == []
        old = the(subject, "old")
        assert old.stay_ended
        subject.end_stays(TODAY)
        assert subject.events == []  # never announced: it ended before it was known


class TestOverlaps:
    def test_the_check_out_day_may_be_the_next_check_in_day(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-12", "07-15"))
        read(subject, BOOKING, event("b", "07-15", "07-18"))
        assert set(by_uid(subject)) == {"a", "b"}
        subject.accept(stay("07-18", "07-20"))

    def test_an_overlapping_reservation_waits_and_is_not_saved(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-12", "07-15"))

        raised = read(subject, BOOKING, event("b", "07-14", "07-16"))

        assert set(by_uid(subject)) == {"a"}
        assert subject.waiting == (
            WaitingEvent(BOOKING, "b", stay("07-14", "07-16"), ReviewReason.OVERLAP),
        )
        assert raised == [
            CalendarEventNeedsReview(
                property_id=PROPERTY_ID,
                channel="booking",
                uid="b",
                check_in_date=day("07-14"),
                check_out_date=day("07-16"),
                reason="overlap",
            )
        ]

    def test_a_waiting_overlap_alerts_once(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-12", "07-15"))
        read(subject, BOOKING, event("b", "07-14", "07-16"))
        assert read(subject, BOOKING, event("b", "07-14", "07-16")) == []

    def test_it_is_imported_once_the_double_booking_is_resolved(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-12", "07-15"), event("c", "07-20", "07-22"))
        read(subject, BOOKING, event("b", "07-14", "07-16"))
        read(subject, AIRBNB, event("c", "07-20", "07-22"))  # the Airbnb guest went elsewhere

        raised = read(subject, BOOKING, event("b", "07-14", "07-16"))

        assert set(by_uid(subject)) == {"b", "c"}
        assert subject.waiting == ()
        assert [type(e) for e in raised] == [ReservationImported]

    def test_a_reschedule_into_another_stay_waits_and_keeps_the_old_dates(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-12", "07-15"))
        read(subject, BOOKING, event("b", "07-16", "07-18"))

        read(subject, BOOKING, event("b", "07-14", "07-18"))

        assert the(subject, "b").dates == stay("07-16", "07-18")
        assert [(w.uid, w.reason) for w in subject.waiting] == [("b", ReviewReason.OVERLAP)]

    def test_a_cancellation_frees_its_nights_in_the_same_read(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-12", "07-15"), event("b", "07-20", "07-22"))

        read(subject, AIRBNB, event("b", "07-13", "07-15"))  # a cancelled, b moved into its nights

        assert by_uid(subject) == {"b": stay("07-13", "07-15")}

    def test_accept_refuses_a_stay_that_shares_a_night(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-12", "07-15"))
        with pytest.raises(OverlappingReservation) as refused:
            subject.accept(stay("07-14", "07-16"))
        assert refused.value.overlapping == (the(subject, "a").id,)


class TestUnknownEvents:
    def test_an_unknown_event_waits_for_the_admin_once(self) -> None:
        subject = calendar()

        first = read(subject, BOOKING, event("b", "07-20", "07-22", kind=UNKNOWN))
        again = read(subject, BOOKING, event("b", "07-20", "07-22", kind=UNKNOWN))

        assert subject.reservations == ()
        assert [(e.uid, e.reason) for e in first if isinstance(e, CalendarEventNeedsReview)] == [
            ("b", "unknown")
        ]
        assert again == []

    def test_the_answer_reservation_imports_it_and_is_remembered(self) -> None:
        subject = calendar()
        read(subject, BOOKING, event("b", "07-20", "07-22", kind=UNKNOWN))
        subject.events.clear()

        subject.decide(BOOKING, "b", EventKind.RESERVATION, today=TODAY)

        assert [type(e) for e in subject.events] == [ReservationImported]
        assert subject.waiting == ()
        assert read(subject, BOOKING, event("b", "07-20", "07-22", kind=UNKNOWN)) == []
        assert set(by_uid(subject)) == {"b"}

    def test_the_answer_block_is_remembered(self) -> None:
        subject = calendar()
        read(subject, BOOKING, event("x", "07-20", "07-22", kind=UNKNOWN))
        subject.decide(BOOKING, "x", BLOCK, today=TODAY)
        assert read(subject, BOOKING, event("x", "07-20", "07-23", kind=UNKNOWN)) == []
        assert (subject.reservations, subject.waiting) == ((), ())

    def test_the_mirror_of_another_channels_reservation_is_a_block(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-12", "07-15"))
        assert read(subject, BOOKING, event("mirror", "07-12", "07-15", kind=UNKNOWN)) == []
        assert subject.waiting == ()

    def test_the_mirror_rule_is_across_channels_only(self) -> None:
        subject = calendar()
        read(subject, BOOKING, event("b", "07-20", "07-22", kind=UNKNOWN))
        subject.decide(BOOKING, "b", EventKind.RESERVATION, today=TODAY)

        read(
            subject,
            BOOKING,
            event("b", "07-20", "07-22", kind=UNKNOWN),
            event("c", "07-20", "07-22", kind=UNKNOWN),  # same channel, same dates: no mirror
        )

        assert [(w.uid, w.reason) for w in subject.waiting] == [("c", ReviewReason.UNKNOWN)]

    def test_a_uid_listed_twice_waits_once(self) -> None:
        subject = calendar()
        raised = read(
            subject,
            BOOKING,
            event("b", "07-20", "07-22", kind=UNKNOWN),
            event("b", "07-20", "07-22", kind=UNKNOWN),
        )
        assert len(subject.waiting) == 1
        assert len(raised) == 1

    def test_an_unknown_event_of_a_stay_that_has_ended_is_not_asked_about(self) -> None:
        subject = calendar()
        assert read(subject, BOOKING, event("old", "07-01", "07-05", kind=UNKNOWN)) == []

    def test_a_reservation_answer_that_overlaps_waits_as_an_overlap(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-20", "07-23"))
        read(subject, BOOKING, event("b", "07-21", "07-24", kind=UNKNOWN))
        subject.events.clear()

        subject.decide(BOOKING, "b", EventKind.RESERVATION, today=TODAY)

        assert [(w.uid, w.reason) for w in subject.waiting] == [("b", ReviewReason.OVERLAP)]
        assert [type(e) for e in subject.events] == [CalendarEventNeedsReview]

    def test_only_a_waiting_unknown_event_is_answered(self) -> None:
        with pytest.raises(CalendarEventNotWaiting):
            calendar().decide(BOOKING, "nothing", EventKind.RESERVATION, today=TODAY)

    def test_the_answer_is_a_reservation_or_a_block(self) -> None:
        subject = calendar()
        read(subject, BOOKING, event("b", "07-20", "07-22", kind=UNKNOWN))
        with pytest.raises(InvalidValue):
            subject.decide(BOOKING, "b", UNKNOWN, today=TODAY)


class TestFeedHealth:
    def test_a_failed_read_changes_nothing(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-12", "07-15"))
        subject.events.clear()

        subject.feed_failed(AIRBNB, now=NOW, policy=POLICY)

        assert subject.events == []
        assert set(by_uid(subject)) == {"a"}
        assert subject.feed(AIRBNB).failing_since == NOW

    def test_an_empty_feed_with_future_reservations_fails_and_cancels_nothing(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-12", "07-15"))

        assert read(subject, AIRBNB) == []

        assert set(by_uid(subject)) == {"a"}
        assert subject.feed(AIRBNB).failing

    def test_an_empty_feed_without_future_reservations_is_fine(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("in-progress", "07-08", "07-12"), today=day("07-07"))
        read(subject, AIRBNB)
        assert not subject.feed(AIRBNB).failing

    def test_failing_for_the_threshold_alerts_exactly_once(self) -> None:
        subject = calendar()
        raised: list[DomainEvent] = []
        for minutes in (0, 30, 60, 90, 120, 150, 180):
            subject.feed_failed(AIRBNB, now=NOW + timedelta(minutes=minutes), policy=POLICY)
            raised += subject.events
            subject.events.clear()
        assert raised == [CalendarFeedFailing(property_id=PROPERTY_ID, channel="airbnb", since=NOW)]

    def test_a_new_incident_after_recovery_alerts_again(self) -> None:
        subject = calendar()
        for hours in (0, 2):
            subject.feed_failed(AIRBNB, now=NOW + timedelta(hours=hours), policy=POLICY)
        read(subject, AIRBNB, now=NOW + timedelta(hours=3))  # recovered: the incident ends
        assert not subject.feed(AIRBNB).failing

        later = NOW + timedelta(hours=10)
        for hours in (0, 2):
            subject.feed_failed(AIRBNB, now=later + timedelta(hours=hours), policy=POLICY)

        assert subject.events == [
            CalendarFeedFailing(property_id=PROPERTY_ID, channel="airbnb", since=later)
        ]

    def test_not_modified_is_a_success(self) -> None:
        subject = calendar()
        subject.feed_failed(AIRBNB, now=NOW, policy=POLICY)
        subject.feed_unchanged(AIRBNB, now=NOW + timedelta(minutes=30))
        assert not subject.feed(AIRBNB).failing
        assert subject.feed(AIRBNB).last_synced_at == NOW + timedelta(minutes=30)

    def test_not_modified_ends_the_incident_and_a_new_one_alerts_again(self) -> None:
        subject = calendar()
        for hours in (0, 2):
            subject.feed_failed(AIRBNB, now=NOW + timedelta(hours=hours), policy=POLICY)
        subject.feed_unchanged(AIRBNB, now=NOW + timedelta(hours=3))
        subject.events.clear()

        later = NOW + timedelta(hours=10)
        for hours in (0, 2):
            subject.feed_failed(AIRBNB, now=later + timedelta(hours=hours), policy=POLICY)

        assert subject.events == [
            CalendarFeedFailing(property_id=PROPERTY_ID, channel="airbnb", since=later)
        ]

    def test_not_modified_disarms_the_empty_calendar_confirmation(self) -> None:
        # The feed has its earlier content again: a later empty read is a failure, as before.
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-12", "07-15"))
        subject.confirm_empty_calendar(AIRBNB)
        subject.feed_unchanged(AIRBNB, now=NOW)
        read(subject, AIRBNB)
        assert set(by_uid(subject)) == {"a"}

    def test_the_admin_confirms_an_empty_calendar(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-12", "07-15"), event("past", "07-01", "07-05"))
        cancelled = the(subject, "a")
        read(subject, AIRBNB)  # refused: future reservations would go

        subject.confirm_empty_calendar(AIRBNB)
        raised = read(subject, AIRBNB)

        assert [type(e) for e in raised] == [ReservationCancelled]
        assert not cancelled.confirmed
        assert set(by_uid(subject)) == {"past"}
        assert not subject.feed(AIRBNB).failing

    def test_the_confirmation_counts_for_the_next_accepted_read_only(self) -> None:
        subject = calendar()
        subject.confirm_empty_calendar(AIRBNB)
        read(subject, AIRBNB, event("a", "07-12", "07-15"))
        assert not subject.feed(AIRBNB).accept_empty
        read(subject, AIRBNB)
        assert set(by_uid(subject)) == {"a"}

    def test_only_an_accepted_read_keeps_its_etag(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-12", "07-15"), etag='"v1"')
        read(subject, AIRBNB, etag='"v2-empty"')  # refused
        assert subject.feed(AIRBNB).etag == '"v1"'


class TestTheAdmin:
    def test_a_direct_reservation_takes_the_property_times(self) -> None:
        subject = calendar()
        reservation_id = new_id()

        subject.add_direct_reservation(
            reservation_id, dates=stay("07-20", "07-23"), guest_name=" Γιάννης ", today=TODAY
        )

        reservation = subject.reservation(reservation_id)
        assert (reservation.channel, reservation.guest_name) == (Channel.DIRECT, "Γιάννης")
        assert (reservation.check_in_time, reservation.check_out_time) == (time(15), time(11))
        assert [type(e) for e in subject.events] == [ReservationImported]

    def test_a_direct_reservation_never_overlaps(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-20", "07-23"))
        with pytest.raises(OverlappingReservation):
            subject.add_direct_reservation(new_id(), dates=stay("07-22", "07-24"), today=TODAY)
        assert len(subject.reservations) == 1

    def test_the_admin_changes_the_times_and_the_guest_name(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-20", "07-23"))
        reservation = the(subject, "a")
        subject.events.clear()

        subject.change_reservation(
            reservation.id,
            dates=reservation.dates,
            check_in_time=time(13),
            check_out_time=time(11),
            guest_name="Anna",
            today=TODAY,
        )

        assert (reservation.check_in_time, reservation.guest_name) == (time(13), "Anna")
        (rescheduled,) = subject.events
        assert isinstance(rescheduled, ReservationRescheduled)
        assert (rescheduled.previous_check_in_time, rescheduled.check_in_time) == (
            time(15),
            time(13),
        )

    def test_only_the_guest_name_raises_nothing(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-20", "07-23"))
        reservation = the(subject, "a")
        subject.events.clear()
        subject.change_reservation(
            reservation.id,
            dates=reservation.dates,
            check_in_time=time(15),
            check_out_time=time(11),
            guest_name="Anna",
            today=TODAY,
        )
        assert subject.events == []

    def test_the_dates_of_a_feed_reservation_change_on_the_platform(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-20", "07-23"))
        reservation = the(subject, "a")
        with pytest.raises(ChangeOnThePlatform):
            subject.change_reservation(
                reservation.id,
                dates=stay("07-21", "07-23"),
                check_in_time=time(15),
                check_out_time=time(11),
                guest_name="",
                today=TODAY,
            )
        with pytest.raises(ChangeOnThePlatform):
            subject.cancel_direct_reservation(reservation.id)
        assert reservation.dates == stay("07-20", "07-23")

    def test_the_admin_moves_and_cancels_a_direct_reservation(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-20", "07-23"))
        reservation_id = new_id()
        subject.add_direct_reservation(reservation_id, dates=stay("07-12", "07-14"), today=TODAY)

        with pytest.raises(OverlappingReservation):
            subject.change_reservation(
                reservation_id,
                dates=stay("07-12", "07-21"),
                check_in_time=time(15),
                check_out_time=time(11),
                guest_name="",
                today=TODAY,
            )
        subject.change_reservation(
            reservation_id,
            dates=stay("07-12", "07-15"),
            check_in_time=time(15),
            check_out_time=time(11),
            guest_name="",
            today=TODAY,
        )
        subject.cancel_direct_reservation(reservation_id)

        assert subject.reservation(reservation_id).dates == stay("07-12", "07-15")
        assert not subject.reservation(reservation_id).confirmed
        assert isinstance(subject.events[-1], ReservationCancelled)

    def test_a_cancelled_reservation_is_not_changed(self) -> None:
        subject = calendar()
        reservation_id = new_id()
        subject.add_direct_reservation(reservation_id, dates=stay("07-12", "07-14"), today=TODAY)
        subject.cancel_direct_reservation(reservation_id)
        with pytest.raises(ReservationNotFound):
            subject.cancel_direct_reservation(reservation_id)

    def test_an_unknown_reservation_is_not_found(self) -> None:
        with pytest.raises(ReservationNotFound):
            calendar().reservation(new_id())


class TestStayEnded:
    def test_announced_once_on_the_check_out_day(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-08", "07-10"), today=day("07-07"))
        reservation = the(subject, "a")
        subject.events.clear()

        subject.end_stays(TODAY)
        subject.end_stays(TODAY)

        assert subject.events == [
            StayEnded(reservation_id=reservation.id, property_id=PROPERTY_ID, check_out_date=TODAY)
        ]

    def test_a_stay_extended_after_it_ended_ends_again_on_its_new_date(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-08", "07-10"), today=day("07-07"))
        subject.end_stays(TODAY)  # 12:00: the guests leave today
        read(subject, AIRBNB, event("a", "07-08", "07-12"))  # 12:30: they stay two more nights
        reservation = the(subject, "a")
        assert not reservation.stay_ended
        subject.events.clear()

        subject.end_stays(day("07-12"))

        assert subject.events == [
            StayEnded(
                reservation_id=reservation.id, property_id=PROPERTY_ID, check_out_date=day("07-12")
            )
        ]

    def test_a_missed_day_is_caught_up(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-05", "07-08"), today=day("07-04"))
        subject.events.clear()
        subject.end_stays(TODAY)
        assert [type(e) for e in subject.events] == [StayEnded]

    def test_future_and_cancelled_stays_are_not_announced(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("future", "07-12", "07-15"))
        reservation_id = new_id()
        subject.add_direct_reservation(
            reservation_id, dates=stay("07-08", "07-10"), today=day("07-07")
        )
        subject.cancel_direct_reservation(reservation_id)
        subject.events.clear()
        subject.end_stays(TODAY)
        assert subject.events == []


class TestSettings:
    def test_a_new_feed_url_starts_a_new_history(self) -> None:
        subject = calendar()
        subject.feed_failed(AIRBNB, now=NOW, policy=POLICY)

        subject.update_settings(
            DETAILS, {AIRBNB: AIRBNB_URL + "&new", BOOKING: "https://b.example/1"}
        )

        assert subject.feed(AIRBNB) == Feed(AIRBNB, AIRBNB_URL + "&new")
        assert subject.feed(BOOKING).url == "https://b.example/1"

    def test_reactivation_starts_the_feeds_health_afresh(self) -> None:
        subject = calendar()
        for hours in (0, 2):
            subject.feed_failed(AIRBNB, now=NOW + timedelta(hours=hours), policy=POLICY)
        feeds = {AIRBNB: AIRBNB_URL, BOOKING: subject.feed(BOOKING).url}
        subject.update_settings(replace(DETAILS, active=False), feeds)

        subject.update_settings(DETAILS, feeds)

        assert not subject.feed(AIRBNB).failing
        assert not subject.feed(AIRBNB).alerted

    def test_the_same_url_keeps_its_history(self) -> None:
        subject = calendar()
        subject.feed_failed(AIRBNB, now=NOW, policy=POLICY)
        subject.update_settings(replace(DETAILS, name="Villa Elena II"), {AIRBNB: AIRBNB_URL})
        assert subject.feed(AIRBNB).failing
        assert subject.details.name == "Villa Elena II"

    def test_a_removed_feed_keeps_its_reservations_and_drops_its_waiting_events(self) -> None:
        subject = calendar()
        read(subject, AIRBNB, event("a", "07-12", "07-15"))
        read(subject, BOOKING, event("b", "07-20", "07-22", kind=UNKNOWN))

        subject.update_settings(DETAILS, {AIRBNB: AIRBNB_URL})

        with pytest.raises(FeedNotConfigured):
            subject.feed(BOOKING)
        assert subject.waiting == ()
        assert set(by_uid(subject)) == {"a"}

    def test_direct_has_no_feed(self) -> None:
        with pytest.raises(InvalidValue):
            Feed(Channel.DIRECT, "https://example.com/direct.ics")

    def test_reading_a_channel_without_a_feed(self) -> None:
        subject = ReservationCalendar(PROPERTY_ID, details=DETAILS)
        with pytest.raises(FeedNotConfigured):
            subject.read_feed(AIRBNB, [], today=TODAY, now=NOW, policy=POLICY)

    def test_only_an_active_property_is_synced(self) -> None:
        assert calendar().syncs
        assert not calendar(details=replace(DETAILS, active=False)).syncs
