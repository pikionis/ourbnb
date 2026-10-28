"""Ports of the identity context: its repository and Unit of Work (Cosmic Python ch. 2, 6).

Every query method passes what it returns through `_track`, so the Unit of Work knows which
aggregates to write back and whose events to collect.
"""

import abc
from uuid import UUID

from kospm.identity.domain.account import Email, OwnerAccount
from kospm.shared.unit_of_work import AbstractUnitOfWork, TrackingRepository


class OwnerAccountRepository(TrackingRepository[OwnerAccount]):
    @abc.abstractmethod
    def find(self, account_id: UUID) -> OwnerAccount | None:
        """The account with this id, if any (links name it)."""

    @abc.abstractmethod
    def find_by_email(self, email: Email) -> OwnerAccount | None:
        """The account that logs in with this email address, if any."""

    @abc.abstractmethod
    def find_by_owner(self, owner_id: UUID) -> OwnerAccount | None:
        """The account of this owner, if any."""


class IdentityUnitOfWork(AbstractUnitOfWork):
    """One unit of work over the owner accounts."""

    accounts: OwnerAccountRepository
