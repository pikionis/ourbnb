"""Ports of the outbox: abstract interfaces that adapters implement (Cosmic Python ch. 2-3).

- AbstractOutbox: what handlers see as `uow.outbox` to enqueue an external side effect.
- OutboxRepository: what the worker uses to claim and save entries.
- MessageSender: what actually delivers a message (console in dev, WhatsApp from Phase 6).
"""

import abc
from datetime import datetime
from typing import Protocol

from kospm.shared.outbox.domain import OutboxEntry, OutboxMessage


class AbstractOutbox(abc.ABC):
    """Enqueue external messages as part of the current Unit of Work.

    Implementations write in the same transaction as the handler's aggregate changes, so a
    message exists if and only if the business change committed.
    """

    @abc.abstractmethod
    def enqueue(self, message: OutboxMessage) -> None: ...


class OutboxRepository(abc.ABC):
    """Storage of OutboxEntry objects for the worker."""

    @abc.abstractmethod
    def claim_next_due(self, now: datetime) -> OutboxEntry | None:
        """Lock and return the oldest PENDING entry due at `now`, or None.

        Entries locked by another worker are skipped, so several workers never send the same
        entry at the same time. The lock lasts until the worker's Unit of Work ends.
        """

    @abc.abstractmethod
    def save(self, entry: OutboxEntry) -> None:
        """Write back the delivery state of an entry returned by claim_next_due."""


class SendError(Exception):
    """A sender could not deliver a message; the worker records it and retries later."""


class MessageSender(Protocol):
    """Delivers one message to the outside world."""

    def send(self, message: OutboxMessage) -> None:
        """Deliver `message`, or raise (SendError for expected delivery failures)."""
        ...
