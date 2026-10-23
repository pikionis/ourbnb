"""Adapters of the BankAccountVerifier port (DOMAIN §5, Phase 2b brings the automatic one)."""

import secrets
from uuid import UUID

from kospm.properties.domain.value_objects import Iban
from kospm.properties.service_layer.ports import BankAccountVerifier
from kospm.shared.outbox.service_layer.ports import AbstractOutbox


class ManualBankAccountVerifier(BankAccountVerifier):
    """The admin sends the €0.01 transfer by hand, with the code the admin page shows."""

    def new_code(self) -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    def request_test_transfer(
        self, *, owner_id: UUID, iban: Iban, code: str, outbox: AbstractOutbox
    ) -> None:
        """Nothing to send: the pending code on the owner is the admin's to-do."""
