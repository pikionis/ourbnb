"""Unit of Work semantics (Cosmic Python ch. 6-8), checked through the in-memory fakes."""

import contextlib
import dataclasses
from uuid import UUID

import pytest

from kospm.shared.domain import Aggregate, DomainEvent, new_id
from kospm.shared.outbox.domain import OutboxChannel, OutboxMessage
from kospm.shared.unit_of_work import AbstractUnitOfWork, TrackingRepository
from tests.fakes import FakeOutbox, FakeUnitOfWork, InMemoryRepository


@dataclasses.dataclass(frozen=True, kw_only=True)
class Counted(DomainEvent):
    counter_id: UUID
    value: int


class Counter(Aggregate[UUID]):
    def __init__(self, id: UUID, value: int = 0) -> None:
        super().__init__(id)
        self.value = value

    def increment(self) -> None:
        self.value += 1
        self.events.append(Counted(counter_id=self.id, value=self.value))


class BoomError(Exception):
    pass


MESSAGE = OutboxMessage(channel=OutboxChannel.WHATSAPP, recipient="+30", template="plan")


def test_the_unit_of_work_and_the_tracking_repository_are_abstract() -> None:
    with pytest.raises(TypeError):
        AbstractUnitOfWork()  # type: ignore[abstract]
    with pytest.raises(TypeError):
        TrackingRepository()  # type: ignore[abstract]


def test_commit_makes_the_events_collectable_in_order_exactly_once() -> None:
    uow = FakeUnitOfWork[Counter]()
    first, second = Counter(new_id()), Counter(new_id())
    with uow:
        uow.items.add(first)
        uow.items.add(second)
        first.increment()
        second.increment()
        first.increment()
        uow.commit()

    assert uow.committed == 1
    assert uow.rolled_back == 0
    assert list(uow.collect_new_events()) == [
        Counted(counter_id=first.id, value=1),
        Counted(counter_id=first.id, value=2),
        Counted(counter_id=second.id, value=1),
    ]
    assert first.events == []
    assert list(uow.collect_new_events()) == []


def test_events_of_aggregates_loaded_with_get_are_collected() -> None:
    counter = Counter(new_id(), value=41)
    uow = FakeUnitOfWork([counter])
    with uow:
        uow.items.get(counter.id).increment()
        uow.commit()
    assert list(uow.collect_new_events()) == [Counted(counter_id=counter.id, value=42)]


def test_an_aggregate_seen_twice_yields_its_events_once() -> None:
    counter = Counter(new_id())
    uow = FakeUnitOfWork[Counter]()
    with uow:
        uow.items.add(counter)
        assert uow.items.get(counter.id) is counter
        counter.increment()
        uow.commit()
    assert uow.items.seen == (counter,)
    assert list(uow.collect_new_events()) == [Counted(counter_id=counter.id, value=1)]


def test_leaving_without_commit_rolls_back_and_discards_the_events() -> None:
    counter = Counter(new_id())
    uow = FakeUnitOfWork([counter])
    with uow:
        uow.items.get(counter.id).increment()

    assert uow.committed == 0
    assert uow.rolled_back == 1
    assert counter.events == []
    assert list(uow.collect_new_events()) == []


def test_an_exception_rolls_back_propagates_and_discards_the_events() -> None:
    counter = Counter(new_id())
    uow = FakeUnitOfWork([counter])

    def increment_then_fail() -> None:
        with uow:
            uow.items.get(counter.id).increment()
            raise BoomError

    with pytest.raises(BoomError):
        increment_then_fail()
    assert uow.committed == 0
    assert uow.rolled_back == 1
    assert counter.events == []
    assert list(uow.collect_new_events()) == []


def test_an_exception_after_commit_still_rolls_back_and_discards_everything() -> None:
    # Deferred commit, as in DjangoUnitOfWork: the unit counts only once its block exits cleanly.
    counter = Counter(new_id())
    uow = FakeUnitOfWork([counter])

    def commit_then_fail() -> None:
        with uow:
            uow.items.get(counter.id).increment()
            uow.outbox.enqueue(MESSAGE)
            uow.commit()
            raise BoomError

    with pytest.raises(BoomError):
        commit_then_fail()

    assert uow.committed == 0
    assert uow.rolled_back == 1
    assert counter.events == []
    assert list(uow.collect_new_events()) == []
    assert uow.outbox.sent == []
    assert uow.outbox.pending == []


