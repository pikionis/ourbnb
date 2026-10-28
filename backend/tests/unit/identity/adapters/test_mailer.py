"""The emails of owner accounts: rendered in the account's language, with absolute links."""

from datetime import timedelta

import pytest

from kospm.identity.adapters.mailer import DjangoAccountMailer
from kospm.identity.domain.account import Email, Language, OwnerAccount
from kospm.identity.domain.policies import LinkLifetimes
from kospm.shared.domain import new_id
from kospm.shared.outbox.domain import OutboxChannel, OutboxMessage

MAILER = DjangoAccountMailer(
    base_url="https://portal.example/",
    portal_name="KosPM",
    lifetimes=LinkLifetimes(password_reset=timedelta(hours=24)),
)


def account(language: Language = Language.ENGLISH) -> OwnerAccount:
    return OwnerAccount.sign_up(
        account_id=new_id(),
        owner_id=new_id(),
        email=Email("maria@example.com"),
        password_hash="hash",
        language=language,
    )


def text(message: OutboxMessage, key: str) -> str:
    value = message.payload[key]
    assert isinstance(value, str)
    return value


def test_the_confirmation_email_holds_the_absolute_link_with_the_token() -> None:
    subject = account()
    message = MAILER.confirmation(subject, "abc-123")
    assert message.channel is OutboxChannel.EMAIL
    assert (message.recipient, message.template) == ("maria@example.com", "identity.confirmation")
    assert text(message, "subject") == "Confirm your email address"
    assert f"https://portal.example/owner/verify/{subject.id}/abc-123/" in text(message, "body")
    assert "72 hours" in text(message, "body")


def test_emails_are_written_in_the_accounts_language() -> None:
    message = MAILER.password_reset(account(Language.GREEK), "abc-123")
    assert text(message, "subject") == "Επιλέξτε νέο κωδικό"
    assert "24 ώρες" in text(message, "body")


def test_an_invitation_is_written_in_greek_and_english() -> None:
    message = MAILER.invitation(account(Language.ENGLISH), "abc-123")
    assert text(message, "subject") == (
        "Πρόσκληση στην πύλη ιδιοκτητών / Invitation to the owner portal"
    )
    body = text(message, "body")
    assert body.index("Γεια σας") < body.index("Hello")
    assert body.count("/owner/invitation/") == 2


@pytest.mark.parametrize("language", list(Language))
def test_the_already_registered_email_points_to_login_and_reset(language: Language) -> None:
    body = text(MAILER.already_registered(account(language)), "body")
    assert "https://portal.example/owner/login/" in body
    assert "https://portal.example/owner/password/forgot/" in body
