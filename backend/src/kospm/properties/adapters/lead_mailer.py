"""The email that tells the IKE about a lead from the public site (ADR 0021).

In Greek, whatever the visitor's browser asks for: its reader is the IKE, not the visitor.
"""

from datetime import datetime

from django.utils import translation
from django.utils.translation import gettext as _

from kospm.properties.domain.lead import ListedOnline, OwnerLead
from kospm.properties.service_layer.ports import LeadMailer
from kospm.shared.domain import to_athens
from kospm.shared.outbox.domain import OutboxChannel, OutboxMessage


class DjangoLeadMailer(LeadMailer):
    def __init__(self, *, recipient: str) -> None:
        self._recipient = recipient

    def new_lead(self, lead: OwnerLead, received_at: datetime) -> OutboxMessage:
        with translation.override("el"):
            subject, body = _compose(lead, received_at)
        return OutboxMessage(
            channel=OutboxChannel.EMAIL,
            recipient=self._recipient,
            template="properties.owner_lead",
            payload={"subject": subject, "body": body},
        )


def _compose(lead: OwnerLead, received_at: datetime) -> tuple[str, str]:
    not_stated = _("Not stated")
    area = lead.area or not_stated
    online = {
        ListedOnline.NO: _("Not yet"),
        ListedOnline.ONE: _("Yes, on one"),
        ListedOnline.BOTH: _("Yes, on both"),
        None: not_stated,
    }[lead.listed_online]
    lines = (
        _("A new request for an estimate from the website"),
        "",
        _("Name: %(value)s") % {"value": lead.name},
        _("Phone: %(value)s") % {"value": lead.phone},
        _("Area: %(value)s") % {"value": area},
        _("Bedrooms: %(value)s") % {"value": lead.bedrooms or not_stated},
        _("Already on Booking.com or Airbnb: %(value)s") % {"value": online},
        "",
        _("Date: %(value)s") % {"value": to_athens(received_at).strftime("%d/%m/%Y %H:%M")},
    )
    return _("New estimate request: %(area)s") % {"area": area}, "\n".join(lines) + "\n"
