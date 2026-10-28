"""Test data of the reservations context: one property on Kos with an Airbnb and a Booking.com feed.

"Today" is 10 July 2026 (Athens). Dates are written as "MM-DD" of 2026 to keep tests readable.
"""

from datetime import UTC, date, datetime, time
from uuid import UUID

from kospm.reservations.domain.calendar import Feed, PropertyDetails, ReservationCalendar
from kospm.reservations.domain.policies import FeedHealthPolicy
from kospm.reservations.domain.value_objects import (
    Channel,
    EventKind,
    ImportedCalendarEvent,
    StayDates,
)

TODAY = date(2026, 7, 10)
NOW = datetime(2026, 7, 10, 9, 0, tzinfo=UTC)
PROPERTY_ID = UUID("00000000-0000-4000-8000-000000000001")
AIRBNB_URL = "https://www.airbnb.com/calendar/ical/1001.ics?s=test"
BOOKING_URL = "https://ical.booking.com/v1/export?t=test"
DETAILS = PropertyDetails(
    code="KOS-001",
    name="Villa Elena",
    active=True,
    check_in_time=time(15),
    check_out_time=time(11),
)
POLICY = FeedHealthPolicy()


def day(text: str) -> date:
    """ "07-12" → 12 July 2026."""
    month, day_of_month = text.split("-")
    return date(2026, int(month), int(day_of_month))


def stay(check_in: str, check_out: str) -> StayDates:
    return StayDates(day(check_in), day(check_out))


def event(
    uid: str,
    check_in: str,
    check_out: str,
    kind: EventKind = EventKind.RESERVATION,
    code: str = "",
) -> ImportedCalendarEvent:
    return ImportedCalendarEvent(
        uid=uid, dates=stay(check_in, check_out), kind=kind, confirmation_code=code
    )


def calendar(*, details: PropertyDetails = DETAILS) -> ReservationCalendar:
    """A property with both feeds and no reservations yet."""
    return ReservationCalendar(
        PROPERTY_ID,
        details=details,
        feeds=[Feed(Channel.AIRBNB, AIRBNB_URL), Feed(Channel.BOOKING, BOOKING_URL)],
    )
