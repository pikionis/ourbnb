"""Adapters of the BankAccountVerifier port (DOMAIN §5, ADR 0018)."""

import secrets
from uuid import UUID

from kospm.properties.domain.value_objects import AccountHolderName, Iban
from kospm.properties.service_layer.ports import BankAccountVerifier
from kospm.shared.outbox.service_layer.ports import AbstractOutbox


class ManualBankAccountVerifier(BankAccountVerifier):
    """The admin sends the €0.01 transfer by hand, with the code the admin page shows, and
    records the bank's payee check (ADR 0018)."""

    def new_code(self) -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    def request_test_transfer(
        self,
        *,
        owner_id: UUID,
        iban: Iban,
        holder_name: AccountHolderName,
        code: str,
        outbox: AbstractOutbox,
    ) -> None:
        """Nothing to send: the pending code on the owner is the admin's to-do."""
