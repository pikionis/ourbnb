"""ConsoleSender: the development MessageSender, which prints messages instead of sending them."""

import io

import pytest

from kospm.shared.outbox.adapters import ConsoleSender
from kospm.shared.outbox.domain import OutboxChannel, OutboxMessage
from kospm.shared.outbox.service_layer.ports import MessageSender

MESSAGE = OutboxMessage(
    channel=OutboxChannel.WHATSAPP,
    recipient="+306900000001",
    template="cleaning_assigned",
    payload={"cleaner": "Μαρία", "property": "KOS-A1", "tasks": [1, 2]},
)


def test_it_writes_channel_recipient_template_and_payload_on_one_line() -> None:
    stream = io.StringIO()
    sender: MessageSender = ConsoleSender(stream)

    sender.send(MESSAGE)

    output = stream.getvalue()
    assert output.endswith("\n")
    assert output.count("\n") == 1
    for expected in ("WHATSAPP", "+306900000001", "cleaning_assigned", '"tasks": [1, 2]'):
        assert expected in output


def test_greek_text_is_printed_readable_not_escaped() -> None:
    stream = io.StringIO()

    ConsoleSender(stream).send(MESSAGE)

    assert '"cleaner": "Μαρία"' in stream.getvalue()


def test_each_message_gets_its_own_line() -> None:
    stream = io.StringIO()
    sender = ConsoleSender(stream)
    email = OutboxMessage(channel=OutboxChannel.EMAIL, recipient="owner@example.com", template="x")

    sender.send(MESSAGE)
    sender.send(email)

    first, second = stream.getvalue().splitlines()
    assert "WHATSAPP" in first
    assert "EMAIL" in second
    assert "owner@example.com" in second


def test_a_console_that_cannot_encode_greek_gets_escapes_instead_of_an_error() -> None:
    # e.g. a Windows console on code page 437: the dev sender must never fail a delivery.
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="ascii")

    ConsoleSender(stream).send(MESSAGE)
    stream.flush()

    output = raw.getvalue().decode("ascii")
    assert "+306900000001" in output
    assert "\\u039c\\u03b1\\u03c1\\u03af\\u03b1" in output  # the Greek name, escaped


def test_by_default_it_writes_to_the_current_standard_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ConsoleSender().send(MESSAGE)

    assert "cleaning_assigned" in capsys.readouterr().out
