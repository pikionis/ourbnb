"""DjangoEmailSender and ChannelRouter: emails leave through Django's email backend."""

import pytest
from django.core.mail import EmailMessage
from django.test import override_settings

from kospm.shared.outbox.adapters import ChannelRouter, DjangoEmailSender
from kospm.shared.outbox.domain import OutboxChannel, OutboxMessage
from kospm.shared.outbox.service_layer.ports import SendError
from tests.fakes import FakeSender

EMAIL = OutboxMessage(
    channel=OutboxChannel.EMAIL,
    recipient="maria@example.com",
    template="identity.confirmation",
    payload={"subject": "Επιβεβαιώστε το email σας", "body": "Γεια σας,\n\nlink\n"},
)
WHATSAPP = OutboxMessage(
    channel=OutboxChannel.WHATSAPP, recipient="+306900000001", template="cleaning_assigned"
)


@override_settings(DEFAULT_FROM_EMAIL="portal@example.com")
def test_sends_the_rendered_subject_and_body(mailoutbox: list[EmailMessage]) -> None:
    DjangoEmailSender().send(EMAIL)
    (sent,) = mailoutbox
    assert sent.to == ["maria@example.com"]
    assert sent.from_email == "portal@example.com"
    assert (sent.subject, sent.body) == ("Επιβεβαιώστε το email σας", "Γεια σας,\n\nlink\n")


def test_a_message_without_subject_or_body_is_a_send_error(
    mailoutbox: list[EmailMessage],
) -> None:
    broken = OutboxMessage(
        channel=OutboxChannel.EMAIL, recipient="maria@example.com", template="x", payload={}
    )
    with pytest.raises(SendError):
        DjangoEmailSender().send(broken)
    assert mailoutbox == []


@override_settings(EMAIL_BACKEND="tests.unit.shared.outbox.test_email_sender.FailingBackend")
def test_a_delivery_failure_is_a_send_error_so_the_worker_retries() -> None:
    with pytest.raises(SendError):
        DjangoEmailSender().send(EMAIL)


class FailingBackend:
    def __init__(self, **kwargs: object) -> None:
        pass

    def send_messages(self, messages: object) -> int:
        raise ConnectionRefusedError("SMTP server down")


def test_the_router_hands_each_message_to_the_sender_of_its_channel() -> None:
    emails, whatsapp = FakeSender(), FakeSender()
    router = ChannelRouter({OutboxChannel.EMAIL: emails, OutboxChannel.WHATSAPP: whatsapp})
    router.send(EMAIL)
    router.send(WHATSAPP)
    assert (emails.sent, whatsapp.sent) == ([EMAIL], [WHATSAPP])


def test_a_channel_without_a_sender_is_a_send_error() -> None:
    with pytest.raises(SendError):
        ChannelRouter({}).send(EMAIL)
