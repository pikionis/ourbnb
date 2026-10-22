"""DomainEvent and Command are immutable value objects (Cosmic Python ch. 8 and 10)."""

import dataclasses
from uuid import UUID, uuid4

import pytest

from kospm.shared.domain import Command, DomainEvent, Message


@dataclasses.dataclass(frozen=True, kw_only=True)
class CleaningCompleted(DomainEvent):
    task_id: UUID


@dataclasses.dataclass(frozen=True, kw_only=True)
class LinenCounted(DomainEvent):
    task_id: UUID


@dataclasses.dataclass(frozen=True, kw_only=True)
class AssignCleaning(Command):
    task_id: UUID
    cleaner: str = "standby"


def test_events_are_compared_by_value() -> None:
    task_id = uuid4()
    assert CleaningCompleted(task_id=task_id) == CleaningCompleted(task_id=task_id)
    assert hash(CleaningCompleted(task_id=task_id)) == hash(CleaningCompleted(task_id=task_id))
    assert CleaningCompleted(task_id=task_id) != CleaningCompleted(task_id=uuid4())


def test_events_of_different_types_with_the_same_fields_are_not_equal() -> None:
    task_id = uuid4()
    completed: object = CleaningCompleted(task_id=task_id)
    assert completed != LinenCounted(task_id=task_id)


def test_events_are_frozen() -> None:
    event = CleaningCompleted(task_id=uuid4())
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.task_id = uuid4()  # type: ignore[misc]


def test_commands_are_frozen_value_objects() -> None:
    task_id = uuid4()
    command = AssignCleaning(task_id=task_id, cleaner="Maria")
    assert command == AssignCleaning(task_id=task_id, cleaner="Maria")
    assert command != AssignCleaning(task_id=task_id)
    with pytest.raises(dataclasses.FrozenInstanceError):
        command.cleaner = "Eleni"  # type: ignore[misc]


def test_fields_are_keyword_only() -> None:
    # kw_only lets every subclass add fields (with or without defaults) in any order, and keeps
    # call sites readable.
    with pytest.raises(TypeError):
        AssignCleaning(uuid4())  # type: ignore[misc]


def test_an_event_is_not_a_command() -> None:
    event: Message = CleaningCompleted(task_id=uuid4())
    command: Message = AssignCleaning(task_id=uuid4())
    assert isinstance(event, DomainEvent)
    assert not isinstance(event, Command)
    assert isinstance(command, Command)
    assert not isinstance(command, DomainEvent)


def test_base_classes_are_frozen_keyword_only_dataclasses() -> None:
    for base in (DomainEvent, Command):
        params = vars(base)["__dataclass_params__"]
        assert params.frozen
        assert params.kw_only
