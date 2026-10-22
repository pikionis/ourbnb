"""Message bus semantics (Cosmic Python ch. 9-10, ADR 0005), checked with the in-memory fakes.

Commands have exactly one handler and fail loudly; events go to every handler, are retried and
never stop the other handlers; events are published only after their Unit of Work committed.
"""

import dataclasses
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest

from kospm.shared.domain import Aggregate, Command, DomainEvent, Message, new_id
from kospm.shared.messagebus import EventRetryPolicy, MessageBus, NoHandlerForCommandError
from tests.fakes import FakeUnitOfWork

BUS_LOGGER = "kospm.shared.messagebus"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Increment(Command):
    counter_id: UUID


@dataclasses.dataclass(frozen=True, kw_only=True)
class Reset(Command):
    counter_id: UUID


@dataclasses.dataclass(frozen=True, kw_only=True)
class IncrementTwice(Increment):
    """A subclass with no handler of its own: routing is by exact type."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class Incremented(DomainEvent):
    counter_id: UUID
    value: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class Noticed(DomainEvent):
    label: str


class Counter(Aggregate[UUID]):
    def __init__(self, id: UUID, value: int = 0) -> None:
        super().__init__(id)
        self.value = value

    def increment(self) -> None:
        self.value += 1
        self.events.append(Incremented(counter_id=self.id, value=self.value))


class BoomError(Exception):
    pass


class Recorder:
    """Records which handler received which message, in call order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Message]] = []

    def handler(self, name: str) -> Callable[[Any], None]:
        def handle(message: Message) -> None:
            self.calls.append((name, message))

        return handle

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


def flaky(recorder: Recorder, name: str, failures: int) -> Callable[[Any], None]:
    """A handler that raises on its first `failures` calls, then succeeds."""
    remaining = [failures]

    def handle(message: Message) -> None:
        recorder.calls.append((name, message))
        if remaining[0] > 0:
            remaining[0] -= 1
            raise BoomError(f"{name} failed")

    # Logs name the failing handler: give it a recognisable one.
    handle.__qualname__ = f"flaky_{name}"
    return handle


def bus_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == BUS_LOGGER]


# --- Commands ----------------------------------------------------------------------------------


def test_a_command_reaches_exactly_its_one_handler() -> None:
    recorder = Recorder()
    bus = MessageBus(
        uows=[],
        command_handlers={
            Increment: recorder.handler("increment"),
            Reset: recorder.handler("reset"),
        },
        event_handlers={},
    )
    command = Increment(counter_id=new_id())

    bus.handle(command)

    assert recorder.calls == [("increment", command)]


def test_a_command_without_a_handler_raises() -> None:
    bus = MessageBus(uows=[], command_handlers={}, event_handlers={})

    with pytest.raises(NoHandlerForCommandError, match="Increment"):
        bus.handle(Increment(counter_id=new_id()))


def test_commands_are_routed_by_their_exact_type() -> None:
    recorder = Recorder()
    bus = MessageBus(
        uows=[], command_handlers={Increment: recorder.handler("increment")}, event_handlers={}
    )

    with pytest.raises(NoHandlerForCommandError, match="IncrementTwice"):
        bus.handle(IncrementTwice(counter_id=new_id()))
    assert recorder.calls == []


def test_a_command_handler_exception_propagates_to_the_caller() -> None:
    def failing(command: Increment) -> None:
        raise BoomError("cannot increment")

    bus = MessageBus(uows=[], command_handlers={Increment: failing}, event_handlers={})

    with pytest.raises(BoomError, match="cannot increment"):
        bus.handle(Increment(counter_id=new_id()))


def test_a_failing_command_handler_is_not_retried() -> None:
    recorder = Recorder()
    bus = MessageBus(
        uows=[],
        command_handlers={Increment: flaky(recorder, "increment", failures=1)},
        event_handlers={},
    )

    with pytest.raises(BoomError):
        bus.handle(Increment(counter_id=new_id()))
    assert recorder.names() == ["increment"]


