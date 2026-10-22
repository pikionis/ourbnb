"""Entity and Aggregate base classes (Cosmic Python ch. 1 and 7).

An **Entity** has a lasting identity: two objects are the same entity when they have the same type
and id, whatever their other attributes. An **Aggregate** is the entity at the root of a
consistency boundary. It is the only thing a repository loads and saves, and it records the
domain events it raises in `self.events`; the message bus collects them from the Unit of Work
after commit.
"""

from collections.abc import Hashable

from kospm.shared.domain.messages import DomainEvent


class Entity[IdT: Hashable]:
    """An object defined by its identity rather than by its attributes."""

    def __init__(self, id: IdT) -> None:
        self._id = id

    @property
    def id(self) -> IdT:
        # Read-only: the hash depends on it, so changing it would corrupt sets and dicts.
        return self._id

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entity):
            return NotImplemented
        return type(other) is type(self) and other.id == self.id

    def __hash__(self) -> int:
        return hash((type(self), self._id))


class Aggregate[IdT: Hashable](Entity[IdT]):
    """Root of a consistency boundary. Appends the events it raises to `self.events`."""

    def __init__(self, id: IdT) -> None:
        super().__init__(id)
        # One list per instance (never a class attribute: it would be shared by all aggregates).
        self.events: list[DomainEvent] = []
