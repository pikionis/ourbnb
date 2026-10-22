"""Outbox domain (ADR 0005, transactional outbox): what to send, when to retry, when to give up.

A handler never talks to WhatsApp or email itself. It enqueues an OutboxMessage in the same
transaction as its aggregate changes (`uow.outbox.enqueue(...)`), and the `process_outbox` worker
delivers it later through a MessageSender port. OutboxEntry is the stored message plus its
delivery state. OutboxRetryPolicy is a configuration object (CLAUDE.md: policies the business may
change are configuration, not constants inside algorithms).

Pure Python: the Django model and repository live in `models.py` and `adapters.py`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, Self
from uuid import UUID

from kospm.shared.domain import DomainError, Entity, new_id, require_aware

# Longest error text kept on an entry: enough for a provider's error body, bounded for the table.
MAX_ERROR_LENGTH: Final = 2000


class OutboxChannel(StrEnum):
    """How a message leaves the system. Values are stored in the database."""

    WHATSAPP = "WHATSAPP"
    EMAIL = "EMAIL"


class OutboxStatus(StrEnum):
    """Delivery state of an entry. Values are stored in the database."""

    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


# What a payload may contain: exactly what JSON round-trips unchanged. No float (DOMAIN §2.5) and
# no Decimal: amounts travel as strings, e.g. str(money.rounded()).
type JsonValue = bool | int | str | list[JsonValue] | dict[str, JsonValue] | None


class OutboxTransitionError(DomainError):
    """Only a PENDING entry can be marked sent or record another failure."""


@dataclass(frozen=True, kw_only=True)
class OutboxMessage:
    """Value object: one external message to deliver, e.g. a WhatsApp template with its values.

    Validated on creation, so a bad payload fails in the handler that builds it (inside its
    transaction, with a useful stack trace) instead of in the worker much later. The payload is
    copied, so later changes to the caller's dict cannot alter an enqueued message. Not hashable:
    the payload is a dict.
    """

    channel: OutboxChannel
    recipient: str
    template: str
    payload: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Coercion accepts the stored string value too (OutboxChannel("WHATSAPP")).
        object.__setattr__(self, "channel", OutboxChannel(self.channel))
        _require_text(self.recipient, "recipient")
        _require_text(self.template, "template")
        object.__setattr__(self, "payload", _json_object(self.payload, "payload"))


@dataclass(frozen=True, kw_only=True)
class OutboxRetryPolicy:
    """Exponential backoff: retry after base_delay, then x factor each time, at most max_delay.

    After `max_attempts` failed attempts the entry is FAILED and needs the admin's attention.
    Defaults (ADR 0014; the OUTBOX_* settings override them): 5 attempts, 1 min, x2, capped at
    1 h, i.e. retries after 1, 2, 4, 8 min.
    """

    max_attempts: int = 5
    base_delay: timedelta = timedelta(minutes=1)
    factor: int = 2
    max_delay: timedelta = timedelta(hours=1)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {self.max_attempts}")
        if self.base_delay <= timedelta(0):
            raise ValueError(f"base_delay must be positive, got {self.base_delay}")
        if self.factor < 1:
            raise ValueError(f"factor must be at least 1 (1 = constant delay), got {self.factor}")
        if self.max_delay < self.base_delay:
            raise ValueError(f"max_delay {self.max_delay} is shorter than base_delay")

    def delay_after(self, attempts: int) -> timedelta:
        """Wait before the next try, after `attempts` failed attempts (1, 2, ...)."""
        if attempts < 1:
            raise ValueError(f"attempts must be at least 1, got {attempts}")
        # Integer microseconds: exact (no float), and capped while growing, so a large attempt
        # count can neither overflow timedelta nor build a huge power.
        delay = self.base_delay // _MICROSECOND
        cap = self.max_delay // _MICROSECOND
        growths = attempts - 1 if self.factor > 1 else 0
        while growths and delay < cap:
            delay *= self.factor
            growths -= 1
        return min(delay, cap) * _MICROSECOND

    def is_exhausted(self, attempts: int) -> bool:
        """True when `attempts` failed attempts mean: stop retrying."""
        return attempts >= self.max_attempts


class OutboxEntry(Entity[UUID]):
    """A stored OutboxMessage and its delivery state: PENDING -> SENT, or PENDING -> FAILED.

    `attempts` counts failed delivery attempts (it drives the backoff). `next_attempt_at` is set
    only while PENDING. Delivery is at-least-once (ADR 0005), so templates must be harmless when
    delivered twice.
    """

    def __init__(
        self,
        *,
        id: UUID,
        message: OutboxMessage,
        status: OutboxStatus,
        attempts: int,
        created_at: datetime,
        next_attempt_at: datetime | None,
        sent_at: datetime | None,
        last_error: str,
    ) -> None:
        super().__init__(id)
        self.message = message
        self.status = status
        self.attempts = attempts
        self.created_at = created_at
        self.next_attempt_at = next_attempt_at
        self.sent_at = sent_at
        self.last_error = last_error

    @classmethod
    def new(cls, message: OutboxMessage, *, now: datetime, id: UUID | None = None) -> Self:
        """A fresh PENDING entry, due immediately."""
        require_aware(now)
        return cls(
            id=id if id is not None else new_id(),
            message=message,
            status=OutboxStatus.PENDING,
            attempts=0,
            created_at=now,
            next_attempt_at=now,
            sent_at=None,
            last_error="",
        )

    def is_due(self, now: datetime) -> bool:
        return (
            self.status == OutboxStatus.PENDING
            and self.next_attempt_at is not None
            and self.next_attempt_at <= now
        )

    def mark_sent(self, *, at: datetime) -> None:
        # Validate everything before changing anything: no half-applied transition.
        self._require_pending("marked as sent")
        require_aware(at)
        self.status = OutboxStatus.SENT
        self.sent_at = at
        self.next_attempt_at = None

    def record_failure(self, *, at: datetime, error: str, policy: OutboxRetryPolicy) -> None:
        """Count a failed attempt: schedule the next one with backoff, or give up (FAILED)."""
        self._require_pending("retried")
        require_aware(at)
        self.attempts += 1
        self.last_error = error[:MAX_ERROR_LENGTH]
        if policy.is_exhausted(self.attempts):
            self.status = OutboxStatus.FAILED
            self.next_attempt_at = None
        else:
            self.next_attempt_at = at + policy.delay_after(self.attempts)

    def _require_pending(self, action: str) -> None:
        if self.status != OutboxStatus.PENDING:
            raise OutboxTransitionError(
                f"outbox entry {self.id} is {self.status}; only PENDING entries can be {action}"
            )


_MICROSECOND: Final = timedelta(microseconds=1)


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")


def _json_object(value: object, path: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{path} must be a mapping with str keys, got {type(value).__name__}")
    copied: dict[str, JsonValue] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{path} has a non-string key {key!r}: JSON object keys are strings")
        copied[key] = _json_value(item, f"{path}[{key!r}]")
    return copied


def _json_value(value: object, path: str) -> JsonValue:
    # bool is an int subclass; float and Decimal are not ints, so they fall through and fail.
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, list):
        return [_json_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, Mapping):
        return _json_object(value, path)
    raise TypeError(
        f"{path} is a {type(value).__name__}: a payload holds only None, bool, int, str, list "
        "and dict with str keys (no float or Decimal: send amounts as strings)"
    )
