"""The outbox admin (ADR 0006) is read only: the Admin watches deliveries and failures there.

Only handlers (`uow.outbox.enqueue`) create outbox rows and only the worker changes them, so the
admin must refuse to add, change or delete one.
"""

from datetime import UTC, datetime

import pytest
from django.test import Client
from django.urls import reverse

from kospm.shared.outbox import models
from kospm.shared.outbox.adapters import from_domain
from kospm.shared.outbox.domain import (
    OutboxChannel,
    OutboxEntry,
    OutboxMessage,
    OutboxRetryPolicy,
    OutboxStatus,
)

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)
POLICY = OutboxRetryPolicy()


@pytest.fixture
def failed_entry() -> OutboxEntry:
    entry = OutboxEntry.new(
        OutboxMessage(
            channel=OutboxChannel.WHATSAPP, recipient="+306900000666", template="cleaning_assigned"
        ),
        now=NOW,
    )
    for _ in range(POLICY.max_attempts):
        entry.record_failure(at=NOW, error="SendError('provider down')", policy=POLICY)
    assert entry.status == OutboxStatus.FAILED
    from_domain(entry).save(force_insert=True)
    return entry


def test_the_admin_lists_the_failed_messages(
    admin_client: Client, failed_entry: OutboxEntry
) -> None:
    response = admin_client.get(
        reverse("admin:outbox_outboxmessage_changelist"),
        {"status__exact": OutboxStatus.FAILED.value},
    )

    assert response.status_code == 200
    assert "+306900000666" in response.content.decode("utf-8")


def test_a_message_can_be_viewed_but_not_changed(
    admin_client: Client, failed_entry: OutboxEntry
) -> None:
    url = reverse("admin:outbox_outboxmessage_change", args=[failed_entry.id])

    assert admin_client.get(url).status_code == 200
    response = admin_client.post(url, {"status": OutboxStatus.PENDING.value})

    assert response.status_code == 403
    assert models.OutboxMessage.objects.get(pk=failed_entry.id).status == OutboxStatus.FAILED


def test_messages_cannot_be_added_or_deleted_in_the_admin(
    admin_client: Client, failed_entry: OutboxEntry
) -> None:
    add = admin_client.get(reverse("admin:outbox_outboxmessage_add"))
    delete = admin_client.post(
        reverse("admin:outbox_outboxmessage_delete", args=[failed_entry.id]), {"post": "yes"}
    )

    assert add.status_code == 403
    assert delete.status_code == 403
    assert models.OutboxMessage.objects.filter(pk=failed_entry.id).exists()
