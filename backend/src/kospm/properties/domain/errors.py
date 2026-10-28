"""Business rules of the properties context that refuse an operation (DOMAIN §5)."""

from collections.abc import Iterable

from kospm.properties.domain.checklist import ActivationRequirement, ProfileItem
from kospm.shared.domain import DomainError


class InvalidValue(DomainError):
    """A value does not satisfy its rule (a malformed ΑΦΜ, IBAN, code, coordinate, ...).

    `field` names the kind of value (e.g. "afm", "commission_rate"), so an entrypoint can explain
    the rule in the reader's language; the message is for logs and developers.
    """

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(message)
        self.field = field


class PropertyNotReadyForActivation(DomainError):
    """Activation was asked for, but items of the checklist are still missing."""

    def __init__(self, missing: Iterable[ActivationRequirement]) -> None:
        self.missing = tuple(missing)
        super().__init__(
            "the property cannot be activated; missing: "
            + ", ".join(item.value for item in self.missing)
        )


class ProfileMustStayComplete(DomainError):
    """An active property may not lose a part of its profile (the activation invariant)."""

    def __init__(self, gaps: Iterable[ProfileItem]) -> None:
        self.gaps = tuple(gaps)
        super().__init__(
            "an active property must keep a complete profile; it would miss: "
            + ", ".join(gap.value for gap in self.gaps)
        )


class InvalidStatusTransition(DomainError):
    """The property's state does not allow this operation."""

    def __init__(self, status: str, action: str) -> None:
        self.status = status
        self.action = action
        super().__init__(f"cannot {action} a property that is {status}")


class OwnerNotFound(DomainError):
    """No owner has this id."""


class PropertyNotFound(DomainError):
    """No property has this id."""


class OwnerAlreadyRegistered(DomainError):
    """Another owner already has this ΑΦΜ or email address."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"an owner with this {field} is already registered")


class PropertyCodeTaken(DomainError):
    """Another property already has this code (codes identify a property to guests)."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"the property code {code} is already used")


class BankVerificationNotStarted(DomainError):
    """A code was entered, but no test transfer is waiting for one."""


class NoContractToSign(DomainError):
    """The owner uploaded a signed contract, but the IKE has not offered one to sign yet."""


class TransferNotSentYet(DomainError):
    """A code was entered before the IKE recorded the test transfer as sent (ADR 0018)."""


class ChangeThroughTheIke(DomainError):
    """The owner may not change this in the portal; the IKE changes it (DOMAIN §5, owner portal).

    `item` names what: "bank_account" (verified already), "email" (the login), "property" (no
    longer onboarding).
    """

    def __init__(self, item: str) -> None:
        self.item = item
        super().__init__(f"the owner changes the {item} through the IKE")


class BankAccountAlreadyVerified(DomainError):
    """The bank account is verified already; change the IBAN to verify another one."""


class WrongVerificationCode(DomainError):
    """The code does not match the test transfer."""

    def __init__(self, attempts_left: int) -> None:
        self.attempts_left = attempts_left
        if attempts_left:
            message = f"wrong verification code; {attempts_left} attempt(s) left"
        else:
            message = "wrong verification code; a new test transfer is needed"
        super().__init__(message)
