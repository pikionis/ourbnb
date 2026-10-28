"""Composition root, outbox worker: settings become a policy, a sender and a Unit of Work.

Building the worker never queries the database (pytest-django would refuse it in a unit test);
only `run()` does. Running it here uses the in-memory fakes of the worker tests instead.
"""

import io
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMessage
from django.test import override_settings

from kospm.bootstrap import OutboxWorker, build_outbox_worker
from kospm.shared.clock import FixedClock, SystemClock
from kospm.shared.outbox.adapters import ChannelRouter, DjangoOutbox, DjangoOutboxUnitOfWork
from kospm.shared.outbox.domain import (
    OutboxChannel,
    OutboxEntry,
    OutboxMessage,
    OutboxRetryPolicy,
    OutboxStatus,
)
from tests.fakes import FakeSender
from tests.unit.shared.outbox.fakes import FakeOutboxUnitOfWork

NOW = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)
MESSAGE = OutboxMessage(
    channel=OutboxChannel.WHATSAPP,
    recipient="+306900000001",
    template="cleaning_assigned",
    payload={"cleaner": "Μαρία"},
)


# --- built from settings -----------------------------------------------------------------------


def test_the_test_settings_build_the_default_policy_and_batch_size() -> None:
    worker = build_outbox_worker(stdout=io.StringIO(), clock=FixedClock(NOW))

    assert worker.policy == OutboxRetryPolicy(
        max_attempts=5,
        base_delay=timedelta(seconds=60),
        factor=2,
        max_delay=timedelta(seconds=3600),
    )
    assert worker.batch_size == 100


@override_settings(
    OUTBOX_MAX_ATTEMPTS=3,
    OUTBOX_BASE_DELAY_SECONDS=30,
    OUTBOX_BACKOFF_FACTOR=3,
    OUTBOX_MAX_DELAY_SECONDS=600,
    OUTBOX_BATCH_SIZE=7,
)
def test_the_retry_policy_and_batch_size_come_from_settings_at_build_time() -> None:
    worker = build_outbox_worker(stdout=io.StringIO(), clock=FixedClock(NOW))

    assert worker.policy == OutboxRetryPolicy(
        max_attempts=3,
        base_delay=timedelta(seconds=30),
        factor=3,
        max_delay=timedelta(minutes=10),
    )
    assert worker.batch_size == 7


def test_the_worker_uses_the_django_outbox_unit_of_work_and_the_given_clock() -> None:
    clock = FixedClock(NOW)

    worker = build_outbox_worker(stdout=io.StringIO(), clock=clock)

    assert isinstance(worker.uow, DjangoOutboxUnitOfWork)
    assert isinstance(worker.uow.outbox, DjangoOutbox)
    assert worker.clock is clock


def test_without_a_clock_the_worker_reads_the_system_clock() -> None:
    worker = build_outbox_worker(stdout=io.StringIO())

    assert isinstance(worker.clock, SystemClock)


# --- the sender ---------------------------------------------------------------------------------


def test_whatsapp_messages_are_printed_to_the_given_stdout() -> None:
    stdout = io.StringIO()
    worker = build_outbox_worker(stdout=stdout, clock=FixedClock(NOW))

    worker.sender.send(MESSAGE)

    assert isinstance(worker.sender, ChannelRouter)
    assert "cleaning_assigned" in stdout.getvalue()
    assert "Μαρία" in stdout.getvalue()


def test_emails_go_through_djangos_email_backend(mailoutbox: list[EmailMessage]) -> None:
    stdout = io.StringIO()
    worker = build_outbox_worker(stdout=stdout, clock=FixedClock(NOW))

    worker.sender.send(
        OutboxMessage(
            channel=OutboxChannel.EMAIL,
            recipient="maria@example.com",
            template="identity.confirmation",
            payload={"subject": "Επιβεβαίωση", "body": "Γεια σας"},
        )
    )

    (email,) = mailoutbox
    assert (email.to, email.subject, email.body) == (
        ["maria@example.com"],
        "Επιβεβαίωση",
        "Γεια σας",
    )
    assert stdout.getvalue() == ""


def test_without_stdout_the_console_sender_writes_to_the_process_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    worker = build_outbox_worker(clock=FixedClock(NOW))

    worker.sender.send(MESSAGE)

    assert "cleaning_assigned" in capsys.readouterr().out


@override_settings(OUTBOX_SENDER="whatsapp")
def test_an_unknown_sender_is_a_configuration_error() -> None:
    with pytest.raises(ImproperlyConfigured, match="OUTBOX_SENDER"):
        build_outbox_worker(stdout=io.StringIO(), clock=FixedClock(NOW))


# --- invalid numbers fail at startup, naming the settings --------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"OUTBOX_MAX_ATTEMPTS": 0},
        {"OUTBOX_BASE_DELAY_SECONDS": 0},
        {"OUTBOX_BACKOFF_FACTOR": 0},
        {"OUTBOX_MAX_DELAY_SECONDS": 10},  # shorter than the 60 s base delay
    ],
)
def test_an_invalid_retry_setting_is_a_configuration_error(overrides: dict[str, int]) -> None:
    with (
        override_settings(**overrides),
        pytest.raises(ImproperlyConfigured, match="OUTBOX_"),
    ):
        build_outbox_worker(stdout=io.StringIO(), clock=FixedClock(NOW))


@pytest.mark.parametrize("batch_size", [0, -1])
def test_a_batch_size_below_one_is_a_configuration_error(batch_size: int) -> None:
    with (
        override_settings(OUTBOX_BATCH_SIZE=batch_size),
        pytest.raises(ImproperlyConfigured, match="OUTBOX_BATCH_SIZE"),
    ):
        build_outbox_worker(stdout=io.StringIO(), clock=FixedClock(NOW))


# --- run() is process_outbox with the wired parts ----------------------------------------------


def test_run_delivers_due_messages_through_its_parts_up_to_the_batch_size() -> None:
    first = OutboxEntry.new(MESSAGE, now=NOW - timedelta(minutes=2))
    second = OutboxEntry.new(MESSAGE, now=NOW - timedelta(minutes=1))
    uow = FakeOutboxUnitOfWork([first, second])
    sender = FakeSender()
    worker = OutboxWorker(
        uow=uow, sender=sender, clock=FixedClock(NOW), policy=OutboxRetryPolicy(), batch_size=1
    )

    report = worker.run()

    assert report.sent == 1
    assert sender.sent == [MESSAGE]
    assert uow.entries.get(first.id).status == OutboxStatus.SENT
    assert uow.entries.get(second.id).status == OutboxStatus.PENDING
