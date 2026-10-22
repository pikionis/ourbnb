"""Fernet encryption at rest for sensitive values (DOMAIN §2.3: guest ID numbers, lockbox codes)."""

import base64

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from kospm.shared.adapters.crypto import (
    DecryptionError,
    FernetCipher,
    decrypt,
    encrypt,
    get_cipher,
)


def _key(seed: bytes) -> str:
    """A deterministic, NON-secret Fernet key: 32 raw bytes, urlsafe-base64 encoded."""
    return base64.urlsafe_b64encode(seed * 32).decode("ascii")


KEY_A = _key(b"a")
KEY_B = _key(b"b")
GREEK = "Κωδικός 1234"


# --- FernetCipher -----------------------------------------------------------------------------


@pytest.mark.parametrize("plaintext", [GREEK, "AB 123456", "", "κλειδί 🔑 & <tag>"])
def test_round_trip_returns_the_original_text(plaintext: str) -> None:
    cipher = FernetCipher([KEY_A])
    assert cipher.decrypt(cipher.encrypt(plaintext)) == plaintext


def test_ciphertext_does_not_reveal_the_plaintext() -> None:
    token = FernetCipher([KEY_A]).encrypt(GREEK)
    assert token != GREEK
    assert "1234" not in token
    assert "Κωδικός" not in token
    # Plain ASCII: safe in any text column, log line or URL.
    assert token.isascii()


def test_ciphertext_is_randomised_on_every_call() -> None:
    # A random IV per token: equal plaintexts must not be recognisable in the database.
    cipher = FernetCipher([KEY_A])
    assert cipher.encrypt(GREEK) != cipher.encrypt(GREEK)


def test_wrong_key_raises_decryption_error() -> None:
    token = FernetCipher([KEY_A]).encrypt(GREEK)
    with pytest.raises(DecryptionError):
        FernetCipher([KEY_B]).decrypt(token)


def test_tampered_token_raises_decryption_error() -> None:
    token = FernetCipher([KEY_A]).encrypt(GREEK)
    middle = len(token) // 2
    tampered = token[:middle] + ("A" if token[middle] != "A" else "B") + token[middle + 1 :]
    with pytest.raises(DecryptionError):
        FernetCipher([KEY_A]).decrypt(tampered)


@pytest.mark.parametrize("garbage", ["", "not-a-token", "Κωδικός 1234", "gAAAAA"])
def test_garbage_raises_decryption_error_not_a_library_error(garbage: str) -> None:
    with pytest.raises(DecryptionError):
        FernetCipher([KEY_A]).decrypt(garbage)


def test_decryption_error_does_not_echo_the_token() -> None:
    token = FernetCipher([KEY_A]).encrypt(GREEK)
    with pytest.raises(DecryptionError) as excinfo:
        FernetCipher([KEY_B]).decrypt(token)
    assert token not in str(excinfo.value)


# --- Key rotation (MultiFernet: newest key first) ---------------------------------------------


def test_tokens_from_a_retiring_key_stay_readable_while_it_is_listed() -> None:
    token = FernetCipher([KEY_A]).encrypt(GREEK)
    assert FernetCipher([KEY_B, KEY_A]).decrypt(token) == GREEK


def test_new_tokens_are_encrypted_with_the_first_key() -> None:
    token = FernetCipher([KEY_B, KEY_A]).encrypt(GREEK)
    assert FernetCipher([KEY_B]).decrypt(token) == GREEK
    with pytest.raises(DecryptionError):
        FernetCipher([KEY_A]).decrypt(token)


def test_rotate_re_encrypts_with_the_newest_key_so_the_old_one_can_be_removed() -> None:
    old_token = FernetCipher([KEY_A]).encrypt(GREEK)
    rotated = FernetCipher([KEY_B, KEY_A]).rotate(old_token)
    assert rotated != old_token
    assert FernetCipher([KEY_B]).decrypt(rotated) == GREEK


def test_rotate_with_an_unknown_key_raises_decryption_error() -> None:
    token = FernetCipher([KEY_A]).encrypt(GREEK)
    with pytest.raises(DecryptionError):
        FernetCipher([KEY_B]).rotate(token)


# --- Configuration errors fail at startup, never at the first guest message --------------------


def test_no_keys_is_improperly_configured() -> None:
    with pytest.raises(ImproperlyConfigured, match="FERNET_KEYS"):
        FernetCipher([])


@pytest.mark.parametrize(
    "bad_key",
    [
        "",
        "not-a-fernet-key",
        base64.urlsafe_b64encode(b"x" * 16).decode("ascii"),  # valid base64, only 16 bytes
        "κλειδί-που-δεν-είναι-base64",
    ],
)
def test_malformed_key_is_improperly_configured_without_echoing_it(bad_key: str) -> None:
    with pytest.raises(ImproperlyConfigured, match=r"FERNET_KEYS\[1\]") as excinfo:
        FernetCipher([KEY_A, bad_key])
    if bad_key:
        assert bad_key not in str(excinfo.value)


def test_a_single_string_instead_of_a_list_is_improperly_configured() -> None:
    # A str is a Sequence[str]: without this check each character would be tried as a key.
    with pytest.raises(ImproperlyConfigured, match="list"):
        FernetCipher(KEY_A)


# --- get_cipher(): one cached cipher built from settings.FERNET_KEYS -------------------------


def test_get_cipher_uses_the_configured_keys() -> None:
    token = get_cipher().encrypt(GREEK)
    assert FernetCipher(settings.FERNET_KEYS).decrypt(token) == GREEK


def test_get_cipher_is_built_once() -> None:
    assert get_cipher() is get_cipher()


def test_module_level_helpers_use_the_configured_cipher() -> None:
    token = encrypt(GREEK)
    assert decrypt(token) == GREEK
    assert FernetCipher(settings.FERNET_KEYS).decrypt(token) == GREEK


def test_overridden_keys_are_picked_up_and_the_original_ones_restored() -> None:
    before = get_cipher()
    token_a = FernetCipher([KEY_A]).encrypt(GREEK)
    with override_settings(FERNET_KEYS=[KEY_A]):
        assert get_cipher() is not before
        assert decrypt(token_a) == GREEK
    # Leaving the override clears the cache again: the test key is back.
    with pytest.raises(DecryptionError):
        decrypt(token_a)


def test_unrelated_setting_changes_keep_the_cached_cipher() -> None:
    before = get_cipher()
    with override_settings(LANGUAGE_CODE="en"):
        assert get_cipher() is before


def test_empty_keys_setting_is_improperly_configured() -> None:
    with override_settings(FERNET_KEYS=[]), pytest.raises(ImproperlyConfigured):
        get_cipher()


def test_missing_keys_setting_is_improperly_configured() -> None:
    with override_settings():
        del settings.FERNET_KEYS
        # Deleting a setting sends no setting_changed signal, so drop the cached cipher by hand.
        get_cipher.cache_clear()
        with pytest.raises(ImproperlyConfigured, match="FERNET_KEYS"):
            get_cipher()
