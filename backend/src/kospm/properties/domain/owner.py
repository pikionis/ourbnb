"""The Owner aggregate and its bank account (DOMAIN §5).

The bank account is verified with a €0.01 test transfer carrying a 6-digit code: the owner reads
the code on their statement and enters it, which proves the account exists, accepts transfers and
is theirs. Who sends the transfer (the admin by hand, later a provider) is an adapter concern;
the domain only knows the states UNVERIFIED → PENDING → VERIFIED.
"""

import hmac
import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Self
from uuid import UUID

from kospm.properties.domain.defaults import BankVerificationPolicy
from kospm.properties.domain.errors import (
    BankAccountAlreadyVerified,
    BankVerificationNotStarted,
    InvalidValue,
)
from kospm.properties.domain.events import BankAccountVerified, OwnerRegistered
from kospm.properties.domain.value_objects import Afm, Email, Iban
from kospm.shared.domain import Aggregate

_VERIFICATION_CODE = re.compile(r"[0-9]{6}")


class BankAccountStatus(StrEnum):
    UNVERIFIED = "unverified"
    PENDING = "pending"  # a test transfer with a code has been sent
    VERIFIED = "verified"


@dataclass(frozen=True)
class BankAccount:
    """The owner's IBAN and where its verification stands. The code never appears in repr."""

    iban: Iban
    status: BankAccountStatus = BankAccountStatus.UNVERIFIED
    verification_code: str = field(default="", repr=False)
    failed_attempts: int = 0


@dataclass(frozen=True)
class VerificationOutcome:
    """Result of entering a code: the caller reports a wrong code after the unit commits."""

    verified: bool
    attempts_left: int


class Owner(Aggregate[UUID]):
    """A person who owns properties and lets the IKE manage them. One owner, many properties."""

    def __init__(
        self,
        id: UUID,
        *,
        name: str,
        email: Email,
        phone: str,
        afm: Afm,
        bank_account: BankAccount,
        show_on_website: bool = False,
        website_consent_requested: bool = False,
    ) -> None:
        super().__init__(id)
        self.name = name
        self.email = email
        self.phone = phone
        self.afm = afm
        self.bank_account = bank_account
        self.show_on_website = show_on_website
        self.website_consent_requested = website_consent_requested

    @classmethod
    def register(
        cls, *, owner_id: UUID, name: str, email: Email, phone: str, afm: Afm, iban: Iban
    ) -> Self:
        """Onboarding step 1. The bank account starts unverified."""
        owner = cls(
            owner_id,
            name=_required(name, "name"),
            email=email,
            phone=_required(phone, "phone"),
            afm=afm,
            bank_account=BankAccount(iban),
        )
        owner.events.append(OwnerRegistered(owner_id=owner_id))
        return owner

    @property
    def bank_account_verified(self) -> bool:
        return self.bank_account.status is BankAccountStatus.VERIFIED

    def update_details(self, *, name: str, email: Email, phone: str) -> None:
        self.name = _required(name, "name")
        self.email = email
        self.phone = _required(phone, "phone")

    def change_iban(self, iban: Iban) -> None:
        """A different account must be verified again; the same one keeps its verification."""
        if iban != self.bank_account.iban:
            self.bank_account = BankAccount(iban)

    def start_bank_verification(self, code: str) -> None:
        """A test transfer carrying `code` is (about to be) sent. Restarting replaces the code."""
        if self.bank_account_verified:
            raise BankAccountAlreadyVerified(
                "the bank account is verified already; change the IBAN to verify another one"
            )
        if not _VERIFICATION_CODE.fullmatch(code):
            raise InvalidValue(
                "a verification code has exactly six digits", field="verification_code"
            )
        self.bank_account = replace(
            self.bank_account,
            status=BankAccountStatus.PENDING,
            verification_code=code,
            failed_attempts=0,
        )

    def confirm_bank_account(
        self, code: str, policy: BankVerificationPolicy
    ) -> VerificationOutcome:
        """Check the code the owner read on their statement.

        A wrong code is recorded, not raised: the attempt must be saved, so the handler commits
        and reports the error afterwards. The last allowed wrong code cancels the transfer.
        """
        account = self.bank_account
        if account.status is not BankAccountStatus.PENDING:
            raise BankVerificationNotStarted(
                "no test transfer is waiting for a code; start the verification first"
            )
        if hmac.compare_digest(code.strip().encode(), account.verification_code.encode()):
            self.bank_account = BankAccount(account.iban, status=BankAccountStatus.VERIFIED)
            self.events.append(BankAccountVerified(owner_id=self.id))
            return VerificationOutcome(verified=True, attempts_left=0)

        failed = account.failed_attempts + 1
        attempts_left = max(policy.max_attempts - failed, 0)
        if attempts_left:
            self.bank_account = replace(account, failed_attempts=failed)
        else:
            self.bank_account = BankAccount(account.iban)
        return VerificationOutcome(verified=False, attempts_left=attempts_left)

    def request_website_consent(self) -> bool:
        """Flag the owner to be asked about the public website (once). True if newly flagged."""
        if self.website_consent_requested:
            return False
        self.website_consent_requested = True
        return True


def _required(text: str, name: str) -> str:
    value = text.strip()
    if not value:
        raise InvalidValue(f"the owner's {name} is required", field=name)
    return value
