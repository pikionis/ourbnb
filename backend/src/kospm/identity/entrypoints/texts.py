"""What people read about the identity domain's refusals, translatable (el/en).

The domain reports facts in code (exception types and attributes); this module turns them into
sentences for the account pages. Business rules never live here.
"""

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django_stubs_ext import StrOrPromise

from kospm.identity.domain.errors import InvalidLink, InvalidValue

# What to tell the user when the domain refuses a value (InvalidValue.field).
INVALID_VALUE_MESSAGES: dict[str, StrOrPromise] = {
    "email": gettext_lazy("Enter a valid email address."),
    "language": gettext_lazy("Choose Greek or English."),
}

THROTTLED = gettext_lazy("Too many attempts. Try again in a few minutes.")


def describe(error: Exception) -> str:
    """A sentence about a refused command; unknown errors keep their own text."""
    if isinstance(error, InvalidValue):
        return str(INVALID_VALUE_MESSAGES.get(error.field, error))
    if isinstance(error, InvalidLink):
        return _("This link has expired or was already used. Ask for a new one.")
    return str(error)
