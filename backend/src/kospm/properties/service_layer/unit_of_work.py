"""Ports of the properties context: its repositories and Unit of Work (Cosmic Python ch. 2, 6).

Abstract on purpose: handlers depend on these, the Django adapters and the test fakes implement
them. Every query method passes what it returns through `_track`, so the Unit of Work knows which
aggregates to write back and whose events to collect.
"""

import abc
from uuid import UUID

from kospm.properties.domain.owner import Owner
from kospm.properties.domain.property import Property
from kospm.properties.domain.value_objects import Afm, Email, PropertyCode
from kospm.shared.unit_of_work import AbstractUnitOfWork, TrackingRepository


class OwnerRepository(TrackingRepository[Owner]):
    @abc.abstractmethod
    def get(self, owner_id: UUID, *, expected_version: int | None = None) -> Owner:
        """The owner with this id; raises OwnerNotFound.

        `expected_version` is the version a form showed: if the stored one differs, or another
        unit saves before this one commits, ConcurrencyError (ADR 0016).
        """

    @abc.abstractmethod
    def find_by_afm(self, afm: Afm) -> Owner | None:
        """The owner with this ΑΦΜ, if any."""

    @abc.abstractmethod
    def find_by_email(self, email: Email) -> Owner | None:
        """The owner with this email address, if any."""


class PropertyRepository(TrackingRepository[Property]):
    @abc.abstractmethod
    def get(self, property_id: UUID, *, expected_version: int | None = None) -> Property:
        """The property with this id; raises PropertyNotFound (and ConcurrencyError, see Owner)."""

    @abc.abstractmethod
    def find_by_code(self, code: PropertyCode) -> Property | None:
        """The property with this code, if any."""

    @abc.abstractmethod
    def list_by_owner(self, owner_id: UUID) -> list[Property]:
        """All properties of one owner."""

    @abc.abstractmethod
    def codes_with_prefix(self, prefix: str) -> list[PropertyCode]:
        """The codes in use that start with `prefix` and a hyphen (read only, not tracked)."""


class PropertiesUnitOfWork(AbstractUnitOfWork):
    """One unit of work over the owners and properties of this context."""

    owners: OwnerRepository
    properties: PropertyRepository
