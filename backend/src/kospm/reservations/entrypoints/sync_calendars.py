"""`manage.py sync_calendars`: read every active property's calendar feeds once (DOMAIN §6).

The scheduler runs it every 30 minutes (ADR 0004); `make run-jobs` runs it once locally. Each
feed is read in its own command: one that fails, or that loses a race with the admin, never stops
the others, and the next run reads it again. An unexpected error is logged with its traceback
and makes the command fail at the end, so the scheduler's log shows it.
"""

import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from kospm.bootstrap import get_bus
from kospm.reservations.adapters.queries import feeds_to_sync
from kospm.reservations.domain.commands import SyncCalendarFeed
from kospm.shared.domain import DomainError
from kospm.shared.unit_of_work import ConcurrencyError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Read the calendar feeds of every active property and apply them (every 30 minutes)."

    def handle(self, *args: Any, **options: Any) -> None:
        bus = get_bus()
        read = refused = errors = 0
        for property_id, channel in feeds_to_sync():
            try:
                bus.handle(SyncCalendarFeed(property_id=property_id, channel=channel))
            except (DomainError, ConcurrencyError) as error:
                refused += 1
                logger.warning("calendar of %s (%s) not applied: %s", property_id, channel, error)
            except Exception:
                errors += 1
                logger.exception("calendar of %s (%s) failed", property_id, channel)
            else:
                read += 1
        self.stdout.write(
            f"sync_calendars: {read} feeds read, {refused} not applied, {errors} errors"
        )
        if errors:
            raise CommandError(f"{errors} calendar feeds failed with an error")
