"""Django admin for the outbox (ADR 0006): read only, for watching deliveries and failures.

Nobody edits, adds or deletes outbox rows by hand: messages come only from handlers through
`uow.outbox.enqueue`, and only the worker changes their delivery state.

An email's body is not shown: account emails carry links that work once (confirmation,
invitation, new password), so staff see the subject only (ADR 0017).
"""

import json

from django.contrib import admin
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

from kospm.shared.outbox.domain import OutboxChannel
from kospm.shared.outbox.models import OutboxMessage

SHOWN_FIELDS = (
    "status",
    "channel",
    "template",
    "recipient",
    "content",
    "attempts",
    "created_at",
    "next_attempt_at",
    "sent_at",
    "last_error",
)


@admin.register(OutboxMessage)
class OutboxMessageAdmin(admin.ModelAdmin[OutboxMessage]):
    list_display = (
        "status",
        "channel",
        "template",
        "recipient",
        "attempts",
        "next_attempt_at",
        "sent_at",
    )
    list_filter = ("status", "channel")
    fields = SHOWN_FIELDS
    readonly_fields = SHOWN_FIELDS

    @admin.display(description=_("content"))
    def content(self, obj: OutboxMessage) -> str:
        if obj.channel == OutboxChannel.EMAIL.value:
            return str(obj.payload.get("subject", ""))
        return json.dumps(obj.payload, ensure_ascii=False)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: OutboxMessage | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: OutboxMessage | None = None) -> bool:
        return False
