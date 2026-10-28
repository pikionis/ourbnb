"""What owners read about their checklist in the portal (el/en). Business rules never live here."""

from django.utils.translation import gettext_lazy
from django_stubs_ext import StrOrPromise

from kospm.properties.domain.owner import BankAccountStatus, PayeeCheckResult

# The bank account's state, in the owner's words (design brief J4).
BANK_STATUS: dict[BankAccountStatus, StrOrPromise] = {
    BankAccountStatus.UNVERIFIED: gettext_lazy("Not verified yet"),
    BankAccountStatus.PENDING: gettext_lazy("We will send you €0.01"),
    BankAccountStatus.TRANSFER_SENT: gettext_lazy("We sent you €0.01: enter its code"),
    BankAccountStatus.VERIFIED: gettext_lazy("Verified"),
}

# Shown while the account is unverified after the bank's payee check refused the name.
PAYEE_CHECK_REFUSED = gettext_lazy(
    "Our bank did not recognise the account holder's name for this IBAN, so we did not send "
    "the transfer. Check the name as your bank writes it, save, and ask again."
)

ALREADY_REGISTERED_HINT = gettext_lazy("Contact us and we will send you an invitation.")


def payee_check_refused(result: PayeeCheckResult | None) -> bool:
    return result is PayeeCheckResult.NO_MATCH
