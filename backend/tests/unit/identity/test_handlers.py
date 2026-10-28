"""Handlers of the identity context, driven through the real bus with fakes (Cosmic Python ch. 5).

Each test sends the commands the owner portal (or an invitation from the admin) sends and checks
the stored accounts and the emails waiting in the outbox. Emails are what the worker delivers
after the unit commits (ADR 0005); they never reveal whether an address has an account.
"""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from kospm.bootstrap import ContextWiring, bootstrap
from kospm.identity.domain.account import AccountLink, AccountStatus, Email, OwnerAccount
from kospm.identity.domain.commands import (
    AcceptInvitation,
    ConfirmEmail,
    FollowOwnerEmail,
    InviteOwner,
    NoteOwnerRegistered,
    RequestPasswordReset,
    ResendConfirmation,
    ResetPassword,
    SignUpOwner,
)
from kospm.identity.domain.errors import (
    AccountLinkedToAnotherOwner,
    EmailAlreadyInUse,
    InvalidLink,
    InvalidValue,
)
from kospm.identity.domain.events import OwnerAccountActivated
from kospm.identity.service_layer.handlers import COMMAND_HANDLERS, EVENT_HANDLERS
from kospm.shared.clock import FixedClock
from kospm.shared.domain import new_id
from kospm.shared.messagebus import MessageBus
from kospm.shared.outbox.domain import OutboxChannel, OutboxMessage
from tests.unit.identity.fakes import (
    FakeAccountMailer,
    FakeAccountTokens,
    FakeIdentityUnitOfWork,
    FakePasswordHasher,
)

NOW = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)
MARIA = "maria@example.com"


class Harness:
    """A bus wired with the identity handlers, a fake Unit of Work and fake adapters."""

    def __init__(self) -> None:
        self.uow = FakeIdentityUnitOfWork()
        self.tokens = FakeAccountTokens()
        self.activated: list[OwnerAccountActivated] = []
        self.bus: MessageBus = bootstrap(
            clock=FixedClock(NOW),
            contexts=[
                ContextWiring(
                    name="identity",
                    uow=self.uow,
                    command_handlers=COMMAND_HANDLERS,
                    event_handlers={**EVENT_HANDLERS, OwnerAccountActivated: [self._record]},
                    dependencies={
                        "password_hasher": FakePasswordHasher(),
                        "account_tokens": self.tokens,
                        "account_mailer": FakeAccountMailer(),
                    },
                )
            ],
        )

    def _record(self, event: OwnerAccountActivated) -> None:
        self.activated.append(event)

    @property
    def emails(self) -> list[OutboxMessage]:
        return self.uow.outbox.sent

    def last_email(self) -> OutboxMessage:
        message = self.emails[-1]
        assert message.channel is OutboxChannel.EMAIL
        return message

    def account(self, email: str = MARIA) -> OwnerAccount:
        (found,) = [account for account in self.uow.accounts.all() if account.email.value == email]
        return found

    def sign_up(self, email: str = MARIA, *, password: str = "correct horse") -> UUID:
        account_id = new_id()
        self.bus.handle(
            SignUpOwner(
                account_id=account_id,
                owner_id=new_id(),
                email=email,
                password=password,
                language="el",
            )
        )
        return account_id

    def token_in(self, message: OutboxMessage) -> str:
        token = message.payload["token"]
        assert isinstance(token, str)
        return token

    def confirm(self, email: str = MARIA) -> OwnerAccount:
        account = self.account(email)
        self.bus.handle(ConfirmEmail(account_id=account.id, token=self.token_in(self.last_email())))
        return account

    def invite(self, owner_id: UUID, email: str = MARIA) -> None:
        self.bus.handle(InviteOwner(account_id=new_id(), owner_id=owner_id, email=email))


@pytest.fixture
def harness() -> Harness:
    return Harness()


def kinds(messages: list[OutboxMessage]) -> list[str]:
    return [message.template for message in messages]


class TestSignUp:
    def test_creates_an_unconfirmed_account_and_emails_the_confirmation_link(
        self, harness: Harness
    ) -> None:
        account_id = harness.sign_up(" Maria@Example.com ")
        account = harness.account()
        assert account.id == account_id
        assert account.status is AccountStatus.UNCONFIRMED
        assert account.password_hash == "hashed:correct horse"
        email = harness.last_email()
        assert (email.recipient, email.template) == (MARIA, "identity.confirmation")
        assert harness.tokens.check(account, AccountLink.CONFIRMATION, harness.token_in(email))

    def test_refuses_a_malformed_email_and_stores_nothing(self, harness: Harness) -> None:
        with pytest.raises(InvalidValue):
            harness.sign_up("maria-at-example.com")
        assert harness.uow.accounts.all() == []
        assert harness.emails == []

    def test_an_address_that_has_an_account_gets_a_reminder_and_no_second_account(
        self, harness: Harness
    ) -> None:
        harness.sign_up()
        harness.sign_up()
        assert len(harness.uow.accounts.all()) == 1
        assert kinds(harness.emails) == ["identity.confirmation", "identity.confirmation"]

    def test_an_active_account_is_told_it_exists_instead(self, harness: Harness) -> None:
        harness.sign_up()
        harness.confirm()
        harness.sign_up()
        assert harness.last_email().template == "identity.already_registered"

    def test_an_invited_owner_gets_the_invitation_again(self, harness: Harness) -> None:
        harness.invite(new_id())
        harness.sign_up()
        assert kinds(harness.emails) == ["identity.invitation", "identity.invitation"]


