"""Models of the crypto test app: stand-ins for a model holding a guest ID or a lockbox code."""

from django.db import models

from kospm.shared.adapters.fields import EncryptedTextField


class EncryptedNote(models.Model):
    """One required and one optional encrypted column."""

    secret = EncryptedTextField()
    # NULL means "no value" (e.g. purged guest identity data) and must stay a real SQL NULL.
    optional_secret = EncryptedTextField(null=True, blank=True)

    def __str__(self) -> str:
        # Never the secret itself: __str__ ends up in logs and in the admin.
        return f"EncryptedNote #{self.pk}"
