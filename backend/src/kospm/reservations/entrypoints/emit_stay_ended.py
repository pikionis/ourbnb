"""`manage.py emit_stay_ended`: announce the stays whose check-out date has come (DOMAIN §6).

The scheduler runs it daily at 12:00 Athens (ADR 0004), after the default check-out. Each stay is
announced once (StayEnded); a day the job missed is caught up on the next run.
"""

from typing import Any

from django.core.management.base import BaseCommand

from kospm.bootstrap import get_bus
from kospm.reservations.adapters.queries import calendars_with_stays_ending
from kospm.reservations.domain.commands import EndStays
from kospm.shared.clock import SystemClock


class Command(BaseCommand):
    help = "Raise StayEnded for the stays whose check-out date has come (daily at 12:00)."

    def handle(self, *args: Any, **options: Any) -> None:
        bus = get_bus()
        property_ids = calendars_with_stays_ending(SystemClock().today_athens())
        for property_id in property_ids:
            bus.handle(EndStays(property_id=property_id))
        self.stdout.write(f"emit_stay_ended: {len(property_ids)} properties")
