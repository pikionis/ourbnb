"""Model fields that keep sensitive values encrypted at rest (DOMAIN §2.3, CLAUDE.md).

IMPORT PATH FROZEN: migrations record "kospm.shared.adapters.fields.EncryptedTextField", so this
class must never move or be renamed (re-export it if the code is reorganised).
"""

from typing import Any

from django.core.exceptions import FieldError
from django.db import models
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models.lookups import Lookup, Transform
from django.utils.translation import gettext_lazy as _

from kospm.shared.adapters.crypto import decrypt, encrypt


class EncryptedTextField[ST, GT](models.TextField[ST, GT]):
    """A TextField stored as a Fernet token: Python code, forms and the admin see plaintext.

    Encrypts in get_prep_value (save, update, bulk_update) and decrypts in from_db_value.
    Ciphertext is randomised, so SQL cannot compare, search or meaningfully index or sort it:
    every lookup except `isnull` raises FieldError instead of silently matching nothing (also
    `field=None`, use `field__isnull=True`). Never combine it with unique=True or db_index=True.
    """

    description = _("Text encrypted at rest")

    def get_prep_value(self, value: Any) -> Any:
        text = super().get_prep_value(value)  # TextField: str(value), lazy text resolved
        if text is None:
            return None
        return encrypt(text)

    def from_db_value(
        self, value: str | None, expression: object, connection: BaseDatabaseWrapper
    ) -> str | None:
        if value is None:
            return None
        return decrypt(value)

    def get_lookup(self, lookup_name: str) -> type[Lookup[Any]] | None:
        if lookup_name != "isnull":
            raise _not_queryable(lookup_name)
        return super().get_lookup(lookup_name)

    def get_transform(self, lookup_name: str) -> type[Transform] | None:
        # Transforms registered on every TextField (e.g. Lower) would compare ciphertext too.
        raise _not_queryable(lookup_name)


def _not_queryable(lookup_name: str) -> FieldError:
    return FieldError(
        f"EncryptedTextField supports only the 'isnull' lookup, not {lookup_name!r}: "
        "its ciphertext is randomised, so SQL cannot compare or search the values."
    )
