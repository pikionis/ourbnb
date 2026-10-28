"""Settings for pytest and for mypy's django-stubs plugin.

Must import with no .env and no running database: every value has a deterministic, non-secret
default. When the repo-root .env exists, its DATABASE_URL supplies the connection, but tests
always run in a separate database (KOSPM_TEST_DB, default "test_kospm") that pytest-django
creates and destroys.
"""

import base64

from config.settings.base import *

SECRET_KEY = "kospm-test-settings-not-a-secret"  # used only by the test suite

# Test-only apps (tables created without migrations): models for the crypto and UoW tests.
INSTALLED_APPS = [*INSTALLED_APPS, "tests.crypto_testapp", "tests.uow_testapp"]

# Pinned, so tests never depend on a developer's .env or environment.
OUTBOX_SENDER = "console"
OUTBOX_MAX_ATTEMPTS = 5
OUTBOX_BASE_DELAY_SECONDS = 60
OUTBOX_BACKOFF_FACTOR = 2
OUTBOX_MAX_DELAY_SECONDS = 3600
OUTBOX_BATCH_SIZE = 100

PROPERTY_DEFAULT_CHECK_IN_TIME = "15:00"
PROPERTY_DEFAULT_CHECK_OUT_TIME = "11:00"
PROPERTY_DEFAULT_LINEN_PAR_LEVEL = 3
PROPERTY_CODE_PREFIX = "KOS"
PROPERTY_CODE_DIGITS = 3
CONTRACT_DEFAULT_COMMISSION_RATE = "0.15"
CONTRACT_DEFAULT_OWNER_CLEANING_CHARGE = "40.00"
BANK_VERIFICATION_MAX_ATTEMPTS = 3

PORTAL_NAME = "KosPM"
PORTAL_BASE_URL = "https://portal.test"
ACCOUNT_CONFIRMATION_LINK_HOURS = 72
ACCOUNT_INVITATION_LINK_HOURS = 72
ACCOUNT_PASSWORD_RESET_LINK_HOURS = 24
PORTAL_THROTTLE_MAX_ATTEMPTS = 10
PORTAL_THROTTLE_WINDOW_SECONDS = 15 * 60
PORTAL_CLIENT_IP_HEADER = ""
PORTAL_UPLOAD_MAX_MB = 15
DEFAULT_FROM_EMAIL = "KosPM <noreply@portal.test>"

# Tests never call the Claude API, even when a developer's .env has a key.
ANTHROPIC_API_KEY = ""
LISTING_EXTRACTOR_MODEL = "claude-opus-5-5"
LISTING_EXTRACTOR_EFFORT = "low"
LISTING_EXTRACTOR_TIMEOUT_SECONDS = 60
LISTING_TEXT_MAX_CHARS = 20_000
LISTING_READINGS_PER_HOUR = 10

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
