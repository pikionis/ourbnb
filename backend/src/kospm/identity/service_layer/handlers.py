"""Command handlers of the identity context (Cosmic Python ch. 10; DOMAIN §5, owner portal).

Each handler runs one Unit of Work and changes one account. Emails are enqueued in the outbox in
that unit, so one leaves only if the change it reports was committed (ADR 0005). Dependencies
besides `uow` and `clock` are injected by bootstrap by name: `password_hasher`, `account_tokens`
and `account_mailer`.

No answer tells whether an address has an account: a sign-up, a new confirmation or a password
reset for an address with an account mails that address what it needs, and for an unknown
address sends nothing; the page says the same in every case.
"""

from collections.abc import Callable
from uuid import UUID

from kospm.identity.domain.account import (
    AccountLink,
    AccountStatus,
    Email,
    Language,
    OwnerAccount,
)
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
from kospm.identity.domain.errors import EmailAlreadyInUse, InvalidLink, InvalidValue
from kospm.identity.service_layer.ports import AccountMailer, AccountTokens, PasswordHasher
from kospm.identity.service_layer.unit_of_work import IdentityUnitOfWork
from kospm.shared.domain import Command, DomainEvent
from kospm.shared.outbox.domain import OutboxMessage

# --- sign-up and confirmation -------------------------------------------------------------------


def sign_up_owner(
    cmd: SignUpOwner,
    uow: IdentityUnitOfWork,
    password_hasher: PasswordHasher,
    account_tokens: AccountTokens,
    account_mailer: AccountMailer,
) -> None:
    email, language = Email(cmd.email), _language(cmd.language)
    # Hashed before the unit, and also when the address has an account: the slow hash stays out
    # of the transaction, and both answers take as long (no account discovery by timing).
    password_hash = password_hasher.hash(cmd.password)
    with uow:
        holder = uow.accounts.find_by_email(email)
        if holder is None:
            account = OwnerAccount.sign_up(
                account_id=cmd.account_id,
                owner_id=cmd.owner_id,
                email=email,
                password_hash=password_hash,
                language=language,
            )
            uow.accounts.add(account)
            message = account_mailer.confirmation(
                account, account_tokens.make(account, AccountLink.CONFIRMATION)
            )
        else:
            message = _reminder(holder, account_tokens, account_mailer)
        uow.outbox.enqueue(message)
        uow.commit()


def resend_confirmation(
    cmd: ResendConfirmation,
    uow: IdentityUnitOfWork,
    account_tokens: AccountTokens,
    account_mailer: AccountMailer,
) -> None:
    email = Email(cmd.email)
    with uow:
        account = uow.accounts.find_by_email(email)
        if account is not None:
            uow.outbox.enqueue(_reminder(account, account_tokens, account_mailer))
        uow.commit()


def confirm_email(
    cmd: ConfirmEmail, uow: IdentityUnitOfWork, account_tokens: AccountTokens
) -> None:
    with uow:
        account = _linked_account(
            uow, account_tokens, cmd.account_id, AccountLink.CONFIRMATION, cmd.token
        )
        account.confirm_email()
        uow.commit()


# --- passwords ----------------------------------------------------------------------------------


def request_password_reset(
    cmd: RequestPasswordReset,
    uow: IdentityUnitOfWork,
    account_tokens: AccountTokens,
    account_mailer: AccountMailer,
) -> None:
    email = Email(cmd.email)
    with uow:
        account = uow.accounts.find_by_email(email)
        if account is not None:
            uow.outbox.enqueue(
                _access_link(
                    account,
                    account_tokens,
                    account_mailer,
                    when_active=lambda active: account_mailer.password_reset(
                        active, account_tokens.make(active, AccountLink.PASSWORD_RESET)
                    ),
                )
            )
        uow.commit()


def reset_password(
    cmd: ResetPassword,
    uow: IdentityUnitOfWork,
    password_hasher: PasswordHasher,
    account_tokens: AccountTokens,
) -> None:
    language = _language(cmd.language)
    password_hash = password_hasher.hash(cmd.password)
    with uow:
        account = _linked_account(
            uow, account_tokens, cmd.account_id, AccountLink.PASSWORD_RESET, cmd.token
        )
        account.set_password(password_hash, language=language)
        uow.commit()


# --- invitations --------------------------------------------------------------------------------


