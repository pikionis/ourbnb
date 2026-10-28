"""The ReservationCalendar aggregate: all reservations of one property (DOMAIN §6).

It is the consistency boundary of the rule that two confirmed reservations never share a night
(Cosmic Python ch. 7, like Product and its Batches): every change to a property's reservations
goes through it — feed syncs, the admin's answers and edits, the end of stays. It also keeps:
- the health of the property's calendar feeds (one alert per incident);
- the feed events waiting for the admin, and the admin's answers by UID;
- its own copy of what it needs from the properties context (DOMAIN §4.1).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from enum import StrEnum
from uuid import UUID

from kospm.reservations.domain.diff import calendar_diff
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
from kospm.reservations.domain.policies import FeedHealthPolicy
from kospm.reservations.domain.reservation import Reservation, ReservationStatus
from kospm.reservations.domain.value_objects import (
    Channel,
    EventKind,
    ImportedCalendarEvent,
    StayDates,
)
from kospm.shared.domain import Aggregate, new_id


@dataclass(frozen=True)
class PropertyDetails:
    """The reservations context's copy of a property (DOMAIN §4.1)."""

    code: str
    name: str
    active: bool
    check_in_time: time
    check_out_time: time


@dataclass(frozen=True)
class Feed:
    """One channel's calendar export of the property, and the health of its syncs (DOMAIN §6).

    - `failing_since`: the first failed sync of the current incident (None: healthy).
    - `alerted`: the admin was alerted about the current incident.
    - `accept_empty`: the admin confirmed that the calendar is empty, for the next accepted read.
    - `etag`, `last_modified`: of the last accepted read, so the server can answer "not modified".
    """

    channel: Channel
    url: str
    failing_since: datetime | None = None
    alerted: bool = False
    accept_empty: bool = False
    etag: str = ""
    last_modified: str = ""
    last_synced_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "channel", Channel(self.channel))
        if self.channel is Channel.DIRECT:
            raise InvalidValue("direct reservations have no calendar feed", field="channel")
        if not self.url.strip():
            raise InvalidValue("a calendar feed has a URL", field="url")

    @property
    def failing(self) -> bool:
        return self.failing_since is not None


class ReviewReason(StrEnum):
    """Why a feed event waits for the admin. Values are stored in the database."""

    UNKNOWN = "unknown"  # the feed does not say whether it is a reservation (Booking.com)
    OVERLAP = "overlap"  # a reservation that would share a night with a confirmed one


@dataclass(frozen=True)
class WaitingEvent:
    """A feed event waiting for the admin (DOMAIN §6)."""

    channel: Channel
    uid: str
    dates: StayDates
    reason: ReviewReason
    confirmation_code: str = ""


