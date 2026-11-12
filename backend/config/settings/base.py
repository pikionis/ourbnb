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
    # The back office's look (django-unfold); it must come before the admin it restyles.
    "unfold",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Shared kernel
    "kospm.shared.outbox",
    # Bounded contexts
    "kospm.identity",
    "kospm.properties",
    "kospm.reservations",
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
        # The layout shared by the owner-portal pages of every context (ADR 0017).
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "kospm.shared.adapters.portal.portal_context",
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

# --- Outbox (ADR 0005): external messages are delivered by the process_outbox worker -----------
# Configuration, not constants (CLAUDE.md): bootstrap turns these into an OutboxRetryPolicy.

# Which MessageSender delivers WhatsApp messages: "console" prints them (dev); the WhatsApp sender
# arrives in Phase 6. Emails always go through Django's EMAIL_BACKEND (below).
OUTBOX_SENDER = env.str("OUTBOX_SENDER", default="console")
# Failed attempts before a message is marked FAILED for the admin.
OUTBOX_MAX_ATTEMPTS = env.int("OUTBOX_MAX_ATTEMPTS", default=5)
# Exponential backoff: 60 s, then x2 per failure, capped at one hour.
OUTBOX_BASE_DELAY_SECONDS = env.int("OUTBOX_BASE_DELAY_SECONDS", default=60)
OUTBOX_BACKOFF_FACTOR = env.int("OUTBOX_BACKOFF_FACTOR", default=2)
OUTBOX_MAX_DELAY_SECONDS = env.int("OUTBOX_MAX_DELAY_SECONDS", default=3600)
# Messages handled per worker run (the scheduler runs it every minute, ADR 0004).
OUTBOX_BATCH_SIZE = env.int("OUTBOX_BATCH_SIZE", default=100)

# --- Properties (DOMAIN §5): defaults and policies, turned into configuration objects by bootstrap

# What a new property starts with.
PROPERTY_DEFAULT_CHECK_IN_TIME = "15:00"
PROPERTY_DEFAULT_CHECK_OUT_TIME = "11:00"
PROPERTY_DEFAULT_LINEN_PAR_LEVEL = 3
# Codes given to the properties that owners add in the portal: KOS-001, KOS-002, ...
PROPERTY_CODE_PREFIX = "KOS"
PROPERTY_CODE_DIGITS = 3
# Contract terms used when a signed contract does not state its own.
CONTRACT_DEFAULT_COMMISSION_RATE = "0.15"
CONTRACT_DEFAULT_OWNER_CLEANING_CHARGE = "40.00"
# Wrong codes allowed per bank-account test transfer before a new transfer is needed.
BANK_VERIFICATION_MAX_ATTEMPTS = 3

# --- Owner portal (ADR 0017): accounts, emailed links, throttling --------------------------------

# The name owners see in the pages and emails (the IKE's brand, once it exists).
PORTAL_NAME = env.str("PORTAL_NAME", default="KosPM")
# Where the portal is reached: emailed links start with it. No trailing slash.
PORTAL_BASE_URL = env.str("PORTAL_BASE_URL", default="http://localhost:8000")
# How long emailed links work (DOMAIN §5: they work once and expire).
ACCOUNT_CONFIRMATION_LINK_HOURS = 72
ACCOUNT_INVITATION_LINK_HOURS = 72
ACCOUNT_PASSWORD_RESET_LINK_HOURS = 24
# Login, sign-up and reset attempts allowed per address and per visitor within the window.
PORTAL_THROTTLE_MAX_ATTEMPTS = 10
PORTAL_THROTTLE_WINDOW_SECONDS = 15 * 60
# Request header with the visitor's address appended by the reverse proxy ("" = REMOTE_ADDR).
PORTAL_CLIENT_IP_HEADER = ""
# Largest file an owner may upload (photos, the signed contract), in megabytes.
PORTAL_UPLOAD_MAX_MB = 15

# --- The public site's form (ADR 0021): the requests for an estimate that reach the IKE ---------

# Who gets them by email. Production requires it (config.settings.prod).
LEAD_NOTIFY_EMAIL = env.str("LEAD_NOTIFY_EMAIL", default="leads@localhost")
# What the form offers, as the site's page writes it. Anything else counts as not stated.
OWNER_LEAD_AREAS = (
    "Κως (πόλη)",
    "Ψαλίδι",
    "Λάμπη",
    "Τιγκάκι",
    "Μαρμάρι",
    "Μαστιχάρι",
    "Καρδάμαινα",
    "Κέφαλος",
    "Ζηπάρι",
    "Αντιμάχεια",
    "Πυλί",
    "Άλλη περιοχή",
)
OWNER_LEAD_BEDROOMS = ("1", "2", "3", "4", "5+")

