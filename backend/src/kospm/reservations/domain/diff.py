"""CalendarDiff: what one feed changes in the stored reservations of its channel (DOMAIN §6).

A pure function (a domain service, Cosmic Python ch. 1), so the rules of the sync are tested
without a feed or a database:
- an event with a UID not stored is a new reservation;
- an event whose dates differ from its reservation's reschedules it, unless that stay has ended;
- a reservation whose event is gone is cancelled only if its check-in date is after today.
The same feed twice gives no changes: the sync is idempotent.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from kospm.reservations.domain.reservation import Reservation
from kospm.reservations.domain.value_objects import ImportedCalendarEvent


@dataclass(frozen=True)
class FeedChanges:
    new: tuple[ImportedCalendarEvent, ...] = ()
    rescheduled: tuple[tuple[Reservation, ImportedCalendarEvent], ...] = ()
    cancelled: tuple[Reservation, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.new or self.rescheduled or self.cancelled)


def calendar_diff(
    stored: Iterable[Reservation], imported: Iterable[ImportedCalendarEvent], *, today: date
) -> FeedChanges:
    """`stored`: the channel's confirmed reservations; `imported`: the feed's reservations."""
    by_uid = {
        reservation.external_uid: reservation for reservation in stored if reservation.external_uid
    }
    found: dict[str, ImportedCalendarEvent] = {}
    for event in imported:
        found.setdefault(event.uid, event)  # a UID listed twice: the first one counts
    return FeedChanges(
        new=tuple(event for uid, event in found.items() if uid not in by_uid),
        rescheduled=tuple(
            (by_uid[uid], event)
            for uid, event in found.items()
            if uid in by_uid
            and event.dates != by_uid[uid].dates
            and not by_uid[uid].dates.has_ended(today)
        ),
        cancelled=tuple(
            reservation
            for uid, reservation in by_uid.items()
            if uid not in found and reservation.dates.starts_after(today)
        ),
    )
