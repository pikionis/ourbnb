"""Composition root (Cosmic Python ch. 13): dependency injection by name, wired with fakes."""

import dataclasses
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from kospm.bootstrap import (
    ContextWiring,
    DuplicateCommandHandlerError,
    MissingDependencyError,
    bootstrap,
    default_contexts,
    get_bus,
    inject_dependencies,
)
from kospm.shared.clock import Clock, FixedClock, SystemClock
from kospm.shared.domain import Aggregate, Command, DomainEvent, new_id
from kospm.shared.messagebus import EventRetryPolicy, MessageBus, NoHandlerForCommandError
from kospm.shared.unit_of_work import AbstractUnitOfWork
from tests.fakes import FakeUnitOfWork

NOW = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Ping(Command):
    target_id: UUID


@dataclasses.dataclass(frozen=True, kw_only=True)
class Pinged(DomainEvent):
    target_id: UUID
    at: datetime


@dataclasses.dataclass(frozen=True, kw_only=True)
class Echoed(DomainEvent):
    target_id: UUID


class Target(Aggregate[UUID]):
    def __init__(self, id: UUID) -> None:
        super().__init__(id)
        self.last_pinged_at: datetime | None = None

    def ping(self, *, at: datetime) -> None:
        self.last_pinged_at = at
        self.events.append(Pinged(target_id=self.id, at=at))

    def echo(self) -> None:
        self.events.append(Echoed(target_id=self.id))


def ping(command: Ping, uow: FakeUnitOfWork[Target], clock: Clock) -> None:
    with uow:
        uow.items.get(command.target_id).ping(at=clock.now())
        uow.commit()


def echo(event: Pinged, uow: FakeUnitOfWork[Target]) -> None:
    with uow:
        uow.items.get(event.target_id).echo()
        uow.commit()


def record_pinged(event: Pinged, journal: list[Pinged]) -> None:
    journal.append(event)


def record_echoed(event: Echoed, echoes: list[Echoed]) -> None:
    echoes.append(event)


class BoomError(Exception):
    pass


# --- End to end --------------------------------------------------------------------------------


def test_a_ping_runs_end_to_end_through_a_fake_unit_of_work() -> None:
    clock = FixedClock(NOW)
    target = Target(new_id())
    uow = FakeUnitOfWork([target])
    journal: list[Pinged] = []
    bus = bootstrap(
        clock=clock,
        contexts=[
            ContextWiring(
                name="pings",
                uow=uow,
                command_handlers={Ping: ping},
                event_handlers={Pinged: [record_pinged]},
                dependencies={"journal": journal},
            )
        ],
    )

    bus.handle(Ping(target_id=target.id))

    assert uow.committed == 1
    assert target.last_pinged_at == NOW
    assert journal == [Pinged(target_id=target.id, at=NOW)]


def test_an_event_raised_in_one_context_reaches_the_handlers_of_another() -> None:
    target = Target(new_id())
    pings_uow, other_uow = FakeUnitOfWork([target]), FakeUnitOfWork[Target]()
    journal: list[Pinged] = []
    bus = bootstrap(
        clock=FixedClock(NOW),
        contexts=[
            ContextWiring(name="pings", uow=pings_uow, command_handlers={Ping: ping}),
            ContextWiring(
                name="journal",
                uow=other_uow,
                event_handlers={Pinged: [record_pinged]},
                dependencies={"journal": journal},
            ),
        ],
    )

    bus.handle(Ping(target_id=target.id))

    assert journal == [Pinged(target_id=target.id, at=NOW)]


def test_events_raised_in_every_context_reach_the_bus() -> None:
    # The bus must collect from the Unit of Work of every context, not only the first one.
    target_id = new_id()  # contexts share ids, never objects
    first_uow, second_uow = FakeUnitOfWork([Target(target_id)]), FakeUnitOfWork([Target(target_id)])
    echoes: list[Echoed] = []
    bus = bootstrap(
        clock=FixedClock(NOW),
        contexts=[
            ContextWiring(
                name="first",
                uow=first_uow,
                command_handlers={Ping: ping},
                event_handlers={Echoed: [record_echoed]},
                dependencies={"echoes": echoes},
            ),
            ContextWiring(name="second", uow=second_uow, event_handlers={Pinged: [echo]}),
        ],
    )

    bus.handle(Ping(target_id=target_id))

    assert second_uow.committed == 1
    assert echoes == [Echoed(target_id=target_id)]


# --- Injection by parameter name ---------------------------------------------------------------


