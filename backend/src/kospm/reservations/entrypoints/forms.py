"""Admin forms of the reservations context.

They validate with the domain, never with rules of their own: the form's change is applied to an
unsaved copy of the property's calendar (`calendar_preview`), so a refusal such as an overlap
shows on the form before anything is sent. A hidden `version` carries the calendar's version the
form was rendered with (ADR 0016).
"""

from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from kospm.reservations import models
from kospm.reservations.adapters.queries import calendar_preview
from kospm.reservations.domain.errors import InvalidValue
from kospm.reservations.domain.value_objects import Channel, StayDates
from kospm.reservations.entrypoints.texts import describe
from kospm.shared.clock import SystemClock
from kospm.shared.domain import DomainError, new_id

DATE_FIELDS = ("check_in_date", "check_out_date")


class ReservationForm(forms.ModelForm[models.Reservation]):
    """Adds a DIRECT reservation, or changes a reservation: its times and guest, and the dates
    of a DIRECT one (DOMAIN §6)."""

    version = forms.IntegerField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = models.Reservation
        fields = ("calendar", *DATE_FIELDS, "check_in_time", "check_out_time", "guest_name")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.adding = self.instance._state.adding
        if "calendar" in self.fields:
            self.fields["calendar"].label = _("property")
        if self.adding:
            for name in ("check_in_time", "check_out_time"):
                self.fields[name].required = False
                self.fields[name].help_text = _("Empty: the property's time.")
        else:
            self.initial.setdefault("version", self.instance.calendar.version)
            if self.instance.channel != Channel.DIRECT:
                for name in DATE_FIELDS:
                    self.fields[name].disabled = True
                    self.fields[name].help_text = _("From the platform's calendar.")

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        if self.errors:
            return data  # judge the whole only when every value is valid
        try:
            dates = StayDates(data["check_in_date"], data["check_out_date"])
            if self.adding:
                calendar = calendar_preview(data["calendar"].pk)
                calendar.add_direct_reservation(
                    new_id(),
                    dates=dates,
                    today=SystemClock().today_athens(),
                    guest_name=data.get("guest_name", ""),
                    check_in_time=data.get("check_in_time"),
                    check_out_time=data.get("check_out_time"),
                )
            else:
                calendar = calendar_preview(self.instance.calendar_id)
                calendar.change_reservation(
                    self.instance.pk,
                    dates=dates,
                    check_in_time=data["check_in_time"],
                    check_out_time=data["check_out_time"],
                    guest_name=data.get("guest_name", ""),
                )
        except InvalidValue as error:
            field = "check_out_date" if error.field == "dates" else None
            self.add_error(field, describe(error))
        except DomainError as error:
            raise ValidationError(describe(error)) from error
        return data
