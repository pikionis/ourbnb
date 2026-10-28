"""Commands of the reservations context (Cosmic Python ch. 10).

Commands carry plain values, as a form, a scheduled job or another context's event sends them;
the handlers turn them into value objects. `expected_version` (on commands sent from a form) is
the version the form was rendered with (ADR 0016).
"""

from dataclasses import dataclass
from datetime import date, time
from uuid import UUID

from kospm.shared.domain import Command


@dataclass(frozen=True, kw_only=True)
class UpdatePropertyCalendar(Command):
    """The properties context changed what reservations keeps of a property (DOMAIN §4.1)."""

    property_id: UUID
    code: str
    name: str
    active: bool
    check_in_time: time
    check_out_time: time
    feeds: tuple[tuple[str, str], ...]  # (channel, url)


@dataclass(frozen=True, kw_only=True)
class SyncCalendarFeed(Command):
    """Read one channel's feed of a property and apply it (scheduled every 30 minutes)."""

    property_id: UUID
    channel: str


@dataclass(frozen=True, kw_only=True)
class ConfirmEmptyCalendar(Command):
    """The admin confirms that the channel's calendar is really empty (DOMAIN §6, feed health)."""

    property_id: UUID
    channel: str


@dataclass(frozen=True, kw_only=True)
class DecideCalendarEvent(Command):
    """The admin's answer about an unknown feed event: "reservation" or "block"."""

    property_id: UUID
    channel: str
    uid: str
    decision: str


@dataclass(frozen=True, kw_only=True)
class AddDirectReservation(Command):
    """A reservation the admin enters (channel DIRECT). Times left out take the property's."""

    reservation_id: UUID
    property_id: UUID
    check_in_date: date
    check_out_date: date
    guest_name: str = ""
    check_in_time: time | None = None
    check_out_time: time | None = None
    expected_version: int | None = None


@dataclass(frozen=True, kw_only=True)
class ChangeReservation(Command):
    """The admin's edit: check-in/out times and guest name; the dates of a DIRECT reservation."""

    property_id: UUID
    reservation_id: UUID
    check_in_date: date
    check_out_date: date
    check_in_time: time
    check_out_time: time
    guest_name: str
    expected_version: int | None = None


@dataclass(frozen=True, kw_only=True)
class CancelDirectReservation(Command):
    property_id: UUID
    reservation_id: UUID
    expected_version: int | None = None


@dataclass(frozen=True, kw_only=True)
class EndStays(Command):
    """Announce the property's stays whose check-out date has come (scheduled at 12:00)."""

    property_id: UUID
