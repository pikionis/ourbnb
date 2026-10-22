"""In-memory fakes of the shared ports for unit tests (Cosmic Python ch. 3, 6: fakes, not mocks).

Pattern for a bounded context (Phase 2+): its real UoW subclasses AbstractUnitOfWork with one
repository attribute per aggregate type, e.g. `properties: PropertyRepository`. Its fake does the
same with InMemoryRepository instances (or a subclass that adds the context's query methods),
reusing FakeOutbox and the commit/rollback bookkeeping of FakeUnitOfWork:

    class FakePropertiesUnitOfWork(FakeUnitOfWork[Property]):
        def __init__(self, properties: Iterable[Property] = ()) -> None:
            super().__init__()
            self.properties = FakePropertyRepository(properties)

Repositories are discovered automatically: any TrackingRepository instance attribute.

The fakes refuse what the real adapters refuse: a nested `with uow:` (RuntimeError) and
`uow.outbox.enqueue()` outside `with uow:` (RuntimeError). Note that a default
`@pytest.mark.django_db` test runs inside an atomic block, so the real enqueue guard shows only
in `transaction=True` tests.
"""

from collections.abc import Hashable, Iterable
from types import TracebackType
from typing import Any, Self

from kospm.shared.domain import Aggregate
from kospm.shared.outbox.domain import OutboxMessage
from kospm.shared.outbox.service_layer.ports import AbstractOutbox, SendError
from kospm.shared.unit_of_work import AbstractUnitOfWork, TrackingRepository


class InMemoryRepository[A: Aggregate[Any]](TrackingRepository[A]):
    """A repository over a dict keyed by aggregate id.

    Not transactional: an aggregate added in a rolled-back unit stays stored. Tests assert on
    `committed` / `rolled_back` and on events instead.
    """

    def __init__(self, aggregates: Iterable[A] = ()) -> None:
        super().__init__()
        self._aggregates: dict[Hashable, A] = {aggregate.id: aggregate for aggregate in aggregates}

    def _add(self, aggregate: A) -> None:
        self._aggregates[aggregate.id] = aggregate

    def get(self, id: Hashable) -> A:
        """The aggregate with this id (KeyError if absent), tracked for event collection."""
        return self._track(self._aggregates[id])

    def all(self) -> list[A]:
        """Every stored aggregate, untracked: for assertions in tests."""
        return list(self._aggregates.values())


class FakeOutbox(AbstractOutbox):
    """Outbox port fake. As with the real outbox, a message counts only once its unit commits.

    The Unit of Work calls `begin` when a unit opens; `enqueue` outside a unit is refused, as
    DjangoOutbox does. `enqueue` puts a message in `pending`; when the unit ends, the Unit of Work
    moves `pending` to `sent` (committed) or empties it (rolled back). Tests assert on `sent`
    ("what the worker would deliver").
    """

    def __init__(self) -> None:
        self.pending: list[OutboxMessage] = []
        self.sent: list[OutboxMessage] = []
        self._in_unit = False

    def begin(self) -> None:
        self.pending.clear()
        self._in_unit = True

    def enqueue(self, message: OutboxMessage) -> None:
        if not self._in_unit:
            raise RuntimeError(
                "enqueue outside a UnitOfWork: call uow.outbox.enqueue() inside `with uow:`"
            )
        self.pending.append(message)

    def commit_pending(self) -> None:
        self.sent.extend(self.pending)
        self.pending.clear()
        self._in_unit = False

    def discard_pending(self) -> None:
        self.pending.clear()
        self._in_unit = False


class FakeUnitOfWorkBase(AbstractUnitOfWork):
    """Commit/rollback bookkeeping shared by the fake Units of Work.

    The commit is deferred, as in DjangoUnitOfWork: `commit()` only marks the unit, and its
    effects (`committed`, the outbox's `sent`, `_apply`) happen when the block exits without an
    exception. Committing and then raising inside the block rolls back, as in production.
    """

    outbox: FakeOutbox

    def __init__(self) -> None:
        self.outbox = FakeOutbox()
        self.committed = 0
        self.rolled_back = 0

    def __enter__(self) -> Self:
        unit = super().__enter__()
        self.outbox.begin()
        return unit

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        committed = exc_type is None and self._committed
        try:
            super().__exit__(exc_type, exc, traceback)  # rollback() unless committed
        finally:
            if committed:
                self.committed += 1
                self.outbox.commit_pending()
                self._apply()
            else:
                self.outbox.discard_pending()
                self._discard()

    def _commit(self) -> None:
        """Nothing yet: the effects apply when the block exits (deferred commit)."""

    def rollback(self) -> None:
        self.rolled_back += 1

    def _apply(self) -> None:
        """Make other staged changes durable; called when the unit really commits."""

    def _discard(self) -> None:
        """Drop other staged changes; called when the unit rolls back."""


class FakeUnitOfWork[A: Aggregate[Any]](FakeUnitOfWorkBase):
    """A Unit of Work over in-memory repositories, counting commits and rollbacks.

    `items` holds the aggregates of a test; subclasses add more repository attributes.
    """

    def __init__(self, items: Iterable[A] = ()) -> None:
        super().__init__()
        self.items = InMemoryRepository(items)


class FakeSender:
    """MessageSender fake: records what it delivers, fails for the given recipients."""

    def __init__(self, failing_recipients: Iterable[str] = ()) -> None:
        self.sent: list[OutboxMessage] = []
        self.failing_recipients = set(failing_recipients)

    def send(self, message: OutboxMessage) -> None:
        if message.recipient in self.failing_recipients:
            raise SendError(f"cannot reach {message.recipient}")
        self.sent.append(message)
