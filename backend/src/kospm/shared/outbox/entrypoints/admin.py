"""Django admin for the outbox (ADR 0006): read only, for watching deliveries and failures.

Nobody edits, adds or deletes outbox rows by hand: messages come only from handlers through
`uow.outbox.enqueue`, and only the worker changes their delivery state.
"""

from django.contrib import admin
from django.http import HttpRequest

from kospm.shared.outbox.models import OutboxMessage


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

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: OutboxMessage | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: OutboxMessage | None = None) -> bool:
        return False
