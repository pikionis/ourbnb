"""The Django repository of the reservations context against PostgreSQL (Appendix D, ADR 0016)."""

from datetime import UTC, datetime, time

import pytest

from kospm.reservations import models
from kospm.reservations.adapters.repository import calendar_values
from kospm.reservations.adapters.unit_of_work import DjangoReservationsUnitOfWork
from kospm.reservations.domain.calendar import ReservationCalendar, ReviewReason
from kospm.reservations.domain.errors import CalendarNotFound
from kospm.reservations.domain.reservation import ReservationStatus
from kospm.reservations.domain.value_objects import Channel, EventKind
from kospm.shared.clock import FixedClock
from kospm.shared.domain import new_id
from kospm.shared.outbox.adapters import DjangoOutbox
from kospm.shared.unit_of_work import ConcurrencyError
from tests.unit.reservations.builders import NOW, POLICY, PROPERTY_ID, TODAY, calendar, event, stay

pytestmark = pytest.mark.django_db


def new_uow() -> DjangoReservationsUnitOfWork:
    return DjangoReservationsUnitOfWork(
        outbox=DjangoOutbox(FixedClock(datetime(2026, 7, 10, tzinfo=UTC)))
    )


def stored(subject: ReservationCalendar | None = None) -> ReservationCalendar:
    subject = subject or calendar()
    uow = new_uow()
    with uow:
        uow.calendars.add(subject)
        uow.commit()
    return subject


def version() -> int:
    return models.PropertyCalendar.objects.values_list("version", flat=True).get(
        property_id=PROPERTY_ID
    )


def full_calendar() -> ReservationCalendar:
    """Every kind of child: feeds with health, all kinds of reservations, waiting, answers."""
    subject = calendar()
    subject.read_feed(
        Channel.AIRBNB,
        [event("a", "07-12", "07-15", code="HMTEST0001"), event("c", "07-20", "07-22")],
        today=TODAY,
        now=NOW,
        policy=POLICY,
        etag='"v1"',
    )
    subject.read_feed(
        Channel.BOOKING,
        [
            event("b", "07-13", "07-14", kind=EventKind.RESERVATION),  # overlaps a
            event("u1", "08-01", "08-03", kind=EventKind.UNKNOWN),
            event("u2", "08-10", "08-12", kind=EventKind.UNKNOWN),
        ],
        today=TODAY,
        now=NOW,
        policy=POLICY,
    )
    subject.decide(Channel.BOOKING, "u2", EventKind.BLOCK, today=TODAY)
    direct = new_id()
    subject.add_direct_reservation(
        direct, dates=stay("08-20", "08-24"), today=TODAY, guest_name="Γιάννης"
    )
    subject.cancel_direct_reservation(direct)
    subject.feed_failed(Channel.BOOKING, now=NOW, policy=POLICY)
    subject.events.clear()
    return subject


