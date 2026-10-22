"""Local development. Secrets and the database come from the environment or the repo-root .env."""

from config.settings.base import *

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

SECRET_KEY = env.str("DJANGO_SECRET_KEY")
DATABASES = {"default": env.db("DATABASE_URL")}
# Fernet keys for sensitive fields (guest ID numbers, lockbox codes), newest first. From Phase 1.
FERNET_KEYS = env.list("FERNET_KEYS")
