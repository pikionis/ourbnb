"""The email a lead becomes: in Greek, for the IKE, in Athens time."""

from datetime import UTC, datetime

from kospm.properties.adapters.lead_mailer import DjangoLeadMailer
from kospm.properties.domain.lead import ListedOnline, OwnerLead
from kospm.shared.outbox.domain import OutboxChannel

RECEIVED = datetime(2026, 7, 12, 9, 30, tzinfo=UTC)  # 12:30 in Athens


def lead(**changes: object) -> OwnerLead:
    fields: dict[str, object] = {
        "name": "Μαρία",
        "phone": "6940000000",
        "area": "Ψαλίδι",
        "bedrooms": "2",
        "listed_online": ListedOnline.BOTH,
        **changes,
    }
    return OwnerLead(**fields)  # type: ignore[arg-type]


def test_the_message_goes_to_the_ike_by_email() -> None:
    message = DjangoLeadMailer(recipient="ike@example.com").new_lead(lead(), RECEIVED)

    assert message.channel is OutboxChannel.EMAIL
    assert message.recipient == "ike@example.com"
    assert message.template == "properties.owner_lead"


def test_the_message_says_everything_the_form_asked_in_greek_and_athens_time() -> None:
    payload = DjangoLeadMailer(recipient="ike@example.com").new_lead(lead(), RECEIVED).payload
    body = str(payload["body"])

    assert payload["subject"] == "Νέο αίτημα εκτίμησης: Ψαλίδι"
    assert "Όνομα: Μαρία" in body
    assert "Τηλέφωνο: 6940000000" in body
    assert "Περιοχή: Ψαλίδι" in body
    assert "Υπνοδωμάτια: 2" in body
    assert "Ήδη σε Booking.com ή Airbnb: Ναι, και στα δύο" in body
    assert "Ημερομηνία: 12/07/2026 12:30" in body


def test_what_was_not_stated_says_so() -> None:
    payload = (
        DjangoLeadMailer(recipient="ike@example.com")
        .new_lead(lead(area=None, bedrooms=None, listed_online=None), RECEIVED)
        .payload
    )
    body = str(payload["body"])

    assert payload["subject"] == "Νέο αίτημα εκτίμησης: Δεν δηλώθηκε"
    assert "Περιοχή: Δεν δηλώθηκε" in body
    assert "Υπνοδωμάτια: Δεν δηλώθηκε" in body
    assert "Ήδη σε Booking.com ή Airbnb: Δεν δηλώθηκε" in body