def test_events_are_discarded_even_if_rollback_itself_fails() -> None:
    class BrokenRollbackUnitOfWork(FakeUnitOfWork[Counter]):
        def rollback(self) -> None:
            raise BoomError("connection lost")

    counter = Counter(new_id())
    uow = BrokenRollbackUnitOfWork([counter])
    with pytest.raises(BoomError), uow:
        uow.items.get(counter.id).increment()
    assert counter.events == []
    assert list(uow.collect_new_events()) == []


def test_seen_aggregates_are_forgotten_when_a_new_unit_starts() -> None:
    counter = Counter(new_id())
    uow = FakeUnitOfWork([counter])
    with uow:
        uow.items.get(counter.id)
        uow.commit()
    assert uow.items.seen == (counter,)

    with uow:
        assert uow.items.seen == ()
        uow.commit()


def test_each_unit_needs_its_own_commit() -> None:
    uow = FakeUnitOfWork[Counter]()
    with uow:
        uow.commit()
    with uow:
        pass
    assert uow.committed == 1
    assert uow.rolled_back == 1


def test_the_next_unit_keeps_the_uncollected_events_of_a_committed_unit() -> None:
    # A handler that runs several units, or code outside the bus: committed facts are never lost.
    first, second = Counter(new_id()), Counter(new_id())
    uow = FakeUnitOfWork([first, second])
    with uow:
        uow.items.get(first.id).increment()
        uow.commit()
    with uow:
        uow.items.get(second.id).increment()
        uow.commit()

    assert list(uow.collect_new_events()) == [
        Counted(counter_id=first.id, value=1),
        Counted(counter_id=second.id, value=1),
    ]
    assert list(uow.collect_new_events()) == []


def test_a_rolled_back_unit_keeps_the_events_of_an_earlier_committed_unit() -> None:
    first, second = Counter(new_id()), Counter(new_id())
    uow = FakeUnitOfWork([first, second])
    with uow:
        uow.items.get(first.id).increment()
        uow.commit()
    with uow:
        uow.items.get(second.id).increment()

    assert list(uow.collect_new_events()) == [Counted(counter_id=first.id, value=1)]


def test_entering_a_unit_that_is_already_open_raises() -> None:
    # Every UoW, fakes included, refuses nesting (ADR 0014): handler tests catch it too.
    counter = Counter(new_id())
    uow = FakeUnitOfWork([counter])

    def enter_twice() -> None:
        with uow:
            uow.items.get(counter.id).increment()
            with uow:
                pytest.fail("a nested unit must not open")

    with pytest.raises(RuntimeError, match="re-entrant"):
        enter_twice()

    assert uow.rolled_back == 1
    assert counter.events == []
    with uow:  # the refused nesting left nothing open
        uow.commit()
    assert uow.committed == 1


def test_enqueue_outside_a_unit_is_refused() -> None:
    # As DjangoOutbox does: outside a unit the message would not depend on any commit.
    uow = FakeUnitOfWork[Counter]()
    with pytest.raises(RuntimeError, match="outside a UnitOfWork"):
        uow.outbox.enqueue(MESSAGE)
    with uow:
        uow.commit()
    with pytest.raises(RuntimeError, match="outside a UnitOfWork"):
        uow.outbox.enqueue(MESSAGE)
    assert uow.outbox.sent == []


# --- identity map: one object per aggregate per unit -------------------------------------------


class LoadingRepository(TrackingRepository[Counter]):
    """Like a Django repository: every load builds a new object from the stored state."""

    def __init__(self, values: dict[UUID, int]) -> None:
        super().__init__()
        self.values = values

    def _add(self, aggregate: Counter) -> None:
        self.values[aggregate.id] = aggregate.value

    def get(self, counter_id: UUID) -> Counter:
        return self._track(Counter(counter_id, self.values[counter_id]))

    def _persist(self, aggregate: Counter) -> None:
        self.values[aggregate.id] = aggregate.value


class LoadingUnitOfWork(FakeUnitOfWork[Counter]):
    def __init__(self, values: dict[UUID, int]) -> None:
        super().__init__()
        self.counters = LoadingRepository(values)