class TestConfirmation:
    def test_the_link_activates_the_account(self, harness: Harness) -> None:
        harness.sign_up()
        account = harness.confirm()
        assert account.status is AccountStatus.ACTIVE
        assert harness.activated == [
            OwnerAccountActivated(account_id=account.id, owner_id=account.owner_id)
        ]

    def test_the_link_works_once(self, harness: Harness) -> None:
        harness.sign_up()
        harness.confirm()
        with pytest.raises(InvalidLink):
            harness.confirm()

    def test_an_expired_link_is_refused(self, harness: Harness) -> None:
        harness.sign_up()
        harness.tokens.expire()
        with pytest.raises(InvalidLink):
            harness.confirm()
        assert harness.account().status is AccountStatus.UNCONFIRMED

    def test_a_link_for_an_unknown_account_is_refused(self, harness: Harness) -> None:
        with pytest.raises(InvalidLink):
            harness.bus.handle(ConfirmEmail(account_id=new_id(), token="anything"))

    def test_resending_mails_a_fresh_link(self, harness: Harness) -> None:
        harness.sign_up()
        harness.bus.handle(ResendConfirmation(email=MARIA))
        assert kinds(harness.emails) == ["identity.confirmation", "identity.confirmation"]

    def test_resending_for_an_unknown_address_sends_nothing_and_says_nothing(
        self, harness: Harness
    ) -> None:
        harness.bus.handle(ResendConfirmation(email="nobody@example.com"))
        assert harness.emails == []


class TestPasswordReset:
    def active_account(self, harness: Harness) -> OwnerAccount:
        harness.sign_up()
        return harness.confirm()

    def test_an_active_account_gets_a_reset_link(self, harness: Harness) -> None:
        self.active_account(harness)
        harness.bus.handle(RequestPasswordReset(email=MARIA))
        assert harness.last_email().template == "identity.password_reset"

    def test_an_unknown_address_gets_nothing(self, harness: Harness) -> None:
        harness.bus.handle(RequestPasswordReset(email="nobody@example.com"))
        assert harness.emails == []

    def test_an_unconfirmed_account_gets_its_confirmation_link_again(
        self, harness: Harness
    ) -> None:
        harness.sign_up()
        harness.bus.handle(RequestPasswordReset(email=MARIA))
        assert kinds(harness.emails) == ["identity.confirmation", "identity.confirmation"]

    def test_the_link_sets_a_new_password_once(self, harness: Harness) -> None:
        account = self.active_account(harness)
        harness.bus.handle(RequestPasswordReset(email=MARIA))
        token = harness.token_in(harness.last_email())
        reset = ResetPassword(account_id=account.id, token=token, password="new one", language="en")
        harness.bus.handle(reset)
        assert account.password_hash == "hashed:new one"
        with pytest.raises(InvalidLink):
            harness.bus.handle(reset)

    def test_the_password_never_appears_in_a_commands_repr(self) -> None:
        command = ResetPassword(
            account_id=new_id(), token="t0k3n", password="s3cret", language="el"
        )
        assert "s3cret" not in repr(command)
        assert "t0k3n" not in repr(command)
        sign_up = SignUpOwner(
            account_id=new_id(), owner_id=new_id(), email=MARIA, password="s3cret", language="el"
        )
        assert "s3cret" not in repr(sign_up)


