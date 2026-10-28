"""Optimistic concurrency for Django repositories (ADR 0016; Cosmic Python ch. 7, Appendix D).

Every aggregate table has an integer `version` column. A repository remembers, per unit, the
version it loaded and a snapshot of the row values. When the unit commits:
- an aggregate whose values equal the snapshot is not written at all;
- a changed one is written with `UPDATE … SET version = version + 1 WHERE id = … AND version = v`,
  and if no row matches, another unit changed it first: ConcurrencyError, and the unit rolls back;
- one loaded with an `expected_version` (what a form showed) is confirmed even if unchanged, with
  `UPDATE … SET version = v WHERE id = … AND version = v`: the save fails if someone else saved
  in between, and the row stays held until the transaction ends, so the save's later commands
  cannot interleave with another writer either (ADR 0016).

Subclasses set `model`, map rows to aggregates (passing every loaded aggregate through
`_load(aggregate, row.version)`) and implement `_values()`, the column values of an aggregate
(everything but its id and `version`). The domain never sees the version. The aggregate's id is
stored in the column `id_field`: the primary key `id` by default, another unique column when the
table's key belongs to the framework (e.g. `identity.User`).

An aggregate with child rows in other tables (e.g. a calendar's reservations) also puts a
comparable snapshot of its children in `_values()`, under keys that `_columns()` leaves out, and
writes them in `_write_children()`. A change to a child then bumps the root's version like any
other change, so the version guards the whole aggregate.
"""

import abc
from collections.abc import Hashable
from dataclasses import dataclass, replace
from typing import Any, ClassVar

from django.db import DEFAULT_DB_ALIAS, IntegrityError, models, transaction

from kospm.shared.domain import Aggregate
from kospm.shared.unit_of_work import ConcurrencyError, TrackingRepository


@dataclass(frozen=True)
class _Snapshot:
    version: int
    values: dict[str, Any]
    confirm: bool = False  # write the version back at commit even if nothing changed


class VersionedDjangoRepository[A: Aggregate[Any]](TrackingRepository[A]):
    """A tracking repository that writes only changed aggregates, and only if nobody else did."""

    model: ClassVar[type[models.Model]]
    # The column that holds the aggregate's id (unique).
    id_field: ClassVar[str] = "id"

    def __init__(self, *, using: str = DEFAULT_DB_ALIAS) -> None:
        super().__init__()
        self.using = using
        self._snapshots: dict[Hashable, _Snapshot] = {}

    @abc.abstractmethod
    def _values(self, aggregate: A) -> dict[str, Any]:
        """Column values of `aggregate` (all but `id` and `version`), comparable with ==."""

    def _columns(self, values: dict[str, Any]) -> dict[str, Any]:
        """The values that are columns of the aggregate's row (by default all of them)."""
        return values

    def _write_children(self, aggregate: A) -> None:
        """Write the aggregate's child rows, after its own row (by default it has none)."""

    def _load(self, aggregate: A, version: int, *, expected_version: int | None = None) -> A:
        """Track a freshly mapped aggregate and remember what was read; returns what to hand out.

        If this unit has seen the aggregate already, that object is returned (identity map) and
        its original snapshot is kept. `expected_version` is the version the caller acted on (a
        form): another stored version raises ConcurrencyError now, and the commit confirms it.
        """
        if expected_version is not None and version != expected_version:
            raise ConcurrencyError(
                f"{type(aggregate).__name__} {aggregate.id} is at version {version}, not "
                f"{expected_version}: someone else saved it since it was shown; reload it and "
                "try again"
            )
        tracked = self._track(aggregate)
        if tracked is aggregate:
            self._snapshots[aggregate.id] = _Snapshot(version, self._values(aggregate))
        if expected_version is not None:
            self._snapshots[aggregate.id] = replace(self._snapshots[aggregate.id], confirm=True)
        return tracked

    def _add(self, aggregate: A) -> None:
        values = self._values(aggregate)
        try:
            with transaction.atomic(using=self.using):  # a savepoint: the unit stays usable
                self._rows().create(
                    **{self.id_field: aggregate.id}, version=0, **self._columns(values)
                )
                self._write_children(aggregate)
        except IntegrityError as error:
            raise self._duplicate(aggregate, error) from error
        self._snapshots[aggregate.id] = _Snapshot(0, values)

    def _duplicate(self, aggregate: A, error: IntegrityError) -> Exception:
        """What to raise when a unique constraint refuses a new or changed aggregate (a race lost
        against another unit). Override to name the business rule (see `violated_constraint`);
        by default the database error."""
        return error

    def _persist(self, aggregate: A) -> None:
        snapshot = self._snapshots[aggregate.id]
        values = self._values(aggregate)
        if values != snapshot.values:
            self._write(aggregate, snapshot, version=snapshot.version + 1, **self._columns(values))
            self._write_children(aggregate)
            self._snapshots[aggregate.id] = _Snapshot(snapshot.version + 1, values)
        elif snapshot.confirm:
            self._write(aggregate, snapshot, version=snapshot.version)
        # Otherwise read only in this unit: writing it back could only overwrite someone else.

    def _write(self, aggregate: A, snapshot: _Snapshot, **columns: Any) -> None:
        """UPDATE the row if it is still at the snapshot's version, else ConcurrencyError."""
        try:
            updated = (
                self._rows()
                .filter(**{self.id_field: aggregate.id}, version=snapshot.version)
                .update(**columns)
            )
        except IntegrityError as error:
            raise self._duplicate(aggregate, error) from error
        if updated != 1:
            raise ConcurrencyError(
                f"{type(aggregate).__name__} {aggregate.id} was changed by someone else since "
                "it was loaded; reload it and try again"
            )

    def forget(self) -> None:
        super().forget()
        self._snapshots.clear()

    def _rows(self) -> models.QuerySet[models.Model]:
        return self.model._default_manager.using(self.using).all()


def violated_constraint(error: IntegrityError) -> str:
    """The name of the constraint PostgreSQL reports for `error` ("" if it reports none).

    Read from psycopg's diagnostics, not from the message, which also quotes the values.
    """
    diagnostics = getattr(error.__cause__, "diag", None)
    return getattr(diagnostics, "constraint_name", None) or ""
