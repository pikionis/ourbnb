"""The OwnerAccount aggregate: an owner's login to the owner portal (DOMAIN §5, ADR 0017).

When an account is created it reserves the id of the owner it belongs to. The owner registers
later in the properties context with that id (onboarding step 1), so the two contexts share only
that id. An account invited by the admin belongs to an owner who is registered already.

States: UNCONFIRMED (signed up, email not confirmed yet) or INVITED (created by the admin's
invitation, no password yet) → ACTIVE (can log in).

Passwords are hashed before they reach the domain (the PasswordHasher port). The hash is opaque
here and kept out of repr. Django auth checks the password at login, on the mapped row.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Self
from uuid import UUID

from kospm.identity.domain.errors import (
    AccountLinkedToAnotherOwner,
    InvalidAccountState,
    InvalidValue,
)
from kospm.identity.domain.events import OwnerAccountActivated, OwnerSignedUp
from kospm.shared.domain import Aggregate

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# The address is also the login name, which holds at most this many characters.
MAX_EMAIL_LENGTH = 150


@dataclass(frozen=True)
class Email:
    """A login email address, lower-cased so that one address never gets two accounts.

    Errors never quote the address: they reach logs, and an address is personal data.
    """

    value: str

    def __post_init__(self) -> None:
        email = self.value.strip().lower()
        if not _EMAIL.fullmatch(email):
            raise InvalidValue("not an email address", field="email")
        if len(email) > MAX_EMAIL_LENGTH:
            raise InvalidValue(
                f"a login address has at most {MAX_EMAIL_LENGTH} characters", field="email"
            )
        object.__setattr__(self, "value", email)

    def __str__(self) -> str:
        return self.value


class AccountStatus(StrEnum):
    UNCONFIRMED = "unconfirmed"  # signed up; the email is not confirmed yet
    INVITED = "invited"  # created by the admin's invitation; no password yet
    ACTIVE = "active"  # can log in


class Language(StrEnum):
    """The language of the emails an account receives (pages follow the language toggle)."""

    GREEK = "el"
    ENGLISH = "en"


class AccountLink(StrEnum):
    """The links the platform emails to an account. Each works once and expires."""

    CONFIRMATION = "confirmation"
    INVITATION = "invitation"
    PASSWORD_RESET = "password_reset"


class OwnerAccount(Aggregate[UUID]):
    """An owner's login. One account per owner, one owner per account."""

    def __init__(
        self,
        id: UUID,
        *,
        owner_id: UUID,
        email: Email,
        status: AccountStatus,
        language: Language,
        password_hash: str | None,
        owner_registered: bool,
    ) -> None:
        super().__init__(id)
        self.owner_id = owner_id
        self.email = email
        self.status = status
        self.language = language
        self.password_hash = password_hash
        self.owner_registered = owner_registered

    def __repr__(self) -> str:
        # Never the password hash: reprs end up in logs and tracebacks.
        return f"OwnerAccount(id={self.id}, owner_id={self.owner_id}, status={self.status})"

    @classmethod
    def sign_up(
        cls,
        *,
        account_id: UUID,
        owner_id: UUID,
        email: Email,
        password_hash: str,
        language: Language,
    ) -> Self:
        """Self-registration: the email must be confirmed before the account can log in."""
        account = cls(
            account_id,
            owner_id=owner_id,
            email=email,
            status=AccountStatus.UNCONFIRMED,
            language=language,
            password_hash=password_hash,
            owner_registered=False,
        )
        account.events.append(OwnerSignedUp(account_id=account_id, owner_id=owner_id))
        return account

    @classmethod
    def invite(cls, *, account_id: UUID, owner_id: UUID, email: Email) -> Self:
        """An account for an owner the admin registered; the owner chooses a password."""
        return cls(
            account_id,
            owner_id=owner_id,
            email=email,
            status=AccountStatus.INVITED,
            language=Language.GREEK,
            password_hash=None,
            owner_registered=True,
        )

    @property
    def can_log_in(self) -> bool:
        return self.status is AccountStatus.ACTIVE

    def confirm_email(self) -> None:
        """The owner opened the confirmation link: the account becomes active."""
        if self.status is not AccountStatus.UNCONFIRMED:
            raise InvalidAccountState(self.status.value, "confirm the email of")
        self._activate()

    def set_password(self, password_hash: str, *, language: Language) -> None:
        """A password chosen through an emailed link (invitation or password reset).

        The link proves that the owner reads that mailbox, so an account that was not active
        becomes active. `language` is the one the owner is using, for the next emails.
        """
        self.password_hash = password_hash
        self.language = language
        if self.status is not AccountStatus.ACTIVE:
            self._activate()

    def change_email(self, email: Email) -> None:
        """An account not in use yet follows its owner's email; an active one changes via the
        IKE (the email is the login)."""
        if self.status is AccountStatus.ACTIVE:
            raise InvalidAccountState(self.status.value, "change the email of")
        self.email = email

    def note_owner_registered(self) -> None:
        """The owner this account reserved has registered (onboarding step 1)."""
        self.owner_registered = True

    def connect_to_owner(self, owner_id: UUID) -> None:
        """The admin invited the owner whose email this account uses (DOMAIN §5, owner portal).

        Allowed only while the account's own reserved owner never registered (its sign-up
        stopped at "contact us"): an account is never moved away from a registered owner.

        Whoever chose the account's password signed up with that address, maybe without being
        its owner (a mail scanner may even have opened the confirmation link), so they are not
        trusted with the invited owner's data: the password is dropped and the account waits
        for the invitation, which only the reader of the mailbox can accept.
        """
        if owner_id == self.owner_id:
            return
        if self.owner_registered:
            raise AccountLinkedToAnotherOwner(
                f"account {self.id} belongs to registered owner {self.owner_id}"
            )
        self.owner_id = owner_id
        self.owner_registered = True
        self.password_hash = None
        self.status = AccountStatus.INVITED

    def _activate(self) -> None:
        self.status = AccountStatus.ACTIVE
        self.events.append(OwnerAccountActivated(account_id=self.id, owner_id=self.owner_id))
