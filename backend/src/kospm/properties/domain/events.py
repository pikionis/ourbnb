"""Domain events of the properties context (Cosmic Python ch. 8; DOMAIN §4.1, §5).

Events carry ids and the few facts their readers need, never secrets (lockbox codes, IBANs):
they are logged by type and read by other contexts.
"""

from dataclasses import dataclass
from uuid import UUID

from kospm.shared.domain import DomainEvent


@dataclass(frozen=True, kw_only=True)
class OwnerRegistered(DomainEvent):
    owner_id: UUID


@dataclass(frozen=True, kw_only=True)
class BankAccountVerified(DomainEvent):
    owner_id: UUID


@dataclass(frozen=True, kw_only=True)
class OwnerEmailChanged(DomainEvent):
    """The owner's email was corrected: an invitation not used yet follows it (identity)."""

    owner_id: UUID
    email: str


@dataclass(frozen=True, kw_only=True)
class PropertyProfileCompleted(DomainEvent):
    property_id: UUID


@dataclass(frozen=True, kw_only=True)
class ContractOffered(DomainEvent):
    """The IKE uploaded the contract to sign for a property."""

    property_id: UUID


@dataclass(frozen=True, kw_only=True)
class ContractSigned(DomainEvent):
    property_id: UUID


@dataclass(frozen=True, kw_only=True)
class SubleaseDeclared(DomainEvent):
    property_id: UUID
    number: str


@dataclass(frozen=True, kw_only=True)
class AmaAssigned(DomainEvent):
    property_id: UUID
    ama_number: str


@dataclass(frozen=True, kw_only=True)
class PropertyActivated(DomainEvent):
    """First activation: reservations starts the iCal sync, the owner is asked for consent."""

    property_id: UUID
    owner_id: UUID
    code: str


@dataclass(frozen=True, kw_only=True)
class PropertyDeactivated(DomainEvent):
    property_id: UUID


@dataclass(frozen=True, kw_only=True)
class PropertyReactivated(DomainEvent):
    property_id: UUID


@dataclass(frozen=True, kw_only=True)
class PropertyOffboarded(DomainEvent):
    property_id: UUID
