"""Bootstrap wires identity: settings become configuration objects, and the events of properties
become identity's own commands (ADR 0014: only bootstrap sees both contexts)."""

from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from kospm.bootstrap import (
    IDENTITY_TRANSLATIONS,
    ContextWiring,
    bootstrap,
    default_contexts,
    link_lifetimes,
    portal_throttle,
)
from kospm.identity.domain.account import AccountStatus, Email
from kospm.identity.domain.commands import InviteOwner, SignUpOwner
from kospm.identity.domain.policies import LinkLifetimes
from kospm.identity.service_layer.handlers import COMMAND_HANDLERS, EVENT_HANDLERS
from kospm.properties.domain.events import OwnerEmailChanged, OwnerRegistered
from kospm.shared.clock import FixedClock, SystemClock
from kospm.shared.domain import new_id
from kospm.shared.messagebus import MessageBus
from tests.unit.identity.fakes import (
    FakeAccountMailer,
    FakeAccountTokens,
    FakeIdentityUnitOfWork,
    FakePasswordHasher,
)

NOW = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)


def test_the_settings_become_the_link_lifetimes() -> None:
    assert link_lifetimes() == LinkLifetimes(
        confirmation=timedelta(hours=72),
        invitation=timedelta(hours=72),
        password_reset=timedelta(hours=24),
    )


@pytest.mark.parametrize(
    "setting",
    [{"ACCOUNT_PASSWORD_RESET_LINK_HOURS": 0}, {"ACCOUNT_INVITATION_LINK_HOURS": "soon"}],
)
def test_invalid_link_lifetimes_fail_at_startup(setting: dict[str, object]) -> None:
    with override_settings(**setting), pytest.raises(ImproperlyConfigured):
        link_lifetimes()


@override_settings(PORTAL_THROTTLE_MAX_ATTEMPTS=0)
def test_an_invalid_throttle_fails_at_startup() -> None:
    with pytest.raises(ImproperlyConfigured):
        portal_throttle("login")


def test_the_production_bus_handles_the_identity_commands() -> None:
    contexts = {context.name: context for context in default_contexts(SystemClock())}
    assert SignUpOwner in contexts["identity"].command_handlers
    assert {OwnerEmailChanged, OwnerRegistered} <= set(contexts["identity"].event_handlers)


class TestTranslations:
    """Events of properties, handled by identity through the bus (as in production)."""

    @pytest.fixture
    def uow(self) -> FakeIdentityUnitOfWork:
        return FakeIdentityUnitOfWork()

    @pytest.fixture
    def bus(self, uow: FakeIdentityUnitOfWork) -> MessageBus:
        return bootstrap(
            clock=FixedClock(NOW),
            contexts=[
                ContextWiring(
                    name="identity",
                    uow=uow,
                    command_handlers=COMMAND_HANDLERS,
                    event_handlers={**EVENT_HANDLERS, **IDENTITY_TRANSLATIONS},
                    dependencies={
                        "password_hasher": FakePasswordHasher(),
                        "account_tokens": FakeAccountTokens(),
                        "account_mailer": FakeAccountMailer(),
                    },
                )
            ],
        )

    def test_a_corrected_email_reaches_an_invitation_not_used_yet(
        self, bus: MessageBus, uow: FakeIdentityUnitOfWork
    ) -> None:
        owner_id = new_id()
        bus.handle(InviteOwner(account_id=new_id(), owner_id=owner_id, email="typo@example.com"))
        bus.handle(OwnerEmailChanged(owner_id=owner_id, email="maria@example.com"))
        (account,) = uow.accounts.all()
        assert (account.email, account.status) == (
            Email("maria@example.com"),
            AccountStatus.INVITED,
        )

    def test_a_registration_is_noted_on_the_account_that_reserved_the_owner(
        self, bus: MessageBus, uow: FakeIdentityUnitOfWork
    ) -> None:
        owner_id = new_id()
        bus.handle(
            SignUpOwner(
                account_id=new_id(),
                owner_id=owner_id,
                email="maria@example.com",
                password="correct horse",
                language="el",
            )
        )
        bus.handle(OwnerRegistered(owner_id=owner_id))
        assert uow.accounts.all()[0].owner_registered is True
