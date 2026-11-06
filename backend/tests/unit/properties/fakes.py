"""In-memory fakes of the properties ports (Cosmic Python ch. 3: fakes, not mocks).

The fakes keep no versions: they record the `expected_version` each `get` was given, so tests
can check that handlers pass a form's version through. The refusal itself (ADR 0016) is covered
by the integration tests against PostgreSQL.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from kospm.properties.domain.errors import OwnerNotFound, PropertyNotFound
from kospm.properties.domain.lead import OwnerLead
from kospm.properties.domain.listing import ListingDraft, ListingText
from kospm.properties.domain.owner import Owner
from kospm.properties.domain.property import Property
from kospm.properties.domain.value_objects import AccountHolderName, Afm, Email, Iban, PropertyCode
from kospm.properties.service_layer.ports import (
    BankAccountVerifier,
    LeadMailer,
    ListingTextExtractor,
)
from kospm.properties.service_layer.unit_of_work import (
    OwnerRepository,
    PropertiesUnitOfWork,
    PropertyRepository,
)
from kospm.shared.outbox.domain import OutboxChannel, OutboxMessage
from kospm.shared.outbox.service_layer.ports import AbstractOutbox
from tests.fakes import FakeUnitOfWorkBase


class FakeOwnerRepository(OwnerRepository):
    def __init__(self, owners: Iterable[Owner] = ()) -> None:
        super().__init__()
        self._owners = {owner.id: owner for owner in owners}
        self.expected_versions: list[int | None] = []

    def _add(self, owner: Owner) -> None:
        self._owners[owner.id] = owner

    def get(self, owner_id: UUID, *, expected_version: int | None = None) -> Owner:
        self.expected_versions.append(expected_version)
        try:
            return self._track(self._owners[owner_id])
        except KeyError:
            raise OwnerNotFound(f"no owner has id {owner_id}") from None

    def find_by_afm(self, afm: Afm) -> Owner | None:
        return self._first(owner for owner in self._owners.values() if owner.afm == afm)

    def find_by_email(self, email: Email) -> Owner | None:
        return self._first(owner for owner in self._owners.values() if owner.email == email)

    def all(self) -> list[Owner]:
        """Every stored owner, untracked: for assertions."""
        return list(self._owners.values())

    def _first(self, owners: Iterable[Owner]) -> Owner | None:
        found = next(iter(owners), None)
        return None if found is None else self._track(found)


class FakePropertyRepository(PropertyRepository):
    def __init__(self, properties: Iterable[Property] = ()) -> None:
        super().__init__()
        self._properties = {prop.id: prop for prop in properties}
        self.expected_versions: list[int | None] = []

    def _add(self, prop: Property) -> None:
        self._properties[prop.id] = prop

    def get(self, property_id: UUID, *, expected_version: int | None = None) -> Property:
        self.expected_versions.append(expected_version)
        try:
            return self._track(self._properties[property_id])
        except KeyError:
            raise PropertyNotFound(f"no property has id {property_id}") from None

    def find_by_code(self, code: PropertyCode) -> Property | None:
        found = next((p for p in self._properties.values() if p.code == code), None)
        return None if found is None else self._track(found)

    def list_by_owner(self, owner_id: UUID) -> list[Property]:
        return [
            self._track(prop) for prop in self._properties.values() if prop.owner_id == owner_id
        ]

    def codes_with_prefix(self, prefix: str) -> list[PropertyCode]:
        return [p.code for p in self._properties.values() if p.code.value.startswith(f"{prefix}-")]

    def all(self) -> list[Property]:
        """Every stored property, untracked: for assertions."""
        return list(self._properties.values())


class FakePropertiesUnitOfWork(FakeUnitOfWorkBase, PropertiesUnitOfWork):
    owners: FakeOwnerRepository
    properties: FakePropertyRepository

    def __init__(self, owners: Iterable[Owner] = (), properties: Iterable[Property] = ()) -> None:
        super().__init__()
        self.owners = FakeOwnerRepository(owners)
        self.properties = FakePropertyRepository(properties)


@dataclass(frozen=True)
class RequestedTransfer:
    owner_id: UUID
    iban: Iban
    holder_name: AccountHolderName
    code: str


class FakeBankAccountVerifier(BankAccountVerifier):
    """Hands out known codes and records the transfers it was asked to send."""

    def __init__(self, codes: Iterable[str] = ("123456", "654321", "111111")) -> None:
        self._codes: Iterator[str] = iter(codes)
        self.transfers: list[RequestedTransfer] = []

    def new_code(self) -> str:
        return next(self._codes)

    def request_test_transfer(
        self,
        *,
        owner_id: UUID,
        iban: Iban,
        holder_name: AccountHolderName,
        code: str,
        outbox: AbstractOutbox,
    ) -> None:
        self.transfers.append(RequestedTransfer(owner_id, iban, holder_name, code))


class FakeLeadMailer(LeadMailer):
    """Records what it was asked to write, and writes a message anyone can recognise."""

    def __init__(self) -> None:
        self.seen: list[tuple[OwnerLead, datetime]] = []

    def new_lead(self, lead: OwnerLead, received_at: datetime) -> OutboxMessage:
        self.seen.append((lead, received_at))
        return OutboxMessage(
            channel=OutboxChannel.EMAIL,
            recipient="ike@example.com",
            template="properties.owner_lead",
            payload={"subject": lead.name, "body": lead.phone},
        )


class FakeListingExtractor(ListingTextExtractor):
    """Answers with a known draft and records every text it was given to read."""

    def __init__(self, draft: ListingDraft | None = None) -> None:
        self.read: list[ListingText] = []
        self._draft = draft or ListingDraft(address="Λάμπη, Κως")

    def extract(self, listing: ListingText) -> ListingDraft:
        self.read.append(listing)
        return self._draft
