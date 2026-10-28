"""The owner-account repository against PostgreSQL (Appendix D, ADR 0016).

An account is one `identity.User` row, found by `account_id`; the row also serves Django's login.
"""

from datetime import UTC, datetime

import pytest
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import make_password

from kospm.identity.adapters.unit_of_work import DjangoIdentityUnitOfWork
from kospm.identity.domain.account import AccountStatus, Email, Language, OwnerAccount
from kospm.identity.domain.errors import EmailAlreadyInUse
from kospm.identity.models import AccountStatusChoices, User
from kospm.shared.clock import FixedClock
from kospm.shared.domain import new_id
from kospm.shared.outbox.adapters import DjangoOutbox
from kospm.shared.unit_of_work import ConcurrencyError

pytestmark = pytest.mark.django_db

PASSWORD_HASH = "md5$salt$" + "0" * 32  # any usable-looking hash; the tests that log in set one


def new_uow() -> DjangoIdentityUnitOfWork:
    return DjangoIdentityUnitOfWork(
        outbox=DjangoOutbox(FixedClock(datetime(2026, 10, 28, tzinfo=UTC)))
    )


def stored(account: OwnerAccount) -> OwnerAccount:
    uow = new_uow()
    with uow:
        uow.accounts.add(account)
        uow.commit()
    return account


def signed_up(email: str = "maria@example.com", password_hash: str = PASSWORD_HASH) -> OwnerAccount:
    return OwnerAccount.sign_up(
        account_id=new_id(),
        owner_id=new_id(),
        email=Email(email),
        password_hash=password_hash,
        language=Language.ENGLISH,
    )


def row_of(account: OwnerAccount) -> User:
    return User.objects.get(account_id=account.id)


class TestMapping:
    def test_round_trip(self) -> None:
        saved = stored(signed_up())
        uow = new_uow()
        with uow:
            loaded = uow.accounts.find(saved.id)
            assert loaded is not None
            assert (loaded.owner_id, loaded.email, loaded.status, loaded.language) == (
                saved.owner_id,
                Email("maria@example.com"),
                AccountStatus.UNCONFIRMED,
                Language.ENGLISH,
            )
            assert loaded.password_hash == PASSWORD_HASH
            assert loaded.owner_registered is False

    def test_the_row_serves_djangos_login(self) -> None:
        account = stored(signed_up())
        row = row_of(account)
        assert (row.username, row.email) == ("maria@example.com", "maria@example.com")
        assert row.is_active is False
        assert row.is_staff is False

    def test_an_invited_account_cannot_log_in_with_any_password(self) -> None:
        invited = stored(
            OwnerAccount.invite(
                account_id=new_id(), owner_id=new_id(), email=Email("n@example.com")
            )
        )
        row = row_of(invited)
        assert not row.has_usable_password()
        uow = new_uow()
        with uow:
            loaded = uow.accounts.find(invited.id)
            assert loaded is not None
            assert loaded.password_hash is None

    def test_finds_by_email_and_by_owner_but_never_a_staff_user(self) -> None:
        User.objects.create_user(username="admin", email="maria@example.com", password="x")
        account = stored(signed_up())
        uow = new_uow()
        with uow:
            assert uow.accounts.find_by_email(Email("MARIA@example.com")) is not None
            assert uow.accounts.find_by_owner(account.owner_id) is not None
            assert uow.accounts.find_by_owner(new_id()) is None
            assert uow.accounts.find(new_id()) is None

    def test_model_choices_match_the_domain(self) -> None:
        assert {choice.value for choice in AccountStatusChoices} == {s.value for s in AccountStatus}


class TestLogin:
    def test_a_confirmed_owner_logs_in_with_email_and_password(self) -> None:
        account = stored(signed_up(password_hash=make_password("correct horse")))
        assert authenticate(username="maria@example.com", password="correct horse") is None
        uow = new_uow()
        with uow:
            loaded = uow.accounts.find(account.id)
            assert loaded is not None
            loaded.confirm_email()
            uow.commit()
        user = authenticate(username="maria@example.com", password="correct horse")
        assert user is not None
        assert user.pk == row_of(account).pk


class TestOptimisticConcurrency:
    def test_a_change_bumps_the_version_and_a_read_writes_nothing(self) -> None:
        account = stored(signed_up())
        uow = new_uow()
        with uow:
            uow.accounts.find(account.id)
            uow.commit()
        assert row_of(account).version == 0
        with uow:
            loaded = uow.accounts.find(account.id)
            assert loaded is not None
            loaded.confirm_email()
            uow.commit()
        assert row_of(account).version == 1

    def test_a_concurrent_change_is_refused(self) -> None:
        account = stored(signed_up())
        first, second = new_uow(), new_uow()
        with first:
            mine = first.accounts.find(account.id)
            assert mine is not None
            User.objects.filter(account_id=account.id).update(version=5)  # someone else saved
            mine.confirm_email()
            with pytest.raises(ConcurrencyError):
                first.commit()
        with second:
            assert second.accounts.find(account.id) is not None


class TestUniqueEmail:
    def test_an_email_used_by_another_login_is_refused(self) -> None:
        User.objects.create_user(username="maria@example.com", password="x")  # a staff login
        uow = new_uow()
        with uow, pytest.raises(EmailAlreadyInUse):
            uow.accounts.add(signed_up())
