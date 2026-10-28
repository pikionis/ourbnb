"""What the admin reads about the reservations domain: sentences for its refusals (el/en).

The domain reports facts in code (exception types and attributes); this module turns them into
sentences. Business rules never live here.
"""

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django_stubs_ext import StrOrPromise

from kospm.reservations.domain.errors import (
    CalendarEventNotWaiting,
    CalendarNotFound,
    ChangeOnThePlatform,
    FeedNotConfigured,
    InvalidValue,
    OverlappingReservation,
    ReservationNotFound,
)
from kospm.shared.unit_of_work import ConcurrencyError

# What to tell the admin when the domain refuses a value (InvalidValue.field).
INVALID_VALUE_MESSAGES: dict[str, StrOrPromise] = {
    "dates": gettext_lazy("The check-out date comes after the check-in date."),
    "decision": gettext_lazy("Answer with “reservation” or “block”."),
    "channel": gettext_lazy("Choose Airbnb or Booking.com."),
    "uid": gettext_lazy("The calendar event has no identifier."),
    "url": gettext_lazy("The calendar link is missing."),
}


def describe(error: Exception) -> str:
    """A sentence for the admin about a refused command; unknown errors keep their own text."""
    if isinstance(error, InvalidValue):
        return str(INVALID_VALUE_MESSAGES.get(error.field, error))
    if isinstance(error, OverlappingReservation):
        return _("These dates overlap another reservation of the property.")
    if isinstance(error, ChangeOnThePlatform):
        return _(
            "The dates of an Airbnb or Booking.com reservation change on the platform, and its "
            "calendar brings them here. Here you change its times and the guest's name."
        )
    if isinstance(error, ReservationNotFound):
        return _("The reservation was not found, or it is cancelled.")
    if isinstance(error, CalendarEventNotWaiting):
        return _("This calendar event no longer waits for an answer.")
    if isinstance(error, CalendarNotFound):
        return _("Reservations does not know this property yet.")
    if isinstance(error, FeedNotConfigured):
        return _("The property has no calendar link for this platform.")
    if isinstance(error, ConcurrencyError):
        return _("Someone else changed this in the meantime. Reload the page and try again.")
    return str(error)
