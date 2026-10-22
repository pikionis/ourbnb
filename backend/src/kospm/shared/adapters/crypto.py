"""Fernet encryption for sensitive values at rest (DOMAIN §2.3: guest ID numbers, lockbox codes).

An adapter, not domain code: the domain holds plaintext values, and encryption happens only on
the way to and from the database (EncryptedTextField) or wherever an adapter stores a secret.

Keys come from settings.FERNET_KEYS (environment, never committed), newest first. MultiFernet
encrypts with the first key and decrypts with any listed key. To rotate a key:
1. put the new key first and keep the old one listed;
2. re-encrypt the stored values with rotate();
3. remove the old key.
"""

import functools
from collections.abc import Sequence

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.signals import setting_changed
from django.dispatch import receiver


class DecryptionError(Exception):
    """No configured key opens the token: wrong or retired key, or the stored value was altered."""


_DECRYPTION_FAILED = "cannot decrypt the value: no key in FERNET_KEYS matches it, or it was altered"


class FernetCipher:
    """Encrypts text to an ASCII Fernet token and back (AES-128-CBC + HMAC-SHA256).

    Every token has a random IV, so equal plaintexts give different tokens and the database
    cannot compare or search them. Messages never contain keys, tokens or plaintext.
    """

    def __init__(self, keys: Sequence[str]) -> None:
        if isinstance(keys, str):
            raise ImproperlyConfigured("FERNET_KEYS must be a list of keys, not a single string.")
        if not keys:
            raise ImproperlyConfigured("FERNET_KEYS is empty: at least one Fernet key is required.")
        fernets: list[Fernet] = []
        for position, key in enumerate(keys):
            try:
                fernets.append(Fernet(key))
            except (ValueError, TypeError):
                # `from None`: the library's message may quote the key material.
                raise ImproperlyConfigured(
                    f"FERNET_KEYS[{position}] is not a valid Fernet key "
                    "(32 random bytes, urlsafe-base64 encoded; see Fernet.generate_key())."
                ) from None
        self._fernet = MultiFernet(fernets)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt with the newest (first) key."""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        """Decrypt with whichever configured key produced the token."""
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except (InvalidToken, ValueError):
            # ValueError covers a non-ASCII token and a plaintext that is not UTF-8.
            raise DecryptionError(_DECRYPTION_FAILED) from None

    def rotate(self, token: str) -> str:
        """Re-encrypt a token with the newest key, so that older keys can be removed."""
        try:
            return self._fernet.rotate(token).decode("ascii")
        except (InvalidToken, ValueError):
            raise DecryptionError(_DECRYPTION_FAILED) from None


@functools.cache
def get_cipher() -> FernetCipher:
    """The cipher for settings.FERNET_KEYS, built once per process (key parsing is not free)."""
    keys = getattr(settings, "FERNET_KEYS", None)
    if keys is None:
        raise ImproperlyConfigured("The FERNET_KEYS setting is missing.")
    return FernetCipher(keys)


@receiver(setting_changed)
def _forget_cipher_when_keys_change(*, setting: str, **kwargs: object) -> None:
    # override_settings(FERNET_KEYS=...) in tests must not keep using the cached cipher. The cache
    # can only be filled after this module is imported, so the receiver is always connected first.
    if setting == "FERNET_KEYS":
        get_cipher.cache_clear()


def encrypt(plaintext: str) -> str:
    """Encrypt with the configured keys (see FernetCipher.encrypt)."""
    return get_cipher().encrypt(plaintext)


def decrypt(token: str) -> str:
    """Decrypt with the configured keys (see FernetCipher.decrypt)."""
    return get_cipher().decrypt(token)
