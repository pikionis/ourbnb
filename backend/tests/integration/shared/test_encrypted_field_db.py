"""EncryptedTextField on PostgreSQL: the column holds Fernet ciphertext, the ORM returns text."""

import pytest
from django.db import connection

from kospm.shared.adapters.crypto import decrypt
from tests.crypto_testapp.models import EncryptedNote

pytestmark = pytest.mark.django_db

GREEK = "Κωδικός 1234"


def _raw_columns(note: EncryptedNote) -> tuple[str | None, str | None]:
    """(secret, optional_secret) exactly as stored, bypassing the field's decryption."""
    quote = connection.ops.quote_name
    # Column names are the field names (no db_column on the test model). Only quoted identifiers
    # are interpolated; the value is a query parameter.
    sql = (
        f"SELECT {quote('secret')}, {quote('optional_secret')} "
        f"FROM {quote(EncryptedNote._meta.db_table)} WHERE {quote('id')} = %s"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, [note.pk])
        row = cursor.fetchone()
    assert row is not None
    return row[0], row[1]


def test_column_holds_ciphertext_not_plaintext() -> None:
    note = EncryptedNote.objects.create(secret=GREEK)
    raw_secret, _raw_optional = _raw_columns(note)
    assert raw_secret is not None
    assert raw_secret != GREEK
    assert "1234" not in raw_secret
    assert "Κωδικός" not in raw_secret
    assert decrypt(raw_secret) == GREEK


def test_equal_plaintexts_are_stored_as_different_ciphertexts() -> None:
    first = EncryptedNote.objects.create(secret=GREEK)
    second = EncryptedNote.objects.create(secret=GREEK)
    assert _raw_columns(first)[0] != _raw_columns(second)[0]


@pytest.mark.parametrize("plaintext", [GREEK, "AB 123456", ""], ids=["greek", "latin", "empty"])
def test_orm_reads_back_the_plaintext(plaintext: str) -> None:
    note = EncryptedNote.objects.create(secret=plaintext)
    assert EncryptedNote.objects.get(pk=note.pk).secret == plaintext
    assert list(EncryptedNote.objects.values_list("secret", flat=True)) == [plaintext]
    note.refresh_from_db()
    assert note.secret == plaintext


def test_null_stays_null() -> None:
    note = EncryptedNote.objects.create(secret=GREEK, optional_secret=None)
    assert _raw_columns(note)[1] is None
    assert EncryptedNote.objects.get(pk=note.pk).optional_secret is None


def test_optional_value_is_encrypted_too() -> None:
    note = EncryptedNote.objects.create(secret="x", optional_secret=GREEK)
    raw_optional = _raw_columns(note)[1]
    assert raw_optional is not None
    assert raw_optional != GREEK
    assert decrypt(raw_optional) == GREEK
    assert EncryptedNote.objects.get(pk=note.pk).optional_secret == GREEK


def test_isnull_filters_work() -> None:
    with_value = EncryptedNote.objects.create(secret="a", optional_secret=GREEK)
    without_value = EncryptedNote.objects.create(secret="b", optional_secret=None)

    assert list(EncryptedNote.objects.filter(optional_secret__isnull=True)) == [without_value]
    assert list(EncryptedNote.objects.filter(optional_secret__isnull=False)) == [with_value]
    assert list(EncryptedNote.objects.exclude(optional_secret__isnull=True)) == [with_value]
    assert EncryptedNote.objects.filter(secret__isnull=False).count() == 2
    assert not EncryptedNote.objects.filter(secret__isnull=True).exists()


def test_queryset_update_encrypts() -> None:
    note = EncryptedNote.objects.create(secret="old")
    EncryptedNote.objects.filter(pk=note.pk).update(secret=GREEK, optional_secret=GREEK)
    raw_secret, raw_optional = _raw_columns(note)
    assert raw_secret is not None
    assert raw_optional is not None
    assert GREEK not in (raw_secret, raw_optional)
    assert decrypt(raw_secret) == decrypt(raw_optional) == GREEK


def test_bulk_update_encrypts() -> None:
    # bulk_update writes through CASE WHEN ... THEN <value> (cast to the field's type).
    notes = [EncryptedNote.objects.create(secret="old") for _ in range(2)]
    notes[0].secret = GREEK
    notes[1].secret = "AB 123456"
    EncryptedNote.objects.bulk_update(notes, ["secret"])

    raw = [_raw_columns(note)[0] for note in notes]
    assert GREEK not in raw
    assert [decrypt(token) for token in raw if token is not None] == [GREEK, "AB 123456"]
    assert sorted(EncryptedNote.objects.values_list("secret", flat=True)) == sorted(
        [GREEK, "AB 123456"]
    )
