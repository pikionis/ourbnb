"""In-memory fakes for the outbox worker (Cosmic Python ch. 3 and 6: fakes, not mocks).

FakeOutboxRepository is transactional like the real table. `claim_next_due` hands out a copy,
`save` only stages it, and the Unit of Work applies the staged entries when the unit commits or
drops them when it rolls back. So a worker that forgets to save or to commit fails these tests.
"""

import copy
from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from kospm.shared.outbox.domain import OutboxEntry, OutboxMessage
from kospm.shared.outbox.service_layer.ports import OutboxRepository
from kospm.shared.outbox.service_layer.worker import OutboxUnitOfWork
from tests.fakes import FakeUnitOfWorkBase


class FakeOutboxRepository(OutboxRepository):
    def __init__(self, entries: Iterable[OutboxEntry] = ()) -> None:
        self._stored: dict[UUID, OutboxEntry] = {entry.id: copy.copy(entry) for entry in entries}
        self._staged: dict[UUID, OutboxEntry] = {}
        self.claims = 0  # calls to claim_next_due: one per unit the worker opens

    def claim_next_due(self, now: datetime) -> OutboxEntry | None:
        self.claims += 1
        due = [entry for entry in self._stored.values() if entry.is_due(now)]
        if not due:
            return None
        # Same order as the Django adapter: earliest due first, then oldest.
        oldest = min(due, key=lambda entry: (entry.next_attempt_at, entry.created_at))
        return copy.copy(oldest)

    def save(self, entry: OutboxEntry) -> None:
        self._staged[entry.id] = copy.copy(entry)

    def apply_staged(self) -> None:
        self._stored.update(self._staged)
        self._staged.clear()

    def discard_staged(self) -> None:
        self._staged.clear()

    def get(self, entry_id: UUID) -> OutboxEntry:
        """The committed state of an entry, for assertions."""
        return copy.copy(self._stored[entry_id])


class FakeOutboxUnitOfWork(FakeUnitOfWorkBase, OutboxUnitOfWork):
    def __init__(self, entries: Iterable[OutboxEntry] = ()) -> None:
        super().__init__()
        self.entries: FakeOutboxRepository = FakeOutboxRepository(entries)

    def _apply(self) -> None:
        self.entries.apply_staged()

    def _discard(self) -> None:
        self.entries.discard_staged()


class BrokenSender:
    """A sender that always raises `error` and records every attempt."""

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.attempts: list[OutboxMessage] = []

    def send(self, message: OutboxMessage) -> None:
        self.attempts.append(message)
        raise self.error
