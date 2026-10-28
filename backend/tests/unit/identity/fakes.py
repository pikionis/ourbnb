"""In-memory fakes of the identity ports (Cosmic Python ch. 3: fakes, not mocks)."""

from collections.abc import Callable, Iterable
from uuid import UUID

from kospm.identity.domain.account import AccountLink, Email, OwnerAccount
from kospm.identity.service_layer.ports import AccountMailer, AccountTokens, PasswordHasher
from kospm.identity.service_layer.unit_of_work import IdentityUnitOfWork, OwnerAccountRepository
from kospm.shared.outbox.domain import OutboxChannel, OutboxMessage
from tests.fakes import FakeUnitOfWorkBase


class FakeOwnerAccountRepository(OwnerAccountRepository):
    def __init__(self, accounts: Iterable[OwnerAccount] = ()) -> None:
        super().__init__()
        self._accounts = {account.id: account for account in accounts}

    def _add(self, account: OwnerAccount) -> None:
        self._accounts[account.id] = account

    def find(self, account_id: UUID) -> OwnerAccount | None:
        account = self._accounts.get(account_id)
        return None if account is None else self._track(account)

    def find_by_email(self, email: Email) -> OwnerAccount | None:
        return self._first(lambda account: account.email == email)

    def find_by_owner(self, owner_id: UUID) -> OwnerAccount | None:
        return self._first(lambda account: account.owner_id == owner_id)

    def all(self) -> list[OwnerAccount]:
        """Every stored account, untracked: for assertions in tests."""
        return list(self._accounts.values())

    def _first(self, matches: Callable[[OwnerAccount], bool]) -> OwnerAccount | None:
        for account in self._accounts.values():
            if matches(account):
                return self._track(account)
        return None


class FakeIdentityUnitOfWork(FakeUnitOfWorkBase, IdentityUnitOfWork):
    accounts: FakeOwnerAccountRepository

    def __init__(self, accounts: Iterable[OwnerAccount] = ()) -> None:
        super().__init__()
        self.accounts = FakeOwnerAccountRepository(accounts)


class FakePasswordHasher(PasswordHasher):
    def hash(self, password: str) -> str:
        return f"hashed:{password}"


class FakeAccountTokens(AccountTokens):
    """A token names the link and the account state it was made for, as the real one does: any
    change of that state (confirmed, new password, new email) makes it stale. `expire()` makes
    every token issued so far too old."""

    def __init__(self) -> None:
        self._expired: set[str] = set()
        self._issued: list[str] = []

    def make(self, account: OwnerAccount, link: AccountLink) -> str:
        token = f"{link}|{account.id}|{_state(account)}"
        self._issued.append(token)
        return token

    def check(self, account: OwnerAccount, link: AccountLink, token: str) -> bool:
        return token not in self._expired and token == f"{link}|{account.id}|{_state(account)}"

    def expire(self) -> None:
        self._expired.update(self._issued)


def _state(account: OwnerAccount) -> str:
    return f"{account.status}|{account.email}|{account.owner_id}|{account.password_hash}"


class FakeAccountMailer(AccountMailer):
    """Builds one outbox message per email; its template names the kind of email."""

    def confirmation(self, account: OwnerAccount, token: str) -> OutboxMessage:
        return _email(account, "confirmation", token)

    def invitation(self, account: OwnerAccount, token: str) -> OutboxMessage:
        return _email(account, "invitation", token)

    def password_reset(self, account: OwnerAccount, token: str) -> OutboxMessage:
        return _email(account, "password_reset", token)

    def already_registered(self, account: OwnerAccount) -> OutboxMessage:
        return _email(account, "already_registered", "")

    def login_reminder(self, account: OwnerAccount) -> OutboxMessage:
        return _email(account, "login_reminder", "")


def _email(account: OwnerAccount, kind: str, token: str) -> OutboxMessage:
    return OutboxMessage(
        channel=OutboxChannel.EMAIL,
        recipient=account.email.value,
        template=f"identity.{kind}",
        payload={"token": token},
    )