def test_loading_an_aggregate_twice_in_one_unit_returns_the_same_object() -> None:
    # Two copies would both be persisted on commit: the stale one would overwrite the change,
    # while the changed one's event would still be published.
    counter_id = new_id()
    uow = LoadingUnitOfWork({counter_id: 10})
    with uow:
        first = uow.counters.get(counter_id)
        first.increment()
        second = uow.counters.get(counter_id)
        uow.commit()

    assert second is first
    assert uow.counters.values[counter_id] == 11
    assert list(uow.collect_new_events()) == [Counted(counter_id=counter_id, value=11)]


def test_the_identity_map_lasts_one_unit() -> None:
    counter_id = new_id()
    uow = LoadingUnitOfWork({counter_id: 10})
    with uow:
        first = uow.counters.get(counter_id)
        uow.commit()
    with uow:
        assert uow.counters.get(counter_id) is not first
        uow.commit()


def test_adding_another_object_with_the_id_of_a_seen_aggregate_is_refused() -> None:
    counter_id = new_id()
    uow = LoadingUnitOfWork({counter_id: 10})
    with uow:
        uow.counters.get(counter_id).increment()
        with pytest.raises(ValueError, match="already"):
            uow.counters.add(Counter(counter_id))
        uow.commit()

    assert uow.counters.values[counter_id] == 11


class SpyRepository(InMemoryRepository[Counter]):
    def __init__(self, journal: list[str]) -> None:
        super().__init__()
        self.journal = journal

    def _persist(self, aggregate: Counter) -> None:
        self.journal.append(f"persist {aggregate.value}")


class TwoRepositoriesUnitOfWork(FakeUnitOfWork[Counter]):
    """A context's UoW usually has several repositories; all of them must be discovered."""

    def __init__(self) -> None:
        super().__init__()
        self.journal: list[str] = []
        self.spied = SpyRepository(self.journal)
        self.not_a_repository = "ignored"

    def _commit(self) -> None:
        self.journal.append("commit")
        super()._commit()


def test_every_repository_attribute_is_discovered() -> None:
    uow = TwoRepositoriesUnitOfWork()
    first, second = Counter(new_id()), Counter(new_id(), value=10)
    with uow:
        uow.items.add(first)
        uow.spied.add(second)
        first.increment()
        second.increment()
        uow.commit()

    assert uow.journal == ["persist 11", "commit"]  # seen aggregates are saved before COMMIT
    assert set(uow.collect_new_events()) == {
        Counted(counter_id=first.id, value=1),
        Counted(counter_id=second.id, value=11),
    }


def test_rollback_discards_events_in_every_repository() -> None:
    uow = TwoRepositoriesUnitOfWork()
    first, second = Counter(new_id()), Counter(new_id())
    with uow:
        uow.items.add(first)
        uow.spied.add(second)
        first.increment()
        second.increment()
    assert first.events == second.events == []
    assert uow.journal == []


def test_outbox_messages_are_kept_only_when_the_unit_commits() -> None:
    uow = FakeUnitOfWork[Counter]()
    with uow:
        uow.outbox.enqueue(MESSAGE)
        assert uow.outbox.sent == []
        uow.commit()
    assert uow.outbox.sent == [MESSAGE]
    assert uow.outbox.pending == []


@pytest.mark.parametrize("fail", [True, False], ids=["exception", "no-commit"])
def test_outbox_messages_of_a_rolled_back_unit_are_dropped(fail: bool) -> None:
    uow = FakeUnitOfWork[Counter]()
    with pytest.raises(BoomError) if fail else contextlib.nullcontext(), uow:
        uow.outbox.enqueue(MESSAGE)
        if fail:
            raise BoomError
    assert uow.outbox.sent == []
    assert uow.outbox.pending == []


def test_fake_outbox_is_usable_on_its_own() -> None:
    outbox = FakeOutbox()
    outbox.begin()
    outbox.enqueue(MESSAGE)
    outbox.discard_pending()
    outbox.begin()
    outbox.enqueue(MESSAGE)
    outbox.commit_pending()
    assert outbox.sent == [MESSAGE]
    with pytest.raises(RuntimeError, match="outside a UnitOfWork"):
        outbox.enqueue(MESSAGE)
