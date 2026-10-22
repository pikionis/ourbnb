"""The outbox worker (ADR 0005): deliver due messages, retry with backoff, give up after N attempts.

BUILD_PLAN Phase 1: "outbox retries and marks failures after N attempts".
"""

from datetime import UTC, datetime, timedelta

import pytest

from kospm.shared.clock import FixedClock
from kospm.shared.outbox.domain import (
    OutboxChannel,
    OutboxEntry,
    OutboxMessage,
    OutboxRetryPolicy,
    OutboxStatus,
)
from kospm.shared.outbox.service_layer.ports import MessageSender, SendError
from kospm.shared.outbox.service_layer.worker import OutboxRunReport, process_outbox
from tests.fakes import FakeSender
from tests.unit.shared.outbox.fakes import BrokenSender, FakeOutboxUnitOfWork

NOW = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)
POLICY = OutboxRetryPolicy(
    max_attempts=3, base_delay=timedelta(minutes=1), factor=2, max_delay=timedelta(hours=1)
)


def a_message(recipient: str = "+306900000001") -> OutboxMessage:
    return OutboxMessage(
        channel=OutboxChannel.WHATSAPP,
        recipient=recipient,
        template="cleaning_assigned",
        payload={"property": "KOS-A1", "cleaner": "Μαρία"},
    )


def an_entry(
    recipient: str = "+306900000001", *, created: datetime = NOW, due: datetime | None = None
) -> OutboxEntry:
    entry = OutboxEntry.new(a_message(recipient), now=created)
    if due is not None:
        entry.next_attempt_at = due
    return entry


def run(
    uow: FakeOutboxUnitOfWork,
    sender: MessageSender,
    clock: FixedClock,
    batch_size: int = 100,
) -> OutboxRunReport:
    return process_outbox(uow=uow, sender=sender, clock=clock, policy=POLICY, batch_size=batch_size)


# --- delivery --------------------------------------------------------------------------------


def test_due_messages_are_sent_oldest_first_and_marked_sent() -> None:
    older = an_entry("+306900000001", created=NOW - timedelta(minutes=2))
    newer = an_entry("+306900000002", created=NOW - timedelta(minutes=1))
    uow = FakeOutboxUnitOfWork([newer, older])
    sender = FakeSender()
    clock = FixedClock(NOW)

    report = run(uow, sender, clock)

    assert [message.recipient for message in sender.sent] == ["+306900000001", "+306900000002"]
    assert report == OutboxRunReport(sent=2, failed_attempts=0, exhausted=0)
    for entry_id in (older.id, newer.id):
        stored = uow.entries.get(entry_id)
        assert stored.status == OutboxStatus.SENT
        assert stored.sent_at == NOW
        assert stored.next_attempt_at is None


def test_each_message_is_its_own_unit_of_work() -> None:
    uow = FakeOutboxUnitOfWork([an_entry("+1"), an_entry("+2"), an_entry("+3")])

    run(uow, FakeSender(), FixedClock(NOW))

    assert uow.committed == 3


def test_messages_not_yet_due_are_left_alone() -> None:
    later = an_entry(due=NOW + timedelta(seconds=1))
    uow = FakeOutboxUnitOfWork([later])
    sender = FakeSender()

    report = run(uow, sender, FixedClock(NOW))

    assert sender.sent == []
    assert report == OutboxRunReport(sent=0, failed_attempts=0, exhausted=0)
    assert uow.entries.get(later.id).status == OutboxStatus.PENDING
    assert uow.committed == 0
    assert uow.entries.claims == 1  # one look, then the run stops


def test_an_empty_outbox_does_nothing() -> None:
    uow = FakeOutboxUnitOfWork()

    report = run(uow, FakeSender(), FixedClock(NOW))

    assert report == OutboxRunReport(sent=0, failed_attempts=0, exhausted=0)
    assert uow.committed == 0
    # One empty unit, not batch_size of them.
    assert uow.entries.claims == 1
    assert uow.rolled_back == 1