class TestCalendarRepository:
    def test_round_trip_of_the_whole_aggregate(self) -> None:
        saved = stored(full_calendar())
        uow = new_uow()
        with uow:
            loaded = uow.calendars.get(PROPERTY_ID)
        assert calendar_values(loaded) == calendar_values(saved)
        assert [(w.uid, w.reason) for w in loaded.waiting] == [
            ("b", ReviewReason.OVERLAP),
            ("u1", ReviewReason.UNKNOWN),
        ]
        assert loaded.decisions == {(Channel.BOOKING, "u2"): EventKind.BLOCK}
        assert loaded.feed(Channel.AIRBNB).etag == '"v1"'
        assert loaded.feed(Channel.BOOKING).failing_since == NOW

    def test_a_change_to_a_child_bumps_the_version(self) -> None:
        stored()
        uow = new_uow()
        with uow:
            uow.calendars.get(PROPERTY_ID).read_feed(
                Channel.AIRBNB, [event("a", "07-12", "07-15")], today=TODAY, now=NOW, policy=POLICY
            )
            uow.commit()
        assert version() == 1
        assert models.Reservation.objects.filter(calendar_id=PROPERTY_ID).count() == 1

    def test_a_sync_that_changes_nothing_keeps_the_version(self) -> None:
        # Otherwise every 30-minute sync would refuse the admin's open forms (ADR 0016).
        subject = calendar()
        subject.read_feed(
            Channel.AIRBNB, [event("a", "07-12", "07-15")], today=TODAY, now=NOW, policy=POLICY
        )
        stored(subject)
        later = NOW.replace(hour=11)
        uow = new_uow()
        with uow:
            uow.calendars.get(PROPERTY_ID).read_feed(
                Channel.AIRBNB,
                [event("a", "07-12", "07-15")],
                today=TODAY,
                now=later,
                policy=POLICY,
            )
            uow.commit()
        assert version() == 0
        feed = models.CalendarFeed.objects.get(calendar_id=PROPERTY_ID, channel="airbnb")
        assert feed.last_synced_at == later  # still shown to the admin

    def test_a_unit_that_only_reads_writes_nothing(self) -> None:
        stored()
        uow = new_uow()
        with uow:
            uow.calendars.get(PROPERTY_ID)
            uow.commit()
        assert version() == 0

    def test_a_concurrent_change_is_refused_and_rolled_back(self) -> None:
        stored()
        uow = new_uow()
        with uow:
            uow.calendars.get(PROPERTY_ID).add_direct_reservation(
                new_id(), dates=stay("07-13", "07-15"), today=TODAY
            )
            # Another unit (e.g. a sync) saves the calendar in the meantime. Here it runs inside
            # this unit's savepoint, so the rollback undoes it too; what matters is the refusal.
            models.PropertyCalendar.objects.filter(property_id=PROPERTY_ID).update(version=1)
            with pytest.raises(ConcurrencyError):
                uow.commit()
        assert models.Reservation.objects.count() == 0

    def test_a_stale_form_is_refused(self) -> None:
        stored()
        uow = new_uow()
        with uow, pytest.raises(ConcurrencyError):
            uow.calendars.get(PROPERTY_ID, expected_version=3)

    def test_a_cancelled_event_may_come_back_as_a_new_reservation(self) -> None:
        subject = calendar()
        subject.read_feed(
            Channel.AIRBNB,
            [event("a", "07-12", "07-15"), event("c", "07-20", "07-22")],
            today=TODAY,
            now=NOW,
            policy=POLICY,
        )
        stored(subject)
        uow = new_uow()
        with uow:
            loaded = uow.calendars.get(PROPERTY_ID)
            loaded.read_feed(
                Channel.AIRBNB, [event("c", "07-20", "07-22")], today=TODAY, now=NOW, policy=POLICY
            )
            loaded.read_feed(
                Channel.AIRBNB,
                [event("a", "07-12", "07-15"), event("c", "07-20", "07-22")],
                today=TODAY,
                now=NOW,
                policy=POLICY,
            )
            uow.commit()
        statuses = sorted(
            models.Reservation.objects.filter(external_uid="a").values_list("status", flat=True)
        )
        assert statuses == ["cancelled", "confirmed"]

    def test_find_and_get_an_unknown_property(self) -> None:
        uow = new_uow()
        with uow:
            assert uow.calendars.find(PROPERTY_ID) is None
            with pytest.raises(CalendarNotFound):
                uow.calendars.get(PROPERTY_ID)

    def test_times_and_statuses_are_stored_as_they_are(self) -> None:
        subject = calendar()
        reservation_id = new_id()
        subject.add_direct_reservation(
            reservation_id, dates=stay("07-12", "07-14"), today=TODAY, check_in_time=time(13, 30)
        )
        stored(subject)
        row = models.Reservation.objects.get(pk=reservation_id)
        assert (row.check_in_time, row.status, row.channel) == (time(13, 30), "confirmed", "direct")


def test_model_choices_match_the_domain() -> None:
    assert set(models.ChannelChoices.values) == {channel.value for channel in Channel}
    assert set(models.FeedChannelChoices.values) == {
        channel.value for channel in Channel if channel is not Channel.DIRECT
    }
    assert set(models.ReservationStatusChoices.values) == {s.value for s in ReservationStatus}
    assert set(models.ReviewReasonChoices.values) == {r.value for r in ReviewReason}
    assert set(models.DecisionChoices.values) == {
        kind.value for kind in EventKind if kind is not EventKind.UNKNOWN
    }
