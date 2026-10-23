"""The Django Unit of Work of the properties context (Cosmic Python ch. 6, Appendix D)."""

from django.db import DEFAULT_DB_ALIAS

from kospm.properties.adapters.repository import DjangoOwnerRepository, DjangoPropertyRepository
from kospm.properties.service_layer.unit_of_work import PropertiesUnitOfWork
from kospm.shared.adapters.django_unit_of_work import DjangoUnitOfWork
from kospm.shared.outbox.service_layer.ports import AbstractOutbox


class DjangoPropertiesUnitOfWork(DjangoUnitOfWork, PropertiesUnitOfWork):
    def __init__(self, *, outbox: AbstractOutbox, using: str = DEFAULT_DB_ALIAS) -> None:
        super().__init__(outbox=outbox, using=using)
        self.owners = DjangoOwnerRepository(using=using)
        self.properties = DjangoPropertyRepository(using=using)
