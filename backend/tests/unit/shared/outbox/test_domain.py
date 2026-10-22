"""Outbox domain (ADR 0005): the message value object, the retry policy and the entry lifecycle."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from kospm.shared.domain import DomainError, new_id
from kospm.shared.outbox.domain import (
    JsonValue,
    OutboxChannel,
    OutboxEntry,
    OutboxMessage,
    OutboxRetryPolicy,
    OutboxStatus,
    OutboxTransitionError,
)

NOW = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)


def a_message(**payload: JsonValue) -> OutboxMessage:
    return OutboxMessage(
        channel=OutboxChannel.WHATSAPP,
        recipient="+306900000000",
        template="cleaning_assigned",
        payload=payload or {"property": "KOS-A1", "date": "2026-07-12"},
    )


# --- OutboxMessage -------------------------------------------------------------------------------


def test_message_is_a_value_object() -> None:
    assert a_message(code="KOS-A1") == a_message(code="KOS-A1")
    assert a_message(code="KOS-A1") != a_message(code="KOS-B2")


def test_message_payload_defaults_to_empty() -> None:
    message = OutboxMessage(channel=OutboxChannel.EMAIL, recipient="a@b.gr", template="welcome")
    assert message.payload == {}


def test_message_accepts_nested_json_and_greek_text() -> None:
    payload: dict[str, JsonValue] = {
        "name": "Μαρία",
        "count": 2,
        "late": False,
        "note": None,
        "tasks": [{"property": "KOS-A1", "order": 1}, {"property": "KOS-B2", "order": 2}],
    }
    assert OutboxMessage(
        channel=OutboxChannel.WHATSAPP, recipient="+30", template="plan", payload=payload
    ).payload == {**payload}


def test_message_keeps_its_own_copy_of_the_payload() -> None:
    payload: dict[str, JsonValue] = {"tasks": ["KOS-A1"]}
    message = OutboxMessage(
        channel=OutboxChannel.WHATSAPP, recipient="+30", template="plan", payload=payload
    )
    tasks = payload["tasks"]
    assert isinstance(tasks, list)
    tasks.append("KOS-B2")
    payload["extra"] = 1
    assert message.payload == {"tasks": ["KOS-A1"]}


@pytest.mark.parametrize(
    "bad_value",
    [
        1.5,  # float: money and quantities are never float (DOMAIN §2.5)
        Decimal("12.50"),  # Decimal: send str(money.rounded()) instead
        {"nested": 0.1},
        [1, 2.0],
        ("a", "b"),  # a tuple would come back from JSON as a list
        {1: "non-string key"},
        datetime(2026, 7, 11, tzinfo=UTC),  # send .isoformat()
        object(),
    ],
)
def test_message_rejects_payloads_that_are_not_plain_json(bad_value: object) -> None:
    with pytest.raises(TypeError, match="payload"):
        OutboxMessage(
            channel=OutboxChannel.WHATSAPP,
            recipient="+30",
            template="plan",
            payload={"value": bad_value},  # type: ignore[dict-item]
        )


@pytest.mark.parametrize("field", ["recipient", "template"])
@pytest.mark.parametrize("blank", ["", "   "])
def test_message_requires_recipient_and_template(field: str, blank: str) -> None:
    recipient = blank if field == "recipient" else "+30"
    template = blank if field == "template" else "plan"
    with pytest.raises(ValueError, match=field):
        OutboxMessage(channel=OutboxChannel.WHATSAPP, recipient=recipient, template=template)


def test_message_channel_accepts_the_stored_string_value() -> None:
    message = OutboxMessage(
        channel="WHATSAPP",  # type: ignore[arg-type]  # as read back from the database
        recipient="+30",
        template="plan",
    )
    assert message.channel is OutboxChannel.WHATSAPP
    with pytest.raises(ValueError, match="SMS"):
        OutboxMessage(channel="SMS", recipient="+30", template="plan")  # type: ignore[arg-type]


def test_channel_and_status_values_are_stable_strings() -> None:
    # Stored in the database: renaming a value needs a data migration.
    assert [c.value for c in OutboxChannel] == ["WHATSAPP", "EMAIL"]
    assert [s.value for s in OutboxStatus] == ["PENDING", "SENT", "FAILED"]


# --- OutboxRetryPolicy ---------------------------------------------------------------------------


def test_default_policy_matches_adr_0005() -> None:
    policy = OutboxRetryPolicy()
    assert policy.max_attempts == 5
    assert policy.base_delay == timedelta(minutes=1)
    assert policy.factor == 2
    assert policy.max_delay == timedelta(hours=1)


def test_backoff_doubles_from_the_base_delay_up_to_the_cap() -> None:
    policy = OutboxRetryPolicy(max_attempts=20)
    delays = [policy.delay_after(attempts) for attempts in range(1, 10)]
    assert delays == [
        timedelta(minutes=1),
        timedelta(minutes=2),
        timedelta(minutes=4),
        timedelta(minutes=8),
        timedelta(minutes=16),
        timedelta(minutes=32),
        timedelta(hours=1),
        timedelta(hours=1),
        timedelta(hours=1),
    ]


def test_backoff_never_overflows_for_large_attempt_counts() -> None:
    policy = OutboxRetryPolicy(max_attempts=10_000)
    assert policy.delay_after(5_000) == timedelta(hours=1)


def test_backoff_is_a_configuration_object() -> None:
    policy = OutboxRetryPolicy(
        max_attempts=3, base_delay=timedelta(seconds=30), factor=3, max_delay=timedelta(minutes=5)
    )
    assert [policy.delay_after(n) for n in (1, 2, 3, 4)] == [
        timedelta(seconds=30),
        timedelta(seconds=90),
        timedelta(seconds=270),
        timedelta(minutes=5),
    ]


def test_delay_is_only_defined_after_at_least_one_attempt() -> None:
    with pytest.raises(ValueError, match="attempts"):
        OutboxRetryPolicy().delay_after(0)


def test_policy_is_exhausted_at_max_attempts() -> None:
    policy = OutboxRetryPolicy(max_attempts=3)
    assert [policy.is_exhausted(n) for n in (0, 1, 2, 3, 4)] == [False, False, False, True, True]


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"max_attempts": 0}, "max_attempts"),
        ({"base_delay": timedelta(0)}, "base_delay"),
        ({"base_delay": timedelta(seconds=-1)}, "base_delay"),
        ({"factor": 0}, "factor"),
        ({"max_delay": timedelta(seconds=59)}, "max_delay"),
    ],
)
def test_invalid_policies_are_rejected(kwargs: dict[str, object], field: str) -> None:
    with pytest.raises(ValueError, match=field):
        OutboxRetryPolicy(**kwargs)  # type: ignore[arg-type]


# --- OutboxEntry ---------------------------------------------------------------------------------


def test_new_entry_is_pending_and_due_immediately() -> None:
    entry = OutboxEntry.new(a_message(), now=NOW)
    assert entry.status is OutboxStatus.PENDING
    assert entry.attempts == 0
    assert entry.created_at == NOW
    assert entry.next_attempt_at == NOW
    assert entry.sent_at is None
    assert entry.last_error == ""
    assert entry.is_due(NOW)
    assert not entry.is_due(NOW - timedelta(seconds=1))


def test_new_entry_gets_a_fresh_id_unless_one_is_given() -> None:
    assert OutboxEntry.new(a_message(), now=NOW).id != OutboxEntry.new(a_message(), now=NOW).id
    given = new_id()
    assert OutboxEntry.new(a_message(), now=NOW, id=given).id == given


def test_new_entry_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="naive"):
        OutboxEntry.new(a_message(), now=datetime(2026, 7, 11, 9, 0))  # noqa: DTZ001


def test_a_naive_time_leaves_the_entry_unchanged() -> None:
    naive = datetime(2026, 7, 11, 9, 5)  # noqa: DTZ001 - the point of the test
    entry = OutboxEntry.new(a_message(), now=NOW)
    with pytest.raises(ValueError, match="naive"):
        entry.mark_sent(at=naive)
    with pytest.raises(ValueError, match="naive"):
        entry.record_failure(at=naive, error="boom", policy=OutboxRetryPolicy())
    assert entry.status is OutboxStatus.PENDING
    assert entry.attempts == 0
    assert entry.sent_at is None
    assert entry.last_error == ""
    assert entry.next_attempt_at == NOW


def test_mark_sent() -> None:
    entry = OutboxEntry.new(a_message(), now=NOW)
    entry.mark_sent(at=NOW + timedelta(seconds=5))
    assert entry.status is OutboxStatus.SENT
    assert entry.sent_at == NOW + timedelta(seconds=5)
    assert entry.next_attempt_at is None
    assert not entry.is_due(NOW + timedelta(days=1))


def test_failure_schedules_the_next_attempt_with_backoff() -> None:
    policy = OutboxRetryPolicy()
    entry = OutboxEntry.new(a_message(), now=NOW)

    entry.record_failure(at=NOW, error="timeout", policy=policy)
    assert entry.status is OutboxStatus.PENDING
    assert entry.attempts == 1
    assert entry.last_error == "timeout"
    assert entry.next_attempt_at == NOW + timedelta(minutes=1)
    assert not entry.is_due(NOW + timedelta(seconds=59))
    assert entry.is_due(NOW + timedelta(minutes=1))

    second_try = NOW + timedelta(minutes=1)
    entry.record_failure(at=second_try, error="HTTP 503", policy=policy)
    assert entry.attempts == 2
    assert entry.last_error == "HTTP 503"
    assert entry.next_attempt_at == second_try + timedelta(minutes=2)


def test_entry_fails_after_exactly_max_attempts_failures() -> None:
    policy = OutboxRetryPolicy(max_attempts=3)
    entry = OutboxEntry.new(a_message(), now=NOW)
    at = NOW
    for _ in range(2):
        entry.record_failure(at=at, error="boom", policy=policy)
        assert entry.status is OutboxStatus.PENDING
        assert entry.next_attempt_at is not None
        at = entry.next_attempt_at

    entry.record_failure(at=at, error="still boom", policy=policy)
    assert entry.status is OutboxStatus.FAILED
    assert entry.attempts == 3
    assert entry.next_attempt_at is None
    assert entry.last_error == "still boom"
    assert not entry.is_due(at + timedelta(days=365))


def test_long_errors_are_truncated() -> None:
    entry = OutboxEntry.new(a_message(), now=NOW)
    entry.record_failure(at=NOW, error="x" * 5000, policy=OutboxRetryPolicy())
    assert entry.last_error == "x" * 2000


@pytest.mark.parametrize("final_status", [OutboxStatus.SENT, OutboxStatus.FAILED])
def test_only_pending_entries_can_be_sent_or_fail(final_status: OutboxStatus) -> None:
    policy = OutboxRetryPolicy(max_attempts=1)
    entry = OutboxEntry.new(a_message(), now=NOW)
    if final_status is OutboxStatus.SENT:
        entry.mark_sent(at=NOW)
    else:
        entry.record_failure(at=NOW, error="boom", policy=policy)
    assert entry.status is final_status

    with pytest.raises(OutboxTransitionError, match=final_status.value) as excinfo:
        entry.mark_sent(at=NOW)
    assert isinstance(excinfo.value, DomainError)
    with pytest.raises(OutboxTransitionError):
        entry.record_failure(at=NOW, error="again", policy=policy)
    assert entry.status is final_status


def test_entries_are_entities_compared_by_id() -> None:
    given = new_id()
    first = OutboxEntry.new(a_message(), now=NOW, id=given)
    again = OutboxEntry.new(a_message(code="other"), now=NOW, id=given)
    assert first == again