def invite_owner(
    cmd: InviteOwner,
    uow: IdentityUnitOfWork,
    account_tokens: AccountTokens,
    account_mailer: AccountMailer,
) -> None:
    """The admin invited a registered owner to the portal (DOMAIN §5, owner portal).

    The owner's own account gets a fresh invitation (or, once active, a reminder to log in). An
    owner without an account gets one, unless their email is already used by an account whose
    own owner never registered (a sign-up that stopped at "contact us"): that account is
    connected to them and waits for the invitation, without the password someone chose for it.
    An account is never moved away from a registered owner.
    """
    email = Email(cmd.email)
    with uow:
        account = uow.accounts.find_by_owner(cmd.owner_id)
        if account is None:
            account = uow.accounts.find_by_email(email)
            if account is None:
                account = OwnerAccount.invite(
                    account_id=cmd.account_id, owner_id=cmd.owner_id, email=email
                )
                uow.accounts.add(account)
            else:
                account.connect_to_owner(cmd.owner_id)
        elif account.email != email and not account.can_log_in:
            _move_to_address(uow, account, email)
        uow.outbox.enqueue(
            _access_link(
                account, account_tokens, account_mailer, when_active=account_mailer.login_reminder
            )
        )
        uow.commit()


def follow_owner_email(cmd: FollowOwnerEmail, uow: IdentityUnitOfWork) -> None:
    """The admin corrected an owner's email: an account not in use yet follows it, so the links
    already sent to the old address stop working (they are bound to the account's email)."""
    email = Email(cmd.email)
    with uow:
        account = uow.accounts.find_by_owner(cmd.owner_id)
        if account is not None and not account.can_log_in and account.email != email:
            _move_to_address(uow, account, email)
        uow.commit()


def accept_invitation(
    cmd: AcceptInvitation,
    uow: IdentityUnitOfWork,
    password_hasher: PasswordHasher,
    account_tokens: AccountTokens,
) -> None:
    language = _language(cmd.language)
    password_hash = password_hasher.hash(cmd.password)
    with uow:
        account = _linked_account(
            uow, account_tokens, cmd.account_id, AccountLink.INVITATION, cmd.token
        )
        account.set_password(password_hash, language=language)
        uow.commit()


def note_owner_registered(cmd: NoteOwnerRegistered, uow: IdentityUnitOfWork) -> None:
    with uow:
        account = uow.accounts.find_by_owner(cmd.owner_id)
        if account is not None:
            account.note_owner_registered()
        uow.commit()


# --- helpers ------------------------------------------------------------------------------------


def _linked_account(
    uow: IdentityUnitOfWork,
    tokens: AccountTokens,
    account_id: UUID,
    link: AccountLink,
    token: str,
) -> OwnerAccount:
    """The account a link names, if the link is still valid for it."""
    account = uow.accounts.find(account_id)
    if account is None or not tokens.check(account, link, token):
        raise InvalidLink(f"the {link} link is unknown, expired or used")
    return account


def _move_to_address(uow: IdentityUnitOfWork, account: OwnerAccount, email: Email) -> None:
    if uow.accounts.find_by_email(email) is not None:
        raise EmailAlreadyInUse(f"another account logs in with the new address of {account.id}")
    account.change_email(email)


def _reminder(account: OwnerAccount, tokens: AccountTokens, mailer: AccountMailer) -> OutboxMessage:
    """What an account needs when its address signs up again."""
    return _access_link(account, tokens, mailer, when_active=mailer.already_registered)


def _access_link(
    account: OwnerAccount,
    tokens: AccountTokens,
    mailer: AccountMailer,
    *,
    when_active: Callable[[OwnerAccount], OutboxMessage],
) -> OutboxMessage:
    """The email that lets this account in: confirm the address, accept the invitation, or (for
    an active account) `when_active`."""
    match account.status:
        case AccountStatus.UNCONFIRMED:
            return mailer.confirmation(account, tokens.make(account, AccountLink.CONFIRMATION))
        case AccountStatus.INVITED:
            return mailer.invitation(account, tokens.make(account, AccountLink.INVITATION))
        case AccountStatus.ACTIVE:
            return when_active(account)


def _language(code: str) -> Language:
    try:
        return Language(code)
    except ValueError as error:
        raise InvalidValue(f"{code!r} is not a language of the portal", field="language") from error


COMMAND_HANDLERS: dict[type[Command], Callable[..., None]] = {
    SignUpOwner: sign_up_owner,
    ResendConfirmation: resend_confirmation,
    ConfirmEmail: confirm_email,
    RequestPasswordReset: request_password_reset,
    ResetPassword: reset_password,
    InviteOwner: invite_owner,
    AcceptInvitation: accept_invitation,
    NoteOwnerRegistered: note_owner_registered,
    FollowOwnerEmail: follow_owner_email,
}

EVENT_HANDLERS: dict[type[DomainEvent], list[Callable[..., None]]] = {}
