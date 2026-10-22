"""The two kinds of message the message bus carries (Cosmic Python ch. 8 and 10).

- A **DomainEvent** records a fact that has already happened (past tense: `CleaningCompleted`).
  Any number of handlers may react to it, and one failing handler must not stop the others.
- A **Command** asks for something to happen (imperative: `AssignCleaning`). Exactly one handler
  owns it, and its errors go back to the caller.

Both are immutable value objects: frozen dataclasses compared by value. `kw_only` lets every
subclass add fields, with or without defaults, without the positional-order trap of dataclass
inheritance, and keeps call sites readable. Subclasses must be declared the same way:

    @dataclass(frozen=True, kw_only=True)
    class CleaningCompleted(DomainEvent):
        task_id: UUID

tests/unit/test_architecture.py checks this for every subclass in the code base.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Base class of every domain event. Subclasses: `@dataclass(frozen=True, kw_only=True)`."""


@dataclass(frozen=True, kw_only=True)
class Command:
    """Base class of every command. Subclasses: `@dataclass(frozen=True, kw_only=True)`."""


type Message = DomainEvent | Command
