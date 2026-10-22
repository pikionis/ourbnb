# 0001 — Modular monolith with DDD and hexagonal contexts

- Status: accepted
- Date: 2026-10-22

## Context
KosPM spans ten bounded contexts (DOMAIN.md §4): properties, reservations, housekeeping, messaging,
guests, local_guide, finance, compliance, owner_portal and identity. One developer builds and runs
it on one VPS. The contexts must stay separable while the product grows from v1 to v3, but
microservices would add network calls, distributed transactions and several deploys for no gain
at this scale.

## Decision
One Django project, one PostgreSQL database, one deploy: a **modular monolith**. Each bounded
context is a package `backend/src/kospm/<context>/` with the same layout: `domain/` (pure Python),
`service_layer/` (handlers, Unit of Work, ports), `adapters/` (repositories, ORM mapping, external
APIs), `entrypoints/` (admin, API, webhooks, management commands), `models.py` (ORM only) and
`apps.py`. Shared building blocks live in `kospm.shared`; wiring lives in `kospm/bootstrap.py`.
Django finds admin classes and commands at fixed paths, so `<context>/admin.py` and
`<context>/management/commands/<cmd>.py` are one-line shims that re-export from `entrypoints/`.

Contexts communicate **only** through commands and events on the message bus and by IDs
(`property_id`, `reservation_id`). They never import another context's domain, models or adapters.
A context keeps its own small copy of foreign data it needs (e.g. `PropertyOpsInfo` in
housekeeping). import-linter contracts enforce these rules in `make check` (ADR 0013).

## Consequences
- One database transaction covers an aggregate and its outbox rows, so no distributed sagas.
- Reactions across contexts happen after commit, so they are eventually consistent even in one process.
- Some data is duplicated across contexts on purpose and kept in sync by event handlers.
- A forbidden import fails CI, so the boundaries do not erode silently.
- A context could later be extracted into a service, because its boundary is already a message
  boundary. We do not plan for that.
