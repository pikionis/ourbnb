"""Reservations end to end (DOMAIN §4.1, §6; BUILD_PLAN Phase 3 tests).

The scheduled commands and the admin run against PostgreSQL. Files replace the network
(FileICalFetcher), and the feeds' dates are written relative to today, since the commands use the
real clock.
"""

import io
from datetime import date, time, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from django.core.management import CommandError, call_command
from django.test import Client
from django.urls import reverse

from kospm import bootstrap
from kospm.reservations import models
from kospm.reservations.adapters.ical import FileICalFetcher
from kospm.reservations.domain.commands import AddDirectReservation, UpdatePropertyCalendar
from kospm.shared.clock import SystemClock
from kospm.shared.domain import new_id
from kospm.shared.outbox.models import OutboxMessage
from kospm.shared.unit_of_work import ConcurrencyError
from tests.e2e.owners import add_property_in_admin, register_owner_in_admin

pytestmark = pytest.mark.django_db

AIRBNB_URL = "https://www.airbnb.com/calendar/ical/1001.ics?s=test"
BOOKING_URL = "https://ical.booking.com/v1/export?t=test"
RESERVED, BLOCKED, CLOSED = "Reserved", "Airbnb (Not available)", "CLOSED - Not available"


def day(offset: int) -> date:
    return SystemClock().today_athens() + timedelta(days=offset)


