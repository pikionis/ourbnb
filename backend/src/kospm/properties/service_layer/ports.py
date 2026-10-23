"""Ports of the properties context besides the repositories (hexagonal architecture)."""

import abc
from uuid import UUID

from kospm.properties.domain.value_objects import Iban
from kospm.shared.outbox.service_layer.ports import AbstractOutbox


class BankAccountVerifier(abc.ABC):
    """Who sends the €0.01 test transfer that verifies an owner's bank account (DOMAIN §5).

    At first the admin sends it by hand from the IKE's e-banking (ManualBankAccountVerifier);
    later a bank or payment provider does it automatically. Handlers do not change in between.
    """

    @abc.abstractmethod
    def new_code(self) -> str:
        """A fresh 6-digit code for the transfer's reference."""

    @abc.abstractmethod
    def request_test_transfer(
        self, *, owner_id: UUID, iban: Iban, code: str, outbox: AbstractOutbox
    ) -> None:
        """Called inside the unit that starts the verification.

        An automatic verifier enqueues the transfer in the outbox, so it happens only if the unit
        commits (no money moves inside the database transaction); the manual one leaves it to the
        admin, who sees the code in the admin.
        """
