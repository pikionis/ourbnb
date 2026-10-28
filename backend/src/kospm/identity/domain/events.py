"""Domain events of the identity context (Cosmic Python ch. 8).

Events carry ids only: never an email address, a password hash or a link.
"""

from dataclasses import dataclass
from uuid import UUID

from kospm.shared.domain import DomainEvent


@dataclass(frozen=True, kw_only=True)
class OwnerSignedUp(DomainEvent):
    account_id: UUID
    owner_id: UUID


@dataclass(frozen=True, kw_only=True)
class OwnerAccountActivated(DomainEvent):
    """The owner can log in: the email is confirmed, or a password was chosen from a link."""

    account_id: UUID
    owner_id: UUID
