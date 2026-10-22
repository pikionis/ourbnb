"""A tiny aggregate used only to test DjangoUnitOfWork against a real table (Appendix D)."""

from dataclasses import dataclass
from uuid import UUID

from kospm.shared.domain import Aggregate, DomainEvent


@dataclass(frozen=True, kw_only=True)
class WidgetRestocked(DomainEvent):
    widget_id: UUID
    quantity: int


class Widget(Aggregate[UUID]):
    def __init__(self, id: UUID, *, name: str, quantity: int = 0) -> None:
        super().__init__(id)
        self.name = name
        self.quantity = quantity

    def restock(self, amount: int) -> None:
        self.quantity += amount
        self.events.append(WidgetRestocked(widget_id=self.id, quantity=self.quantity))
