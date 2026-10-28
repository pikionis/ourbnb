"""Django admin of the reservations context (ADR 0006; BUILD_PLAN Phase 3).

- Reservations: a list with filters; DIRECT reservations are added, changed and cancelled here,
  and any reservation's times and guest name are changed here (DOMAIN §6).
- Calendar events to review: the admin answers "reservation" or "block" about unknown events;
  overlaps are resolved on the platforms.
- Calendar feeds: their health, "sync now" and "confirm empty calendar".

Forms and actions send commands through the message bus: the admin never writes the tables.
Nothing is deleted. The feeds themselves are set in the property's page (properties context).
"""

from collections.abc import Callable
from typing import Any

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.utils.html import format_html
from django.utils.safestring import SafeString
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from kospm.bootstrap import get_bus
from kospm.reservations import models
from kospm.reservations.domain.commands import (
    AddDirectReservation,
    CancelDirectReservation,
    ChangeReservation,
    ConfirmEmptyCalendar,
    DecideCalendarEvent,
    SyncCalendarFeed,
)
from kospm.reservations.entrypoints.forms import ReservationForm
from kospm.reservations.entrypoints.texts import describe
from kospm.shared.domain import Command, DomainError, new_id, to_athens
from kospm.shared.unit_of_work import ConcurrencyError

GREEN, AMBER, RED, BLUE, GREY = "#15803d", "#b45309", "#b42318", "#1d4ed8", "#6b7280"


class CommandRefused(Exception):
    """The domain refused a command while a form was saved; the change view reports it."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def send(command: Command) -> None:
    get_bus().handle(command)


def send_or_refuse(command: Command) -> None:
    """Send a form's command; a refusal becomes CommandRefused (rolls the page back)."""
    try:
        send(command)
    except (DomainError, ConcurrencyError) as error:
        raise CommandRefused(describe(error)) from error


def badge(text: str, colour: str) -> SafeString:
    return format_html(
        '<span style="background:{};color:#fff;border-radius:999px;padding:2px 10px;'
        'font-size:11px;white-space:nowrap">{}</span>',
        colour,
        text,
    )


