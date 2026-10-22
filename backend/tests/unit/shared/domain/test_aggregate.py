"""Entity identity, Aggregate event collection, ids and the domain error base."""

import dataclasses
from uuid import UUID

import pytest

from kospm.shared.domain import Aggregate, DomainError, DomainEvent, Entity, new_id


@dataclasses.dataclass(frozen=True, kw_only=True)
class Renamed(DomainEvent):
    name: str


class Cleaner(Entity[UUID]):
    def __init__(self, id: UUID, name: str) -> None:
        super().__init__(id)
        self.name = name


class Owner(Entity[UUID]):
    pass


class Villa(Aggregate[UUID]):
    def __init__(self, id: UUID, name: str) -> None:
        super().__init__(id)
        self.name = name

    def rename(self, name: str) -> None:
        self.name = name
        self.events.append(Renamed(name=name))


def test_entities_are_equal_when_type_and_id_match_whatever_their_attributes() -> None:
    same_id = new_id()
    assert Cleaner(same_id, "Maria") == Cleaner(same_id, "Μαρία")
    assert hash(Cleaner(same_id, "Maria")) == hash(Cleaner(same_id, "Μαρία"))
    assert Cleaner(same_id, "Maria") != Cleaner(new_id(), "Maria")


def test_entities_of_different_types_are_never_equal() -> None:
    same_id = new_id()
    assert Cleaner(same_id, "Maria") != Owner(same_id)
    assert hash(Cleaner(same_id, "Maria")) != hash(Owner(same_id))


def test_an_entity_is_not_equal_to_its_bare_id() -> None:
    same_id = new_id()
    assert Owner(same_id) != same_id


def test_the_id_is_read_only() -> None:
    # The hash depends on the id: changing it would corrupt every set/dict holding the entity.
    owner = Owner(new_id())
    with pytest.raises(AttributeError):
        owner.id = new_id()  # type: ignore[misc]


def test_entities_can_live_in_sets_by_identity() -> None:
    same_id = new_id()
    assert len({Owner(same_id), Owner(same_id), Owner(new_id())}) == 2


def test_aggregate_records_events_in_order() -> None:
    villa = Villa(new_id(), "Villa Ilios")
    villa.rename("Villa Zefyros")
    villa.rename("Villa Thalassa")
    assert villa.events == [Renamed(name="Villa Zefyros"), Renamed(name="Villa Thalassa")]


def test_each_aggregate_has_its_own_events_list() -> None:
    first = Villa(new_id(), "A")
    second = Villa(new_id(), "B")
    first.rename("A2")
    assert second.events == []
    assert first.events is not second.events


def test_new_ids_are_unique_uuids() -> None:
    ids = {new_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(isinstance(value, UUID) for value in ids)


def test_domain_error_is_an_exception_contexts_subclass() -> None:
    class PropertyNotReadyError(DomainError):
        pass

    with pytest.raises(DomainError):
        raise PropertyNotReadyError("missing lockbox code")
