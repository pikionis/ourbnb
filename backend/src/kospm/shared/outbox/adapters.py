"""Django adapters of the outbox ports (Cosmic Python ch. 2 and Appendix D).

- DjangoOutbox: `uow.outbox` in every Django Unit of Work. It writes the message in the caller's
  transaction, so the message exists only if the business change commits.
- DjangoOutboxRepository + DjangoOutboxUnitOfWork: what the worker uses to claim and save entries.
- ConsoleSender: the development MessageSender, which prints instead of sending.
- DjangoEmailSender: delivers emails through Django's email backend.
- ChannelRouter: hands each message to the sender of its channel.

Rows and domain objects are mapped by `to_domain` / `from_domain` / `update_from_domain`; the
ORM model stays free of rules.
"""

import json
import sys
from collections.abc import Mapping
from datetime import datetime
from typing import Final, Protocol, Self
from uuid import UUID

from django.core.mail import EmailMessage
from django.db import DEFAULT_DB_ALIAS, transaction

from kospm.shared.adapters.django_unit_of_work import DjangoUnitOfWork
from kospm.shared.clock import Clock
from kospm.shared.outbox import models
from kospm.shared.outbox.domain import OutboxChannel, OutboxEntry, OutboxMessage, OutboxStatus
from kospm.shared.outbox.service_layer.ports import (
    AbstractOutbox,
    MessageSender,
    OutboxRepository,
    SendError,
)
from kospm.shared.outbox.service_layer.worker import OutboxUnitOfWork

# The columns a delivery attempt changes; the message itself never changes after enqueue.
DELIVERY_FIELDS: Final = ("status", "attempts", "next_attempt_at", "sent_at", "last_error")


# --- mapping ------------------------------------------------------------------------------------


def to_domain(row: models.OutboxMessage) -> OutboxEntry:
    return OutboxEntry(
        id=row.id,
        message=OutboxMessage(
            channel=OutboxChannel(row.channel),
            recipient=row.recipient,
            template=row.template,
            payload=row.payload,
        ),
        status=OutboxStatus(row.status),
        attempts=row.attempts,
        created_at=row.created_at,
        next_attempt_at=row.next_attempt_at,
        sent_at=row.sent_at,
        last_error=row.last_error,
    )


def from_domain(entry: OutboxEntry) -> models.OutboxMessage:
    """A new, unsaved row holding every attribute of `entry`."""
    row = models.OutboxMessage(
        id=entry.id,
        channel=entry.message.channel.value,
        recipient=entry.message.recipient,
        template=entry.message.template,
        payload=dict(entry.message.payload),
        created_at=entry.created_at,
    )
    update_from_domain(row, entry)
    return row


def update_from_domain(row: models.OutboxMessage, entry: OutboxEntry) -> None:
    """Copy the delivery state (DELIVERY_FIELDS) of `entry` onto `row`."""
    row.status = entry.status.value
    row.attempts = entry.attempts
    row.next_attempt_at = entry.next_attempt_at
    row.sent_at = entry.sent_at
    row.last_error = entry.last_error


# --- the outbox port, used by handlers ------------------------------------------------------------


class DjangoOutbox(AbstractOutbox):
    """Writes messages to the outbox table inside the caller's Unit of Work."""

    def __init__(self, clock: Clock, *, using: str = DEFAULT_DB_ALIAS) -> None:
        self._clock = clock
        self._using = using

    def enqueue(self, message: OutboxMessage) -> None:
        # In autocommit the row would be stored at once, even if the business change then fails:
        # exactly what the transactional outbox exists to prevent.
        if not transaction.get_connection(self._using).in_atomic_block:
            raise RuntimeError(
                "enqueue outside a UnitOfWork: call uow.outbox.enqueue() inside `with uow:`"
            )
        entry = OutboxEntry.new(message, now=self._clock.now())
        from_domain(entry).save(using=self._using, force_insert=True)


# --- the worker's repository and Unit of Work ---------------------------------------------------