class _CommandsOnly[M: models.Reservation | models.WaitingCalendarEvent | models.CalendarFeed](
    admin.ModelAdmin[M]
):
    """Refusals are reported on the form's page, and nothing is deletable."""

    def changeform_view(
        self,
        request: HttpRequest,
        object_id: str | None = None,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except CommandRefused as refused:
            # The admin's own transaction has rolled back: nothing of this save remains.
            self.message_user(request, refused.message, messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())

    def has_delete_permission(self, request: HttpRequest, obj: M | None = None) -> bool:
        return False

    def _each(
        self,
        request: HttpRequest,
        commands: list[tuple[str, Command]],
        done: Callable[[int], str],
    ) -> None:
        """Send one command per selected row, each in its own unit; report refusals by row."""
        sent = 0
        for label, command in commands:
            try:
                send(command)
            except (DomainError, ConcurrencyError) as error:
                self.message_user(request, f"{label}: {describe(error)}", messages.ERROR)
            else:
                sent += 1
        if sent:
            self.message_user(request, done(sent), messages.SUCCESS)


# --- reservations --------------------------------------------------------------------------------


@admin.register(models.Reservation)
class ReservationAdmin(_CommandsOnly[models.Reservation]):
    form = ReservationForm
    list_display = (
        "property_code",
        "check_in_date",
        "check_out_date",
        "nights",
        "channel",
        "guest_name",
        "confirmation_code",
        "status_badge",
    )
    list_filter = ("status", "channel", "calendar")
    list_select_related = ("calendar",)
    date_hierarchy = "check_in_date"
    search_fields = ("confirmation_code", "guest_name", "calendar__code", "calendar__name")
    actions = ("cancel_direct_reservations",)

    def get_fields(self, request: HttpRequest, obj: models.Reservation | None = None) -> Any:
        editable = ("check_in_date", "check_out_date", "check_in_time", "check_out_time")
        if obj is None:
            return ("calendar", *editable, "guest_name", "version")
        return (
            "property_code",
            "channel",
            "confirmation_code",
            "status_badge",
            *editable,
            "guest_name",
            "version",
        )

    def get_readonly_fields(
        self, request: HttpRequest, obj: models.Reservation | None = None
    ) -> Any:
        if obj is None:
            return ()
        return ("property_code", "channel", "confirmation_code", "status_badge")

    def has_change_permission(
        self, request: HttpRequest, obj: models.Reservation | None = None
    ) -> bool:
        cancelled = obj is not None and obj.status == models.ReservationStatusChoices.CANCELLED
        return not cancelled and super().has_change_permission(request, obj)

    @admin.display(description=gettext_lazy("property"), ordering="calendar__code")
    def property_code(self, obj: models.Reservation) -> str:
        return obj.calendar.code

    @admin.display(description=gettext_lazy("nights"))
    def nights(self, obj: models.Reservation) -> int:
        return (obj.check_out_date - obj.check_in_date).days

    @admin.display(description=gettext_lazy("status"), ordering="status")
    def status_badge(self, obj: models.Reservation) -> SafeString:
        status = models.ReservationStatusChoices(obj.status)
        colour = GREEN if status is models.ReservationStatusChoices.CONFIRMED else GREY
        return badge(str(status.label), colour)

    def save_model(
        self, request: HttpRequest, obj: models.Reservation, form: ReservationForm, change: bool
    ) -> None:
        data = form.cleaned_data
        if not change:
            obj.id = new_id()
            send_or_refuse(
                AddDirectReservation(
                    reservation_id=obj.id,
                    property_id=data["calendar"].pk,
                    check_in_date=data["check_in_date"],
                    check_out_date=data["check_out_date"],
                    guest_name=data.get("guest_name", ""),
                    check_in_time=data.get("check_in_time"),
                    check_out_time=data.get("check_out_time"),
                )
            )
            return
        send_or_refuse(
            ChangeReservation(
                property_id=obj.calendar_id,
                reservation_id=obj.pk,
                check_in_date=data["check_in_date"],
                check_out_date=data["check_out_date"],
                check_in_time=data["check_in_time"],
                check_out_time=data["check_out_time"],
                guest_name=data.get("guest_name", ""),
                expected_version=data.get("version"),
            )
        )

    @admin.action(description=gettext_lazy("Cancel the selected direct reservations"))
    def cancel_direct_reservations(
        self, request: HttpRequest, queryset: QuerySet[models.Reservation]
    ) -> None:
        self._each(
            request,
            [
                (
                    str(reservation),
                    CancelDirectReservation(
                        property_id=reservation.calendar_id, reservation_id=reservation.pk
                    ),
                )
                for reservation in queryset
            ],
            lambda count: (
                ngettext(
                    "%(count)d reservation cancelled.", "%(count)d reservations cancelled.", count
                )
                % {"count": count}
            ),
        )


# --- calendar events to review -------------------------------------------------------------------


@admin.register(models.WaitingCalendarEvent)
class WaitingCalendarEventAdmin(_CommandsOnly[models.WaitingCalendarEvent]):
    list_display = ("property_code", "channel", "check_in_date", "check_out_date", "reason_badge")
    list_filter = ("reason", "channel", "calendar")
    list_select_related = ("calendar",)
    readonly_fields = (
        "property_code",
        "channel",
        "check_in_date",
        "check_out_date",
        "reason_badge",
    )
    fields = readonly_fields
    actions = ("answer_reservation", "answer_block")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @admin.display(description=gettext_lazy("property"), ordering="calendar__code")
    def property_code(self, obj: models.WaitingCalendarEvent) -> str:
        return obj.calendar.code

    @admin.display(description=gettext_lazy("reason"), ordering="reason")
    def reason_badge(self, obj: models.WaitingCalendarEvent) -> SafeString:
        reason = models.ReviewReasonChoices(obj.reason)
        colour = AMBER if reason is models.ReviewReasonChoices.UNKNOWN else RED
        return badge(str(reason.label), colour)

    @admin.action(description=gettext_lazy("It is a reservation"))
    def answer_reservation(
        self, request: HttpRequest, queryset: QuerySet[models.WaitingCalendarEvent]
    ) -> None:
        self._answer(request, queryset, "reservation")

    @admin.action(description=gettext_lazy("It is a block (closed dates)"))
    def answer_block(
        self, request: HttpRequest, queryset: QuerySet[models.WaitingCalendarEvent]
    ) -> None:
        self._answer(request, queryset, "block")

    def _answer(
        self,
        request: HttpRequest,
        queryset: QuerySet[models.WaitingCalendarEvent],
        decision: str,
    ) -> None:
        commands: list[tuple[str, Command]] = []
        for event in list(queryset):
            if event.reason != models.ReviewReasonChoices.UNKNOWN:
                self.message_user(
                    request,
                    _("%(event)s overlaps a reservation: resolve it on the platforms.")
                    % {"event": event},
                    messages.WARNING,
                )
                continue
            command = DecideCalendarEvent(
                property_id=event.calendar_id,
                channel=event.channel,
                uid=event.uid,
                decision=decision,
            )
            commands.append((str(event), command))
        self._each(
            request,
            commands,
            lambda count: (
                ngettext("%(count)d answer saved.", "%(count)d answers saved.", count)
                % {"count": count}
            ),
        )


# --- calendar feeds ------------------------------------------------------------------------------


@admin.register(models.CalendarFeed)
class CalendarFeedAdmin(_CommandsOnly[models.CalendarFeed]):
    list_display = ("property_code", "channel", "health", "last_synced_at")
    list_filter = ("channel", "alerted")
    list_select_related = ("calendar",)
    readonly_fields = ("property_code", "channel", "health", "last_synced_at")
    fields = readonly_fields
    actions = ("sync_now", "confirm_empty_calendar")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @admin.display(description=gettext_lazy("property"), ordering="calendar__code")
    def property_code(self, obj: models.CalendarFeed) -> str:
        return obj.calendar.code

    @admin.display(description=gettext_lazy("health"))
    def health(self, obj: models.CalendarFeed) -> SafeString:
        if obj.failing_since is not None:
            since = to_athens(obj.failing_since).strftime("%d/%m %H:%M")
            return badge(_("Failing since %(since)s") % {"since": since}, RED)
        if obj.accept_empty:
            return badge(_("Empty calendar confirmed"), BLUE)
        if obj.last_synced_at is None:
            return badge(_("Not read yet"), GREY)
        return badge(_("OK"), GREEN)

    @admin.action(description=gettext_lazy("Sync now"))
    def sync_now(self, request: HttpRequest, queryset: QuerySet[models.CalendarFeed]) -> None:
        self._each(
            request,
            [
                (str(feed), SyncCalendarFeed(property_id=feed.calendar_id, channel=feed.channel))
                for feed in queryset
            ],
            lambda count: (
                ngettext("%(count)d calendar read.", "%(count)d calendars read.", count)
                % {"count": count}
            ),
        )

    @admin.action(description=gettext_lazy("Confirm that the calendar is empty"))
    def confirm_empty_calendar(
        self, request: HttpRequest, queryset: QuerySet[models.CalendarFeed]
    ) -> None:
        commands: list[tuple[str, Command]] = []
        for feed in queryset:
            commands.append(
                (
                    str(feed),
                    ConfirmEmptyCalendar(property_id=feed.calendar_id, channel=feed.channel),
                )
            )
            commands.append(
                (str(feed), SyncCalendarFeed(property_id=feed.calendar_id, channel=feed.channel))
            )
        self._each(request, commands, lambda count: _("Confirmed: the calendars were read again."))
