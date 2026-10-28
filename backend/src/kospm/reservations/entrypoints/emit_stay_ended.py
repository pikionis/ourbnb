"""`manage.py emit_stay_ended`: announce the stays whose check-out date has come (DOMAIN §6).

The scheduler runs it daily at 12:00 Athens (ADR 0004), after the default check-out. Each stay is
announced once (StayEnded); a day the job missed is caught up on the next run. Each property is
handled on its own: one that fails (e.g. a sync saving it at the same moment) never stops the
others, is tried again on the next run, and makes the command fail at the end.
"""

import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from kospm.bootstrap import get_bus
from kospm.reservations.adapters.queries import calendars_with_stays_ending
from kospm.reservations.domain.commands import EndStays
from kospm.shared.clock import SystemClock

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Raise StayEnded for the stays whose check-out date has come (daily at 12:00)."

    def handle(self, *args: Any, **options: Any) -> None:
        bus = get_bus()
        property_ids = calendars_with_stays_ending(SystemClock().today_athens())
        failed = 0
        for property_id in property_ids:
            try:
                bus.handle(EndStays(property_id=property_id))
            except Exception:
                failed += 1
                logger.exception("the stays of %s could not be ended", property_id)
        self.stdout.write(f"emit_stay_ended: {len(property_ids)} properties")
        if failed:
            raise CommandError(f"{failed} properties failed: they are tried again on the next run")
