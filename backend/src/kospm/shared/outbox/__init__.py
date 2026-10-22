"""Transactional outbox (ADR 0005): external side effects leave the system only after commit.

A Django app (label "outbox") laid out like a bounded context: `domain.py` (pure),
`service_layer/` (ports and the worker), `models.py` (ORM), `adapters.py`, `entrypoints/`.
Handlers reach it only through the `AbstractOutbox` port (`uow.outbox.enqueue(...)`).
"""
