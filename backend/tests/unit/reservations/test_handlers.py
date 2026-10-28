"""Handlers of the reservations context, driven through the real bus with fakes (Cosmic Python
ch. 5): properties' announcements, feed syncs, the admin's commands and alerts."""

import logging
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest

from kospm.bootstrap import ContextWiring, bootstrap
from kospm.reservations.adapters.alerts import OutboxAdminAlerts
from kospm.reservations.domain.commands import (
    AddDirectReservation,
    CancelDirectReservation,
    ChangeReservation,
    ConfirmEmptyCalendar,
    DecideCalendarEvent,
    EndStays,
    SyncCalendarFeed,
    UpdatePropertyCalendar,
)
from kospm.reservations.domain.errors import CalendarNotFound, InvalidValue
from kospm.reservations.domain.policies import FeedHealthPolicy
from kospm.reservations.domain.value_objects import Channel, EventKind
from kospm.reservations.service_layer.handlers import COMMAND_HANDLERS, EVENT_HANDLERS
from kospm.reservations.service_layer.ports import FeedUnreadable, FetchedFeed
from kospm.shared.clock import FixedClock
from kospm.shared.domain import new_id
from kospm.shared.messagebus import MessageBus
from kospm.shared.outbox.domain import OutboxChannel
from tests.unit.reservations.builders import AIRBNB_URL, BOOKING_URL, PROPERTY_ID, day, event
from tests.unit.reservations.fakes import (
    FakeICalFetcher,
    FakeICalParser,
    FakeReservationsUnitOfWork,
)

NOW = datetime(2026, 7, 10, 6, 0, tzinfo=UTC)  # 09:00 in Athens
ADMIN = "+306900000000"


class Harness:
    """A bus wired with the reservations handlers, a fake Unit of Work and fake feeds."""

    def __init__(self, *, admin_whatsapp: str = ADMIN) -> None:
        self.uow = FakeReservationsUnitOfWork()
        self.fetcher = FakeICalFetcher()
        self.parser = FakeICalParser()
        self.clock = FixedClock(NOW)
        self.bus: MessageBus = bootstrap(
            clock=self.clock,
            contexts=[
                ContextWiring(
                    name="reservations",
                    uow=self.uow,
                    command_handlers=COMMAND_HANDLERS,
                    event_handlers=EVENT_HANDLERS,
                    dependencies={
                        "ical_fetcher": self.fetcher,
                        "ical_parser": self.parser,
                        "feed_health": FeedHealthPolicy(),
                        "admin_alerts": OutboxAdminAlerts(whatsapp_number=admin_whatsapp),
                    },
                )
            ],
        )

    def property_announced(self, *, active: bool = True, **overrides: Any) -> None:
        values: dict[str, Any] = {
            "property_id": PROPERTY_ID,
            "code": "KOS-001",
            "name": "Villa Elena",
            "active": active,
            "check_in_time": time(15),
            "check_out_time": time(11),
            "feeds": (("airbnb", AIRBNB_URL), ("booking", BOOKING_URL)),
        }
        values.update(overrides)
        self.bus.handle(UpdatePropertyCalendar(**values))

    def feed(self, url: str, content: bytes, *events: Any, etag: str = "") -> None:
        """The next fetch of `url` answers `content`, which parses to `events`."""
        self.fetcher.answers[url] = FetchedFeed(content=content, etag=etag)
        self.parser.feeds[content] = list(events)

    def sync(self, channel: str = "airbnb") -> None:
        self.bus.handle(SyncCalendarFeed(property_id=PROPERTY_ID, channel=channel))

    def calendar(self) -> Any:
        (calendar,) = self.uow.calendars.all()
        return calendar

    def confirmed_uids(self) -> set[str | None]:
        return {r.external_uid for r in self.calendar().reservations if r.confirmed}

    @property
    def whatsapp_sent(self) -> list[Any]:
        return [m for m in self.uow.outbox.sent if m.channel is OutboxChannel.WHATSAPP]


@pytest.fixture
def harness() -> Harness:
    return Harness()