# --- Events ------------------------------------------------------------------------------------


def test_an_event_reaches_all_its_handlers_in_registration_order() -> None:
    recorder = Recorder()
    bus = MessageBus(
        uows=[],
        command_handlers={},
        event_handlers={
            Noticed: [recorder.handler("first"), recorder.handler("second")],
            Incremented: [recorder.handler("other event")],
        },
    )
    event = Noticed(label="linen low")

    bus.handle(event)

    assert recorder.calls == [("first", event), ("second", event)]


def test_an_event_without_handlers_is_fine() -> None:
    bus = MessageBus(uows=[], command_handlers={}, event_handlers={})

    bus.handle(Noticed(label="nobody listens"))


def test_events_of_a_committed_command_reach_the_event_handlers() -> None:
    counter = Counter(new_id())
    uow = FakeUnitOfWork([counter])
    recorder = Recorder()

    def increment(command: Increment) -> None:
        with uow:
            uow.items.get(command.counter_id).increment()
            uow.commit()

    bus = MessageBus(
        uows=[uow],
        command_handlers={Increment: increment},
        event_handlers={Incremented: [recorder.handler("on incremented")]},
    )

    bus.handle(Increment(counter_id=counter.id))

    assert uow.committed == 1
    assert recorder.calls == [("on incremented", Incremented(counter_id=counter.id, value=1))]
    assert counter.events == []


def test_events_raised_by_event_handlers_cascade_first_in_first_out() -> None:
    # Command -> A, B; A -> C; B -> D. FIFO (breadth first) handles A, B, C, D in that order.
    a, b, c, d = (Counter(new_id()) for _ in range(4))
    uow = FakeUnitOfWork([a, b, c, d])
    follow_up = {a.id: c.id, b.id: d.id}
    handled: list[UUID] = []

    def start(command: Increment) -> None:
        with uow:
            uow.items.get(a.id).increment()
            uow.items.get(b.id).increment()
            uow.commit()

    def cascade(event: Incremented) -> None:
        handled.append(event.counter_id)
        if event.counter_id in follow_up:
            with uow:
                uow.items.get(follow_up[event.counter_id]).increment()
                uow.commit()

    bus = MessageBus(
        uows=[uow], command_handlers={Increment: start}, event_handlers={Incremented: [cascade]}
    )

    bus.handle(Increment(counter_id=a.id))

    assert handled == [a.id, b.id, c.id, d.id]


def test_events_from_every_unit_of_work_are_collected() -> None:
    left, right = Counter(new_id()), Counter(new_id())
    left_uow, right_uow = FakeUnitOfWork([left]), FakeUnitOfWork([right])
    recorder = Recorder()

    def increment_both(command: Increment) -> None:
        with left_uow:
            left_uow.items.get(left.id).increment()
            left_uow.commit()
        with right_uow:
            right_uow.items.get(right.id).increment()
            right_uow.commit()

    bus = MessageBus(
        uows=[left_uow, right_uow],
        command_handlers={Increment: increment_both},
        event_handlers={Incremented: [recorder.handler("on incremented")]},
    )

    bus.handle(Increment(counter_id=left.id))

    assert [message for _, message in recorder.calls] == [
        Incremented(counter_id=left.id, value=1),
        Incremented(counter_id=right.id, value=1),
    ]


def test_events_of_every_unit_a_handler_ran_are_published() -> None:
    # e.g. a sync that commits one unit per property: no committed fact may be dropped.
    counters = [Counter(new_id()) for _ in range(3)]
    uow = FakeUnitOfWork(counters)
    recorder = Recorder()

    def increment_each(command: Increment) -> None:
        for counter in counters:
            with uow:
                uow.items.get(counter.id).increment()
                uow.commit()

    bus = MessageBus(
        uows=[uow],
        command_handlers={Increment: increment_each},
        event_handlers={Incremented: [recorder.handler("on incremented")]},
    )

    bus.handle(Increment(counter_id=counters[0].id))

    assert [message for _, message in recorder.calls] == [
        Incremented(counter_id=counter.id, value=1) for counter in counters
    ]


