"""Phase 1 "done when": `process_outbox` turns a PENDING message into SENT and prints it.

Real wiring end to end: a handler-style Unit of Work enqueues through DjangoOutbox, the command
builds its worker in bootstrap from the test settings (console sender) and runs it.
"""

import io
from datetime import UTC, datetime

import pytest
from django.core.management import call_command

from kospm.shared.clock import FixedClock
from kospm.shared.outbox import models
from kospm.shared.outbox.adapters import DjangoOutbox, DjangoOutboxUnitOfWork
from kospm.shared.outbox.domain import OutboxChannel, OutboxMessage, OutboxStatus

pytestmark = pytest.mark.django_db

# In the past, so the message is due for the worker, which reads the system clock.
ENQUEUED_AT = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)
MESSAGE = OutboxMessage(
    channel=OutboxChannel.WHATSAPP,
    recipient="+306900000001",
    template="cleaning_assigned",
    payload={"cleaner": "Μαρία", "property": "KOS-A1"},
)


def enqueue(message: OutboxMessage) -> None:
    uow = DjangoOutboxUnitOfWork(outbox=DjangoOutbox(FixedClock(ENQUEUED_AT)))
    with uow:
        uow.outbox.enqueue(message)
        uow.commit()


def test_a_pending_message_is_sent_to_the_console_and_marked_sent() -> None:
    enqueue(MESSAGE)
    stdout = io.StringIO()

    call_command("process_outbox", stdout=stdout)

    row = models.OutboxMessage.objects.get()
    assert row.status == OutboxStatus.SENT
    assert row.sent_at is not None
    assert row.attempts == 0
    output = stdout.getvalue()
    assert "cleaning_assigned" in output
    assert "+306900000001" in output
    assert "Μαρία" in output
    assert output.splitlines()[-1] == (
        "process_outbox: 1 sent, 0 failed attempts, 0 failed for good"
    )


def test_a_second_run_sends_nothing_again() -> None:
    enqueue(MESSAGE)
    call_command("process_outbox", stdout=io.StringIO())
    stdout = io.StringIO()

    call_command("process_outbox", stdout=stdout)

    assert stdout.getvalue().splitlines() == [
        "process_outbox: 0 sent, 0 failed attempts, 0 failed for good"
    ]
    assert models.OutboxMessage.objects.get().status == OutboxStatus.SENT
