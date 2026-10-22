"""Outbox adapters against PostgreSQL: row mapping, enqueue, claiming and saving entries."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from kospm.shared.clock import FixedClock
from kospm.shared.outbox import models
from kospm.shared.outbox.adapters import (
    DjangoOutbox,
    DjangoOutboxUnitOfWork,
    from_domain,
    to_domain,
)
from kospm.shared.outbox.domain import (
    OutboxChannel,
    OutboxEntry,
    OutboxMessage,
    OutboxRetryPolicy,
    OutboxStatus,
)
from kospm.shared.outbox.service_layer.worker import OutboxRunReport, process_outbox
from tests.fakes import FakeSender

NOW = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)
POLICY = OutboxRetryPolicy()


def a_message(recipient: str = "+306900000001") -> OutboxMessage:
    return OutboxMessage(
        channel=OutboxChannel.WHATSAPP,
        recipient=recipient,
        template="cleaning_assigned",
        payload={
            "cleaner": "Μαρία",
            "tasks": [{"property": "KOS-A1", "order": 1, "late": False, "note": None}],
        },
    )


def store(entry: OutboxEntry) -> OutboxEntry:
    from_domain(entry).save(force_insert=True)
    return entry


def a_stored_entry(
    recipient: str = "+306900000001",
    *,
    created: datetime = NOW,
    due: datetime | None = None,
    id: UUID | None = None,
) -> OutboxEntry:
    entry = OutboxEntry.new(a_message(recipient), now=created, id=id)
    if due is not None:
        entry.next_attempt_at = due
    return store(entry)


def state(entry: OutboxEntry) -> tuple[object, ...]:
    """Every attribute of an entry (entities compare by id only)."""
    return (
        entry.id,
        entry.message,
        entry.status,
        entry.attempts,
        entry.created_at,
        entry.next_attempt_at,
        entry.sent_at,
        entry.last_error,
    )


def a_worker_uow() -> DjangoOutboxUnitOfWork:
    return DjangoOutboxUnitOfWork(outbox=DjangoOutbox(FixedClock(NOW)))


def claim_order(now: datetime) -> list[UUID]:
    """Claim and mark sent until nothing is due; return the ids in the order they were claimed."""
    uow = a_worker_uow()
    claimed: list[UUID] = []
    while True:
        with uow:
            entry = uow.entries.claim_next_due(now)
            if entry is None:
                return claimed
            claimed.append(entry.id)
            entry.mark_sent(at=now)
            uow.entries.save(entry)
            uow.commit()


# --- mapping ----------------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_pending_entry_survives_the_round_trip_through_the_table() -> None:
    entry = OutboxEntry.new(a_message(), now=NOW)
    entry.record_failure(
        at=NOW + timedelta(seconds=3), error="Σφάλμα: provider timeout", policy=POLICY
    )
    store(entry)

    loaded = to_domain(models.OutboxMessage.objects.get(pk=entry.id))

    assert state(loaded) == state(entry)
    assert isinstance(loaded.status, OutboxStatus)
    assert isinstance(loaded.message.channel, OutboxChannel)


@pytest.mark.django_db
def test_a_sent_entry_survives_the_round_trip_through_the_table() -> None:
    entry = OutboxEntry.new(a_message(), now=NOW)
    entry.mark_sent(at=NOW + timedelta(microseconds=123_456))
    store(entry)

    loaded = to_domain(models.OutboxMessage.objects.get(pk=entry.id))

    assert state(loaded) == state(entry)


@pytest.mark.django_db
def test_the_payload_is_stored_as_queryable_json_with_greek_text() -> None:
    entry = a_stored_entry()

    row = models.OutboxMessage.objects.get(payload__cleaner="Μαρία")

    assert row.pk == entry.id
    assert row.payload["tasks"][0]["property"] == "KOS-A1"


# --- enqueue ----------------------------------------------------------------------------------


@pytest.mark.django_db
def test_enqueue_stores_a_pending_entry_that_is_due_now() -> None:
    uow = DjangoOutboxUnitOfWork(outbox=DjangoOutbox(FixedClock(NOW)))
    with uow:
        uow.outbox.enqueue(a_message("+306900000042"))
        uow.commit()

    loaded = to_domain(models.OutboxMessage.objects.get())
    assert loaded.message == a_message("+306900000042")
    assert loaded.status == OutboxStatus.PENDING
    assert loaded.attempts == 0
    assert loaded.created_at == NOW
    assert loaded.next_attempt_at == NOW
    assert loaded.sent_at is None
    assert loaded.last_error == ""


@pytest.mark.django_db(transaction=True)
def test_enqueue_outside_a_unit_of_work_is_refused() -> None:
    # Outside a transaction the message would be stored even if the business change failed.
    with pytest.raises(RuntimeError, match="outside a UnitOfWork"):
        DjangoOutbox(FixedClock(NOW)).enqueue(a_message())

    assert not models.OutboxMessage.objects.exists()


# --- claim_next_due and save ------------------------------------------------------------------


@pytest.mark.django_db
def test_claim_returns_due_entries_earliest_due_first_then_oldest() -> None:
    due_first = a_stored_entry(created=NOW - timedelta(hours=1), due=NOW - timedelta(minutes=30))
    # Same due time. Their ids sort the other way round, so only created_at can order them.
    tie_older = a_stored_entry(
        created=NOW - timedelta(minutes=50), due=NOW - timedelta(minutes=5), id=UUID(int=2**128 - 1)
    )
    tie_newer = a_stored_entry(
        created=NOW - timedelta(minutes=40), due=NOW - timedelta(minutes=5), id=UUID(int=1)
    )
    due_exactly_now = a_stored_entry(created=NOW - timedelta(hours=2), due=NOW)

    assert claim_order(NOW) == [due_first.id, tie_older.id, tie_newer.id, due_exactly_now.id]


@pytest.mark.django_db
def test_claim_skips_entries_not_yet_due_and_entries_sent_or_failed() -> None:
    a_stored_entry(due=NOW + timedelta(microseconds=1))
    sent = OutboxEntry.new(a_message(), now=NOW - timedelta(hours=1))
    sent.mark_sent(at=NOW - timedelta(minutes=59))
    store(sent)
    failed = OutboxEntry.new(a_message(), now=NOW - timedelta(hours=1))
    for _ in range(POLICY.max_attempts):
        failed.record_failure(at=NOW - timedelta(hours=1), error="down", policy=POLICY)
    assert failed.status == OutboxStatus.FAILED
    store(failed)

    assert claim_order(NOW) == []


@pytest.mark.django_db
def test_save_writes_back_the_delivery_state() -> None:
    entry = a_stored_entry()
    uow = a_worker_uow()
    with uow:
        claimed = uow.entries.claim_next_due(NOW)
        assert claimed is not None
        claimed.record_failure(at=NOW, error="SendError('no route')", policy=POLICY)
        uow.entries.save(claimed)
        uow.commit()

    loaded = to_domain(models.OutboxMessage.objects.get(pk=entry.id))
    assert loaded.status == OutboxStatus.PENDING
    assert loaded.attempts == 1
    assert loaded.last_error == "SendError('no route')"
    assert loaded.next_attempt_at == NOW + POLICY.delay_after(1)
    assert loaded.message == entry.message


@pytest.mark.django_db
def test_save_without_commit_changes_nothing() -> None:
    entry = a_stored_entry()
    uow = a_worker_uow()
    with uow:
        claimed = uow.entries.claim_next_due(NOW)
        assert claimed is not None
        claimed.mark_sent(at=NOW)
        uow.entries.save(claimed)

    assert models.OutboxMessage.objects.get(pk=entry.id).status == OutboxStatus.PENDING


@pytest.mark.django_db
def test_save_refuses_an_entry_that_was_not_claimed_in_this_unit() -> None:
    entry = a_stored_entry()
    uow = a_worker_uow()
    with uow, pytest.raises(ValueError, match="claim_next_due"):
        uow.entries.save(entry)


# --- the worker on the real table ---------------------------------------------------------------


@pytest.mark.django_db
def test_the_worker_sends_stored_messages_and_marks_them_sent() -> None:
    first = a_stored_entry("+306900000001", created=NOW - timedelta(minutes=2))
    second = a_stored_entry("+306900000002", created=NOW - timedelta(minutes=1))
    sender = FakeSender(failing_recipients={"+306900000002"})

    report = process_outbox(uow=a_worker_uow(), sender=sender, clock=FixedClock(NOW), policy=POLICY)

    assert report == OutboxRunReport(sent=1, failed_attempts=1, exhausted=0)
    assert [message.recipient for message in sender.sent] == ["+306900000001"]
    sent = models.OutboxMessage.objects.get(pk=first.id)
    assert sent.status == OutboxStatus.SENT
    assert sent.sent_at == NOW
    retried = models.OutboxMessage.objects.get(pk=second.id)
    assert retried.status == OutboxStatus.PENDING
    assert retried.attempts == 1
    assert retried.next_attempt_at == NOW + POLICY.delay_after(1)
