"""Domain events of the reservations context (DOMAIN §4.1 and §6).

Plain values only (ids, dates, times, the channel's name), so another context reads them without
importing this one.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from uuid import UUID

from kospm.shared.domain import DomainEvent


@dataclass(frozen=True, kw_only=True)
class ReservationImported(DomainEvent):
    """A new confirmed reservation: from a feed, or entered by the admin (channel "direct")."""

    reservation_id: UUID
    property_id: UUID
    channel: str
    check_in_date: date
    check_out_date: date
    check_in_time: time
    check_out_time: time


@dataclass(frozen=True, kw_only=True)
class ReservationRescheduled(DomainEvent):
    """A reservation's dates or check-in/out times changed: the previous values, then the new."""

    reservation_id: UUID
    property_id: UUID
    previous_check_in_date: date
    previous_check_out_date: date
    previous_check_in_time: time
    previous_check_out_time: time
    check_in_date: date
    check_out_date: date
    check_in_time: time
    check_out_time: time


@dataclass(frozen=True, kw_only=True)
class ReservationCancelled(DomainEvent):
    reservation_id: UUID
    property_id: UUID
    check_in_date: date
    check_out_date: date


@dataclass(frozen=True, kw_only=True)
class StayEnded(DomainEvent):
    """The guests' check-out date has come (raised by the scheduled job, once per stay)."""

    reservation_id: UUID
    property_id: UUID
    check_out_date: date


@dataclass(frozen=True, kw_only=True)
class CalendarEventNeedsReview(DomainEvent):
    """A feed event waits for the admin. `reason` is "unknown" (reservation or block? the feed does
    not say) or "overlap" (a reservation that would share a night with a confirmed one)."""

    property_id: UUID
    channel: str
    uid: str
    check_in_date: date
    check_out_date: date
    reason: str


@dataclass(frozen=True, kw_only=True)
class CalendarFeedFailing(DomainEvent):
    """A feed has kept failing for longer than the alert threshold: one per incident."""

    property_id: UUID
    channel: str
    since: datetime
