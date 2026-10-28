# 0008 — Owner portal: React + Vite + TypeScript on a Django Ninja API (v3)

- Status: accepted; amended by 0017 (owner onboarding pages and the owner login are built in
  Phase 2b, server-rendered)
- Date: 2026-10-22

## Context
In v3, owners log in to see (DOMAIN.md §12):
- their properties and onboarding status;
- reservations and the money per reservation;
- payouts and approved charges;
- documents;
- the website-consent setting.

The UI is read-heavy and interactive, separate from the admin, and used on phones and desktops.

## Decision
A single-page app in `frontend/owner-portal/`, built with React, Vite and TypeScript, in Greek and
English. It talks to a JSON API built with Django Ninja in the `owner_portal` context.
- The API serves **read models** (the CQRS read side, Cosmic Python ch. 12) and never loads or
  changes aggregates directly.
- Writes, such as the website-consent toggle, are commands dispatched on the message bus.
- Authentication uses Django auth: email + password, with password reset. It is built in Phase 2b
  with the onboarding pages (ADR 0017).
- The portal is built in Phase 12.

## Consequences
- A second toolchain (Node, npm) enters the repo only in v3, so v1 and v2 stay pure Python.
- The API contract can be typed end to end: Ninja schemas produce OpenAPI, which can generate
  TypeScript types.
- Event handlers keep the read models up to date, and the models may lag slightly behind writes.
- An owner must only ever see their own data. Every query is scoped by `owner_id`, with tests.
- Session/CSRF or token authentication, and same-origin hosting behind Caddy, are decided in
  Phase 12. Any deviation from this ADR gets a new ADR.