# --- Listing text read by the Claude API (DOMAIN §5 owner portal; design brief J6) ------------

# Without a key the owner fills in the profile by hand (the default in development and tests).
ANTHROPIC_API_KEY = env.str("ANTHROPIC_API_KEY", default="")
# Reading a listing is a small task: a low effort answers sooner and costs less.
# Efforts: "low", "medium", "high", "xhigh", "max".
LISTING_EXTRACTOR_MODEL = env.str("LISTING_EXTRACTOR_MODEL", default="claude-opus-5-5")
LISTING_EXTRACTOR_EFFORT = env.str("LISTING_EXTRACTOR_EFFORT", default="low")
# How long the owner's page waits for an answer. A failed call is retried once, so the page may
# wait twice this: the web server's timeout must be longer (Phase 7).
LISTING_EXTRACTOR_TIMEOUT_SECONDS = 60
# The longest text sent in one reading, and the readings allowed per owner per hour (cost).
LISTING_TEXT_MAX_CHARS = 20_000
LISTING_READINGS_PER_HOUR = 10

# --- Reservations: iCal sync and admin alerts (DOMAIN §6, ADR 0004) ----------------------------
# The sync runs every 30 minutes from the scheduler (deploy/crontab, Phase 7; locally run-jobs).

# A failing feed alerts the admin after failing for this long (default 2 h, about 4 syncs).
ICAL_ALERT_AFTER_MINUTES = env.int("ICAL_ALERT_AFTER_MINUTES", default=120)
# One feed read: how long to wait, and the largest feed accepted.
ICAL_FETCH_TIMEOUT_SECONDS = 20
ICAL_MAX_BYTES = 5 * 1024 * 1024
# Where admin alerts go by WhatsApp, international format (e.g. +3069...). Empty: only logged.
ADMIN_WHATSAPP_NUMBER = env.str("ADMIN_WHATSAPP_NUMBER", default="")

# --- Email: delivered by the outbox worker through this backend (ADR 0005, 0017) ---------------

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL", default="KosPM <noreply@localhost>")

# --- Authentication ----------------------------------------------------------------------------

AUTH_USER_MODEL = "identity.User"
LOGIN_URL = "identity:login"
# The owner's dashboard (Phase 2b, properties portal pages).
LOGIN_REDIRECT_URL = "portal:dashboard"

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
# The owner portal's stylesheet (ADR 0017).
STATICFILES_DIRS = [BASE_DIR / "static"]

# --- The back office's look (django-unfold, ADR 0006) --------------------------------------------

# Which installation this is: staging, production, or a developer's machine (deploy/setup_host.sh
# writes it to the environment file). The back office shows it, so staging is never mistaken for
# production.
KOSPM_ENV = env.str("KOSPM_ENV", default="development")

UNFOLD = {
    "SITE_TITLE": "OurBnb",
    "SITE_HEADER": "OurBnb",
    "SITE_SUBHEADER": _("Back office"),
    "SITE_SYMBOL": "villa",
    "SITE_URL": "/",
    "ENVIRONMENT": "config.backoffice.environment_label",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "SIDEBAR": {"show_search": True, "show_all_applications": True},
    # The site's colours: "sea" teal for actions, warm greys for the rest. Shade 600 is the
    # button colour, dark enough for white text (WCAG AA).
    "COLORS": {
        "primary": {
            "50": "#eef9f8",
            "100": "#e5f5f3",
            "200": "#c4eae5",
            "300": "#9ad9d1",
            "400": "#6cc6bc",
            "500": "#2b8a80",
            "600": "#1f6f67",
            "700": "#1a5a54",
            "800": "#164a45",
            "900": "#123d39",
            "950": "#0b2725",
        },
        "base": {
            "50": "#faf9f8",
            "100": "#f2f0ee",
            "200": "#ece7e2",
            "300": "#d9d2cc",
            "400": "#a8a09a",
            "500": "#7a726d",
            "600": "#5e5753",
            "700": "#3f3a37",
            "800": "#2f2b2a",
            "900": "#221f1e",
            "950": "#151313",
        },
    },
}

# Uploaded files (signed contracts, property photos). In production they are not served publicly
# (contracts hold personal data); serving through an authenticated view is part of Phase 7.
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env.str("MEDIA_ROOT", default=str(BASE_DIR / "media")))

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
