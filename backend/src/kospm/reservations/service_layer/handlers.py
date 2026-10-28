"""Command and event handlers of the reservations context (Cosmic Python ch. 10).

Each handler runs one Unit of Work over one ReservationCalendar. Dependencies besides `uow` and
`clock` are injected by bootstrap by name: `ical_fetcher`, `ical_parser`, `feed_health` (policy)
and `admin_alerts`. "Today" is always the Athens date of the injected clock (DOMAIN §2.6).

The admin's alerts are queued in the unit that raised them, not by a later event handler: the
alert and the state that records it ("alerted") commit together or not at all (ADR 0005).
"""

import logging
from collections.abc import Callable
from datetime import datetime

from kospm.reservations.domain.calendar import Feed, PropertyDetails, ReservationCalendar
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
from kospm.reservations.domain.errors import InvalidValue
from kospm.reservations.domain.events import CalendarEventNeedsReview, CalendarFeedFailing
from kospm.reservations.domain.policies import FeedHealthPolicy
from kospm.reservations.domain.value_objects import (
    Channel,
    EventKind,
    ImportedCalendarEvent,
    StayDates,
)
from kospm.reservations.service_layer.ports import (
    AdminAlerts,
    FeedUnreadable,
    FetchedFeed,
    ICalFetcher,
    ICalParser,
)
from kospm.reservations.service_layer.unit_of_work import ReservationsUnitOfWork
from kospm.shared.clock import Clock
from kospm.shared.domain import Command, DomainEvent

logger = logging.getLogger(__name__)

# --- the properties context's copy (DOMAIN §4.1) -------------------------------------------------


def update_property_calendar(cmd: UpdatePropertyCalendar, uow: ReservationsUnitOfWork) -> None:
    details = PropertyDetails(
        code=cmd.code,
        name=cmd.name,
        active=cmd.active,
        check_in_time=cmd.check_in_time,
        check_out_time=cmd.check_out_time,
    )
    feeds = {_channel(channel): url for channel, url in cmd.feeds}
    with uow:
        calendar = uow.calendars.find(cmd.property_id)
        if calendar is None:
            feed_list = [Feed(channel, url) for channel, url in feeds.items()]
            uow.calendars.add(
                ReservationCalendar(cmd.property_id, details=details, feeds=feed_list)
            )
        else:
            calendar.update_settings(details, feeds)
        uow.commit()


# --- feed syncs (DOMAIN §6) ----------------------------------------------------------------------


def sync_calendar_feed(
    cmd: SyncCalendarFeed,
    uow: ReservationsUnitOfWork,
    clock: Clock,
    ical_fetcher: ICalFetcher,
    ical_parser: ICalParser,
    feed_health: FeedHealthPolicy,
    admin_alerts: AdminAlerts,
) -> None:
    """Read one channel's feed and apply it.

    The network is read between two units, never inside a database transaction. The read is
    applied only if nothing changed meanwhile that makes it stale: the property is still active,
    the feed still has this URL, and no newer read was applied (e.g. the admin's "sync now").
    """
    channel = _channel(cmd.channel)
    with uow:  # read only: nothing to commit
        calendar = uow.calendars.get(cmd.property_id)
        if not calendar.syncs:
            return
        feed, code = calendar.feed(channel), calendar.details.code
    started = clock.now()
    read = _read(feed, code, ical_fetcher, ical_parser)
    with uow:
        calendar = uow.calendars.get(cmd.property_id)
        if _stale(calendar, feed, started):
            return
        now = clock.now()
        if read is None:
            calendar.feed_failed(channel, now=now, policy=feed_health)
        elif read[0].not_modified:
            calendar.feed_unchanged(channel, now=now)
        else:
            calendar.read_feed(
                channel,
                read[1],
                today=clock.today_athens(),
                now=now,
                policy=feed_health,
                etag=read[0].etag,
                last_modified=read[0].last_modified,
            )
        _alert_admin(calendar, uow, admin_alerts)
        uow.commit()


def _stale(calendar: ReservationCalendar, fetched: Feed, started: datetime) -> bool:
    current = next((feed for feed in calendar.feeds if feed.channel is fetched.channel), None)
    return (
        not calendar.syncs
        or current is None
        or current.url != fetched.url
        or (current.last_synced_at is not None and current.last_synced_at > started)
    )


def _read(
    feed: Feed, code: str, ical_fetcher: ICalFetcher, ical_parser: ICalParser
) -> tuple[FetchedFeed, list[ImportedCalendarEvent]] | None:
    """The fetched feed and its events; None if it could not be read (logged without its URL)."""
    try:
        fetched = ical_fetcher.fetch(feed.url, etag=feed.etag, last_modified=feed.last_modified)
        if fetched.content is None:
            return fetched, []
        return fetched, list(ical_parser.parse(feed.channel, fetched.content))
    except FeedUnreadable as error:
        logger.warning("%s: the %s feed could not be read: %s", code, feed.channel.value, error)
        return None


