"""Commands of the identity context (Cosmic Python ch. 10).

They carry plain values, as a form sends them; the handlers turn them into value objects. Ids are
chosen by the sender (`new_id()`), so a page knows the account it created. Passwords and link
tokens are kept out of repr, so they never reach logs or tracebacks.
"""

from dataclasses import dataclass, field
from uuid import UUID

from kospm.shared.domain import Command


@dataclass(frozen=True, kw_only=True)
class SignUpOwner(Command):
    """Self-registration. `owner_id` is the id the owner will register with (step 1)."""

    account_id: UUID
    owner_id: UUID
    email: str
    password: str = field(repr=False)
    language: str


@dataclass(frozen=True, kw_only=True)
class ResendConfirmation(Command):
    email: str


@dataclass(frozen=True, kw_only=True)
class ConfirmEmail(Command):
    account_id: UUID
    token: str = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class RequestPasswordReset(Command):
    email: str


@dataclass(frozen=True, kw_only=True)
class ResetPassword(Command):
    account_id: UUID
    token: str = field(repr=False)
    password: str = field(repr=False)
    language: str


@dataclass(frozen=True, kw_only=True)
class InviteOwner(Command):
    """An account for an owner the admin registered (sent when the admin invites them)."""

    account_id: UUID  # used only if a new account is needed
    owner_id: UUID
    email: str


@dataclass(frozen=True, kw_only=True)
class AcceptInvitation(Command):
    account_id: UUID
    token: str = field(repr=False)
    password: str = field(repr=False)
    language: str


@dataclass(frozen=True, kw_only=True)
class NoteOwnerRegistered(Command):
    """The owner with this id registered (properties' OwnerRegistered, translated by bootstrap)."""

    owner_id: UUID


@dataclass(frozen=True, kw_only=True)
class FollowOwnerEmail(Command):
    """The admin changed an owner's email (properties' OwnerEmailChanged, via bootstrap)."""

    owner_id: UUID
    email: str
