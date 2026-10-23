"""Unit of Work and tracking repositories (Cosmic Python ch. 6-8). Pure Python, no Django.

A handler does all its work inside one Unit of Work:

    with uow:
        prop = uow.properties.get(cmd.property_id)
        prop.activate()
        uow.commit()  # keep it the last statement of the block

- Leaving the block without `commit()`, or with an exception, rolls back. Aggregates seen in that
  unit lose their pending events, so a rolled-back change never publishes an event.
- After every handler call the message bus calls `collect_new_events()` and dispatches the events
  of every aggregate the repositories handed out or received (the "seen" aggregates). Events of a
  committed unit are kept until then, even if the same UoW runs another unit first.
- A unit cannot be opened while another one is open (not re-entrant).
- Within one unit a repository is an identity map: loading the same aggregate twice returns the
  same object.

Each bounded context subclasses AbstractUnitOfWork with its own repositories, set as instance
attributes (one UoW per context). The concrete transaction is an adapter: DjangoUnitOfWork in
`kospm.shared.adapters`, FakeUnitOfWork in tests.
"""

import abc
from collections.abc import Hashable, Iterator
from types import TracebackType
from typing import Any, Self

from kospm.shared.domain import Aggregate, DomainEvent
from kospm.shared.outbox.service_layer.ports import AbstractOutbox


class ConcurrencyError(Exception):
    """Another unit changed the aggregate since this unit loaded it (ADR 0016).

    Raised on commit; the unit rolls back. Command callers ask the person to reload and retry;
    the message bus retries event handlers, and each retry loads the newer version.
    """


class TrackingRepository[A: Aggregate[Any]](abc.ABC):
    """Repository base that remembers every aggregate it hands out or receives.

    Subclasses implement `_add` and their own query methods (`get`, `get_by_code`, ...); every
    query method must pass each aggregate it loads through `_track` and return what `_track`
    returns. Django repositories also override `_persist` to write a changed aggregate back
    (Repository pattern: callers never call save). A subclass that defines `__init__` must call
    `super().__init__()`.
    """

    def __init__(self) -> None:
        # An identity map (Fowler, PoEAA), keyed by entity identity: one object per aggregate per
        # unit. Two copies of one aggregate would both be written back on commit, the stale one
        # last, while the changed one's events would still be published.
        self._seen: dict[tuple[type, Hashable], A] = {}

    @property
    def seen(self) -> tuple[A, ...]:
        """Aggregates seen in the current unit, in the order they were first seen."""
        return tuple(self._seen.values())

    def add(self, aggregate: A) -> None:
        key = _identity(aggregate)
        if self._seen.get(key, aggregate) is not aggregate:
            raise ValueError(
                f"another {type(aggregate).__name__} with id {aggregate.id} is already in this unit"
            )
        self._add(aggregate)
        self._seen[key] = aggregate

    @abc.abstractmethod
    def _add(self, aggregate: A) -> None:
        """Store a new aggregate."""

    def _track(self, aggregate: A) -> A:
        """Remember a loaded aggregate and return the object to hand out.

        If this unit has already seen the aggregate, that object is returned and the fresh copy
        is dropped, so changes made through the first one are neither lost nor overwritten.
        """
        return self._seen.setdefault(_identity(aggregate), aggregate)

    def _persist(self, aggregate: A) -> None:  # noqa: B027 - optional hook, no-op by default
        """Write a seen aggregate back to storage. In-memory repositories need nothing."""

    def persist_seen(self) -> None:
        for aggregate in self._seen.values():
            self._persist(aggregate)

    def collect_events(self) -> Iterator[DomainEvent]:
        """Pop the pending events of every seen aggregate, oldest first."""
        for aggregate in self._seen.values():
            while aggregate.events:
                yield aggregate.events.pop(0)

    def forget(self) -> None:
        self._seen.clear()


class AbstractUnitOfWork(abc.ABC):
    """One atomic unit of work: commit everything or nothing (Cosmic Python ch. 6).

    Repositories are discovered automatically: every TrackingRepository instance attribute.
    """

    # Port for external side effects, written in the same transaction (ADR 0005).
    outbox: AbstractOutbox
    _committed: bool = False
    _open: bool = False
    # Events of earlier committed units that the bus has not collected yet (a tuple: a class
    # attribute must not be a shared mutable list).
    _uncollected: tuple[DomainEvent, ...] = ()

    def __enter__(self) -> Self:
        if self._open:
            raise RuntimeError(
                f"{type(self).__name__} is not re-entrant: a unit is already open. "
                "Finish it before starting the next one."
            )
        # The previous unit committed if its aggregates still hold events (a rolled-back unit has
        # discarded them). They are facts: keep them for the bus before forgetting the aggregates.
        self._uncollected = (*self._uncollected, *self._collect_from_repositories())
        self._committed = False
        for repository in self._repositories():
            repository.forget()
        self._open = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._open = False
        if exc_type is not None or not self._committed:
            try:
                self.rollback()
            finally:
                self._discard_tracked()

    def commit(self) -> None:
        for repository in self._repositories():
            repository.persist_seen()
        self._commit()
        self._committed = True

    def collect_new_events(self) -> Iterator[DomainEvent]:
        """Pop the events of the committed units, oldest unit first."""
        uncollected, self._uncollected = self._uncollected, ()
        yield from uncollected
        yield from self._collect_from_repositories()

    @abc.abstractmethod
    def _commit(self) -> None:
        """Make the unit's changes durable."""

    @abc.abstractmethod
    def rollback(self) -> None:
        """Undo the unit's changes. Called by __exit__; handlers need not call it."""

    def _repositories(self) -> list[TrackingRepository[Any]]:
        return [value for value in vars(self).values() if isinstance(value, TrackingRepository)]

    def _collect_from_repositories(self) -> Iterator[DomainEvent]:
        for repository in self._repositories():
            yield from repository.collect_events()

    def _discard_tracked(self) -> None:
        # Rolled-back work must never be announced: drop pending events, forget the aggregates.
        for repository in self._repositories():
            for aggregate in repository.seen:
                aggregate.events.clear()
            repository.forget()


def _identity(aggregate: Aggregate[Any]) -> tuple[type, Hashable]:
    return (type(aggregate), aggregate.id)
