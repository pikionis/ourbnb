"""EncryptedTextField without a database: ciphertext goes to the DB, plaintext comes back.

Building a QuerySet filter compiles the lookups but never connects, so the refused lookups are
tested here too; the round trip through PostgreSQL is in tests/integration/shared.
"""

import base64
from typing import Any

import pytest
from django.core.exceptions import FieldError
from django.db import connection
from django.db.models import TextField
from django.db.models.functions import Lower
from django.db.models.lookups import IsNull
from django.test.utils import register_lookup

from kospm.shared.adapters.crypto import DecryptionError, FernetCipher, decrypt, encrypt
from kospm.shared.adapters.fields import EncryptedTextField
from tests.crypto_testapp.models import EncryptedNote

GREEK = "Κωδικός 1234"


# --- Values on the way to and from the database -----------------------------------------------


def test_prepared_value_is_ciphertext_of_the_plaintext() -> None:
    token = EncryptedTextField().get_prep_value(GREEK)
    assert token != GREEK
    assert "1234" not in token
    assert decrypt(token) == GREEK


def test_prepared_value_is_randomised() -> None:
    # Outside a model the mypy plugin cannot infer the field's types, hence the annotation.
    field: EncryptedTextField[str, str] = EncryptedTextField()
    assert field.get_prep_value(GREEK) != field.get_prep_value(GREEK)


def test_value_saved_to_the_database_is_ciphertext() -> None:
    # The path Model.save() and QuerySet.update() take.
    token = EncryptedTextField().get_db_prep_save(GREEK, connection)
    assert token != GREEK
    assert decrypt(token) == GREEK


def test_non_string_values_are_stored_as_their_text() -> None:
    # Same coercion as TextField: str(value) before encrypting.
    assert decrypt(EncryptedTextField().get_prep_value(1234)) == "1234"


def test_value_read_from_the_database_is_decrypted() -> None:
    assert EncryptedTextField().from_db_value(encrypt(GREEK), None, connection) == GREEK


def test_none_passes_through_both_ways() -> None:
    field: EncryptedTextField[str | None, str | None] = EncryptedTextField(null=True)
    assert field.get_prep_value(None) is None
    assert field.from_db_value(None, None, connection) is None


def test_value_from_another_key_fails_loudly() -> None:
    other_key = base64.urlsafe_b64encode(b"b" * 32).decode("ascii")
    foreign = FernetCipher([other_key]).encrypt(GREEK)
    with pytest.raises(DecryptionError):
        EncryptedTextField().from_db_value(foreign, None, connection)


def test_import_path_is_frozen_for_migrations() -> None:
    _name, path, args, kwargs = EncryptedTextField(null=True, blank=True).deconstruct()
    assert path == "kospm.shared.adapters.fields.EncryptedTextField"
    assert list(args) == []
    assert kwargs == {"null": True, "blank": True}


# --- Lookups: random ciphertext cannot be compared in SQL, so only isnull is allowed ----------


@pytest.mark.parametrize(
    "lookup", ["exact", "iexact", "contains", "icontains", "in", "startswith", "gt", "regex"]
)
def test_lookups_other_than_isnull_are_refused(lookup: str) -> None:
    with pytest.raises(FieldError, match="isnull"):
        EncryptedTextField().get_lookup(lookup)


def test_isnull_lookup_is_allowed() -> None:
    assert EncryptedTextField().get_lookup("isnull") is IsNull


def test_transforms_are_refused_even_when_registered_for_every_text_field() -> None:
    # Lower(ciphertext) would compile fine and silently match nothing.
    with register_lookup(TextField, Lower), pytest.raises(FieldError, match="isnull"):
        EncryptedTextField().get_transform("lower")


@pytest.mark.parametrize(
    "filters",
    [
        {"secret": GREEK},
        {"secret__exact": GREEK},
        {"secret__icontains": "1234"},
        {"secret__in": [GREEK]},
        {"secret__startswith": "Κωδ"},
        # Even None: Django resolves `exact` before turning `= None` into IS NULL.
        {"optional_secret": None},
    ],
    ids=lambda filters: ",".join(filters),
)
def test_queryset_filters_on_the_ciphertext_are_refused(filters: dict[str, Any]) -> None:
    with pytest.raises(FieldError, match="isnull"):
        EncryptedNote.objects.filter(**filters)


def test_queryset_transforms_on_the_ciphertext_are_refused() -> None:
    # Passed as **{...}: the django-stubs mypy plugin evaluates literal lookup kwargs by calling
    # get_lookup() at type-check time, and the FieldError would stop mypy with an INTERNAL ERROR.
    refused = {"secret__lower__exact": "κωδικός 1234"}
    with register_lookup(TextField, Lower), pytest.raises(FieldError, match="isnull"):
        EncryptedNote.objects.filter(**refused)


def test_queryset_isnull_filters_are_allowed() -> None:
    queryset = EncryptedNote.objects.filter(optional_secret__isnull=True).exclude(
        secret__isnull=True
    )
    assert IsNull in {type(leaf) for leaf in _leaves(queryset.query.where)}


def _leaves(node: object) -> list[object]:
    """The lookups of a WHERE tree (WhereNode children are lookups or nested WhereNodes)."""
    children: list[object] | None = getattr(node, "children", None)
    if children is None:
        return [node]
    return [leaf for child in children for leaf in _leaves(child)]