def test_dependencies_are_injected_by_parameter_name() -> None:
    clock = FixedClock(NOW)
    uow = FakeUnitOfWork[Target]()
    notes: list[str] = []
    received: dict[str, object] = {}

    # Deliberately not in the order of the dependencies mapping.
    def handler(command: Ping, notes: list[str], clock: Clock, uow: AbstractUnitOfWork) -> None:
        received.update(command=command, notes=notes, clock=clock, uow=uow)

    bus = bootstrap(
        clock=clock,
        contexts=[
            ContextWiring(
                name="pings",
                uow=uow,
                command_handlers={Ping: handler},
                dependencies={"notes": notes},
            )
        ],
    )
    command = Ping(target_id=new_id())

    bus.handle(command)

    assert received["command"] is command
    assert received["notes"] is notes
    assert received["clock"] is clock
    assert received["uow"] is uow


def test_each_context_injects_its_own_unit_of_work() -> None:
    first_uow, second_uow = FakeUnitOfWork[Target](), FakeUnitOfWork[Target]()
    seen: list[tuple[str, AbstractUnitOfWork]] = []

    def in_first(event: Pinged, uow: AbstractUnitOfWork) -> None:
        seen.append(("first", uow))

    def in_second(event: Pinged, uow: AbstractUnitOfWork) -> None:
        seen.append(("second", uow))

    bus = bootstrap(
        clock=FixedClock(NOW),
        contexts=[
            ContextWiring(name="first", uow=first_uow, event_handlers={Pinged: [in_first]}),
            ContextWiring(name="second", uow=second_uow, event_handlers={Pinged: [in_second]}),
        ],
    )

    bus.handle(Pinged(target_id=new_id(), at=NOW))

    # Handlers of the same event run in context order, then registration order.
    assert seen == [("first", first_uow), ("second", second_uow)]


def test_the_injected_handler_takes_only_the_message_and_keeps_its_name() -> None:
    journal: list[Pinged] = []
    injected = inject_dependencies(record_pinged, {"journal": journal, "unused": object()})
    event = Pinged(target_id=new_id(), at=NOW)

    injected(event)

    assert journal == [event]
    # Bus logs name the original handler, not "functools.partial".
    assert injected.__qualname__ == "record_pinged"
    assert injected.__module__ == __name__


def test_a_parameter_with_a_default_keeps_it_unless_the_dependency_exists() -> None:
    received: list[int] = []

    def handler(event: Pinged, batch_size: int = 100) -> None:
        received.append(batch_size)

    event = Pinged(target_id=new_id(), at=NOW)
    inject_dependencies(handler, {})(event)
    inject_dependencies(handler, {"batch_size": 5})(event)

    assert received == [100, 5]


def test_keyword_only_dependencies_are_injected() -> None:
    received: list[object] = []

    def handler(event: Pinged, *, journal: list[Pinged]) -> None:
        received.append(journal)

    journal: list[Pinged] = []
    inject_dependencies(handler, {"journal": journal})(Pinged(target_id=new_id(), at=NOW))

    assert received == [journal]


def _no_parameters() -> None: ...


def _variadic(event: Pinged, *dependencies: object) -> None: ...


def _keywords(event: Pinged, **dependencies: object) -> None: ...


def _positional_only(event: Pinged, uow: AbstractUnitOfWork, /) -> None: ...


def _keyword_only_message(*, event: Pinged) -> None: ...


@pytest.mark.parametrize(
    "handler", [_no_parameters, _variadic, _keywords, _positional_only, _keyword_only_message]
)
def test_handlers_whose_dependencies_cannot_be_named_are_rejected(
    handler: Callable[..., None],
) -> None:
    with pytest.raises(TypeError, match=handler.__name__):
        inject_dependencies(handler, {"uow": FakeUnitOfWork[Target]()})


# --- Wiring errors fail at bootstrap time ------------------------------------------------------


def test_an_unknown_parameter_fails_at_bootstrap_time() -> None:
    def handler(command: Ping, uow: AbstractUnitOfWork, mailer: object) -> None:
        raise AssertionError("never called")

    with pytest.raises(MissingDependencyError, match="mailer") as raised:
        bootstrap(
            clock=FixedClock(NOW),
            contexts=[
                ContextWiring(
                    name="pings", uow=FakeUnitOfWork[Target](), command_handlers={Ping: handler}
                )
            ],
        )
    assert "handler" in str(raised.value)
    assert any("pings" in note for note in raised.value.__notes__)


