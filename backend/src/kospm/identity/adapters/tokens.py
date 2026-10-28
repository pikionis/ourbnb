"""Tokens of the links emailed to owner accounts (AccountTokens port).

Built like Django's password-reset tokens: the issue time and an HMAC (keyed with SECRET_KEY) of
the account's state at that time. Nothing is stored. A token stops working when the account's
state changes (the email is confirmed, the password or the email changes), so a link works once,
and when it is older than its lifetime (LinkLifetimes, timed by the injected Clock).
"""

from django.conf import settings
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.http import base36_to_int, int_to_base36

from kospm.identity.domain.account import AccountLink, OwnerAccount
from kospm.identity.domain.policies import LinkLifetimes
from kospm.identity.service_layer.ports import AccountTokens
from kospm.shared.clock import Clock

# base36 of a Unix time stays far below this length; longer input is refused before parsing.
_MAX_TIMESTAMP_LENGTH = 13


class SignedAccountTokens(AccountTokens):
    def __init__(
        self, *, clock: Clock, lifetimes: LinkLifetimes, secret: str | None = None
    ) -> None:
        self._clock = clock
        self._lifetimes = lifetimes
        self._secret = secret

    def make(self, account: OwnerAccount, link: AccountLink) -> str:
        issued = self._seconds_now()
        return f"{int_to_base36(issued)}-{self._digest(account, link, issued)}"

    def check(self, account: OwnerAccount, link: AccountLink, token: str) -> bool:
        stamp, _, digest = token.partition("-")
        if not stamp or not digest or len(stamp) > _MAX_TIMESTAMP_LENGTH:
            return False
        try:
            issued = base36_to_int(stamp)
        except ValueError:
            return False
        if not constant_time_compare(digest, self._digest(account, link, issued)):
            return False
        age = self._seconds_now() - issued
        return 0 <= age <= self._lifetimes.of(link).total_seconds()

    def _digest(self, account: OwnerAccount, link: AccountLink, issued: int) -> str:
        state = "|".join(
            (
                str(account.id),
                account.status.value,
                account.email.value,
                str(account.owner_id),
                account.password_hash or "",
                str(issued),
            )
        )
        secret = self._secret if self._secret is not None else settings.SECRET_KEY
        mac = salted_hmac(f"kospm.identity.{link.value}", state, secret=secret, algorithm="sha256")
        return mac.hexdigest()[::2]  # half the digits, as Django does: links stay short

    def _seconds_now(self) -> int:
        return int(self._clock.now().timestamp())
