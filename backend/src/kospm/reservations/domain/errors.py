"""Business rules of the reservations context that refuse an operation (DOMAIN §6)."""

from collections.abc import Iterable
from uuid import UUID

from kospm.shared.domain import DomainError


class InvalidValue(DomainError):
    """A value does not satisfy its rule (dates that end before they start, an empty UID, ...).

    `field` names the kind of value (e.g. "dates"), so an entrypoint can explain the rule in the
    reader's language; the message is for logs and developers.
    """

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(message)
        self.field = field


class OverlappingReservation(DomainError):
    """The stay would share a night with confirmed reservations of the property."""

    def __init__(self, overlapping: Iterable[UUID]) -> None:
        self.overlapping = tuple(overlapping)
        super().__init__(
            "the stay overlaps confirmed reservations: "
            + ", ".join(str(reservation_id) for reservation_id in self.overlapping)
        )


class CalendarNotFound(DomainError):
    """The reservations context knows no property with this id."""


class ReservationNotFound(DomainError):
    """The property has no confirmed reservation with this id."""


class FeedNotConfigured(DomainError):
    """The property has no calendar feed for this channel."""


class ChangeOnThePlatform(DomainError):
    """The dates and the cancellation of an Airbnb or Booking.com reservation come from its feed:
    they change on the platform, never in KosPM (DOMAIN §6)."""

    def __init__(self, channel: str) -> None:
        self.channel = channel
        super().__init__(f"a {channel} reservation is changed or cancelled on the platform")


class CalendarEventNotWaiting(DomainError):
    """The admin answered about a calendar event that is not waiting for an answer."""
