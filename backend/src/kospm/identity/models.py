"""ORM models of the identity context (infrastructure only, no business rules).

A custom user model from day one, because Django cannot swap AUTH_USER_MODEL after the first
migration without hand-written data migrations.

A row is either a staff user (the admin) or the login of an owner. Owner logins are the identity
domain's OwnerAccount aggregates: `adapters/repository.py` maps them by `account_id` and writes
their columns (the admin shows them read-only). `version` serves optimistic concurrency (ADR
0016). For owners, `username` is the email address, so Django's own login backend authenticates
them by email. Django's login itself also writes `last_login`, and may rehash the password with
a newer hasher, without a version bump: both are harmless, as the hash stays valid either way.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class AccountStatusChoices(models.TextChoices):
    UNCONFIRMED = "unconfirmed", _("Email not confirmed")
    INVITED = "invited", _("Invited, no password yet")
    ACTIVE = "active", _("Can log in")


class LanguageChoices(models.TextChoices):
    GREEK = "el", _("Greek")
    ENGLISH = "en", _("English")


class User(AbstractUser):
    """A login account: the admin, or an owner of the owner portal (Phase 2b, ADR 0017)."""

    # Owner accounts only (null for staff users).
    account_id = models.UUIDField(
        _("portal account"), null=True, blank=True, unique=True, editable=False
    )
    owner_id = models.UUIDField(_("owner"), null=True, blank=True, unique=True, editable=False)
    account_status = models.CharField(
        _("portal account status"), max_length=16, choices=AccountStatusChoices.choices, blank=True
    )
    owner_registered = models.BooleanField(_("owner registered"), default=False)
    language = models.CharField(
        _("language"), max_length=8, choices=LanguageChoices.choices, default=LanguageChoices.GREEK
    )
    version = models.PositiveIntegerField(default=0)
