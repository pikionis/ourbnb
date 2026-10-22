"""Phase 0: the settings encode the platform-wide rules of DOMAIN.md §2 and CLAUDE.md."""

import base64
import importlib
import sys
import zoneinfo
from types import ModuleType

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured

from kospm.identity.models import User


def test_business_time_zone_is_athens_and_storage_is_utc_aware() -> None:
    assert settings.TIME_ZONE == "Europe/Athens"
    assert settings.USE_TZ is True


def test_iana_time_zone_database_is_available() -> None:
    # Windows has no system tz database: the `tzdata` package must provide it.
    assert str(zoneinfo.ZoneInfo("Europe/Athens")) == "Europe/Athens"


def test_languages_are_greek_and_english_with_greek_default() -> None:
    assert {code for code, _name in settings.LANGUAGES} == {"el", "en"}
    assert settings.LANGUAGE_CODE == "el"
    assert settings.USE_I18N is True


def test_locale_middleware_sits_between_session_and_common() -> None:
    middleware = list(settings.MIDDLEWARE)
    session = middleware.index("django.contrib.sessions.middleware.SessionMiddleware")
    locale = middleware.index("django.middleware.locale.LocaleMiddleware")
    common = middleware.index("django.middleware.common.CommonMiddleware")
    assert session < locale < common


def test_django_admin_is_installed() -> None:
    assert "django.contrib.admin" in settings.INSTALLED_APPS


def test_requests_are_not_wrapped_in_a_transaction() -> None:
    # The Unit of Work owns transactions; an outer atomic block would let the bus publish
    # events for work that is later rolled back.
    assert not settings.DATABASES["default"].get("ATOMIC_REQUESTS", False)


def test_custom_user_model_lives_in_identity_context() -> None:
    assert settings.AUTH_USER_MODEL == "identity.User"
    assert get_user_model() is User


def test_fernet_keys_are_urlsafe_base64_of_32_bytes() -> None:
    assert settings.FERNET_KEYS
    for key in settings.FERNET_KEYS:
        assert len(base64.urlsafe_b64decode(key)) == 32


# --- dev / prod: secrets come only from the environment ---------------------------------------
# config.settings.base is already imported (and the .env, if any, already read), so importing
# dev/prod afresh sees exactly the variables set or removed below.

_REQUIRED_SECRETS = {
    "DJANGO_SECRET_KEY": "not-a-real-secret-only-for-this-test-0123456789abcdef",
    "DATABASE_URL": "postgres://user:pass@localhost:5432/db",
    "FERNET_KEYS": base64.urlsafe_b64encode(b"0" * 32).decode("ascii"),
}


def _import_fresh(module: str, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.delitem(sys.modules, module, raising=False)
    imported = importlib.import_module(module)
    monkeypatch.delitem(sys.modules, module)
    return imported


@pytest.fixture
def secrets_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name, value in _REQUIRED_SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "kospm.example")
    return monkeypatch


@pytest.mark.parametrize("module", ["config.settings.dev", "config.settings.prod"])
@pytest.mark.parametrize("missing", sorted(_REQUIRED_SECRETS))
def test_refuses_to_start_without_a_required_secret(
    secrets_env: pytest.MonkeyPatch, module: str, missing: str
) -> None:
    secrets_env.delenv(missing)
    with pytest.raises(ImproperlyConfigured, match=missing):
        _import_fresh(module, secrets_env)


@pytest.mark.parametrize("module", ["config.settings.dev", "config.settings.prod"])
def test_serving_settings_do_not_wrap_requests_in_a_transaction(
    secrets_env: pytest.MonkeyPatch, module: str
) -> None:
    loaded = _import_fresh(module, secrets_env)
    assert not loaded.DATABASES["default"].get("ATOMIC_REQUESTS", False)
    expected_secret = _REQUIRED_SECRETS["DJANGO_SECRET_KEY"]
    assert expected_secret == loaded.SECRET_KEY


def test_prod_is_not_in_debug_mode(secrets_env: pytest.MonkeyPatch) -> None:
    prod = _import_fresh("config.settings.prod", secrets_env)
    assert prod.DEBUG is False
    assert prod.ALLOWED_HOSTS == ["kospm.example"]
