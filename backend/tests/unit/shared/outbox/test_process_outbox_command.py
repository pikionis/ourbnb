"""The `process_outbox` command, with the composition root swapped for fakes (no database).

The command is a thin entrypoint: build the worker (bootstrap), run it once, print a summary.
tests/e2e/test_process_outbox_command.py runs the real wiring against PostgreSQL.
"""

import io
from datetime import UTC, datetime, timedelta

import pytest
from django.core.management import call_command

from kospm.bootstrap import OutboxWorker
from kospm.shared.clock import Clock, FixedClock
from kospm.shared.outbox.adapters import ConsoleSender, TextStream
from kospm.shared.outbox.domain import (
    OutboxChannel,
    OutboxEntry,
    OutboxMessage,
    OutboxRetryPolicy,
    OutboxStatus,
)
from kospm.shared.outbox.entrypoints import process_outbox
from tests.unit.shared.outbox.fakes import FakeOutboxUnitOfWork

NOW = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)
MESSAGE = OutboxMessage(
    channel=OutboxChannel.WHATSAPP,
    recipient="+306900000001",
    template="cleaning_assigned",
    payload={"cleaner": "Μαρία"},
)
# The fake repository stores copies, so this module-level entry is never changed by a test.
DUE_ENTRY = OutboxEntry.new(MESSAGE, now=NOW - timedelta(minutes=1))


@pytest.fixture
def uow(monkeypatch: pytest.MonkeyPatch) -> FakeOutboxUnitOfWork:
    """Make the command build its worker from fakes; the Unit of Work holds one due message."""
    fake_uow = FakeOutboxUnitOfWork([DUE_ENTRY])

    def build_fake_worker(
        *, stdout: TextStream | None = None, clock: Clock | None = None
    ) -> OutboxWorker:
        return OutboxWorker(
            uow=fake_uow,
            sender=ConsoleSender(stdout),
            clock=FixedClock(NOW),
            policy=OutboxRetryPolicy(),
            batch_size=100,
        )

    monkeypatch.setattr(process_outbox, "build_outbox_worker", build_fake_worker)
    return fake_uow


def test_the_command_sends_due_messages_to_its_own_stdout(uow: FakeOutboxUnitOfWork) -> None:
    stdout = io.StringIO()

    call_command("process_outbox", stdout=stdout)

    output = stdout.getvalue()
    assert "cleaning_assigned" in output
    assert "Μαρία" in output
    assert uow.entries.get(DUE_ENTRY.id).status == OutboxStatus.SENT


def test_the_command_ends_with_a_one_line_summary(uow: FakeOutboxUnitOfWork) -> None:
    stdout = io.StringIO()

    call_command("process_outbox", stdout=stdout)

    summary = stdout.getvalue().splitlines()[-1]
    assert summary == "process_outbox: 1 sent, 0 failed attempts, 0 failed for good"


def test_the_command_explains_itself_in_help() -> None:
    assert "outbox" in process_outbox.Command.help
