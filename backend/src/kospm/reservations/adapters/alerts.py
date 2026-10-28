"""Admin alerts as WhatsApp messages through the outbox (ADR 0005, 0011; DOMAIN §6).

The worker sends them only if the unit that queued them commits. The WhatsApp templates, with
these names and values, come with the WhatsApp adapter (Phase 6, `messaging/templates.py`); until
then the console sender prints the messages. Without a configured number, alerts are logged and
not queued: the admin's pages show the same state.
"""

import logging
from datetime import datetime

from kospm.reservations.domain.value_objects import Channel, StayDates
from kospm.reservations.service_layer.ports import AdminAlerts
from kospm.shared.domain import to_athens
from kospm.shared.outbox.domain import JsonValue, OutboxChannel, OutboxMessage
from kospm.shared.outbox.service_layer.ports import AbstractOutbox

logger = logging.getLogger(__name__)

CHANNEL_NAMES = {Channel.AIRBNB: "Airbnb", Channel.BOOKING: "Booking.com", Channel.DIRECT: "Direct"}


class OutboxAdminAlerts(AdminAlerts):
    def __init__(self, *, whatsapp_number: str) -> None:
        self._number = whatsapp_number.strip()

    def feed_failing(
        self,
        *,
        outbox: AbstractOutbox,
        property_code: str,
        property_name: str,
        channel: Channel,
        since: datetime,
    ) -> None:
        self._send(
            outbox,
            "admin_calendar_feed_failing",
            {
                "property": f"{property_code} {property_name}",
                "channel": CHANNEL_NAMES[channel],
                "since": to_athens(since).strftime("%d/%m %H:%M"),
            },
        )

    def event_to_review(
        self,
        *,
        outbox: AbstractOutbox,
        property_code: str,
        property_name: str,
        channel: Channel,
        dates: StayDates,
        reason: str,
    ) -> None:
        self._send(
            outbox,
            "admin_calendar_event_to_review",
            {
                "property": f"{property_code} {property_name}",
                "channel": CHANNEL_NAMES[channel],
                "dates": f"{dates.check_in:%d/%m}-{dates.check_out:%d/%m}",
                "reason": reason,
            },
        )

    def _send(self, outbox: AbstractOutbox, template: str, payload: dict[str, JsonValue]) -> None:
        if not self._number:
            logger.warning("no ADMIN_WHATSAPP_NUMBER: admin alert %s not queued", template)
            return
        outbox.enqueue(
            OutboxMessage(
                channel=OutboxChannel.WHATSAPP,
                recipient=self._number,
                template=template,
                payload=payload,
            )
        )
