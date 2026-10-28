"""Django repository of owner accounts (Repository pattern, Cosmic Python Appendix D).

An OwnerAccount is one `identity.User` row, found by `account_id`. The row also serves Django
auth: `username` and `email` hold the login email, `password` the hash (Django's unusable marker
while an invited owner has none), and `is_active` says whether the account can log in, so
Django's own login checks it. Writes go through the version check of ADR 0016.
"""

from typing import Any
from uuid import UUID

from django.contrib.auth.hashers import UNUSABLE_PASSWORD_PREFIX, is_password_usable
from django.db import IntegrityError

from kospm.identity.domain.account import AccountStatus, Email, Language, OwnerAccount
from kospm.identity.domain.errors import EmailAlreadyInUse
from kospm.identity.models import User
from kospm.identity.service_layer.unit_of_work import OwnerAccountRepository
from kospm.shared.adapters.versioned_repository import (
    VersionedDjangoRepository,
    violated_constraint,
)

# Stored while an invited owner has no password: Django never accepts it at login. Always the
# same value, so an unchanged account compares equal to its snapshot (ADR 0016).
NO_PASSWORD = UNUSABLE_PASSWORD_PREFIX


def account_to_domain(row: User) -> OwnerAccount:
    assert row.account_id is not None, "not an owner account"
    assert row.owner_id is not None, "an owner account always has an owner id"
    return OwnerAccount(
        row.account_id,
        owner_id=row.owner_id,
        email=Email(row.email),
        status=AccountStatus(row.account_status),
        language=Language(row.language),
        password_hash=row.password if is_password_usable(row.password) else None,
        owner_registered=row.owner_registered,
    )


def account_values(account: OwnerAccount) -> dict[str, Any]:
    return {
        "username": account.email.value,
        "email": account.email.value,
        "password": account.password_hash or NO_PASSWORD,
        "is_active": account.can_log_in,
        "owner_id": account.owner_id,
        "account_status": account.status.value,
        "owner_registered": account.owner_registered,
        "language": account.language.value,
    }


class DjangoOwnerAccountRepository(VersionedDjangoRepository[OwnerAccount], OwnerAccountRepository):
    model = User
    id_field = "account_id"

    def find(self, account_id: UUID) -> OwnerAccount | None:
        return self._first(account_id=account_id)

    def find_by_email(self, email: Email) -> OwnerAccount | None:
        return self._first(email=email.value)

    def find_by_owner(self, owner_id: UUID) -> OwnerAccount | None:
        return self._first(owner_id=owner_id)

    def _first(self, **lookup: Any) -> OwnerAccount | None:
        row = (
            User.objects.using(self.using)
            .filter(account_id__isnull=False, **lookup)
            .order_by("pk")
            .first()
        )
        return None if row is None else self._load(account_to_domain(row), row.version)

    def _values(self, account: OwnerAccount) -> dict[str, Any]:
        return account_values(account)

    def _duplicate(self, account: OwnerAccount, error: IntegrityError) -> Exception:
        # The login email is the username: another login (an owner's, or a staff user's) took it
        # between the handler's check and the write.
        if "username" in violated_constraint(error):
            # Name the account, never the address: errors reach logs.
            return EmailAlreadyInUse(f"another login uses the address of account {account.id}")
        return error