def confirm_empty_calendar(cmd: ConfirmEmptyCalendar, uow: ReservationsUnitOfWork) -> None:
    with uow:
        uow.calendars.get(cmd.property_id).confirm_empty_calendar(_channel(cmd.channel))
        uow.commit()


# --- the admin -----------------------------------------------------------------------------------


def decide_calendar_event(
    cmd: DecideCalendarEvent,
    uow: ReservationsUnitOfWork,
    clock: Clock,
    admin_alerts: AdminAlerts,
) -> None:
    channel, decision = _channel(cmd.channel), _decision(cmd.decision)
    with uow:
        calendar = uow.calendars.get(cmd.property_id)
        calendar.decide(channel, cmd.uid, decision, today=clock.today_athens())
        _alert_admin(calendar, uow, admin_alerts)  # the answer may reveal an overlap
        uow.commit()


def add_direct_reservation(
    cmd: AddDirectReservation, uow: ReservationsUnitOfWork, clock: Clock
) -> None:
    dates = StayDates(cmd.check_in_date, cmd.check_out_date)
    with uow:
        calendar = uow.calendars.get(cmd.property_id, expected_version=cmd.expected_version)
        calendar.add_direct_reservation(
            cmd.reservation_id,
            dates=dates,
            today=clock.today_athens(),
            guest_name=cmd.guest_name,
            check_in_time=cmd.check_in_time,
            check_out_time=cmd.check_out_time,
        )
        uow.commit()


def change_reservation(cmd: ChangeReservation, uow: ReservationsUnitOfWork, clock: Clock) -> None:
    dates = StayDates(cmd.check_in_date, cmd.check_out_date)
    with uow:
        calendar = uow.calendars.get(cmd.property_id, expected_version=cmd.expected_version)
        calendar.change_reservation(
            cmd.reservation_id,
            dates=dates,
            check_in_time=cmd.check_in_time,
            check_out_time=cmd.check_out_time,
            guest_name=cmd.guest_name,
            today=clock.today_athens(),
        )
        uow.commit()


def cancel_direct_reservation(cmd: CancelDirectReservation, uow: ReservationsUnitOfWork) -> None:
    with uow:
        calendar = uow.calendars.get(cmd.property_id, expected_version=cmd.expected_version)
        calendar.cancel_direct_reservation(cmd.reservation_id)
        uow.commit()


# --- scheduled -----------------------------------------------------------------------------------


def end_stays(cmd: EndStays, uow: ReservationsUnitOfWork, clock: Clock) -> None:
    with uow:
        uow.calendars.get(cmd.property_id).end_stays(clock.today_athens())
        uow.commit()


# --- alerts to the admin (DOMAIN §6) ------------------------------------------------------------


def _alert_admin(
    calendar: ReservationCalendar, uow: ReservationsUnitOfWork, admin_alerts: AdminAlerts
) -> None:
    """Queue the alerts for what this unit raised, in this unit (ADR 0005)."""
    details = calendar.details
    for event in calendar.events:
        if isinstance(event, CalendarFeedFailing):
            admin_alerts.feed_failing(
                outbox=uow.outbox,
                property_code=details.code,
                property_name=details.name,
                channel=_channel(event.channel),
                since=event.since,
            )
        elif isinstance(event, CalendarEventNeedsReview):
            admin_alerts.event_to_review(
                outbox=uow.outbox,
                property_code=details.code,
                property_name=details.name,
                channel=_channel(event.channel),
                dates=StayDates(event.check_in_date, event.check_out_date),
                reason=event.reason,
            )


# --- helpers -------------------------------------------------------------------------------------


def _channel(name: str) -> Channel:
    try:
        return Channel(name)
    except ValueError as error:
        raise InvalidValue(f"{name!r} is not a channel", field="channel") from error


def _decision(name: str) -> EventKind:
    if name not in (EventKind.RESERVATION, EventKind.BLOCK):
        raise InvalidValue(f"{name!r} is not a reservation or a block", field="decision")
    return EventKind(name)


COMMAND_HANDLERS: dict[type[Command], Callable[..., None]] = {
    UpdatePropertyCalendar: update_property_calendar,
    SyncCalendarFeed: sync_calendar_feed,
    ConfirmEmptyCalendar: confirm_empty_calendar,
    DecideCalendarEvent: decide_calendar_event,
    AddDirectReservation: add_direct_reservation,
    ChangeReservation: change_reservation,
    CancelDirectReservation: cancel_direct_reservation,
    EndStays: end_stays,
}

# The context's events are for the other contexts (DOMAIN §4.1); it reacts to none of its own.
EVENT_HANDLERS: dict[type[DomainEvent], list[Callable[..., None]]] = {}