# --- Rolled-back units never publish -----------------------------------------------------------


def test_events_of_a_command_that_rolled_back_are_not_published() -> None:
    counter = Counter(new_id())
    uow = FakeUnitOfWork([counter])
    recorder = Recorder()

    def increment_then_fail(command: Increment) -> None:
        with uow:
            uow.items.get(command.counter_id).increment()
            raise BoomError("after the change, before the commit")

    bus = MessageBus(
        uows=[uow],
        command_handlers={Increment: increment_then_fail},
        event_handlers={Incremented: [recorder.handler("on incremented")]},
    )

    with pytest.raises(BoomError):
        bus.handle(Increment(counter_id=counter.id))
    assert uow.rolled_back == 1
    assert recorder.calls == []
    assert list(uow.collect_new_events()) == []


def test_events_of_an_event_handler_that_rolled_back_are_not_published() -> None:
    counter = Counter(new_id())
    uow = FakeUnitOfWork([counter])
    recorder = Recorder()

    def increment_then_fail(event: Noticed) -> None:
        with uow:
            uow.items.get(counter.id).increment()
            raise BoomError("after the change, before the commit")

    bus = MessageBus(
        uows=[uow],
        command_handlers={},
        event_handlers={
            Noticed: [increment_then_fail],
            Incremented: [recorder.handler("on incremented")],
        },
    )

    bus.handle(Noticed(label="try"))

    assert uow.committed == 0
    assert uow.rolled_back == EventRetryPolicy().max_attempts
    assert recorder.calls == []
    assert list(uow.collect_new_events()) == []


# --- Committed units always publish, even if their handler fails afterwards --------------------


def test_a_command_that_fails_after_committing_publishes_its_events_then_raises() -> None:
    counter = Counter(new_id())
    uow = FakeUnitOfWork([counter])
    recorder = Recorder()

    def commit_then_fail(command: Increment) -> None:
        with uow:
            uow.items.get(command.counter_id).increment()
            uow.commit()
        raise BoomError("after the unit")

    bus = MessageBus(
        uows=[uow],
        command_handlers={Increment: commit_then_fail},
        event_handlers={
            Incremented: [recorder.handler("on incremented")],
            Noticed: [recorder.handler("on noticed")],
        },
    )

    with pytest.raises(BoomError, match="after the unit"):
        bus.handle(Increment(counter_id=counter.id))
    assert recorder.calls == [("on incremented", Incremented(counter_id=counter.id, value=1))]

    # Nothing is left behind to leak into the cascade of a later, unrelated message.
    recorder.calls.clear()
    bus.handle(Noticed(label="unrelated"))
    assert recorder.names() == ["on noticed"]


def test_an_event_handler_that_fails_after_committing_still_publishes_its_events() -> None:
    counters = [Counter(new_id()), Counter(new_id())]  # one per attempt
    uow = FakeUnitOfWork(counters)
    recorder = Recorder()
    attempts: list[Counter] = []

    def commit_then_fail_once(event: Noticed) -> None:
        counter = counters[len(attempts)]
        attempts.append(counter)
        with uow:
            uow.items.get(counter.id).increment()
            uow.commit()
        if len(attempts) == 1:
            raise BoomError("after the unit")

    bus = MessageBus(
        uows=[uow],
        command_handlers={},
        event_handlers={
            Noticed: [commit_then_fail_once],
            Incremented: [recorder.handler("on incremented")],
        },
    )

    bus.handle(Noticed(label="try"))

    # Both attempts committed a unit, so both facts are published.
    assert [message for _, message in recorder.calls] == [
        Incremented(counter_id=counter.id, value=1) for counter in counters
    ]


# --- Event handler retries ---------------------------------------------------------------------


def test_the_default_retry_policy_attempts_an_event_handler_three_times() -> None:
    assert EventRetryPolicy().max_attempts == 3


