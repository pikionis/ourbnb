"""The Django Unit of Work of the reservations context (Cosmic Python ch. 6, Appendix D)."""

from django.db import DEFAULT_DB_ALIAS

from kospm.reservations.adapters.repository import DjangoCalendarRepository
from kospm.reservations.service_layer.unit_of_work import ReservationsUnitOfWork
from kospm.shared.adapters.django_unit_of_work import DjangoUnitOfWork
from kospm.shared.outbox.service_layer.ports import AbstractOutbox


class DjangoReservationsUnitOfWork(DjangoUnitOfWork, ReservationsUnitOfWork):
    def __init__(self, *, outbox: AbstractOutbox, using: str = DEFAULT_DB_ALIAS) -> None:
        super().__init__(outbox=outbox, using=using)
        self.calendars = DjangoCalendarRepository(using=using)
