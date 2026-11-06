"""Ports of the properties context besides the repositories (hexagonal architecture)."""

import abc
from datetime import datetime
from uuid import UUID

from kospm.properties.domain.lead import OwnerLead
from kospm.properties.domain.listing import ListingDraft, ListingText
from kospm.properties.domain.value_objects import AccountHolderName, Iban
from kospm.shared.outbox.domain import OutboxMessage
from kospm.shared.outbox.service_layer.ports import AbstractOutbox


class ListingTextExtractor(abc.ABC):
    """Reads an owner's listing text into a draft profile (DOMAIN §5): the Claude API in
    production, a fake in tests. It only interprets text (DOMAIN §2.4) and never fetches."""

    @abc.abstractmethod
    def extract(self, listing: ListingText) -> ListingDraft:
        """The draft read from `listing`; raises ListingNotRead when it cannot."""


class LeadMailer(abc.ABC):
    """Turns a lead from the public site into the message that tells the IKE (ADR 0021)."""

    @abc.abstractmethod
    def new_lead(self, lead: OwnerLead, received_at: datetime) -> OutboxMessage:
        """The message to enqueue; the handler decides when."""


class BankAccountVerifier(abc.ABC):
    """Who sends the €0.01 test transfer that verifies an owner's bank account (DOMAIN §5).

    Today the admin sends it by hand from the IKE's e-banking (ManualBankAccountVerifier, ADR
    0018) and records the bank's payee check; later a business-account API can do both
    (it needs the holder's name for the check). Handlers do not change in between.
    """

    @abc.abstractmethod
    def new_code(self) -> str:
        """A fresh 6-digit code for the transfer's reference."""

    @abc.abstractmethod
    def request_test_transfer(
        self,
        *,
        owner_id: UUID,
        iban: Iban,
        holder_name: AccountHolderName,
        code: str,
        outbox: AbstractOutbox,
    ) -> None:
        """Called inside the unit that starts the verification.

        An automatic verifier enqueues the transfer in the outbox, so it happens only if the unit
        commits (no money moves inside the database transaction); the manual one leaves it to the
        admin, who sees the code in the admin.
        """
