"""DjangoUnitOfWork: the Unit of Work on top of `transaction.atomic` (Cosmic Python Appendix D).

Deferred commit. `__enter__` opens an atomic block. `commit()` writes the seen aggregates back
(`persist_seen`) and marks the unit as committed. The real COMMIT happens when the `with` block
exits, so `uow.commit()` must be the last statement of the block. Leaving without commit, or with
an exception, marks the block for rollback and Django rolls it back on exit.

Inside an outer atomic block, such as pytest-django's test transaction, the unit's block is a
savepoint. Its "commit" then only releases the savepoint and the outer transaction decides. This
is why ATOMIC_REQUESTS stays off (config/settings/base.py): the message bus publishes events
when the unit ends, and that must mean the work was really committed.
"""

from types import TracebackType
from typing import Self

from django.db import DEFAULT_DB_ALIAS, transaction
from psycopg.pq import TransactionStatus

from kospm.shared.outbox.service_layer.ports import AbstractOutbox
from kospm.shared.unit_of_work import AbstractUnitOfWork


class DjangoUnitOfWork(AbstractUnitOfWork):
    """Base for every context's Django Unit of Work: subclasses add their repositories.

    One instance runs one unit at a time and can be reused for the next one (the bus does that).
    Entering it again while a unit is open raises RuntimeError.
    """

    def __init__(self, *, outbox: AbstractOutbox, using: str = DEFAULT_DB_ALIAS) -> None:
        self.outbox = outbox
        self.using = using
        self._atomic: transaction.Atomic | None = None

    def __enter__(self) -> Self:
        if self._atomic is not None:
            raise RuntimeError(
                f"{type(self).__name__} is not re-entrant: a unit is already open. "
                "Finish it before starting the next one."
            )
        atomic = transaction.atomic(using=self.using)
        atomic.__enter__()
        self._atomic = atomic
        try:
            return super().__enter__()
        except BaseException as error:
            self._atomic = None
            atomic.__exit__(type(error), error, error.__traceback__)
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        atomic, self._atomic = self._atomic, None
        if atomic is None:
            raise RuntimeError(f"{type(self).__name__} exited without being entered")
        try:
            # Without commit, or on an exception: rollback() marks the block, events are dropped.
            super().__exit__(exc_type, exc, traceback)
        except BaseException as error:
            atomic.__exit__(type(error), error, error.__traceback__)
            raise
        try:
            atomic.__exit__(exc_type, exc, traceback)  # COMMIT (or release the savepoint) here
        except BaseException:
            # The COMMIT itself failed, so the work is gone: its events must never be published.
            self._discard_tracked()
            raise

    def _commit(self) -> None:
        # A caught database error has already doomed the block, and it would roll back silently
        # on exit. Django marks it for rollback after a failed ORM write; after a failed read or
        # raw query only PostgreSQL knows (it answers COMMIT with ROLLBACK, without an error).
        # Fail now, instead of reporting a commit that is not going to happen.
        if transaction.get_rollback(using=self.using) or self._aborted_by_postgresql():
            raise transaction.TransactionManagementError(
                "cannot commit: a database error aborted the transaction, so it would roll back"
            )
        # Nothing else to do here: the atomic block commits when the `with` block exits.

    def rollback(self) -> None:
        transaction.set_rollback(True, using=self.using)

    def _aborted_by_postgresql(self) -> bool:
        raw = transaction.get_connection(self.using).connection  # the psycopg connection
        if raw is None:
            return False
        status: TransactionStatus = raw.info.transaction_status
        return status == TransactionStatus.INERROR
