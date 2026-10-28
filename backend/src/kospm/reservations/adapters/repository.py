"""The Django repository of the reservations context (Cosmic Python ch. 2, Appendix D).

A ReservationCalendar is a `PropertyCalendar` row and its child rows. `calendar_to_domain` and
`calendar_values` map between them: the values include a snapshot of the children, so a change to
any reservation, feed, waiting event or answer bumps the root's version (ADR 0016) and rewrites
the children.

When a feed was last read is not a change of the calendar: it is left out of the snapshot and
written on its own, without the version, so a sync that finds nothing new never refuses the
admin's open forms.
"""

from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import DEFAULT_DB_ALIAS

from kospm.reservations import models
from kospm.reservations.domain.calendar import (
    Feed,
    PropertyDetails,
    ReservationCalendar,
    ReviewReason,
    WaitingEvent,
)
from kospm.reservations.domain.errors import CalendarNotFound
from kospm.reservations.domain.reservation import Reservation, ReservationStatus
from kospm.reservations.domain.value_objects import Channel, EventKind, StayDates
from kospm.reservations.service_layer.unit_of_work import CalendarRepository
from kospm.shared.adapters.versioned_repository import VersionedDjangoRepository

_CHILDREN = "children"  # a key of the values that is not a column of the root's row
_RESERVATION_FIELDS = (
    "channel",
    "external_uid",
    "confirmation_code",
    "check_in_date",
    "check_out_date",
    "check_in_time",
    "check_out_time",
    "status",
    "guest_name",
    "stay_ended",
)


def calendar_to_domain(row: models.PropertyCalendar) -> ReservationCalendar:
    return ReservationCalendar(
        row.property_id,
        details=PropertyDetails(
            code=row.code,
            name=row.name,
            active=row.active,
            check_in_time=row.check_in_time,
            check_out_time=row.check_out_time,
        ),
        feeds=[
            Feed(
                Channel(feed.channel),
                feed.url,
                failing_since=feed.failing_since,
                alerted=feed.alerted,
                accept_empty=feed.accept_empty,
                etag=feed.etag,
                last_modified=feed.last_modified,
                last_synced_at=feed.last_synced_at,
            )
            for feed in row.feeds.all()
        ],
        reservations=[_reservation(reservation) for reservation in row.reservations.all()],
        waiting=[
            WaitingEvent(
                Channel(event.channel),
                event.uid,
                StayDates(event.check_in_date, event.check_out_date),
                ReviewReason(event.reason),
                event.confirmation_code,
            )
            for event in row.waiting.all()
        ],
        decisions={
            (Channel(decision.channel), decision.uid): EventKind(decision.decision)
            for decision in row.decisions.all()
        },
    )


def _reservation(row: models.Reservation) -> Reservation:
    return Reservation(
        row.id,
        channel=Channel(row.channel),
        dates=StayDates(row.check_in_date, row.check_out_date),
        check_in_time=row.check_in_time,
        check_out_time=row.check_out_time,
        external_uid=row.external_uid or None,
        confirmation_code=row.confirmation_code,
        guest_name=row.guest_name,
        status=ReservationStatus(row.status),
        stay_ended=row.stay_ended,
    )


def calendar_values(calendar: ReservationCalendar) -> dict[str, Any]:
    """The root row's columns, and a snapshot of the children that ignores their order (the
    table returns them by date, the aggregate keeps them as it met them)."""
    details = calendar.details
    return {
        "code": details.code,
        "name": details.name,
        "active": details.active,
        "check_in_time": details.check_in_time,
        "check_out_time": details.check_out_time,
        _CHILDREN: (
            tuple(
                sorted(
                    (replace(feed, last_synced_at=None) for feed in calendar.feeds),
                    key=lambda feed: feed.channel.value,
                )
            ),
            tuple(sorted((_reservation_values(r) for r in calendar.reservations), key=str)),
            tuple(sorted(calendar.waiting, key=repr)),
            tuple(
                sorted(
                    (channel.value, uid, kind.value)
                    for (channel, uid), kind in calendar.decisions.items()
                )
            ),
        ),
    }


def _reservation_values(reservation: Reservation) -> tuple[Any, ...]:
    return (
        reservation.id,
        reservation.channel.value,
        reservation.external_uid,
        reservation.confirmation_code,
        reservation.dates.check_in,
        reservation.dates.check_out,
        reservation.check_in_time,
        reservation.check_out_time,
        reservation.status.value,
        reservation.guest_name,
        reservation.stay_ended,
    )


