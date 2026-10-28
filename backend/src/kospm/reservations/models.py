"""ORM tables of the reservations context. Infrastructure only: the rules live in `domain/`.

One ReservationCalendar aggregate is a `PropertyCalendar` row with its child rows (feeds,
reservations, events waiting for the admin, the admin's answers). They are mapped in
`adapters/repository.py`; nothing else writes them (the admin sends commands). The root's
`version` guards the whole aggregate (ADR 0016).
"""

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class ChannelChoices(models.TextChoices):
    AIRBNB = "airbnb", "Airbnb"
    BOOKING = "booking", "Booking.com"
    DIRECT = "direct", _("Direct")


class FeedChannelChoices(models.TextChoices):
    AIRBNB = "airbnb", "Airbnb"
    BOOKING = "booking", "Booking.com"


class ReservationStatusChoices(models.TextChoices):
    CONFIRMED = "confirmed", _("Confirmed")
    CANCELLED = "cancelled", _("Cancelled")


class ReviewReasonChoices(models.TextChoices):
    UNKNOWN = "unknown", _("Reservation or block?")
    OVERLAP = "overlap", _("Overlaps a reservation")


class DecisionChoices(models.TextChoices):
    RESERVATION = "reservation", _("Reservation")
    BLOCK = "block", _("Block")


class PropertyCalendar(models.Model):
    """The reservations context's copy of a property (DOMAIN §4.1) and the root of its calendar."""

    property_id = models.UUIDField(primary_key=True, editable=False)
    code = models.CharField(_("code"), max_length=16)
    name = models.CharField(_("name"), max_length=200)
    active = models.BooleanField(_("active"), default=False)
    check_in_time = models.TimeField(_("check-in time"))
    check_out_time = models.TimeField(_("check-out time"))
    version = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("property calendar")
        verbose_name_plural = _("property calendars")
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class CalendarFeed(models.Model):
    calendar = models.ForeignKey(PropertyCalendar, on_delete=models.CASCADE, related_name="feeds")
    channel = models.CharField(_("channel"), max_length=16, choices=FeedChannelChoices.choices)
    url = models.URLField(_("calendar link"), max_length=1000)
    failing_since = models.DateTimeField(_("failing since"), null=True, blank=True)
    alerted = models.BooleanField(_("admin alerted"), default=False)
    accept_empty = models.BooleanField(_("empty calendar confirmed"), default=False)
    etag = models.CharField(max_length=255, blank=True)
    last_modified = models.CharField(max_length=64, blank=True)
    last_synced_at = models.DateTimeField(_("last synced"), null=True, blank=True)

    class Meta:
        verbose_name = _("calendar feed")
        verbose_name_plural = _("calendar feeds")
        constraints = (
            models.UniqueConstraint(fields=("calendar", "channel"), name="one_feed_per_channel"),
        )

    def __str__(self) -> str:
        return f"{self.calendar_id} {self.channel}"


class Reservation(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    calendar = models.ForeignKey(
        PropertyCalendar, on_delete=models.PROTECT, related_name="reservations"
    )
    channel = models.CharField(_("channel"), max_length=16, choices=ChannelChoices.choices)
    external_uid = models.CharField(_("calendar event"), max_length=255, blank=True)  # "": direct
    confirmation_code = models.CharField(_("confirmation code"), max_length=32, blank=True)
    check_in_date = models.DateField(_("check-in"))
    check_out_date = models.DateField(_("check-out"))
    check_in_time = models.TimeField(_("check-in time"))
    check_out_time = models.TimeField(_("check-out time"))
    status = models.CharField(
        _("status"),
        max_length=16,
        choices=ReservationStatusChoices.choices,
        default=ReservationStatusChoices.CONFIRMED,
    )
    guest_name = models.CharField(_("guest"), max_length=200, blank=True)
    stay_ended = models.BooleanField(_("stay ended"), default=False)

    class Meta:
        verbose_name = _("reservation")
        verbose_name_plural = _("reservations")
        ordering = ("check_in_date",)
        constraints = (
            # One confirmed reservation per feed event (a cancelled one may come back as new).
            models.UniqueConstraint(
                fields=("calendar", "channel", "external_uid"),
                condition=Q(status="confirmed") & ~Q(external_uid=""),
                name="one_confirmed_reservation_per_event",
            ),
            models.CheckConstraint(
                condition=Q(check_out_date__gt=models.F("check_in_date")),
                name="reservation_ends_after_it_starts",
            ),
        )
        indexes = (models.Index(fields=("status", "check_out_date"), name="reservation_ends_idx"),)

    def __str__(self) -> str:
        return f"{self.check_in_date} to {self.check_out_date} ({self.channel})"


class WaitingCalendarEvent(models.Model):
    """A feed event waiting for the admin: unknown, or overlapping a reservation."""

    calendar = models.ForeignKey(PropertyCalendar, on_delete=models.CASCADE, related_name="waiting")
    channel = models.CharField(_("channel"), max_length=16, choices=FeedChannelChoices.choices)
    uid = models.CharField(_("calendar event"), max_length=255)
    check_in_date = models.DateField(_("check-in"))
    check_out_date = models.DateField(_("check-out"))
    reason = models.CharField(_("reason"), max_length=16, choices=ReviewReasonChoices.choices)
    confirmation_code = models.CharField(_("confirmation code"), max_length=32, blank=True)

    class Meta:
        verbose_name = _("calendar event to review")
        verbose_name_plural = _("calendar events to review")
        ordering = ("check_in_date",)

    def __str__(self) -> str:
        return f"{self.check_in_date} to {self.check_out_date} ({self.channel})"


class CalendarDecision(models.Model):
    """The admin's answer about an unknown feed event, remembered by its UID."""

    calendar = models.ForeignKey(
        PropertyCalendar, on_delete=models.CASCADE, related_name="decisions"
    )
    channel = models.CharField(max_length=16, choices=FeedChannelChoices.choices)
    uid = models.CharField(max_length=255)
    decision = models.CharField(max_length=16, choices=DecisionChoices.choices)

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=("calendar", "channel", "uid"), name="one_answer_per_event"
            ),
        )

    def __str__(self) -> str:
        return f"{self.uid}: {self.decision}"
