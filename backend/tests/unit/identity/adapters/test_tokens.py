"""Tokens of emailed links: they work once and expire (DOMAIN §5, owner portal)."""

from datetime import UTC, datetime, timedelta

import pytest

from kospm.identity.adapters.tokens import SignedAccountTokens
from kospm.identity.domain.account import AccountLink, Email, Language, OwnerAccount
from kospm.identity.domain.policies import LinkLifetimes
from kospm.shared.clock import FixedClock
from kospm.shared.domain import new_id

NOW = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)
LIFETIMES = LinkLifetimes(
    confirmation=timedelta(days=3), invitation=timedelta(days=3), password_reset=timedelta(days=1)
)


def account() -> OwnerAccount:
    return OwnerAccount.sign_up(
        account_id=new_id(),
        owner_id=new_id(),
        email=Email("maria@example.com"),
        password_hash="hash-1",
        language=Language.GREEK,
    )


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def tokens(clock: FixedClock) -> SignedAccountTokens:
    return SignedAccountTokens(clock=clock, lifetimes=LIFETIMES, secret="test-secret")


def test_a_fresh_token_opens_its_link(tokens: SignedAccountTokens) -> None:
    subject = account()
    token = tokens.make(subject, AccountLink.CONFIRMATION)
    assert tokens.check(subject, AccountLink.CONFIRMATION, token)


def test_a_token_opens_only_the_link_and_the_account_it_was_made_for(
    tokens: SignedAccountTokens,
) -> None:
    subject, other = account(), account()
    token = tokens.make(subject, AccountLink.CONFIRMATION)
    assert not tokens.check(subject, AccountLink.PASSWORD_RESET, token)
    assert not tokens.check(other, AccountLink.CONFIRMATION, token)


def test_a_link_works_once_because_using_it_changes_the_account(
    tokens: SignedAccountTokens,
) -> None:
    subject = account()
    confirmation = tokens.make(subject, AccountLink.CONFIRMATION)
    subject.confirm_email()
    assert not tokens.check(subject, AccountLink.CONFIRMATION, confirmation)

    reset = tokens.make(subject, AccountLink.PASSWORD_RESET)
    subject.set_password("hash-2", language=Language.GREEK)
    assert not tokens.check(subject, AccountLink.PASSWORD_RESET, reset)


def test_a_link_expires_after_its_lifetime(tokens: SignedAccountTokens, clock: FixedClock) -> None:
    subject = account()
    reset = tokens.make(subject, AccountLink.PASSWORD_RESET)
    confirmation = tokens.make(subject, AccountLink.CONFIRMATION)
    clock.advance(timedelta(days=1, seconds=1))
    assert not tokens.check(subject, AccountLink.PASSWORD_RESET, reset)
    assert tokens.check(subject, AccountLink.CONFIRMATION, confirmation)
    clock.advance(timedelta(days=2))
    assert not tokens.check(subject, AccountLink.CONFIRMATION, confirmation)


def test_a_token_signed_with_another_key_is_refused(clock: FixedClock) -> None:
    subject = account()
    forged = SignedAccountTokens(clock=clock, lifetimes=LIFETIMES, secret="other").make(
        subject, AccountLink.CONFIRMATION
    )
    real = SignedAccountTokens(clock=clock, lifetimes=LIFETIMES, secret="test-secret")
    assert not real.check(subject, AccountLink.CONFIRMATION, forged)


@pytest.mark.parametrize("token", ["", "-", "abc", "zz-", "-abc", "!!-abc", "1" * 40 + "-abc"])
def test_garbage_is_refused(tokens: SignedAccountTokens, token: str) -> None:
    assert not tokens.check(account(), AccountLink.CONFIRMATION, token)
