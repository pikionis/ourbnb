"""The Owner aggregate and its bank account (DOMAIN §5, ADR 0018).

The bank account is verified with a €0.01 test transfer carrying a 6-digit code: the owner reads
the code on their statement and enters it, which proves the account exists, accepts transfers and
is theirs. When the IKE sends the transfer, its bank checks the holder's name against the IBAN
(Verification of Payee) and the admin records the answer, a PayeeCheck. Who sends the transfer
(the admin by hand, later a provider) is an adapter concern; the domain knows the states
UNVERIFIED → PENDING → TRANSFER_SENT → VERIFIED.
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
    ChangeThroughTheIke,
    InvalidValue,
    TransferNotSentYet,
)
from kospm.properties.domain.events import (
    BankAccountVerified,
    OwnerEmailChanged,
    OwnerRegistered,
)
from kospm.properties.domain.value_objects import AccountHolderName, Afm, Email, Iban
from kospm.shared.domain import Aggregate

_VERIFICATION_CODE = re.compile(r"[0-9]{6}")


class BankAccountStatus(StrEnum):
    UNVERIFIED = "unverified"
    PENDING = "pending"  # the IKE has to send the test transfer with the code
    TRANSFER_SENT = "transfer_sent"  # sent: the owner has to enter the code
    VERIFIED = "verified"


class PayeeCheckResult(StrEnum):
    """The answer of the IKE's bank when the test transfer is sent (Verification of Payee)."""

    MATCH = "match"
    CLOSE_MATCH = "close_match"  # the bank returns its own spelling of the name
    NOT_POSSIBLE = "not_possible"  # e.g. a bank outside the euro area: the code is the proof
    NO_MATCH = "no_match"  # nothing is sent


@dataclass(frozen=True)
class PayeeCheck:
    """What the admin recorded about the bank's payee check (ADR 0018)."""

    result: PayeeCheckResult
    bank_name: AccountHolderName | None = None  # with CLOSE_MATCH only

    def __post_init__(self) -> None:
        if (self.result is PayeeCheckResult.CLOSE_MATCH) != (self.bank_name is not None):
            raise InvalidValue(
                "a close match comes with the name the bank returned, the other results without",
                field="payee_check",
            )

    @property
    def transfer_sent(self) -> bool:
        return self.result is not PayeeCheckResult.NO_MATCH


@dataclass(frozen=True)
class BankAccount:
    """The owner's IBAN and where its verification stands. The code never appears in repr.

    `payee_check` is the last recorded check: it stays after a NO_MATCH, so the owner sees why
    the verification stopped, and after the verification, as its record.
    """

    iban: Iban
    holder_name: AccountHolderName
    status: BankAccountStatus = BankAccountStatus.UNVERIFIED
    verification_code: str = field(default="", repr=False)
    failed_attempts: int = 0
    payee_check: PayeeCheck | None = None


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
        cls,
        *,
        owner_id: UUID,
        name: str,
        email: Email,
        phone: str,
        afm: Afm,
        iban: Iban,
        holder_name: AccountHolderName,
    ) -> Self:
        """Onboarding step 1. The bank account starts unverified."""
        owner = cls(
            owner_id,
            name=_required(name, "name"),
            email=email,
            phone=_required(phone, "phone"),
            afm=afm,
            bank_account=BankAccount(iban, holder_name),
        )
        owner.events.append(OwnerRegistered(owner_id=owner_id))
        return owner

    @property
    def bank_account_verified(self) -> bool:
        return self.bank_account.status is BankAccountStatus.VERIFIED

    def update_details(self, *, name: str, email: Email, phone: str) -> None:
        name, phone = _required(name, "name"), _required(phone, "phone")
        if email != self.email:
            # The owner's portal invitation, if not used yet, follows the corrected address.
            self.events.append(OwnerEmailChanged(owner_id=self.id, email=email.value))
        self.name, self.email, self.phone = name, email, phone

    def change_bank_account(self, iban: Iban, holder_name: AccountHolderName) -> None:
        """A different account or holder name must be verified again; the same one keeps its
        state (the bank compares both)."""
        if (iban, holder_name) != (self.bank_account.iban, self.bank_account.holder_name):
            self.bank_account = BankAccount(iban, holder_name)

    def change_own_bank_account(self, iban: Iban, holder_name: AccountHolderName) -> None:
        """The owner changes it in the portal, only until it is verified: then through the IKE,
        so that taking over an owner's login is not enough to redirect their payouts."""
        unchanged = (iban, holder_name) == (self.bank_account.iban, self.bank_account.holder_name)
        if self.bank_account_verified and not unchanged:
            raise ChangeThroughTheIke("bank_account")
        self.change_bank_account(iban, holder_name)

    def start_bank_verification(self, code: str) -> None:
        """A test transfer carrying `code` is to be sent. Restarting replaces the code."""
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
            payee_check=None,
        )

    def record_test_transfer(self, check: PayeeCheck) -> None:
        """The admin sent the test transfer, or did not (NO_MATCH), and records the bank's payee
        check. A close match takes the bank's spelling of the name: it is the bank's own, so the
        verification goes on."""
        account = self.bank_account
        if account.status is not BankAccountStatus.PENDING:
            raise BankVerificationNotStarted(
                "no test transfer is waiting to be sent; start the verification first"
            )
        if not check.transfer_sent:
            self.bank_account = BankAccount(account.iban, account.holder_name, payee_check=check)
            return
        self.bank_account = replace(
            account,
            status=BankAccountStatus.TRANSFER_SENT,
            holder_name=check.bank_name or account.holder_name,
            payee_check=check,
        )

    def confirm_bank_account(
        self, code: str, policy: BankVerificationPolicy
    ) -> VerificationOutcome:
        """Check the code the owner read on their statement.

        A wrong code is recorded, not raised: the attempt must be saved, so the handler commits
        and reports the error afterwards. The last allowed wrong code cancels the transfer.
        """
        account = self.bank_account
        if account.status is BankAccountStatus.PENDING:
            raise TransferNotSentYet("the IKE has not sent the test transfer yet")
        if account.status is not BankAccountStatus.TRANSFER_SENT:
            raise BankVerificationNotStarted(
                "no test transfer is waiting for a code; start the verification first"
            )
        if hmac.compare_digest(code.strip().encode(), account.verification_code.encode()):
            self.bank_account = BankAccount(
                account.iban,
                account.holder_name,
                status=BankAccountStatus.VERIFIED,
                payee_check=account.payee_check,
            )
            self.events.append(BankAccountVerified(owner_id=self.id))
            return VerificationOutcome(verified=True, attempts_left=0)

        failed = account.failed_attempts + 1
        attempts_left = max(policy.max_attempts - failed, 0)
        if attempts_left:
            self.bank_account = replace(account, failed_attempts=failed)
        else:
            self.bank_account = BankAccount(account.iban, account.holder_name)
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
