"""Django repository and Unit of Work for the Widget test aggregate.

The shape every bounded context follows from Phase 2 (Cosmic Python Appendix D): the repository
maps rows to domain objects (`to_domain` / `from_domain`), passes everything it returns through
`_track`, and writes the seen aggregates back in `_persist` when the Unit of Work commits, so
handlers never call save.
"""

from uuid import UUID

from django.db import DEFAULT_DB_ALIAS

from kospm.shared.adapters.django_unit_of_work import DjangoUnitOfWork
from kospm.shared.outbox.service_layer.ports import AbstractOutbox
from kospm.shared.unit_of_work import TrackingRepository
from tests.uow_testapp.domain import Widget
from tests.uow_testapp.models import WidgetRow


def to_domain(row: WidgetRow) -> Widget:
    return Widget(row.id, name=row.name, quantity=row.quantity)


def from_domain(widget: Widget) -> WidgetRow:
    return WidgetRow(id=widget.id, name=widget.name, quantity=widget.quantity)


class DjangoWidgetRepository(TrackingRepository[Widget]):
    def __init__(self, *, using: str = DEFAULT_DB_ALIAS) -> None:
        super().__init__()
        self._using = using

    def _add(self, widget: Widget) -> None:
        from_domain(widget).save(using=self._using, force_insert=True)

    def get(self, widget_id: UUID) -> Widget:
        return self._track(to_domain(WidgetRow.objects.using(self._using).get(pk=widget_id)))

    def _persist(self, widget: Widget) -> None:
        from_domain(widget).save(using=self._using, force_update=True)


class WidgetUnitOfWork(DjangoUnitOfWork):
    def __init__(self, *, outbox: AbstractOutbox, using: str = DEFAULT_DB_ALIAS) -> None:
        super().__init__(outbox=outbox, using=using)
        self.widgets = DjangoWidgetRepository(using=using)