def ics(*events: tuple[str, int, int, str], prodid: str = "-//test//EN") -> bytes:
    """A feed with events (uid, check-in offset, check-out offset, summary), CRLF as sent."""
    lines = ["BEGIN:VCALENDAR", f"PRODID:{prodid}", "VERSION:2.0"]
    for uid, start, end, summary in events:
        lines += [
            "BEGIN:VEVENT",
            f"DTSTART;VALUE=DATE:{day(start):%Y%m%d}",
            f"DTEND;VALUE=DATE:{day(end):%Y%m%d}",
            f"UID:{uid}",
            f"SUMMARY:{summary}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode()


class Feeds:
    """The two feeds of the property, as files the fetcher reads."""

    def __init__(self, folder: Path) -> None:
        self.files = {AIRBNB_URL: folder / "airbnb.ics", BOOKING_URL: folder / "booking.ics"}

    def airbnb(self, *events: tuple[str, int, int, str], prodid: str = "-//test//EN") -> None:
        self.files[AIRBNB_URL].write_bytes(ics(*events, prodid=prodid))

    def booking(self, *events: tuple[str, int, int, str]) -> None:
        self.files[BOOKING_URL].write_bytes(ics(*events))

    def break_airbnb(self) -> None:
        self.files[AIRBNB_URL].unlink(missing_ok=True)


@pytest.fixture
def feeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Feeds:
    feeds = Feeds(tmp_path)
    feeds.airbnb()
    feeds.booking()
    monkeypatch.setattr(bootstrap, "ical_fetcher", lambda: FileICalFetcher(feeds.files))
    monkeypatch.setattr(bootstrap._thread_local, "bus", None, raising=False)  # rebuilt with it
    return feeds


@pytest.fixture
def property_id(feeds: Feeds) -> UUID:
    """An ACTIVE property with both feeds, as properties announces it."""
    property_id = new_id()
    bootstrap.get_bus().handle(
        UpdatePropertyCalendar(
            property_id=property_id,
            code="KOS-001",
            name="Villa Elena",
            active=True,
            check_in_time=time(15),
            check_out_time=time(11),
            feeds=(("airbnb", AIRBNB_URL), ("booking", BOOKING_URL)),
        )
    )
    return property_id


def sync() -> str:
    out = io.StringIO()
    call_command("sync_calendars", stdout=out)
    return out.getvalue()


def confirmed() -> dict[str, tuple[date, date]]:
    return {
        row.external_uid: (row.check_in_date, row.check_out_date)
        for row in models.Reservation.objects.filter(status="confirmed").exclude(external_uid="")
    }


def version(property_id: UUID) -> int:
    return models.PropertyCalendar.objects.get(pk=property_id).version


def alerts(template: str) -> list[OutboxMessage]:
    return list(OutboxMessage.objects.filter(channel="WHATSAPP", template=template))


class TestSync:
    def test_the_first_import_creates_and_the_same_feed_again_changes_nothing(
        self, feeds: Feeds, property_id: UUID
    ) -> None:
        feeds.airbnb(("a", 2, 5, RESERVED), ("b", 10, 12, RESERVED))

        assert "2 feeds read" in sync()
        assert confirmed() == {"a": (day(2), day(5)), "b": (day(10), day(12))}
        before = version(property_id)
        # The same events in a file that differs: read and parsed again, not "not modified".
        feeds.airbnb(("a", 2, 5, RESERVED), ("b", 10, 12, RESERVED), prodid="-//other//EN")

        sync()

        assert version(property_id) == before
        assert models.Reservation.objects.count() == 2

    def test_changed_dates_reschedule(self, feeds: Feeds, property_id: UUID) -> None:
        feeds.airbnb(("a", 2, 5, RESERVED))
        sync()
        feeds.airbnb(("a", 3, 6, RESERVED))
        sync()
        assert confirmed() == {"a": (day(3), day(6))}

    def test_a_removed_future_reservation_is_cancelled_and_a_past_one_kept(
        self, feeds: Feeds, property_id: UUID
    ) -> None:
        feeds.airbnb(("past", -5, -2, RESERVED), ("a", 2, 5, RESERVED), ("b", 10, 12, RESERVED))
        sync()
        feeds.airbnb(("b", 10, 12, RESERVED))
        sync()
        assert set(confirmed()) == {"past", "b"}
        assert models.Reservation.objects.get(external_uid="a").status == "cancelled"

    def test_an_overlap_alerts_the_admin_and_is_not_saved(
        self, feeds: Feeds, property_id: UUID
    ) -> None:
        bootstrap.get_bus().handle(
            AddDirectReservation(
                reservation_id=new_id(),
                property_id=property_id,
                check_in_date=day(3),
                check_out_date=day(6),
            )
        )
        feeds.airbnb(("a", 2, 5, RESERVED))

        sync()

        assert confirmed() == {}
        assert models.WaitingCalendarEvent.objects.get().reason == "overlap"
        (alert,) = alerts("admin_calendar_event_to_review")
        assert alert.payload["reason"] == "overlap"

    def test_blocks_are_ignored(self, feeds: Feeds, property_id: UUID) -> None:
        feeds.airbnb(("x", 2, 5, BLOCKED))
        sync()
        assert models.Reservation.objects.count() == 0

    def test_an_unknown_event_waits_for_the_admin(self, feeds: Feeds, property_id: UUID) -> None:
        feeds.booking(("b", 2, 5, CLOSED))
        sync()
        assert models.WaitingCalendarEvent.objects.get().reason == "unknown"
        assert len(alerts("admin_calendar_event_to_review")) == 1

    def test_the_check_out_day_may_be_the_next_check_in_day(
        self, feeds: Feeds, property_id: UUID
    ) -> None:
        feeds.airbnb(("a", 2, 5, RESERVED), ("b", 5, 8, RESERVED))
        sync()
        assert set(confirmed()) == {"a", "b"}

    def test_a_fetch_error_changes_nothing(self, feeds: Feeds, property_id: UUID) -> None:
        feeds.airbnb(("a", 2, 5, RESERVED))
        sync()
        feeds.break_airbnb()

        sync()

        assert set(confirmed()) == {"a"}
        assert models.CalendarFeed.objects.get(channel="airbnb").failing_since is not None

    def test_an_empty_feed_with_reservations_to_come_cancels_nothing(
        self, feeds: Feeds, property_id: UUID
    ) -> None:
        feeds.airbnb(("a", 2, 5, RESERVED))
        sync()
        feeds.airbnb()
        sync()
        assert set(confirmed()) == {"a"}

    def test_a_failing_feed_alerts_once_and_again_after_a_new_incident(
        self, feeds: Feeds, property_id: UUID
    ) -> None:
        def fail_for_three_hours() -> None:
            feeds.break_airbnb()
            sync()
            failing = models.CalendarFeed.objects.filter(channel="airbnb")
            started = failing.get().failing_since
            assert started is not None
            failing.update(failing_since=started - timedelta(hours=3))
            sync()
            sync()  # still failing: no new alert

        fail_for_three_hours()
        assert len(alerts("admin_calendar_feed_failing")) == 1
        feeds.airbnb(("a", 2, 5, RESERVED))
        sync()  # recovered: the incident ends
        assert models.CalendarFeed.objects.get(channel="airbnb").failing_since is None

        fail_for_three_hours()

        assert len(alerts("admin_calendar_feed_failing")) == 2

    def test_an_event_that_cannot_be_read_cancels_nothing(
        self, feeds: Feeds, property_id: UUID
    ) -> None:
        feeds.airbnb(("a", 2, 5, RESERVED), ("b", 10, 12, RESERVED))
        sync()
        content = feeds.files[AIRBNB_URL].read_bytes()
        broken = content.replace(f"DTEND;VALUE=DATE:{day(5):%Y%m%d}".encode(), b"DTEND:notadate")
        feeds.files[AIRBNB_URL].write_bytes(broken)

        sync()

        assert set(confirmed()) == {"a", "b"}
        assert models.CalendarFeed.objects.get(channel="airbnb").failing_since is not None

    def test_an_unexpected_error_fails_the_command_after_the_other_feeds(
        self, feeds: Feeds, property_id: UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Broken(FileICalFetcher):
            def fetch(self, url: str, *, etag: str = "", last_modified: str = "") -> Any:
                if url == AIRBNB_URL:
                    raise RuntimeError("a bug")
                return super().fetch(url, etag=etag, last_modified=last_modified)

        monkeypatch.setattr(bootstrap, "ical_fetcher", lambda: Broken(feeds.files))
        monkeypatch.setattr(bootstrap._thread_local, "bus", None, raising=False)
        feeds.booking(("b", 10, 12, CLOSED))

        with pytest.raises(CommandError):
            sync()

        assert models.WaitingCalendarEvent.objects.get().uid == "b"  # Booking was still read

    def test_an_inactive_property_is_not_read(self, feeds: Feeds, property_id: UUID) -> None:
        models.PropertyCalendar.objects.filter(pk=property_id).update(active=False)
        feeds.airbnb(("a", 2, 5, RESERVED))
        assert "0 feeds read" in sync()


class TestStaysEnd:
    def test_a_stay_ending_today_is_announced_once(self, feeds: Feeds, property_id: UUID) -> None:
        bootstrap.get_bus().handle(
            AddDirectReservation(
                reservation_id=new_id(),
                property_id=property_id,
                check_in_date=day(-3),
                check_out_date=day(0),
            )
        )
        out = io.StringIO()
        call_command("emit_stay_ended", stdout=out)
        call_command("emit_stay_ended", stdout=out)
        assert models.Reservation.objects.get().stay_ended
        assert "emit_stay_ended: 1 properties" in out.getvalue()
        assert "emit_stay_ended: 0 properties" in out.getvalue()

    def test_one_property_failing_never_stops_the_others(
        self, feeds: Feeds, property_id: UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from kospm.reservations.entrypoints import emit_stay_ended

        handled: list[Any] = []

        class Bus:
            def handle(self, command: Any) -> None:
                handled.append(command.property_id)
                if len(handled) == 1:
                    raise ConcurrencyError("a sync saved the calendar meanwhile")

        monkeypatch.setattr(
            emit_stay_ended, "calendars_with_stays_ending", lambda today: [new_id(), new_id()]
        )
        monkeypatch.setattr(emit_stay_ended, "get_bus", Bus)

        with pytest.raises(CommandError):
            call_command("emit_stay_ended", stdout=io.StringIO())

        assert len(handled) == 2


class TestAdmin:
    def test_every_page_opens(self, admin_client: Client, feeds: Feeds, property_id: UUID) -> None:
        feeds.airbnb(("a", 2, 5, RESERVED))
        feeds.booking(("b", 10, 12, CLOSED))
        sync()
        reservation = models.Reservation.objects.get()
        pages = [
            reverse("admin:reservations_reservation_changelist"),
            reverse("admin:reservations_reservation_add"),
            reverse("admin:reservations_reservation_change", args=[reservation.pk]),
            reverse("admin:reservations_waitingcalendarevent_changelist"),
            reverse("admin:reservations_calendarfeed_changelist"),
        ]
        for page in pages:
            assert admin_client.get(page).status_code == 200, page
        assert AIRBNB_URL not in admin_client.get(pages[-1]).content.decode()  # its secret token

    def test_the_admin_confirms_an_empty_calendar(
        self, admin_client: Client, feeds: Feeds, property_id: UUID
    ) -> None:
        feeds.airbnb(("a", 2, 5, RESERVED))
        sync()
        feeds.airbnb()
        sync()  # refused: reservations would go
        feed = models.CalendarFeed.objects.get(channel="airbnb")

        admin_client.post(
            reverse("admin:reservations_calendarfeed_changelist"),
            {"action": "confirm_empty_calendar", "_selected_action": [str(feed.pk)]},
        )

        assert confirmed() == {}

    def test_the_admins_answer_imports_an_unknown_event(
        self, admin_client: Client, feeds: Feeds, property_id: UUID
    ) -> None:
        feeds.booking(("b", 2, 5, CLOSED))
        sync()
        waiting = models.WaitingCalendarEvent.objects.get()

        admin_client.post(
            reverse("admin:reservations_waitingcalendarevent_changelist"),
            {"action": "answer_reservation", "_selected_action": [str(waiting.pk)]},
        )
        sync()  # the answer is remembered

        assert confirmed() == {"b": (day(2), day(5))}
        assert models.WaitingCalendarEvent.objects.count() == 0

    def test_the_admin_adds_a_direct_reservation_but_never_an_overlap(
        self, admin_client: Client, feeds: Feeds, property_id: UUID
    ) -> None:
        feeds.airbnb(("a", 2, 5, RESERVED))
        sync()
        add = reverse("admin:reservations_reservation_add")

        refused = admin_client.post(add, direct_form(property_id, 4, 7))
        added = admin_client.post(add, direct_form(property_id, 5, 7, guest_name="Γιάννης"))

        assert refused.status_code == 200
        assert "επικαλύπτονται" in refused.content.decode()
        assert added.status_code == 302, added.content.decode()[:2000]
        direct = models.Reservation.objects.get(channel="direct")
        assert (direct.check_in_time, direct.guest_name) == (time(15), "Γιάννης")

    def test_a_cancelled_airbnb_reservation_opens(
        self, admin_client: Client, feeds: Feeds, property_id: UUID
    ) -> None:
        feeds.airbnb(("a", 2, 5, RESERVED), ("b", 10, 12, RESERVED))
        sync()
        feeds.airbnb(("b", 10, 12, RESERVED))
        sync()
        cancelled = models.Reservation.objects.get(external_uid="a")
        page = reverse("admin:reservations_reservation_change", args=[cancelled.pk])
        assert admin_client.get(page).status_code == 200

    def test_a_form_shown_before_a_change_is_refused(
        self, admin_client: Client, feeds: Feeds, property_id: UUID
    ) -> None:
        feeds.airbnb(("a", 2, 5, RESERVED))
        sync()
        reservation = models.Reservation.objects.get()
        shown = version(property_id)
        feeds.airbnb(("a", 2, 5, RESERVED), ("b", 10, 12, RESERVED))
        sync()  # a new booking arrives while the admin's form is open

        response = admin_client.post(
            reverse("admin:reservations_reservation_change", args=[reservation.pk]),
            {
                "check_in_date": str(day(2)),
                "check_out_date": str(day(5)),
                "check_in_time": "13:00",
                "check_out_time": "11:00",
                "guest_name": "Anna",
                "version": str(shown),
            },
            follow=True,
        )

        assert "Κάποιος άλλος" in response.content.decode()
        reservation.refresh_from_db()
        assert reservation.check_in_time == time(15)

    def test_the_admin_changes_an_airbnb_reservations_times_not_its_dates(
        self, admin_client: Client, feeds: Feeds, property_id: UUID
    ) -> None:
        feeds.airbnb(("a", 2, 5, RESERVED))
        sync()
        reservation = models.Reservation.objects.get()
        change = reverse("admin:reservations_reservation_change", args=[reservation.pk])

        saved = admin_client.post(
            change,
            {
                "check_in_date": str(day(1)),  # disabled: ignored, the feed's dates stay
                "check_out_date": str(day(5)),
                "check_in_time": "13:00",
                "check_out_time": "11:00",
                "guest_name": "Anna",
                "version": str(version(property_id)),
            },
        )

        assert saved.status_code == 302, saved.content.decode()[:2000]
        reservation.refresh_from_db()
        assert (reservation.check_in_date, reservation.check_in_time) == (day(2), time(13))
        assert reservation.guest_name == "Anna"


def direct_form(
    property_id: UUID, check_in: int, check_out: int, **overrides: Any
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "calendar": str(property_id),
        "check_in_date": str(day(check_in)),
        "check_out_date": str(day(check_out)),
        "check_in_time": "",
        "check_out_time": "",
        "guest_name": "",
        "version": "",
    }
    data.update(overrides)
    return data


AIRBNB_FEED = "https://www.airbnb.com/calendar/ical/2002.ics?s=test"


class TestPropertyCopy:
    def test_the_admins_property_reaches_the_reservations_context(
        self, admin_client: Client
    ) -> None:
        prop = admin_property_with_feed(admin_client)
        copy = models.PropertyCalendar.objects.get(property_id=prop.pk)
        assert (copy.code, copy.name, copy.active) == ("KOS-001", "Villa Elena", False)
        assert list(copy.feeds.values_list("channel", "url")) == [("airbnb", AIRBNB_FEED)]

    def test_properties_from_before_are_announced_by_a_command(self, admin_client: Client) -> None:
        prop = admin_property_with_feed(admin_client)
        models.CalendarFeed.objects.all().delete()
        models.PropertyCalendar.objects.all().delete()  # as before the reservations context

        call_command("announce_calendar_settings", stdout=io.StringIO())
        call_command("announce_calendar_settings", stdout=io.StringIO())  # again: no harm

        copy = models.PropertyCalendar.objects.get(property_id=prop.pk)
        assert list(copy.feeds.values_list("url", flat=True)) == [AIRBNB_FEED]


def admin_property_with_feed(admin_client: Client) -> Any:
    owner = register_owner_in_admin(admin_client)
    prop = add_property_in_admin(admin_client, owner, code="KOS-001", name="Villa Elena")
    data = {
        "owner": str(owner.pk),
        "code": prop.code,
        "name": prop.name,
        "default_check_in_time": "15:00",
        "default_check_out_time": "11:00",
        "linen_par_level": "3",
        "airbnb_ical_url": AIRBNB_FEED,
        "contract_signed_at_0": "",
        "contract_signed_at_1": "",
        "version": "0",
    }
    saved = admin_client.post(reverse("admin:properties_property_change", args=[prop.pk]), data)
    assert saved.status_code == 302, saved.content.decode()[:2000]
    return prop
