"""Business rules of the identity context that refuse an operation (DOMAIN §5, owner portal)."""

from kospm.shared.domain import DomainError


class InvalidValue(DomainError):
    """A value does not satisfy its rule (e.g. a malformed email address).

    `field` names the kind of value, so an entrypoint can explain the rule in the reader's
    language; the message is for logs and developers.
    """

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(message)
        self.field = field


class InvalidAccountState(DomainError):
    """The account's state does not allow this operation."""

    def __init__(self, status: str, action: str) -> None:
        self.status = status
        self.action = action
        super().__init__(f"cannot {action} an account that is {status}")


class InvalidLink(DomainError):
    """An emailed link is unknown, expired or already used (links work once and expire)."""


class AccountLinkedToAnotherOwner(DomainError):
    """The account belongs to a registered owner, so an invitation cannot move it to another."""


class EmailAlreadyInUse(DomainError):
    """Another account already logs in with this email address."""
