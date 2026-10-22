"""Settings for pytest and for mypy's django-stubs plugin.

Must import with no .env and no running database: every value has a deterministic, non-secret
default. When the repo-root .env exists, its DATABASE_URL supplies the connection, but tests
always run in a separate database (KOSPM_TEST_DB, default "test_kospm") that pytest-django
creates and destroys.
"""

import base64

from config.settings.base import *

SECRET_KEY = "kospm-test-settings-not-a-secret"  # used only by the test suite

DATABASES = {
    "default": {
        **env.db("DATABASE_URL", default="postgres://kospm:kospm@localhost:5432/kospm"),
        "TEST": {
            "NAME": env.str("KOSPM_TEST_DB", default="test_kospm"),
            # Identical encoding on every machine (local PG18 on Windows, PG16 in CI).
            "TEMPLATE": "template0",
            "CHARSET": "UTF8",
        },
    }
}

# Deterministic, NON-secret key: exactly 32 raw bytes, urlsafe-base64 encoded (Fernet's format).
FERNET_KEYS = [base64.urlsafe_b64encode(b"kospm-test-fernet-key-not-secret").decode("ascii")]

# Fast hashing: password strength is irrelevant for throwaway test users.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
