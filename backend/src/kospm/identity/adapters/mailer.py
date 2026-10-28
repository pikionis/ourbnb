"""The emails of owner accounts (AccountMailer port), in the account's language.

Each email is rendered when it is enqueued: the outbox message carries its `subject` and `body`,
and the email sender only delivers them (ADR 0005). Links are absolute, built on the portal's
base URL. An invitation is written in Greek and English, because the owner has not chosen a
language yet. Texts are marked for translation here, so the translation test covers them.
"""

from collections.abc import Callable, Sequence
from uuid import UUID

from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from kospm.identity.domain.account import AccountLink, Language, OwnerAccount
from kospm.identity.domain.policies import LinkLifetimes
from kospm.identity.service_layer.ports import AccountMailer
from kospm.shared.outbox.domain import OutboxChannel, OutboxMessage

# One email: its subject and its paragraphs, written in the active language when called.
type Composer = Callable[[], tuple[str, Sequence[str]]]

_LANGUAGE_SEPARATOR = "\n\n— English —\n\n"


class DjangoAccountMailer(AccountMailer):
    def __init__(self, *, base_url: str, portal_name: str, lifetimes: LinkLifetimes) -> None:
        self._base_url = base_url.rstrip("/")
        self._portal = portal_name
        self._lifetimes = lifetimes

    def confirmation(self, account: OwnerAccount, token: str) -> OutboxMessage:
        link = self._link("identity:confirm", account.id, token)
        return self._email(
            account,
            "confirmation",
            lambda: (
                _("Confirm your email address"),
                [
                    _("Hello,"),
                    _(
                        "Please confirm your email address to finish creating your account on "
                        "the %(portal)s owner portal:"
                    )
                    % {"portal": self._portal},
                    link,
                    self._expiry(AccountLink.CONFIRMATION),
                    _("If you did not create an account, you can ignore this email."),
                ],
            ),
        )

    def invitation(self, account: OwnerAccount, token: str) -> OutboxMessage:
        link = self._link("identity:invitation", account.id, token)
        return self._email(
            account,
            "invitation",
            lambda: (
                _("Invitation to the owner portal"),
                [
                    _("Hello,"),
                    _(
                        "%(portal)s invites you to its owner portal, where you complete the "
                        "details of your properties yourself. Choose your password here:"
                    )
                    % {"portal": self._portal},
                    link,
                    self._expiry(AccountLink.INVITATION),
                ],
            ),
            languages=(Language.GREEK, Language.ENGLISH),
        )

    def password_reset(self, account: OwnerAccount, token: str) -> OutboxMessage:
        link = self._link("identity:password_reset", account.id, token)
        return self._email(
            account,
            "password_reset",
            lambda: (
                _("Choose a new password"),
                [
                    _("Hello,"),
                    _(
                        "Someone, hopefully you, asked for a new password for your account on "
                        "the %(portal)s owner portal. Choose it here:"
                    )
                    % {"portal": self._portal},
                    link,
                    self._expiry(AccountLink.PASSWORD_RESET),
                    _(
                        "If you did not ask for it, ignore this email: your password stays as "
                        "it is."
                    ),
                ],
            ),
        )

    def already_registered(self, account: OwnerAccount) -> OutboxMessage:
        login = self._base_url + reverse("identity:login")
        forgot = self._base_url + reverse("identity:password_forgot")
        return self._email(
            account,
            "already_registered",
            lambda: (
                _("You already have an account"),
                [
                    _("Hello,"),
                    _(
                        "Someone, hopefully you, tried to create an account with this email "
                        "address, but you already have one on the %(portal)s owner portal."
                    )
                    % {"portal": self._portal},
                    _("Log in: %(url)s") % {"url": login},
                    _("Forgot your password? %(url)s") % {"url": forgot},
                    _("If it was not you, ignore this email."),
                ],
            ),
        )

    def login_reminder(self, account: OwnerAccount) -> OutboxMessage:
        login = self._base_url + reverse("identity:login")
        forgot = self._base_url + reverse("identity:password_forgot")
        return self._email(
            account,
            "login_reminder",
            lambda: (
                _("Your account on the owner portal"),
                [
                    _("Hello,"),
                    _(
                        "%(portal)s invites you to its owner portal, and you already have an "
                        "account there with this email address."
                    )
                    % {"portal": self._portal},
                    _("Log in: %(url)s") % {"url": login},
                    _("Forgot your password? %(url)s") % {"url": forgot},
                ],
            ),
        )

    # --- helpers ----------------------------------------------------------------------------

    def _email(
        self,
        account: OwnerAccount,
        kind: str,
        compose: Composer,
        *,
        languages: Sequence[Language] | None = None,
    ) -> OutboxMessage:
        subjects, bodies = [], []
        for language in languages or (account.language,):
            with translation.override(language.value):
                subject, paragraphs = compose()
            subjects.append(subject)
            bodies.append("\n\n".join(paragraphs))
        return OutboxMessage(
            channel=OutboxChannel.EMAIL,
            recipient=account.email.value,
            template=f"identity.{kind}",
            payload={
                "subject": " / ".join(subjects),
                "body": _LANGUAGE_SEPARATOR.join(bodies) + "\n",
            },
        )

    def _link(self, view: str, account_id: UUID, token: str) -> str:
        return self._base_url + reverse(view, kwargs={"account_id": account_id, "token": token})

    def _expiry(self, link: AccountLink) -> str:
        hours = int(self._lifetimes.of(link).total_seconds() // 3600)
        return ngettext(
            "The link works once and expires in %(hours)d hour.",
            "The link works once and expires in %(hours)d hours.",
            hours,
        ) % {"hours": hours}
