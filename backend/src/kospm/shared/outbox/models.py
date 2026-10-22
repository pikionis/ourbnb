"""ORM models of the outbox (infrastructure only, no business rules).

The rules (validation, retries, giving up) live in `domain.py`. `adapters.py` maps rows to
OutboxEntry objects and back. Times come from the injected Clock, so no `auto_now_add` here.
"""

from typing import Final

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from kospm.shared.outbox.domain import OutboxChannel, OutboxStatus

# Labels for the admin. Built from the domain enums, so a new member without a label fails at
# import time instead of showing a raw value.
_CHANNEL_LABELS: Final[dict[OutboxChannel, Promise]] = {
    OutboxChannel.WHATSAPP: _("WhatsApp"),
    OutboxChannel.EMAIL: _("Email"),
}
_STATUS_LABELS: Final[dict[OutboxStatus, Promise]] = {
    OutboxStatus.PENDING: _("Pending"),
    OutboxStatus.SENT: _("Sent"),
    OutboxStatus.FAILED: _("Failed"),
}


class OutboxMessage(models.Model):
    """One external message and its delivery state (domain: OutboxEntry)."""

    # Assigned by the domain (OutboxEntry.new), never by the database.
    id = models.UUIDField(primary_key=True, editable=False)
    channel = models.CharField(
        _("channel"),
        max_length=16,
        choices=[(channel.value, _CHANNEL_LABELS[channel]) for channel in OutboxChannel],
    )
    recipient = models.CharField(_("recipient"), max_length=255)
    template = models.CharField(_("template"), max_length=100)
    payload = models.JSONField(_("payload"), default=dict, encoder=DjangoJSONEncoder)
    status = models.CharField(
        _("status"),
        max_length=16,
        choices=[(status.value, _STATUS_LABELS[status]) for status in OutboxStatus],
        default=OutboxStatus.PENDING.value,
    )
    attempts = models.PositiveSmallIntegerField(_("failed attempts"), default=0)
    created_at = models.DateTimeField(_("created at"))
    next_attempt_at = models.DateTimeField(_("next attempt at"), null=True, blank=True)
    sent_at = models.DateTimeField(_("sent at"), null=True, blank=True)
    last_error = models.TextField(_("last error"), blank=True)

    class Meta:
        verbose_name = _("outbox message")
        verbose_name_plural = _("outbox messages")
        ordering = ("-created_at",)
        indexes = (
            # The worker's query: PENDING entries by due time. SENT and FAILED rows, the vast
            # majority over time, stay out of the index.
            models.Index(
                fields=["next_attempt_at"],
                condition=Q(status=OutboxStatus.PENDING.value),
                name="outbox_pending_due_idx",
            ),
        )

    def __str__(self) -> str:
        return f"{self.template} -> {self.recipient} ({self.status})"
