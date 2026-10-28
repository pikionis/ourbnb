"""The Django Unit of Work of the identity context (Cosmic Python ch. 6, Appendix D)."""

from django.db import DEFAULT_DB_ALIAS

from kospm.identity.adapters.repository import DjangoOwnerAccountRepository
from kospm.identity.service_layer.unit_of_work import IdentityUnitOfWork
from kospm.shared.adapters.django_unit_of_work import DjangoUnitOfWork
from kospm.shared.outbox.service_layer.ports import AbstractOutbox


class DjangoIdentityUnitOfWork(DjangoUnitOfWork, IdentityUnitOfWork):
    def __init__(self, *, outbox: AbstractOutbox, using: str = DEFAULT_DB_ALIAS) -> None:
        super().__init__(outbox=outbox, using=using)
        self.accounts = DjangoOwnerAccountRepository(using=using)