@pytest.mark.parametrize("attempts", [0, -1])
def test_the_retry_policy_needs_at_least_one_attempt(attempts: int) -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        EventRetryPolicy(max_attempts=attempts)


def test_a_failing_event_handler_is_retried_logged_and_swallowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=BUS_LOGGER)
    recorder = Recorder()
    bus = MessageBus(
        uows=[],
        command_handlers={},
        event_handlers={
            Noticed: [
                recorder.handler("before"),
                flaky(recorder, "broken", failures=99),
                recorder.handler("after"),
            ]
        },
    )

    bus.handle(Noticed(label="linen low"))  # does not raise

    assert recorder.names() == ["before", "broken", "broken", "broken", "after"]
    records = bus_records(caplog)
    assert [record.levelno for record in records] == [
        logging.WARNING,
        logging.WARNING,
        logging.ERROR,
    ]
    assert all("flaky_broken" in record.getMessage() for record in records)
    assert records[-1].exc_info is not None
    assert isinstance(records[-1].exc_info[1], BoomError)


def test_failure_logs_name_the_event_type_but_never_its_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Events may carry guest data (DOMAIN §2.3); logs are data at rest too.
    caplog.set_level(logging.DEBUG, logger=BUS_LOGGER)
    recorder = Recorder()
    bus = MessageBus(
        uows=[],
        command_handlers={},
        event_handlers={Noticed: [flaky(recorder, "broken", failures=99)]},
    )

    bus.handle(Noticed(label="lockbox 4711"))

    records = bus_records(caplog)
    assert records
    assert all("Noticed" in record.getMessage() for record in records)
    assert not any("4711" in record.getMessage() for record in records)


def test_an_event_handler_that_succeeds_on_its_second_attempt_runs_exactly_twice(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=BUS_LOGGER)
    recorder = Recorder()
    bus = MessageBus(
        uows=[],
        command_handlers={},
        event_handlers={Noticed: [flaky(recorder, "flaky", failures=1)]},
    )

    bus.handle(Noticed(label="linen low"))

    assert recorder.names() == ["flaky", "flaky"]
    assert [record.levelno for record in bus_records(caplog)] == [logging.WARNING]


def test_events_of_a_retried_handler_are_published_once_it_succeeds() -> None:
    counter = Counter(new_id())
    uow = FakeUnitOfWork([counter])
    recorder = Recorder()
    failures = [1]

    def increment_flakily(event: Noticed) -> None:
        with uow:
            uow.items.get(counter.id).increment()
            if failures[0] > 0:
                failures[0] -= 1
                raise BoomError("transient")
            uow.commit()

    bus = MessageBus(
        uows=[uow],
        command_handlers={},
        event_handlers={
            Noticed: [increment_flakily],
            Incremented: [recorder.handler("on incremented")],
        },
    )

    bus.handle(Noticed(label="try"))

    # The fake repository is not transactional, so the counter keeps the rolled-back increment;
    # what matters is that only the committed attempt's event is published, exactly once.
    assert recorder.calls == [("on incremented", Incremented(counter_id=counter.id, value=2))]


def test_the_retry_policy_sets_the_number_of_attempts(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=BUS_LOGGER)
    recorder = Recorder()
    bus = MessageBus(
        uows=[],
        command_handlers={},
        event_handlers={Noticed: [flaky(recorder, "broken", failures=99)]},
        retry_policy=EventRetryPolicy(max_attempts=1),
    )

    bus.handle(Noticed(label="linen low"))

    assert recorder.names() == ["broken"]
    assert [record.levelno for record in bus_records(caplog)] == [logging.ERROR]


# --- Anything else -----------------------------------------------------------------------------


@pytest.mark.parametrize("message", ["Increment", 42, None, object()])
def test_handling_something_that_is_not_a_message_raises_type_error(message: object) -> None:
    bus = MessageBus(uows=[], command_handlers={}, event_handlers={})

    with pytest.raises(TypeError, match="DomainEvent or a Command"):
        bus.handle(message)  # type: ignore[arg-type]
