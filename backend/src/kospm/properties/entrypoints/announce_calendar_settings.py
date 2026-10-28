"""`manage.py announce_calendar_settings`: tell the reservations context about every property.

Run once where properties existed before the reservations context (Phase 3): each property's
calendar settings travel as PropertyCalendarSettingsChanged, as they do on every later change
(DOMAIN §4.1). Running it again changes nothing.
"""

from typing import Any

from django.core.management.base import BaseCommand

from kospm.bootstrap import get_bus
from kospm.properties import models
from kospm.properties.domain.commands import AnnounceCalendarSettings


class Command(BaseCommand):
    help = "Tell the reservations context about every property's calendar settings (once)."

    def handle(self, *args: Any, **options: Any) -> None:
        bus = get_bus()
        property_ids = list(models.Property.objects.values_list("id", flat=True))
        for property_id in property_ids:
            bus.handle(AnnounceCalendarSettings(property_id=property_id))
        self.stdout.write(f"announce_calendar_settings: {len(property_ids)} properties announced")