class TestPropertyCopy:
    def test_the_first_announcement_creates_the_calendar(self, harness: Harness) -> None:
        harness.property_announced()
        calendar = harness.calendar()
        assert (calendar.id, calendar.details.code, calendar.syncs) == (
            PROPERTY_ID,
            "KOS-001",
            True,
        )
        assert [feed.url for feed in calendar.feeds] == [AIRBNB_URL, BOOKING_URL]

    def test_a_later_announcement_updates_it(self, harness: Harness) -> None:
        harness.property_announced()
        harness.property_announced(active=False, name="Villa Elena II", feeds=())
        calendar = harness.calendar()
        assert (calendar.details.name, calendar.syncs, calendar.feeds) == (
            "Villa Elena II",
            False,
            (),
        )


class TestSync:
    def test_a_feed_is_fetched_parsed_and_applied(self, harness: Harness) -> None:
        harness.property_announced()
        harness.feed(AIRBNB_URL, b"airbnb-1", event("a", "07-12", "07-15"), etag='"v1"')

        harness.sync()

        assert harness.confirmed_uids() == {"a"}
        assert harness.uow.committed == 2  # the announcement, then the sync

    def test_the_next_fetch_asks_whether_the_feed_changed(self, harness: Harness) -> None:
        harness.property_announced()
        harness.feed(AIRBNB_URL, b"airbnb-1", event("a", "07-12", "07-15"), etag='"v1"')
        harness.sync()
        harness.fetcher.answers[AIRBNB_URL] = FetchedFeed(content=None)  # not modified

        harness.sync()

        assert harness.fetcher.requests[-1] == (AIRBNB_URL, '"v1"', "")
        assert harness.confirmed_uids() == {"a"}
        assert not harness.calendar().feed(Channel.AIRBNB).failing

    @pytest.mark.parametrize("failure", ["fetch", "parse"])
    def test_an_unreadable_feed_changes_nothing(self, harness: Harness, failure: str) -> None:
        harness.property_announced()
        harness.feed(AIRBNB_URL, b"airbnb-1", event("a", "07-12", "07-15"))
        harness.sync()
        if failure == "fetch":
            harness.fetcher.answers[AIRBNB_URL] = FeedUnreadable("HTTP 503")
        else:
            harness.fetcher.answers[AIRBNB_URL] = FetchedFeed(content=b"<html>")

        harness.sync()

        assert harness.confirmed_uids() == {"a"}
        assert harness.calendar().feed(Channel.AIRBNB).failing_since == NOW

    def test_the_feeds_url_never_reaches_the_log(
        self, harness: Harness, caplog: pytest.LogCaptureFixture
    ) -> None:
        harness.property_announced()
        harness.fetcher.answers[AIRBNB_URL] = FeedUnreadable("HTTP 503")
        with caplog.at_level(logging.DEBUG):
            harness.sync()
        assert "KOS-001" in caplog.text
        assert AIRBNB_URL not in caplog.text

    def test_an_inactive_property_is_not_fetched(self, harness: Harness) -> None:
        harness.property_announced(active=False)
        harness.sync()
        assert harness.fetcher.requests == []

    def test_an_unknown_property_is_not_found(self, harness: Harness) -> None:
        with pytest.raises(CalendarNotFound):
            harness.sync()