class DjangoOutboxRepository(OutboxRepository):
    """Claims entries with SELECT ... FOR UPDATE SKIP LOCKED: concurrent workers never collide.

    Lives for one unit only (DjangoOutboxUnitOfWork creates a new one each time): it keeps the
    rows it claimed, so that `save` updates exactly those rows.
    """

    def __init__(self, *, using: str = DEFAULT_DB_ALIAS) -> None:
        self._using = using
        self._claimed: dict[UUID, models.OutboxMessage] = {}

    def claim_next_due(self, now: datetime) -> OutboxEntry | None:
        row = (
            models.OutboxMessage.objects.using(self._using)
            .select_for_update(skip_locked=True)
            .filter(status=OutboxStatus.PENDING.value, next_attempt_at__lte=now)
            .order_by("next_attempt_at", "created_at", "id")
            .first()
        )
        if row is None:
            return None
        self._claimed[row.id] = row
        return to_domain(row)

    def save(self, entry: OutboxEntry) -> None:
        row = self._claimed.get(entry.id)
        if row is None:
            raise ValueError(
                f"outbox entry {entry.id} was not returned by claim_next_due in this unit"
            )
        update_from_domain(row, entry)
        row.save(using=self._using, update_fields=DELIVERY_FIELDS)


class DjangoOutboxUnitOfWork(DjangoUnitOfWork, OutboxUnitOfWork):
    """The worker's Unit of Work: one short transaction per message."""

    def __enter__(self) -> Self:
        # Open the transaction first: entering twice raises there, before the open unit's
        # repository (and the rows it claimed) could be replaced.
        unit = super().__enter__()
        self.entries = DjangoOutboxRepository(using=self.using)
        return unit


# --- senders ------------------------------------------------------------------------------------


class TextStream(Protocol):
    """Where ConsoleSender writes: a text file such as sys.stdout, or a management command's
    `self.stdout` (Django's OutputWrapper, which is not a typing.TextIO)."""

    def write(self, text: str, /) -> object: ...

    def flush(self) -> None: ...


class ConsoleSender:
    """MessageSender for development: prints each message as one line instead of sending it.

    Writes to `stream`, or to the current `sys.stdout` when none is given (resolved at send time,
    so redirected or captured output is honoured). Greek text is printed as is; a console that
    cannot encode it gets backslash escapes rather than a failed delivery.
    """

    def __init__(self, stream: TextStream | None = None) -> None:
        self._stream = stream

    def send(self, message: OutboxMessage) -> None:
        stream = self._stream if self._stream is not None else sys.stdout
        payload = json.dumps(message.payload, ensure_ascii=False)
        line = f"[outbox] {message.channel} to {message.recipient}: {message.template} {payload}\n"
        stream.write(_encodable(line, stream))
        stream.flush()


def _encodable(text: str, stream: TextStream) -> str:
    encoding = getattr(stream, "encoding", None)
    if not encoding:  # e.g. io.StringIO: any text goes
        return text
    return text.encode(encoding, errors="backslashreplace").decode(encoding)


class DjangoEmailSender:
    """MessageSender for email through Django's EMAIL_BACKEND: SMTP in production, the console in
    development, memory in tests (ADR 0017).

    The message is rendered when it is enqueued: its payload holds the `subject` and the plain
    text `body`; the sender only delivers them, from DEFAULT_FROM_EMAIL.
    """

    def send(self, message: OutboxMessage) -> None:
        subject = message.payload.get("subject")
        body = message.payload.get("body")
        if not isinstance(subject, str) or not isinstance(body, str):
            raise SendError(f"{message.template}: an email needs a text subject and body")
        try:
            EmailMessage(subject=subject, body=body, to=[message.recipient]).send()
        except OSError as error:  # smtplib's errors are OSErrors too
            # The entry holds the recipient; the error (stored and logged) does not repeat it.
            raise SendError(f"{message.template}: {error}") from error


class ChannelRouter:
    """MessageSender that hands each message to the sender of its channel."""

    def __init__(self, senders: Mapping[OutboxChannel, MessageSender]) -> None:
        self._senders = dict(senders)

    def send(self, message: OutboxMessage) -> None:
        sender = self._senders.get(message.channel)
        if sender is None:
            raise SendError(f"no sender delivers {message.channel} messages")
        sender.send(message)
