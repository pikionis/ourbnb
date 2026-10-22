"""`manage.py process_outbox`: deliver the due outbox messages once (ADR 0004, 0005).

The scheduler runs it every minute; `make run-jobs` runs it once locally. A thin entrypoint:
bootstrap wires the worker from settings, the service layer (`process_outbox`) does the work.
"""

from typing import Any

from django.core.management.base import BaseCommand

from kospm.bootstrap import build_outbox_worker


class Command(BaseCommand):
    help = (
        "Send the due outbox messages (WhatsApp, email) once, retrying failed ones with "
        "exponential backoff. The scheduler runs it every minute."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        # The console sender prints to this command's stdout, so call_command(stdout=...) and
        # the scheduler's log both see what would have been sent.
        report = build_outbox_worker(stdout=self.stdout).run()
        self.stdout.write(
            f"process_outbox: {report.sent} sent, {report.failed_attempts} failed attempts, "
            f"{report.exhausted} failed for good"
        )
