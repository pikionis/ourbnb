"""Read side of the reservations context (Cosmic Python ch. 12, CQRS): what the scheduled
commands and the admin's forms need to know, read straight from the tables."""

from datetime import date
from uuid import UUID

from kospm.reservations import models
from kospm.reservations.adapters.repository import calendar_to_domain
from kospm.reservations.domain.calendar import ReservationCalendar
from kospm.reservations.domain.errors import CalendarNotFound


def feeds_to_sync() -> list[tuple[UUID, str]]:
    """The feeds of the ACTIVE properties, as (property_id, channel), by property code."""
    return list(
        models.CalendarFeed.objects.filter(calendar__active=True)
        .order_by("calendar__code", "channel")
        .values_list("calendar_id", "channel")
    )


def calendars_with_stays_ending(today: date) -> list[UUID]:
    """The properties with confirmed stays whose check-out date has come and is not announced."""
    return list(
        models.Reservation.objects.filter(
            status=models.ReservationStatusChoices.CONFIRMED,
            stay_ended=False,
            check_out_date__lte=today,
        )
        .order_by()
        .values_list("calendar_id", flat=True)
        .distinct()
    )


def calendar_preview(property_id: UUID) -> ReservationCalendar:
    """An unsaved copy of a property's calendar: forms apply a change to it, to show the
    domain's refusal next to the field before anything is sent."""
    row = (
        models.PropertyCalendar.objects.prefetch_related(
            "feeds", "reservations", "waiting", "decisions"
        )
        .filter(property_id=property_id)
        .first()
    )
    if row is None:
        raise CalendarNotFound(f"the reservations context knows no property {property_id}")
    return calendar_to_domain(row)
