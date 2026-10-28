"""Value objects of the reservations context (DOMAIN §6)."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from kospm.reservations.domain.errors import InvalidValue


class Channel(StrEnum):
    """Where a reservation was booked (DOMAIN §3). Values are stored in the database."""

    AIRBNB = "airbnb"
    BOOKING = "booking"
    DIRECT = "direct"


@dataclass(frozen=True)
class StayDates:
    """The nights of a stay: from the check-in date to the check-out date, the morning the guests
    leave. The check-out day of one stay may be the check-in day of the next."""

    check_in: date
    check_out: date

    def __post_init__(self) -> None:
        if self.check_out <= self.check_in:
            raise InvalidValue(
                f"a stay ends after it starts: {self.check_in} to {self.check_out}", field="dates"
            )

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days

    def overlaps(self, other: "StayDates") -> bool:
        """The two stays share a night (a check-out day may be the next check-in day)."""
        return self.check_in < other.check_out and other.check_in < self.check_out

    def has_ended(self, today: date) -> bool:
        """The guests left before today."""
        return self.check_out < today

    def starts_after(self, today: date) -> bool:
        return self.check_in > today


class EventKind(StrEnum):
    """What a feed event is, as its channel adapter reads it (DOMAIN §6)."""

    RESERVATION = "reservation"
    BLOCK = "block"  # closed by the host, or the mirror of another platform's reservation
    UNKNOWN = "unknown"  # the feed does not say (Booking.com): the admin answers


@dataclass(frozen=True)
class ImportedCalendarEvent:
    """One event of a channel's calendar feed, classified by the channel adapter.

    Only what the sync needs is kept: the summary and description are read by the adapter and
    dropped (an Airbnb description holds digits of the guest's phone).
    """

    uid: str
    dates: StayDates
    kind: EventKind
    confirmation_code: str = ""

    def __post_init__(self) -> None:
        if not self.uid.strip():
            raise InvalidValue("a calendar event has a UID", field="uid")
