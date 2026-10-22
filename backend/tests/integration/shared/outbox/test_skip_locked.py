"""Two workers never claim the same entry: SELECT ... FOR UPDATE SKIP LOCKED on PostgreSQL.

Needs real concurrent transactions, so the test commits for real (`transaction=True`) and runs
the second worker in a thread with its own connection. The threads are synchronised with
events, never with sleeps.
"""

import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from django.db import connection

from kospm.shared.clock import FixedClock
from kospm.shared.outbox.adapters import DjangoOutbox, DjangoOutboxUnitOfWork, from_domain
from kospm.shared.outbox.domain import OutboxChannel, OutboxEntry, OutboxMessage

NOW = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)
TIMEOUT_SECONDS = 10


def a_stored_entry(created: datetime) -> OutboxEntry:
    message = OutboxMessage(
        channel=OutboxChannel.WHATSAPP, recipient="+306900000001", template="cleaning_assigned"
    )
    entry = OutboxEntry.new(message, now=created)
    from_domain(entry).save(force_insert=True)
    return entry


def a_worker_uow() -> DjangoOutboxUnitOfWork:
    return DjangoOutboxUnitOfWork(outbox=DjangoOutbox(FixedClock(NOW)))


@pytest.mark.django_db(transaction=True)
def test_an_entry_locked_by_one_worker_is_skipped_by_another() -> None:
    first = a_stored_entry(created=NOW - timedelta(minutes=2))
    second = a_stored_entry(created=NOW - timedelta(minutes=1))
    claimed_by_thread: list[UUID | None] = []
    errors: list[BaseException] = []
    holding_lock = threading.Event()
    may_release = threading.Event()

    def worker_holding_the_oldest_entry() -> None:
        try:
            uow = a_worker_uow()
            with uow:
                entry = uow.entries.claim_next_due(NOW)
                claimed_by_thread.append(entry.id if entry is not None else None)
                holding_lock.set()
                may_release.wait(TIMEOUT_SECONDS)
                # No commit: the claim is released by the rollback.
        except BaseException as error:
            errors.append(error)
        finally:
            holding_lock.set()  # never leave the main thread waiting
            connection.close()  # this thread's own connection

    thread = threading.Thread(target=worker_holding_the_oldest_entry)
    thread.start()
    try:
        assert holding_lock.wait(TIMEOUT_SECONDS), "the first worker never claimed an entry"
        assert errors == []
        assert claimed_by_thread == [first.id]

        uow = a_worker_uow()
        with uow:
            entry = uow.entries.claim_next_due(NOW)
            assert entry is not None
            assert entry.id == second.id  # the oldest is locked by the other worker: skipped
    finally:
        may_release.set()
        thread.join(TIMEOUT_SECONDS)

    assert not thread.is_alive(), "the first worker did not finish"
    assert errors == []

    # Once the first worker's transaction has ended, its entry can be claimed again.
    with uow:
        entry = uow.entries.claim_next_due(NOW)
        assert entry is not None
        assert entry.id == first.id
