"""The outbox worker (ADR 0005): deliver due messages through a MessageSender port.

`process_outbox` is a service-layer function, wired by bootstrap and run every minute by the
scheduler (ADR 0004). It handles one message per Unit of Work:

    with uow:
        entry = claim the oldest due entry (row lock; other workers skip it)
        send it, then mark it SENT, or record the failure (backoff, or FAILED after N attempts)
        save the entry and commit

The send runs inside the worker's own short transaction, never inside a business transaction:
the business change committed long before, when the handler enqueued the message. Holding the
row lock while sending is what stops two workers from sending the same entry. Delivery is
at-least-once: if the commit fails after a successful send, the entry is still PENDING and is
sent again later.
"""

import logging
from dataclasses import dataclass

from kospm.shared.clock import Clock
from kospm.shared.outbox.domain import OutboxRetryPolicy, OutboxStatus
from kospm.shared.outbox.service_layer.ports import MessageSender, OutboxRepository
from kospm.shared.unit_of_work import AbstractUnitOfWork

logger = logging.getLogger(__name__)


class OutboxUnitOfWork(AbstractUnitOfWork):
    """The worker's Unit of Work: one transaction around claiming, sending and saving an entry."""

    entries: OutboxRepository


@dataclass(frozen=True, kw_only=True)
class OutboxRunReport:
    """What one worker run did.

    `failed_attempts` counts every failed send, including the ones that used up the last attempt;
    `exhausted` counts the entries that became FAILED in this run.
    """

    sent: int
    failed_attempts: int
    exhausted: int

    @property
    def processed(self) -> int:
        return self.sent + self.failed_attempts


def process_outbox(
    *,
    uow: OutboxUnitOfWork,
    sender: MessageSender,
    clock: Clock,
    policy: OutboxRetryPolicy,
    batch_size: int = 100,
) -> OutboxRunReport:
    """Send up to `batch_size` due messages, one Unit of Work each, oldest first."""
    if batch_size < 1:
        raise ValueError(f"batch_size must be at least 1, got {batch_size}")
    sent = failed_attempts = exhausted = 0
    for _ in range(batch_size):
        with uow:
            entry = uow.entries.claim_next_due(clock.now())
            if entry is None:
                break
            try:
                sender.send(entry.message)
            # Broad on purpose: whatever one message does wrong, the queue behind it must move on.
            # BaseException (Ctrl+C, SystemExit) still propagates and rolls the claim back.
            except Exception as error:
                entry.record_failure(at=clock.now(), error=repr(error), policy=policy)
                failed_attempts += 1
                if entry.status == OutboxStatus.FAILED:
                    exhausted += 1
                    logger.error(
                        "outbox entry %s failed for good after %d attempts: %r",
                        entry.id,
                        entry.attempts,
                        error,
                    )
                else:
                    logger.warning(
                        "outbox entry %s failed (attempt %d), next try at %s: %r",
                        entry.id,
                        entry.attempts,
                        entry.next_attempt_at,
                        error,
                    )
            else:
                entry.mark_sent(at=clock.now())
                sent += 1
            uow.entries.save(entry)
            uow.commit()
    return OutboxRunReport(sent=sent, failed_attempts=failed_attempts, exhausted=exhausted)