def test_a_sent_message_is_never_sent_again() -> None:
    uow = FakeOutboxUnitOfWork([an_entry()])
    sender = FakeSender()
    clock = FixedClock(NOW)

    run(uow, sender, clock)
    clock.advance(timedelta(days=1))
    run(uow, sender, clock)

    assert len(sender.sent) == 1


def test_timestamps_are_taken_when_the_send_has_finished() -> None:
    clock = FixedClock(NOW)

    class SlowSender:
        def send(self, message: OutboxMessage) -> None:
            clock.advance(timedelta(seconds=5))

    entry = an_entry()
    uow = FakeOutboxUnitOfWork([entry])

    run(uow, SlowSender(), clock)

    assert uow.entries.get(entry.id).sent_at == NOW + timedelta(seconds=5)


# --- failures, backoff and giving up -----------------------------------------------------------


def test_a_failed_send_is_recorded_and_retried_only_after_the_backoff() -> None:
    entry = an_entry("+306900000009")
    uow = FakeOutboxUnitOfWork([entry])
    sender = FakeSender(failing_recipients={"+306900000009"})
    clock = FixedClock(NOW)

    report = run(uow, sender, clock)

    assert report == OutboxRunReport(sent=0, failed_attempts=1, exhausted=0)
    failed = uow.entries.get(entry.id)
    assert failed.status == OutboxStatus.PENDING
    assert failed.attempts == 1
    assert failed.next_attempt_at == NOW + timedelta(minutes=1)
    assert "SendError" in failed.last_error
    assert "+306900000009" in failed.last_error

    sender.failing_recipients.clear()  # the recipient is reachable again
    clock.advance(timedelta(seconds=59))
    assert run(uow, sender, clock).sent == 0
    assert sender.sent == []

    clock.advance(timedelta(seconds=1))
    assert run(uow, sender, clock) == OutboxRunReport(sent=1, failed_attempts=0, exhausted=0)
    assert [message.recipient for message in sender.sent] == ["+306900000009"]
    assert uow.entries.get(entry.id).status == OutboxStatus.SENT


def test_a_message_that_always_fails_is_marked_failed_after_exactly_max_attempts() -> None:
    entry = an_entry()
    uow = FakeOutboxUnitOfWork([entry])
    sender = BrokenSender(SendError("provider down"))
    clock = FixedClock(NOW)
    reports = []

    for _ in range(10):  # far more runs than attempts, each after the longest backoff
        reports.append(run(uow, sender, clock))
        clock.advance(POLICY.max_delay)

    assert len(sender.attempts) == POLICY.max_attempts
    failed = uow.entries.get(entry.id)
    assert failed.status == OutboxStatus.FAILED
    assert failed.attempts == POLICY.max_attempts
    assert failed.next_attempt_at is None
    assert reports[: POLICY.max_attempts] == [
        OutboxRunReport(sent=0, failed_attempts=1, exhausted=0),
        OutboxRunReport(sent=0, failed_attempts=1, exhausted=0),
        OutboxRunReport(sent=0, failed_attempts=1, exhausted=1),
    ]
    assert set(reports[POLICY.max_attempts :]) == {
        OutboxRunReport(sent=0, failed_attempts=0, exhausted=0)
    }


def test_retries_follow_the_exponential_backoff_of_the_policy() -> None:
    entry = an_entry()
    uow = FakeOutboxUnitOfWork([entry])
    sender = BrokenSender(SendError("provider down"))
    clock = FixedClock(NOW)

    run(uow, sender, clock)
    assert uow.entries.get(entry.id).next_attempt_at == NOW + timedelta(minutes=1)

    clock.set(NOW + timedelta(minutes=1))
    run(uow, sender, clock)
    assert uow.entries.get(entry.id).next_attempt_at == NOW + timedelta(minutes=3)


def test_any_exception_from_the_sender_counts_as_a_failed_attempt() -> None:
    # A bug in one sender call (not only SendError) must not stop the worker or the queue.
    entry = an_entry()
    uow = FakeOutboxUnitOfWork([entry])

    report = run(uow, BrokenSender(ValueError("bad template")), FixedClock(NOW))

    assert report == OutboxRunReport(sent=0, failed_attempts=1, exhausted=0)
    stored = uow.entries.get(entry.id)
    assert stored.attempts == 1
    assert stored.last_error == repr(ValueError("bad template"))


