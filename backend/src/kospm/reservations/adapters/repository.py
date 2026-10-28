"""The Django repository of the reservations context (Cosmic Python ch. 2, Appendix D).

A ReservationCalendar is a `PropertyCalendar` row and its child rows. `calendar_to_domain` and
`calendar_values` map between them: the values include a snapshot of the children, so a change to
any reservation, feed, waiting event or answer bumps the root's version (ADR 0016) and rewrites
the children.

A feed's sync bookkeeping (its ETag, Last-Modified and when it was last read) is no change of the
calendar: it is left out of the snapshot and written on its own, without the version, and only to
the feed that still has the URL that was read. So a sync that finds nothing new never refuses the
admin's open forms, whatever validators the platform sends.

Children are written in place by their natural keys (a feed by channel, a waiting event or an
answer by channel and UID), so their rows keep their keys and the admin's actions keep naming
them; of the reservations, only the changed ones are written.
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
    table returns them by date, the aggregate keeps them as it met them) and the feeds' sync
    bookkeeping (written apart)."""
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
                    (
                        replace(feed, etag="", last_modified="", last_synced_at=None)
                        for feed in calendar.feeds
                    ),
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


def _bookkeeping(feed: Feed) -> tuple[str, str, str, datetime | None]:
    """A feed's URL and sync bookkeeping."""
    return (feed.url, feed.etag, feed.last_modified, feed.last_synced_at)


class DjangoCalendarRepository(VersionedDjangoRepository[ReservationCalendar], CalendarRepository):
    model = models.PropertyCalendar
    id_field = "property_id"

    def __init__(self, *, using: str = DEFAULT_DB_ALIAS) -> None:
        super().__init__(using=using)
        # What the tables hold for each calendar of this unit: its feeds' sync bookkeeping, and
        # its reservations (only those that differ are written back).
        self._stored_bookkeeping: dict[UUID, dict[str, tuple[str, str, str, datetime | None]]] = {}
        self._stored_reservations: dict[UUID, dict[UUID, tuple[Any, ...]]] = {}

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
        if row.property_id not in self._stored_bookkeeping:  # the unit's first look at it
            self._stored_bookkeeping[row.property_id] = {
                feed.channel: (feed.url, feed.etag, feed.last_modified, feed.last_synced_at)
                for feed in row.feeds.all()
            }
            self._stored_reservations[row.property_id] = {
                reservation.id: _reservation_values(_reservation(reservation))
                for reservation in row.reservations.all()
            }
        return calendar

    def _add(self, calendar: ReservationCalendar) -> None:
        super()._add(calendar)
        self._now_stored(calendar)

    def _persist(self, calendar: ReservationCalendar) -> None:
        super()._persist(calendar)
        self._write_bookkeeping(calendar)
        self._now_stored(calendar)

    def _write_bookkeeping(self, calendar: ReservationCalendar) -> None:
        """Each feed's ETag, Last-Modified and last read, without the version: written only to
        the feed that still has the URL that was read, and only when they changed."""
        stored = self._stored_bookkeeping.get(calendar.id, {})
        for feed in calendar.feeds:
            if stored.get(feed.channel.value) == _bookkeeping(feed):
                continue
            models.CalendarFeed.objects.using(self.using).filter(
                calendar_id=calendar.id, channel=feed.channel.value, url=feed.url
            ).update(
                etag=feed.etag, last_modified=feed.last_modified, last_synced_at=feed.last_synced_at
            )

    def _now_stored(self, calendar: ReservationCalendar) -> None:
        self._stored_bookkeeping[calendar.id] = {
            feed.channel.value: _bookkeeping(feed) for feed in calendar.feeds
        }
        self._stored_reservations[calendar.id] = {
            reservation.id: _reservation_values(reservation)
            for reservation in calendar.reservations
        }

    def forget(self) -> None:
        super().forget()
        self._stored_bookkeeping.clear()
        self._stored_reservations.clear()

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
        """Write the children in place, by their natural keys. Reservations: the changed ones
        are updated first (a cancelled one frees its event for a new one), then the new ones are
        added; they are never deleted."""
        db, root = self.using, calendar.id
        stored = self._stored_reservations.get(root, {})
        rows = {r.id: self._reservation_row(root, r) for r in calendar.reservations}
        models.Reservation.objects.using(db).bulk_update(
            [
                rows[r.id]
                for r in calendar.reservations
                if r.id in stored and stored[r.id] != _reservation_values(r)
            ],
            fields=_RESERVATION_FIELDS,
        )
        models.Reservation.objects.using(db).bulk_create(
            [rows[r.id] for r in calendar.reservations if r.id not in stored]
        )
        _write_by_key(
            models.CalendarFeed.objects.using(db).filter(calendar_id=root),
            ("channel",),
            {
                (feed.channel.value,): {
                    "url": feed.url,
                    "failing_since": feed.failing_since,
                    "alerted": feed.alerted,
                    "accept_empty": feed.accept_empty,
                    "etag": feed.etag,
                    "last_modified": feed.last_modified,
                    "last_synced_at": feed.last_synced_at,
                }
                for feed in calendar.feeds
            },
            calendar_id=root,
        )
        _write_by_key(
            models.WaitingCalendarEvent.objects.using(db).filter(calendar_id=root),
            ("channel", "uid"),
            {
                (event.channel.value, event.uid): {
                    "check_in_date": event.dates.check_in,
                    "check_out_date": event.dates.check_out,
                    "reason": event.reason.value,
                    "confirmation_code": event.confirmation_code,
                }
                for event in calendar.waiting
            },
            calendar_id=root,
        )
        _write_by_key(
            models.CalendarDecision.objects.using(db).filter(calendar_id=root),
            ("channel", "uid"),
            {
                (channel.value, uid): {"decision": kind.value}
                for (channel, uid), kind in calendar.decisions.items()
            },
            calendar_id=root,
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


def _write_by_key(
    rows: Any,
    key: tuple[str, ...],
    wanted: dict[tuple[Any, ...], dict[str, Any]],
    **parent: Any,
) -> None:
    """Make the child rows of `rows` the `wanted` ones, by natural key: a row whose values differ
    is updated in place, a missing one is added, one no longer wanted is deleted."""
    stored = {tuple(getattr(row, name) for name in key): row for row in rows}
    for natural_key, values in wanted.items():
        row = stored.pop(natural_key, None)
        if row is None:
            rows.model.objects.using(rows.db).create(
                **parent, **dict(zip(key, natural_key, strict=True)), **values
            )
        elif any(getattr(row, name) != value for name, value in values.items()):
            rows.model.objects.using(rows.db).filter(pk=row.pk).update(**values)
    if stored:
        rows.model.objects.using(rows.db).filter(
            pk__in=[row.pk for row in stored.values()]
        ).delete()