class TestAlerts:
    def test_a_feed_failing_for_the_threshold_alerts_the_admin_once(self, harness: Harness) -> None:
        harness.property_announced()
        harness.fetcher.answers[AIRBNB_URL] = FeedUnreadable("timeout")
        for _ in range(6):  # every 30 minutes, for 2.5 hours
            harness.sync()
            harness.clock.advance(timedelta(minutes=30))

        (alert,) = harness.whatsapp_sent
        assert (alert.recipient, alert.template) == (ADMIN, "admin_calendar_feed_failing")
        assert alert.payload == {
            "property": "KOS-001 Villa Elena",
            "channel": "Airbnb",
            "since": "10/07 09:00",
        }

    def test_an_event_to_review_alerts_the_admin(self, harness: Harness) -> None:
        harness.property_announced()
        harness.feed(
            BOOKING_URL, b"booking-1", event("b", "07-20", "07-22", kind=EventKind.UNKNOWN)
        )

        harness.sync("booking")

        (alert,) = harness.whatsapp_sent
        assert alert.template == "admin_calendar_event_to_review"
        assert alert.payload == {
            "property": "KOS-001 Villa Elena",
            "channel": "Booking.com",
            "dates": "20/07-22/07",
            "reason": "unknown",
        }

    def test_without_an_admin_number_no_message_is_queued(self) -> None:
        harness = Harness(admin_whatsapp="")
        harness.property_announced()
        harness.feed(
            BOOKING_URL, b"booking-1", event("b", "07-20", "07-22", kind=EventKind.UNKNOWN)
        )
        harness.sync("booking")
        assert harness.whatsapp_sent == []


class TestTheAdmin:
    def test_the_answer_about_an_unknown_event(self, harness: Harness) -> None:
        harness.property_announced()
        harness.feed(
            BOOKING_URL, b"booking-1", event("b", "07-20", "07-22", kind=EventKind.UNKNOWN)
        )
        harness.sync("booking")

        harness.bus.handle(
            DecideCalendarEvent(
                property_id=PROPERTY_ID, channel="booking", uid="b", decision="reservation"
            )
        )

        assert harness.confirmed_uids() == {"b"}

    def test_an_answer_is_a_reservation_or_a_block(self, harness: Harness) -> None:
        harness.property_announced()
        with pytest.raises(InvalidValue):
            harness.bus.handle(
                DecideCalendarEvent(
                    property_id=PROPERTY_ID, channel="booking", uid="b", decision="maybe"
                )
            )

    def test_a_confirmed_empty_calendar_cancels_on_the_next_sync(self, harness: Harness) -> None:
        harness.property_announced()
        harness.feed(AIRBNB_URL, b"airbnb-1", event("a", "07-12", "07-15"))
        harness.sync()
        harness.feed(AIRBNB_URL, b"empty")

        harness.bus.handle(ConfirmEmptyCalendar(property_id=PROPERTY_ID, channel="airbnb"))
        harness.sync()

        assert harness.confirmed_uids() == set()

    def test_direct_reservations_carry_the_forms_version(self, harness: Harness) -> None:
        harness.property_announced()
        reservation_id = new_id()
        harness.bus.handle(
            AddDirectReservation(
                reservation_id=reservation_id,
                property_id=PROPERTY_ID,
                check_in_date=day("07-20"),
                check_out_date=day("07-23"),
                guest_name="Γιάννης",
                expected_version=1,
            )
        )
        harness.bus.handle(
            ChangeReservation(
                property_id=PROPERTY_ID,
                reservation_id=reservation_id,
                check_in_date=day("07-20"),
                check_out_date=day("07-24"),
                check_in_time=time(16),
                check_out_time=time(10),
                guest_name="Γιάννης Π.",
                expected_version=2,
            )
        )
        reservation = harness.calendar().reservation(reservation_id)
        assert (reservation.dates.check_out, reservation.check_in_time) == (day("07-24"), time(16))

        harness.bus.handle(
            CancelDirectReservation(
                property_id=PROPERTY_ID, reservation_id=reservation_id, expected_version=3
            )
        )

        assert not reservation.confirmed
        assert harness.uow.calendars.expected_versions[-3:] == [1, 2, 3]

    def test_stays_end_on_the_athens_date(self, harness: Harness) -> None:
        # The clock says 06:00 UTC, already 10 July in Athens: stays leaving that day end.
        harness.property_announced()
        harness.bus.handle(
            AddDirectReservation(
                reservation_id=new_id(),
                property_id=PROPERTY_ID,
                check_in_date=day("07-07"),
                check_out_date=day("07-10"),
            )
        )
        harness.bus.handle(EndStays(property_id=PROPERTY_ID))
        assert all(r.stay_ended for r in harness.calendar().reservations)
