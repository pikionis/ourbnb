"""Read side of the identity context, for the account pages (CQRS-lite).

Pages check a link before they show its form, so an expired link says so at once instead of
after the owner typed a new password. Nothing here changes an account.
"""

from uuid import UUID

from django.contrib.auth.hashers import check_password, make_password

from kospm.identity.adapters.repository import account_to_domain
from kospm.identity.domain.account import AccountLink, AccountStatus, OwnerAccount
from kospm.identity.models import User
from kospm.identity.service_layer.ports import AccountTokens


def linked_account(
    account_id: UUID, link: AccountLink, token: str, tokens: AccountTokens
) -> OwnerAccount | None:
    """The account a link names, if the link is still valid for it."""
    row = User.objects.filter(account_id=account_id).first()
    if row is None:
        return None
    account = account_to_domain(row)
    return account if tokens.check(account, link, token) else None


def is_unconfirmed_login(email: str, password: str) -> bool:
    """True if these are the right credentials of an account whose email is not confirmed yet.

    Only someone who knows the password learns that the account exists. The hash is only
    checked, never upgraded or saved here. Without such an account a password is hashed all
    the same, so the time of the answer does not tell either (as Django's login backend does).
    """
    row = User.objects.filter(
        username=email, account_id__isnull=False, account_status=AccountStatus.UNCONFIRMED
    ).first()
    if row is None:
        make_password(password)
        return False
    return check_password(password, row.password)
