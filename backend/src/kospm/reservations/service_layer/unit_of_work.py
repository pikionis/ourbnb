"""Ports of the reservations context: its repository and Unit of Work (Cosmic Python ch. 2, 6).

Abstract on purpose: handlers depend on these, the Django adapters and the test fakes implement
them. Every query method passes what it returns through `_track`, so the Unit of Work knows which
calendars to write back and whose events to collect.
"""

import abc
from uuid import UUID

from kospm.reservations.domain.calendar import ReservationCalendar
from kospm.shared.unit_of_work import AbstractUnitOfWork, TrackingRepository


class CalendarRepository(TrackingRepository[ReservationCalendar]):
    @abc.abstractmethod
    def get(self, property_id: UUID, *, expected_version: int | None = None) -> ReservationCalendar:
        """The calendar of this property; raises CalendarNotFound.

        `expected_version` is the version a form showed: if the stored one differs, or another
        unit saves before this one commits, ConcurrencyError (ADR 0016).
        """

    @abc.abstractmethod
    def find(self, property_id: UUID) -> ReservationCalendar | None:
        """The calendar of this property, if the reservations context knows the property."""


class ReservationsUnitOfWork(AbstractUnitOfWork):
    """One unit of work over the reservation calendars."""

    calendars: CalendarRepository
