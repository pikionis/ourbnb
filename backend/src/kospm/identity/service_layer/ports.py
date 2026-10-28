"""Ports of the identity context besides the repository (hexagonal architecture, Cosmic Python
ch. 3): what the handlers need from the outside world, implemented by adapters and by fakes."""

import abc

from kospm.identity.domain.account import AccountLink, OwnerAccount
from kospm.shared.outbox.domain import OutboxMessage


class PasswordHasher(abc.ABC):
    """Turns a password into the hash that is stored; the password itself is never stored."""

    @abc.abstractmethod
    def hash(self, password: str) -> str: ...


class AccountTokens(abc.ABC):
    """Tokens of the links emailed to an account (DOMAIN §5: they work once and expire).

    A token is bound to the account's current state: once the email is confirmed, the password
    changes or the email changes, the tokens issued before stop working.
    """

    @abc.abstractmethod
    def make(self, account: OwnerAccount, link: AccountLink) -> str: ...

    @abc.abstractmethod
    def check(self, account: OwnerAccount, link: AccountLink, token: str) -> bool:
        """True if `token` was made for this link, for the account as it is now, and is not
        older than the link's lifetime."""


class AccountMailer(abc.ABC):
    """The emails of an account, as outbox messages: the handler enqueues them in its unit, so an
    email leaves only if the change it reports was committed (ADR 0005)."""

    @abc.abstractmethod
    def confirmation(self, account: OwnerAccount, token: str) -> OutboxMessage: ...

    @abc.abstractmethod
    def invitation(self, account: OwnerAccount, token: str) -> OutboxMessage: ...

    @abc.abstractmethod
    def password_reset(self, account: OwnerAccount, token: str) -> OutboxMessage: ...

    @abc.abstractmethod
    def already_registered(self, account: OwnerAccount) -> OutboxMessage:
        """To an address that signs up again: it has an account; log in, or reset the password."""

    @abc.abstractmethod
    def login_reminder(self, account: OwnerAccount) -> OutboxMessage:
        """To an invited owner whose account is active: log in, or reset the password."""