class TestInvitation:
    def test_creates_an_invited_account_for_the_owner_and_emails_the_link(
        self, harness: Harness
    ) -> None:
        owner_id = new_id()
        harness.invite(owner_id)
        account = harness.account()
        assert account.status is AccountStatus.INVITED
        assert account.owner_id == owner_id
        assert harness.last_email().template == "identity.invitation"

    def test_accepting_it_sets_the_password_and_activates_the_account(
        self, harness: Harness
    ) -> None:
        harness.invite(new_id())
        account = harness.account()
        token = harness.token_in(harness.last_email())
        harness.bus.handle(
            AcceptInvitation(account_id=account.id, token=token, password="mine", language="en")
        )
        assert account.status is AccountStatus.ACTIVE
        assert account.password_hash == "hashed:mine"
        assert account.language.value == "en"
        assert len(harness.activated) == 1

    def test_inviting_again_sends_a_new_link_to_the_same_account(self, harness: Harness) -> None:
        owner_id = new_id()
        harness.invite(owner_id)
        harness.invite(owner_id)
        assert len(harness.uow.accounts.all()) == 1
        assert kinds(harness.emails) == ["identity.invitation", "identity.invitation"]

    def test_an_owner_whose_account_is_active_is_told_to_log_in(self, harness: Harness) -> None:
        owner_id = new_id()
        harness.invite(owner_id)
        account = harness.account()
        harness.bus.handle(
            AcceptInvitation(
                account_id=account.id,
                token=harness.token_in(harness.last_email()),
                password="mine",
                language="el",
            )
        )
        harness.invite(owner_id)
        assert harness.last_email().template == "identity.login_reminder"

    def test_an_invited_account_follows_the_owners_new_email(self, harness: Harness) -> None:
        owner_id = new_id()
        harness.invite(owner_id, "old@example.com")
        harness.invite(owner_id, "new@example.com")
        assert harness.account("new@example.com").owner_id == owner_id
        assert harness.last_email().recipient == "new@example.com"

    def test_the_new_email_must_not_belong_to_another_account(self, harness: Harness) -> None:
        owner_id = new_id()
        harness.invite(owner_id, "old@example.com")
        harness.invite(new_id(), "taken@example.com")
        with pytest.raises(EmailAlreadyInUse):
            harness.invite(owner_id, "taken@example.com")

    @pytest.mark.parametrize("confirmed", [True, False])
    def test_connects_a_sign_up_that_stopped_at_contact_us(
        self, harness: Harness, confirmed: bool
    ) -> None:
        # Someone signed up with the email the admin had already registered, so their own
        # registration was refused; the admin now invites the registered owner. The account is
        # connected, but whoever chose its password must not get in with it: the invitation
        # link, sent to the address, sets a new one.
        harness.sign_up(password="chosen by whoever signed up")
        if confirmed:
            harness.confirm()
        stale_link = harness.token_in(harness.emails[0])
        registered_owner = new_id()
        harness.invite(registered_owner)
        account = harness.account()
        assert account.owner_id == registered_owner
        assert account.owner_registered is True
        assert (account.status, account.password_hash) == (AccountStatus.INVITED, None)
        assert harness.last_email().template == "identity.invitation"
        with pytest.raises(InvalidLink):
            harness.bus.handle(ConfirmEmail(account_id=account.id, token=stale_link))

    def test_never_moves_an_account_whose_own_owner_registered(self, harness: Harness) -> None:
        harness.sign_up()
        harness.bus.handle(NoteOwnerRegistered(owner_id=harness.account().owner_id))
        with pytest.raises(AccountLinkedToAnotherOwner):
            harness.invite(new_id())


class TestOwnerEmail:
    """The admin corrected an owner's email (properties' OwnerEmailChanged, via bootstrap)."""

    def test_an_invitation_not_used_yet_follows_it_and_its_old_link_dies(
        self, harness: Harness
    ) -> None:
        owner_id = new_id()
        harness.invite(owner_id, "mistyped@example.com")
        account = harness.account("mistyped@example.com")
        old_link = harness.token_in(harness.last_email())
        harness.bus.handle(FollowOwnerEmail(owner_id=owner_id, email="maria@example.com"))
        assert account.email == Email("maria@example.com")
        with pytest.raises(InvalidLink):
            harness.bus.handle(
                AcceptInvitation(
                    account_id=account.id, token=old_link, password="mine", language="el"
                )
            )

    def test_an_active_account_keeps_its_login(self, harness: Harness) -> None:
        harness.sign_up()
        account = harness.confirm()
        harness.bus.handle(FollowOwnerEmail(owner_id=account.owner_id, email="new@example.com"))
        assert account.email == Email(MARIA)

    def test_an_owner_without_an_account_changes_nothing(self, harness: Harness) -> None:
        harness.bus.handle(FollowOwnerEmail(owner_id=new_id(), email="new@example.com"))
        assert harness.uow.accounts.all() == []

    def test_an_address_of_another_account_is_refused(self, harness: Harness) -> None:
        owner_id = new_id()
        harness.invite(owner_id, "old@example.com")
        harness.sign_up("taken@example.com")
        with pytest.raises(EmailAlreadyInUse):
            harness.bus.handle(FollowOwnerEmail(owner_id=owner_id, email="taken@example.com"))


class TestOwnerRegistration:
    def test_is_noted_on_the_account_that_reserved_the_owner(self, harness: Harness) -> None:
        harness.sign_up()
        harness.bus.handle(NoteOwnerRegistered(owner_id=harness.account().owner_id))
        assert harness.account().owner_registered is True

    def test_an_owner_without_an_account_changes_nothing(self, harness: Harness) -> None:
        harness.bus.handle(NoteOwnerRegistered(owner_id=new_id()))
        assert harness.uow.committed == 1


def test_emails_are_sent_only_when_the_unit_commits(harness: Harness) -> None:
    harness.sign_up("maria@example.com")
    assert harness.uow.outbox.pending == []
    assert Email(harness.emails[0].recipient) == Email(MARIA)