def test_an_interrupted_worker_leaves_the_message_pending_and_untouched() -> None:
    entry = an_entry()
    uow = FakeOutboxUnitOfWork([entry])

    with pytest.raises(KeyboardInterrupt):
        run(uow, BrokenSender(KeyboardInterrupt()), FixedClock(NOW))

    stored = uow.entries.get(entry.id)
    assert stored.status == OutboxStatus.PENDING
    assert stored.attempts == 0
    assert uow.rolled_back == 1
    assert uow.committed == 0


def test_a_poison_message_does_not_block_the_others() -> None:
    poison = an_entry("+306900000666", created=NOW - timedelta(minutes=5))
    good = [an_entry(f"+30690000000{n}", created=NOW - timedelta(minutes=n)) for n in (3, 2, 1)]
    uow = FakeOutboxUnitOfWork([poison, *good])
    sender = FakeSender(failing_recipients={"+306900000666"})

    report = run(uow, sender, FixedClock(NOW))

    assert report == OutboxRunReport(sent=3, failed_attempts=1, exhausted=0)
    assert [message.recipient for message in sender.sent] == [
        "+306900000003",
        "+306900000002",
        "+306900000001",
    ]
    assert uow.entries.get(poison.id).attempts == 1


def test_the_report_counts_sent_failed_and_exhausted_messages() -> None:
    ok = [an_entry("+1"), an_entry("+2")]
    retried = an_entry("+3")
    last_chance = an_entry("+4")
    last_chance.attempts = POLICY.max_attempts - 1
    uow = FakeOutboxUnitOfWork([*ok, retried, last_chance])
    sender = FakeSender(failing_recipients={"+3", "+4"})

    report = run(uow, sender, FixedClock(NOW))

    assert report == OutboxRunReport(sent=2, failed_attempts=2, exhausted=1)
    assert report.processed == 4
    assert uow.entries.get(retried.id).status == OutboxStatus.PENDING
    assert uow.entries.get(last_chance.id).status == OutboxStatus.FAILED


# --- batch size --------------------------------------------------------------------------------


def test_one_run_handles_at_most_batch_size_messages() -> None:
    entries = [an_entry(f"+{n}", created=NOW - timedelta(minutes=10 - n)) for n in range(5)]
    uow = FakeOutboxUnitOfWork(entries)
    sender = FakeSender()
    clock = FixedClock(NOW)

    assert run(uow, sender, clock, batch_size=2).sent == 2
    assert [message.recipient for message in sender.sent] == ["+0", "+1"]
    assert uow.entries.get(entries[2].id).status == OutboxStatus.PENDING
    assert uow.entries.claims == 2

    assert run(uow, sender, clock, batch_size=2).sent == 2
    assert run(uow, sender, clock, batch_size=2).sent == 1
    assert [message.recipient for message in sender.sent] == ["+0", "+1", "+2", "+3", "+4"]
    assert uow.entries.claims == 2 + 2 + 2  # the last run: one message, then an empty claim


def test_failed_attempts_count_towards_the_batch_size() -> None:
    entries = [an_entry(f"+{n}", created=NOW - timedelta(minutes=10 - n)) for n in range(3)]
    uow = FakeOutboxUnitOfWork(entries)

    report = run(uow, FakeSender(failing_recipients={"+0", "+1"}), FixedClock(NOW), batch_size=2)

    assert report == OutboxRunReport(sent=0, failed_attempts=2, exhausted=0)
    assert uow.entries.get(entries[2].id).status == OutboxStatus.PENDING


@pytest.mark.parametrize("batch_size", [0, -1])
def test_batch_size_must_be_positive(batch_size: int) -> None:
    with pytest.raises(ValueError, match="batch_size"):
        run(FakeOutboxUnitOfWork(), FakeSender(), FixedClock(NOW), batch_size=batch_size)
