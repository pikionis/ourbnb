"""Pure-Python domain building blocks shared by all contexts.

Pure means: standard library only, no Django, no other context, no adapters. This is the only
`kospm` package a context's `domain/` may import besides its own.
"""

from kospm.shared.domain.aggregate import Aggregate, Entity
from kospm.shared.domain.errors import DomainError
from kospm.shared.domain.ids import new_id
from kospm.shared.domain.local_time import (
    ATHENS,
    athens_date,
    athens_datetime,
    require_aware,
    to_athens,
)
from kospm.shared.domain.messages import Command, DomainEvent, Message
from kospm.shared.domain.money import Money

__all__ = [
    "ATHENS",
    "Aggregate",
    "Command",
    "DomainError",
    "DomainEvent",
    "Entity",
    "Message",
    "Money",
    "athens_date",
    "athens_datetime",
    "new_id",
    "require_aware",
    "to_athens",
]