class DjangoCalendarRepository(VersionedDjangoRepository[ReservationCalendar], CalendarRepository):
    model = models.PropertyCalendar
    id_field = "property_id"

    def __init__(self, *, using: str = DEFAULT_DB_ALIAS) -> None:
        super().__init__(using=using)
        self._synced: dict[UUID, dict[str, datetime | None]] = {}

    def get(self, property_id: UUID, *, expected_version: int | None = None) -> ReservationCalendar:
        row = self._row(property_id)
        if row is None:
            raise CalendarNotFound(f"the reservations context knows no property {property_id}")
        return self._remember(row, expected_version)

    def find(self, property_id: UUID) -> ReservationCalendar | None:
        row = self._row(property_id)
        return None if row is None else self._remember(row, None)

    def _remember(
        self, row: models.PropertyCalendar, expected_version: int | None
    ) -> ReservationCalendar:
        calendar = self._load(
            calendar_to_domain(row), row.version, expected_version=expected_version
        )
        self._synced.setdefault(
            row.property_id, {feed.channel: feed.last_synced_at for feed in row.feeds.all()}
        )
        return calendar

    def _persist(self, calendar: ReservationCalendar) -> None:
        super()._persist(calendar)
        # When each feed was last read: no version, and only what changed.
        synced = self._synced.get(calendar.id, {})
        for feed in calendar.feeds:
            if synced.get(feed.channel.value, feed.last_synced_at) != feed.last_synced_at:
                models.CalendarFeed.objects.using(self.using).filter(
                    calendar_id=calendar.id, channel=feed.channel.value
                ).update(last_synced_at=feed.last_synced_at)
        self._synced[calendar.id] = {
            feed.channel.value: feed.last_synced_at for feed in calendar.feeds
        }

    def forget(self) -> None:
        super().forget()
        self._synced.clear()

    def _row(self, property_id: UUID) -> models.PropertyCalendar | None:
        return (
            models.PropertyCalendar.objects.using(self.using)
            .prefetch_related("feeds", "reservations", "waiting", "decisions")
            .filter(property_id=property_id)
            .first()
        )

    def _values(self, calendar: ReservationCalendar) -> dict[str, Any]:
        return calendar_values(calendar)

    def _columns(self, values: dict[str, Any]) -> dict[str, Any]:
        return {name: value for name, value in values.items() if name != _CHILDREN}

    def _write_children(self, calendar: ReservationCalendar) -> None:
        """Rewrite the children: feeds, waiting events and answers are replaced; reservations
        are updated in place (first, so a cancelled one frees its event for a new one) or
        added. Reservations are never deleted."""
        root = calendar.id
        db = self.using
        models.CalendarFeed.objects.using(db).filter(calendar_id=root).delete()
        models.CalendarFeed.objects.using(db).bulk_create(
            models.CalendarFeed(
                calendar_id=root,
                channel=feed.channel.value,
                url=feed.url,
                failing_since=feed.failing_since,
                alerted=feed.alerted,
                accept_empty=feed.accept_empty,
                etag=feed.etag,
                last_modified=feed.last_modified,
                last_synced_at=feed.last_synced_at,
            )
            for feed in calendar.feeds
        )
        stored = set(
            models.Reservation.objects.using(db)
            .filter(calendar_id=root)
            .values_list("id", flat=True)
        )
        rows = [self._reservation_row(root, reservation) for reservation in calendar.reservations]
        models.Reservation.objects.using(db).bulk_update(
            [row for row in rows if row.id in stored], fields=_RESERVATION_FIELDS
        )
        models.Reservation.objects.using(db).bulk_create(
            [row for row in rows if row.id not in stored]
        )
        models.WaitingCalendarEvent.objects.using(db).filter(calendar_id=root).delete()
        models.WaitingCalendarEvent.objects.using(db).bulk_create(
            models.WaitingCalendarEvent(
                calendar_id=root,
                channel=event.channel.value,
                uid=event.uid,
                check_in_date=event.dates.check_in,
                check_out_date=event.dates.check_out,
                reason=event.reason.value,
                confirmation_code=event.confirmation_code,
            )
            for event in calendar.waiting
        )
        models.CalendarDecision.objects.using(db).filter(calendar_id=root).delete()
        models.CalendarDecision.objects.using(db).bulk_create(
            models.CalendarDecision(
                calendar_id=root, channel=channel.value, uid=uid, decision=kind.value
            )
            for (channel, uid), kind in calendar.decisions.items()
        )

    @staticmethod
    def _reservation_row(root: UUID, reservation: Reservation) -> models.Reservation:
        return models.Reservation(
            id=reservation.id,
            calendar_id=root,
            channel=reservation.channel.value,
            external_uid=reservation.external_uid or "",
            confirmation_code=reservation.confirmation_code,
            check_in_date=reservation.dates.check_in,
            check_out_date=reservation.dates.check_out,
            check_in_time=reservation.check_in_time,
            check_out_time=reservation.check_out_time,
            status=reservation.status.value,
            guest_name=reservation.guest_name,
            stay_ended=reservation.stay_ended,
        )
