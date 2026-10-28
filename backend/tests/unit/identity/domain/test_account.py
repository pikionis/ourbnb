"""The OwnerAccount aggregate: an owner's login to the portal (DOMAIN §5, owner portal)."""

from uuid import UUID

import pytest

from kospm.identity.domain.account import AccountStatus, Email, Language, OwnerAccount
from kospm.identity.domain.errors import (
    AccountLinkedToAnotherOwner,
    InvalidAccountState,
    InvalidValue,
)
from kospm.identity.domain.events import OwnerAccountActivated, OwnerSignedUp
from kospm.shared.domain import new_id


def status_of(account: OwnerAccount) -> AccountStatus:
    """Read the status afresh (mypy keeps narrowing an attribute across method calls)."""
    return account.status


def signed_up(*, owner_id: UUID | None = None, email: str = "maria@example.com") -> OwnerAccount:
    account = OwnerAccount.sign_up(
        account_id=new_id(),
        owner_id=owner_id or new_id(),
        email=Email(email),
        password_hash="hash-1",
        language=Language.GREEK,
    )
    account.events.clear()
    return account


def invited(*, owner_id: UUID | None = None, email: str = "maria@example.com") -> OwnerAccount:
    return OwnerAccount.invite(
        account_id=new_id(), owner_id=owner_id or new_id(), email=Email(email)
    )


class TestEmail:
    def test_is_trimmed_and_lower_cased(self) -> None:
        assert Email("  Maria@Example.COM ").value == "maria@example.com"

    @pytest.mark.parametrize("text", ["", "maria", "maria@", "maria@example", "a b@example.com"])
    def test_refuses_what_is_not_an_address(self, text: str) -> None:
        with pytest.raises(InvalidValue) as refused:
            Email(text)
        assert refused.value.field == "email"

    def test_fits_the_login_name(self) -> None:
        local = "m" * 138
        assert Email(f"{local}@example.com").value  # 150 characters
        with pytest.raises(InvalidValue):
            Email(f"{local}x@example.com")

    def test_never_puts_the_address_in_its_error(self) -> None:
        # Errors reach logs; an address is personal data.
        with pytest.raises(InvalidValue) as refused:
            Email("maria at example")
        assert "maria" not in str(refused.value)


class TestSignUp:
    def test_starts_unconfirmed_and_reserves_its_owner_id(self) -> None:
        account_id, owner_id = new_id(), new_id()
        account = OwnerAccount.sign_up(
            account_id=account_id,
            owner_id=owner_id,
            email=Email("maria@example.com"),
            password_hash="hash-1",
            language=Language.ENGLISH,
        )
        assert account.status is AccountStatus.UNCONFIRMED
        assert account.owner_id == owner_id
        assert account.owner_registered is False
        assert account.language is Language.ENGLISH
        assert account.can_log_in is False
        assert account.events == [OwnerSignedUp(account_id=account_id, owner_id=owner_id)]

    def test_the_password_hash_never_appears_in_its_repr(self) -> None:
        assert "hash-1" not in repr(signed_up())


class TestConfirmEmail:
    def test_activates_the_account(self) -> None:
        account = signed_up()
        account.confirm_email()
        assert account.status is AccountStatus.ACTIVE
        assert account.can_log_in is True
        assert account.events == [
            OwnerAccountActivated(account_id=account.id, owner_id=account.owner_id)
        ]

    def test_works_once(self) -> None:
        account = signed_up()
        account.confirm_email()
        with pytest.raises(InvalidAccountState):
            account.confirm_email()

    def test_an_invited_account_chooses_a_password_instead(self) -> None:
        with pytest.raises(InvalidAccountState):
            invited().confirm_email()


class TestInvitation:
    def test_an_invited_account_has_no_password_and_a_registered_owner(self) -> None:
        owner_id = new_id()
        account = invited(owner_id=owner_id)
        assert account.status is AccountStatus.INVITED
        assert account.password_hash is None
        assert account.owner_id == owner_id
        assert account.owner_registered is True
        assert account.can_log_in is False
        assert account.events == []

    def test_accepting_it_sets_the_password_and_activates_the_account(self) -> None:
        account = invited()
        account.set_password("hash-2", language=Language.ENGLISH)
        assert account.status is AccountStatus.ACTIVE
        assert account.password_hash == "hash-2"
        assert account.language is Language.ENGLISH
        assert account.events == [
            OwnerAccountActivated(account_id=account.id, owner_id=account.owner_id)
        ]

    def test_an_invited_account_follows_the_owners_new_email(self) -> None:
        account = invited(email="old@example.com")
        account.change_email(Email("new@example.com"))
        assert account.email == Email("new@example.com")

    def test_the_email_of_an_account_in_use_changes_only_through_the_ike(self) -> None:
        account = invited()
        account.set_password("hash-2", language=Language.GREEK)
        with pytest.raises(InvalidAccountState):
            account.change_email(Email("new@example.com"))


class TestPasswordReset:
    def test_replaces_the_password_of_an_active_account(self) -> None:
        account = signed_up()
        account.confirm_email()
        account.events.clear()
        account.set_password("hash-2", language=Language.GREEK)
        assert account.password_hash == "hash-2"
        assert account.events == []

    def test_also_confirms_an_unconfirmed_account_because_the_link_came_by_email(self) -> None:
        account = signed_up()
        account.set_password("hash-2", language=Language.GREEK)
        assert status_of(account) is AccountStatus.ACTIVE


class TestOwnerLink:
    def test_notes_when_its_owner_registers(self) -> None:
        account = signed_up()
        account.note_owner_registered()
        assert account.owner_registered is True

    def test_an_invitation_connects_an_account_whose_own_owner_never_registered(self) -> None:
        account = signed_up()
        invited_owner = new_id()
        account.connect_to_owner(invited_owner)
        assert account.owner_id == invited_owner
        assert account.owner_registered is True

    @pytest.mark.parametrize("confirmed", [False, True])
    def test_connecting_drops_the_password_so_only_the_mailbox_chooses_the_next_one(
        self, confirmed: bool
    ) -> None:
        # Whoever chose this password signed up with the owner's address: maybe not the owner
        # (a mail scanner may even have opened the confirmation link). Not trusted with the
        # registered owner's data: the invitation link, sent to that address, sets a new one.
        account = signed_up()
        if confirmed:
            account.confirm_email()
        account.connect_to_owner(new_id())
        assert account.password_hash is None
        assert account.status is AccountStatus.INVITED
        assert account.can_log_in is False

    def test_an_account_whose_owner_registered_is_never_moved_to_another_owner(self) -> None:
        account = signed_up()
        account.note_owner_registered()
        with pytest.raises(AccountLinkedToAnotherOwner):
            account.connect_to_owner(new_id())

    def test_connecting_it_to_its_own_owner_changes_nothing(self) -> None:
        owner_id = new_id()
        account = signed_up(owner_id=owner_id)
        account.note_owner_registered()
        account.connect_to_owner(owner_id)
        assert account.owner_id == owner_id