class ReservationCalendar(Aggregate[UUID]):
    """A property's reservations, identified by the property's id."""

    def __init__(
        self,
        property_id: UUID,
        *,
        details: PropertyDetails,
        feeds: Iterable[Feed] = (),
        reservations: Iterable[Reservation] = (),
        waiting: Iterable[WaitingEvent] = (),
        decisions: Mapping[tuple[Channel, str], EventKind] | None = None,
    ) -> None:
        super().__init__(property_id)
        self.details = details
        self._feeds = {feed.channel: feed for feed in feeds}
        self._reservations = {reservation.id: reservation for reservation in reservations}
        self._waiting = list(waiting)
        self._decisions = dict(decisions or {})

    # --- reading -------------------------------------------------------------------------------

    @property
    def syncs(self) -> bool:
        """Only an ACTIVE property's feeds are read (DOMAIN §5)."""
        return self.details.active

    @property
    def feeds(self) -> tuple[Feed, ...]:
        return tuple(self._feeds.values())

    def feed(self, channel: Channel) -> Feed:
        try:
            return self._feeds[Channel(channel)]
        except KeyError:
            raise FeedNotConfigured(f"{self.details.code} has no {channel} feed") from None

    @property
    def reservations(self) -> tuple[Reservation, ...]:
        return tuple(self._reservations.values())

    def reservation(self, reservation_id: UUID) -> Reservation:
        try:
            return self._reservations[reservation_id]
        except KeyError:
            raise ReservationNotFound(f"no reservation has id {reservation_id}") from None

    @property
    def waiting(self) -> tuple[WaitingEvent, ...]:
        return tuple(self._waiting)

    @property
    def decisions(self) -> dict[tuple[Channel, str], EventKind]:
        return dict(self._decisions)

    # --- the properties context's copy ---------------------------------------------------------

    def update_settings(self, details: PropertyDetails, feeds: Mapping[Channel, str]) -> None:
        """A feed with a new URL starts a new history. A removed feed's reservations stay;
        its waiting events go. A property active again starts its feeds' health afresh."""
        if details.active and not self.details.active:
            self._feeds = {
                channel: replace(feed, failing_since=None, alerted=False)
                for channel, feed in self._feeds.items()
            }
        self.details = details
        for channel, url in feeds.items():
            current = self._feeds.get(Channel(channel))
            if current is None or current.url != url:
                feed = Feed(Channel(channel), url)
                self._feeds[feed.channel] = feed
        for channel in set(self._feeds) - {Channel(channel) for channel in feeds}:
            del self._feeds[channel]
            self._waiting = [event for event in self._waiting if event.channel is not channel]

    # --- the no-overlap rule -------------------------------------------------------------------

    def accept(self, dates: StayDates, *, except_id: UUID | None = None) -> None:
        """Raise OverlappingReservation if the stay would share a night with a confirmed one."""
        overlapping = self._overlapping(dates, except_id)
        if overlapping:
            raise OverlappingReservation(reservation.id for reservation in overlapping)

    # --- feed syncs ----------------------------------------------------------------------------

    def read_feed(
        self,
        channel: Channel,
        events: Iterable[ImportedCalendarEvent],
        *,
        today: date,
        now: datetime,
        policy: FeedHealthPolicy,
        etag: str = "",
        last_modified: str = "",
    ) -> None:
        """Apply one read of the channel's feed (DOMAIN §6).

        A feed with no events while the channel still has reservations to come is a failed read,
        and changes nothing, unless the admin confirmed that the calendar is empty.
        """
        channel = Channel(channel)
        feed = self.feed(channel)
        events = list(events)
        if (
            not events
            and not feed.accept_empty
            and any(r.dates.starts_after(today) for r in self._confirmed(channel))
        ):
            self.feed_failed(channel, now=now, policy=policy)
            return
        self._feeds[channel] = replace(
            feed,
            failing_since=None,
            alerted=False,
            accept_empty=False,
            etag=etag,
            last_modified=last_modified,
            last_synced_at=now,
        )
        found, waiting = self._classify(channel, events, today)
        changes = calendar_diff(self._confirmed(channel), found, today=today)
        for reservation in changes.cancelled:  # first: they free their nights
            self._cancel(reservation)
        for reservation, event in changes.rescheduled:
            if self._overlapping(event.dates, reservation.id):
                waiting.append(_waiting(channel, event, ReviewReason.OVERLAP))
            else:
                self._reschedule(
                    reservation,
                    event.dates,
                    reservation.check_in_time,
                    reservation.check_out_time,
                    today=today,
                )
        for event in changes.new:
            self._import(channel, event, today, waiting)
        self._replace_waiting(channel, waiting)

    def feed_unchanged(self, channel: Channel, *, now: datetime) -> None:
        """The server answered "not modified": a successful read that changes nothing. The
        feed has its earlier content again, so an empty-calendar confirmation no longer holds."""
        feed = self.feed(channel)
        self._feeds[feed.channel] = replace(
            feed, failing_since=None, alerted=False, accept_empty=False, last_synced_at=now
        )

    def feed_failed(self, channel: Channel, *, now: datetime, policy: FeedHealthPolicy) -> None:
        """A read failed: nothing else changes. Failing for `policy.alert_after` alerts the
        admin, once per incident."""
        feed = self.feed(channel)
        since = feed.failing_since or now
        alerted = feed.alerted
        if not alerted and now - since >= policy.alert_after:
            self.events.append(
                CalendarFeedFailing(property_id=self.id, channel=feed.channel.value, since=since)
            )
            alerted = True
        self._feeds[feed.channel] = replace(feed, failing_since=since, alerted=alerted)

    def confirm_empty_calendar(self, channel: Channel) -> None:
        """The admin confirms the calendar is empty: the next accepted read may be empty, and
        its reservations to come are then cancelled as usual."""
        feed = self.feed(channel)
        self._feeds[feed.channel] = replace(feed, accept_empty=True)

    # --- the admin -----------------------------------------------------------------------------

    def decide(self, channel: Channel, uid: str, decision: EventKind, *, today: date) -> None:
        """The admin's answer about an unknown event; remembered for the event's next reads."""
        channel, decision = Channel(channel), EventKind(decision)
        if decision is EventKind.UNKNOWN:
            raise InvalidValue("the answer is a reservation or a block", field="decision")
        waiting = next(
            (
                event
                for event in self._waiting
                if event.channel is channel
                and event.uid == uid
                and event.reason is ReviewReason.UNKNOWN
            ),
            None,
        )
        if waiting is None:
            raise CalendarEventNotWaiting(f"no {channel} event {uid!r} waits for an answer")
        self._decisions[(channel, uid)] = decision
        self._waiting.remove(waiting)
        if decision is EventKind.RESERVATION:
            overlaps: list[WaitingEvent] = []
            imported = ImportedCalendarEvent(
                uid=uid,
                dates=waiting.dates,
                kind=EventKind.RESERVATION,
                confirmation_code=waiting.confirmation_code,
            )
            self._import(channel, imported, today, overlaps)
            self._add_waiting(overlaps)

    def add_direct_reservation(
        self,
        reservation_id: UUID,
        *,
        dates: StayDates,
        today: date,
        guest_name: str = "",
        check_in_time: time | None = None,
        check_out_time: time | None = None,
    ) -> None:
        """A reservation the admin enters. Times left out take the property's."""
        self.accept(dates)
        self._add(
            Reservation(
                reservation_id,
                channel=Channel.DIRECT,
                dates=dates,
                check_in_time=self.details.check_in_time
                if check_in_time is None
                else check_in_time,
                check_out_time=(
                    self.details.check_out_time if check_out_time is None else check_out_time
                ),
                guest_name=guest_name.strip(),
                stay_ended=dates.has_ended(today),
            )
        )

    def change_reservation(
        self,
        reservation_id: UUID,
        *,
        dates: StayDates,
        check_in_time: time,
        check_out_time: time,
        guest_name: str,
        today: date,
    ) -> None:
        """The admin's edit: times and guest name; the dates of a DIRECT reservation only."""
        reservation = self._confirmed_reservation(reservation_id)
        if dates != reservation.dates:
            if reservation.channel is not Channel.DIRECT:
                raise ChangeOnThePlatform(reservation.channel.value)
            self.accept(dates, except_id=reservation.id)
        reservation.guest_name = guest_name.strip()
        self._reschedule(reservation, dates, check_in_time, check_out_time, today=today)

    def cancel_direct_reservation(self, reservation_id: UUID) -> None:
        reservation = self._confirmed_reservation(reservation_id)
        if reservation.channel is not Channel.DIRECT:
            raise ChangeOnThePlatform(reservation.channel.value)
        self._cancel(reservation)

    # --- scheduled -----------------------------------------------------------------------------

    def end_stays(self, today: date) -> None:
        """Announce every confirmed stay whose check-out date has come, once; a missed day is
        caught up."""
        for reservation in self._confirmed():
            if not reservation.stay_ended and reservation.dates.check_out <= today:
                reservation.stay_ended = True
                self.events.append(
                    StayEnded(
                        reservation_id=reservation.id,
                        property_id=self.id,
                        check_out_date=reservation.dates.check_out,
                    )
                )

    # --- helpers -------------------------------------------------------------------------------

    def _confirmed(self, channel: Channel | None = None) -> list[Reservation]:
        return [
            reservation
            for reservation in self._reservations.values()
            if reservation.confirmed and (channel is None or reservation.channel is channel)
        ]

    def _confirmed_reservation(self, reservation_id: UUID) -> Reservation:
        reservation = self.reservation(reservation_id)
        if not reservation.confirmed:
            raise ReservationNotFound(f"reservation {reservation_id} is cancelled")
        return reservation

    def _overlapping(self, dates: StayDates, except_id: UUID | None = None) -> list[Reservation]:
        return [
            reservation
            for reservation in self._confirmed()
            if reservation.id != except_id and reservation.dates.overlaps(dates)
        ]

    def _classify(
        self, channel: Channel, events: list[ImportedCalendarEvent], today: date
    ) -> tuple[list[ImportedCalendarEvent], list[WaitingEvent]]:
        """The feed's reservations, and its unknown events that wait for the admin."""
        found: list[ImportedCalendarEvent] = []
        waiting: list[WaitingEvent] = []
        for event in events:
            kind = self._kind_of(channel, event)
            if kind is EventKind.RESERVATION:
                found.append(event)
            elif kind is EventKind.UNKNOWN and not event.dates.has_ended(today):
                waiting.append(_waiting(channel, event, ReviewReason.UNKNOWN))
        return found, waiting

    def _kind_of(self, channel: Channel, event: ImportedCalendarEvent) -> EventKind:
        if event.kind is not EventKind.UNKNOWN:
            return event.kind
        if any(r.external_uid == event.uid for r in self._confirmed(channel)):
            return EventKind.RESERVATION  # imported already: it stays a reservation
        decided = self._decisions.get((channel, event.uid))
        if decided is not None:
            return decided
        if any(r.channel is not channel and r.dates == event.dates for r in self._confirmed()):
            return EventKind.BLOCK  # the mirror of another channel's reservation
        return EventKind.UNKNOWN

    def _import(
        self,
        channel: Channel,
        event: ImportedCalendarEvent,
        today: date,
        waiting: list[WaitingEvent],
    ) -> None:
        ended = event.dates.has_ended(today)
        if not ended and self._overlapping(event.dates):
            waiting.append(_waiting(channel, event, ReviewReason.OVERLAP))
            return
        self._add(
            Reservation(
                new_id(),
                channel=channel,
                dates=event.dates,
                check_in_time=self.details.check_in_time,
                check_out_time=self.details.check_out_time,
                external_uid=event.uid,
                confirmation_code=event.confirmation_code,
                stay_ended=ended,  # first seen after it ended: recorded, never announced
            )
        )

    def _add(self, reservation: Reservation) -> None:
        self._reservations[reservation.id] = reservation
        if not reservation.stay_ended:
            self.events.append(
                ReservationImported(
                    reservation_id=reservation.id,
                    property_id=self.id,
                    channel=reservation.channel.value,
                    check_in_date=reservation.dates.check_in,
                    check_out_date=reservation.dates.check_out,
                    check_in_time=reservation.check_in_time,
                    check_out_time=reservation.check_out_time,
                )
            )

    def _reschedule(
        self,
        reservation: Reservation,
        dates: StayDates,
        check_in_time: time,
        check_out_time: time,
        *,
        today: date,
    ) -> None:
        """New dates or times. A stay that ended and now leaves later (the guests extend it)
        has not ended any more: its StayEnded comes again on the new check-out date."""
        before = (reservation.dates, reservation.check_in_time, reservation.check_out_time)
        if before == (dates, check_in_time, check_out_time):
            return
        if reservation.stay_ended and dates.check_out > today:
            reservation.stay_ended = False
        reservation.dates = dates
        reservation.check_in_time, reservation.check_out_time = check_in_time, check_out_time
        self.events.append(
            ReservationRescheduled(
                reservation_id=reservation.id,
                property_id=self.id,
                previous_check_in_date=before[0].check_in,
                previous_check_out_date=before[0].check_out,
                previous_check_in_time=before[1],
                previous_check_out_time=before[2],
                check_in_date=dates.check_in,
                check_out_date=dates.check_out,
                check_in_time=check_in_time,
                check_out_time=check_out_time,
            )
        )

    def _cancel(self, reservation: Reservation) -> None:
        reservation.status = ReservationStatus.CANCELLED
        self.events.append(
            ReservationCancelled(
                reservation_id=reservation.id,
                property_id=self.id,
                check_in_date=reservation.dates.check_in,
                check_out_date=reservation.dates.check_out,
            )
        )

    def _replace_waiting(self, channel: Channel, waiting: list[WaitingEvent]) -> None:
        """The channel's waiting events, as its latest read found them."""
        before = [event for event in self._waiting if event.channel is channel]
        self._waiting = [event for event in self._waiting if event.channel is not channel]
        self._add_waiting(waiting, already=before)

    def _add_waiting(
        self, waiting: Iterable[WaitingEvent], already: Iterable[WaitingEvent] = ()
    ) -> None:
        """The admin is told once about each waiting event (and again if its dates change)."""
        known = {(event.uid, event.reason, event.dates) for event in already}
        for event in waiting:
            if any(w.channel is event.channel and w.uid == event.uid for w in self._waiting):
                continue  # listed twice in the feed: it waits once
            if (event.uid, event.reason, event.dates) not in known:
                self.events.append(
                    CalendarEventNeedsReview(
                        property_id=self.id,
                        channel=event.channel.value,
                        uid=event.uid,
                        check_in_date=event.dates.check_in,
                        check_out_date=event.dates.check_out,
                        reason=event.reason.value,
                    )
                )
            self._waiting.append(event)


def _waiting(channel: Channel, event: ImportedCalendarEvent, reason: ReviewReason) -> WaitingEvent:
    return WaitingEvent(channel, event.uid, event.dates, reason, event.confirmation_code)
