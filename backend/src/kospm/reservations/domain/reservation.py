"""The Reservation entity (DOMAIN §6). It changes only through its ReservationCalendar."""

from datetime import time
from enum import StrEnum
from uuid import UUID

from kospm.reservations.domain.value_objects import Channel, StayDates
from kospm.shared.domain import Entity


class ReservationStatus(StrEnum):
    """Values are stored in the database."""

    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class Reservation(Entity[UUID]):
    """One stay at a property, booked on a channel.

    `external_uid` is the event's UID in the channel's feed (None for DIRECT). `stay_ended` says
    that its StayEnded was raised, or that the stay had ended before KosPM learned of it.
    """

    def __init__(
        self,
        reservation_id: UUID,
        *,
        channel: Channel,
        dates: StayDates,
        check_in_time: time,
        check_out_time: time,
        external_uid: str | None = None,
        confirmation_code: str = "",
        guest_name: str = "",
        status: ReservationStatus = ReservationStatus.CONFIRMED,
        stay_ended: bool = False,
    ) -> None:
        super().__init__(reservation_id)
        self.channel = Channel(channel)
        self.dates = dates
        self.check_in_time = check_in_time
        self.check_out_time = check_out_time
        self.external_uid = external_uid
        self.confirmation_code = confirmation_code
        self.guest_name = guest_name
        self.status = ReservationStatus(status)
        self.stay_ended = stay_ended

    @property
    def confirmed(self) -> bool:
        return self.status is ReservationStatus.CONFIRMED

    def __repr__(self) -> str:
        return (
            f"Reservation({self.id}, {self.channel.value}, "
            f"{self.dates.check_in}..{self.dates.check_out}, {self.status.value})"
        )
