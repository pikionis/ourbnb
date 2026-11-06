"""Production and staging (VPS, behind nginx and Caddy: ADR 0010, 0022).

Everything secret or host-specific is required from env.

Minimal hardening for now; Phase 7 completes it. `manage.py check --deploy` currently reports
only W005/W021 (HSTS subdomains/preload) and W008 (HTTPS redirect, which Caddy performs).
"""

from config.settings.base import *

DEBUG = False

SECRET_KEY = env.str("DJANGO_SECRET_KEY")
DATABASES = {"default": env.db("DATABASE_URL")}
# Fernet keys for sensitive fields (guest ID numbers, lockbox codes), newest first. From Phase 1.
FERNET_KEYS = env.list("FERNET_KEYS")

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# The owner portal's address: links in emails start with it (ADR 0017).
PORTAL_BASE_URL = env.str("PORTAL_BASE_URL")
# Emails leave through SMTP; the provider is chosen with the deploy (Phase 7). Format, e.g.
# smtp+tls://USER:PASSWORD@HOST:587 (django-environ's email_url).
vars().update(env.email_url("EMAIL_URL"))
# Who gets the requests for an estimate from the public site (ADR 0021).
LEAD_NOTIFY_EMAIL = env.str("LEAD_NOTIFY_EMAIL")
# Caddy puts the visitor's address in X-Forwarded-For (ADR 0022); throttling reads it.
PORTAL_CLIENT_IP_HEADER = "HTTP_X_FORWARDED_FOR"
# Attempts are counted in the database, so all workers share one count (ADR 0017). The table comes
# from `manage.py createcachetable`, which every deploy runs (deploy/remote_up.sh).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "kospm_cache",
        # The default of 300 rows would let made-up usernames push real counts out of the table.
        "OPTIONS": {"MAX_ENTRIES": 100_000},
    }
}

# nginx terminates TLS and redirects HTTP to HTTPS; Caddy tells Django the scheme (ADR 0022).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# Start with one day; raise to a year (plus includeSubDomains) once HTTPS is verified (Phase 7).
SECURE_HSTS_SECONDS = 60 * 60 * 24