def test_an_unknown_parameter_of_an_event_handler_fails_at_bootstrap_time() -> None:
    with pytest.raises(MissingDependencyError, match="journal"):
        bootstrap(
            clock=FixedClock(NOW),
            contexts=[
                ContextWiring(
                    name="pings",
                    uow=FakeUnitOfWork[Target](),
                    event_handlers={Pinged: [record_pinged]},
                )
            ],
        )


def test_a_context_cannot_use_the_dependencies_of_another() -> None:
    with pytest.raises(MissingDependencyError, match="journal"):
        bootstrap(
            clock=FixedClock(NOW),
            contexts=[
                ContextWiring(
                    name="owner",
                    uow=FakeUnitOfWork[Target](),
                    dependencies={"journal": []},
                ),
                ContextWiring(
                    name="other",
                    uow=FakeUnitOfWork[Target](),
                    event_handlers={Pinged: [record_pinged]},
                ),
            ],
        )


def test_the_same_command_in_two_contexts_fails_at_bootstrap_time() -> None:
    with pytest.raises(DuplicateCommandHandlerError, match="Ping") as raised:
        bootstrap(
            clock=FixedClock(NOW),
            contexts=[
                ContextWiring(
                    name="first", uow=FakeUnitOfWork[Target](), command_handlers={Ping: ping}
                ),
                ContextWiring(
                    name="second", uow=FakeUnitOfWork[Target](), command_handlers={Ping: ping}
                ),
            ],
        )
    assert "first" in str(raised.value)
    assert "second" in str(raised.value)


@pytest.mark.parametrize("name", ["uow", "clock"])
def test_a_context_cannot_redefine_the_injected_uow_or_clock(name: str) -> None:
    # The bus collects events only from the context's own uow, and the clock is shared.
    with pytest.raises(ValueError, match=name):
        ContextWiring(name="pings", uow=FakeUnitOfWork[Target](), dependencies={name: object()})


# --- Retry policy and defaults -----------------------------------------------------------------


@pytest.mark.parametrize(("policy", "attempts"), [(None, 3), (EventRetryPolicy(max_attempts=1), 1)])
def test_the_event_retry_policy_reaches_the_bus(
    policy: EventRetryPolicy | None, attempts: int
) -> None:
    calls: list[Pinged] = []

    def broken(event: Pinged) -> None:
        calls.append(event)
        raise BoomError

    bus = bootstrap(
        clock=FixedClock(NOW),
        contexts=[
            ContextWiring(
                name="pings", uow=FakeUnitOfWork[Target](), event_handlers={Pinged: [broken]}
            )
        ],
        retry_policy=policy,
    )

    bus.handle(Pinged(target_id=new_id(), at=NOW))

    assert len(calls) == attempts


def test_bootstrap_defaults_to_the_system_clock_and_the_production_contexts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clocks: list[Clock] = []

    def spy(clock: Clock) -> list[ContextWiring]:
        clocks.append(clock)
        return default_contexts(clock)

    monkeypatch.setattr("kospm.bootstrap.default_contexts", spy)

    bus = bootstrap()

    assert len(clocks) == 1
    assert isinstance(clocks[0], SystemClock)
    with pytest.raises(NoHandlerForCommandError):
        bus.handle(Ping(target_id=new_id()))


def test_the_production_contexts_are_the_bounded_contexts_built_so_far() -> None:
    assert [context.name for context in default_contexts(FixedClock(NOW))] == [
        "properties",
        "identity",
    ]


# --- One bus per thread ------------------------------------------------------------------------


def test_get_bus_returns_one_bus_per_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kospm.bootstrap._thread_local", threading.local())
    other_thread: list[MessageBus] = []

    def in_other_thread() -> None:
        other_thread.extend([get_bus(), get_bus()])

    bus = get_bus()
    thread = threading.Thread(target=in_other_thread)
    thread.start()
    thread.join()

    assert isinstance(bus, MessageBus)
    assert get_bus() is bus
    assert other_thread[0] is other_thread[1]
    assert other_thread[0] is not bus


def test_get_bus_bootstraps_once_per_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kospm.bootstrap._thread_local", threading.local())
    built: list[MessageBus] = []
    real_bootstrap = bootstrap

    def counting_bootstrap(**kwargs: Any) -> MessageBus:
        built.append(real_bootstrap(**kwargs))
        return built[-1]

    monkeypatch.setattr("kospm.bootstrap.bootstrap", counting_bootstrap)

    get_bus()
    get_bus()

    assert len(built) == 1
