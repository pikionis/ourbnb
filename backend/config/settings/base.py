"""Settings shared by every environment. dev / prod / test import * from here.

No secrets and no database here: dev and prod require them from the environment (12-factor),
test pins deterministic, non-secret values.
"""

import django_stubs_ext

# Lets classes such as admin.ModelAdmin[User] be subscripted at runtime (needed by strict mypy).
django_stubs_ext.monkeypatch()

from pathlib import Path  # noqa: E402

import environ  # noqa: E402
from django.utils.translation import gettext_lazy as _  # noqa: E402

BASE_DIR = Path(__file__).resolve().parents[2]  # backend/
REPO_ROOT = BASE_DIR.parent

env = environ.Env()  # type: ignore[no-untyped-call]  # Env.__init__(**scheme) is unannotated
_DOTENV = REPO_ROOT / ".env"
if _DOTENV.is_file():
    # Real environment variables win: read_env never overrides a variable that is already set.
    # utf-8-sig tolerates the BOM that some Windows editors write.
    environ.Env.read_env(_DOTENV, encoding="utf-8-sig")

# --- Applications ------------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Bounded contexts
    "kospm.identity",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # After sessions (may read the language from them), before Common (may redirect by URL).
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database & transactions -------------------------------------------------------------------
# DATABASES is defined per environment (dev/prod: DATABASE_URL; test: a placeholder default).
#
# ATOMIC_REQUESTS is deliberately NOT enabled. The Unit of Work (Cosmic Python ch. 6) owns every
# transaction and the message bus publishes the collected events after the UoW commits. Inside an
# outer request-wide atomic block that "commit" would only release a savepoint, so events could be
# published for work that is later rolled back with the request.

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Authentication ----------------------------------------------------------------------------

AUTH_USER_MODEL = "identity.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internationalisation & time (DOMAIN.md §2.6: store UTC, reason in Europe/Athens) ----------

LANGUAGE_CODE = "el"
LANGUAGES = [
    ("el", _("Greek")),
    ("en", _("English")),
]
USE_I18N = True
LOCALE_PATHS = [BASE_DIR / "locale"]

TIME_ZONE = "Europe/Athens"
USE_TZ = True

# --- Static files ------------------------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Logging -----------------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        # Replace Django's default handlers so records are not printed twice.
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
