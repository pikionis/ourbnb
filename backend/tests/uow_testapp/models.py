"""Models of the Unit of Work test app: one table for the Widget test aggregate."""

from django.db import models


class WidgetRow(models.Model):
    """ORM row of a Widget (tests.uow_testapp.domain). Infrastructure only."""

    id = models.UUIDField(primary_key=True)
    name = models.CharField(max_length=100)
    quantity = models.IntegerField()

    def __str__(self) -> str:
        return f"{self.name} ({self.quantity})"
