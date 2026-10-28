from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ReservationsConfig(AppConfig):
    name = "kospm.reservations"
    label = "reservations"
    verbose_name = _("Reservations")
