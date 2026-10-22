# 0006 — Django admin as the back-office

- Status: accepted
- Date: 2026-10-22

## Context
In v1 the only back-office user is the admin (Petros). He onboards owners and properties, reviews
reservations and unclassified calendar events, watches the daily cleaning board, approves issues
and edits team and policy configuration. He works in Greek, with English available. A custom
back-office UI would delay v1 by months.

## Decision
The **Django admin** is the back-office. It runs in Greek and English (`LANGUAGE_CODE="el"`,
`LANGUAGES` el/en, `LocaleMiddleware`) with the custom user model `identity.User`.
- Admin classes are entrypoints in `<context>/entrypoints/admin.py`. `<context>/admin.py` is a
  one-line shim so that Django's autodiscovery finds them.
- State changes with business rules go through **admin actions or custom admin views that dispatch
  commands on the message bus**. Examples are activating a property, reassigning a cleaning and
  approving an issue.
- Plain ModelAdmin editing is limited to data that has no invariants.

## Consequences
- Login, permissions, list filters, search and translations come for free.
- Admin forms must not bypass the domain. A ModelAdmin that saved an aggregate's status field
  directly would skip its invariants and events, so reviewers check for this.
- Sensitive fields (lockbox codes) are shown masked. Infrastructure tables such as the outbox are
  read-only.
- Owners and cleaners do not use the admin. Owners get the portal (ADR 0008), and cleaners get
  signed-link pages (ADR 0007).
- Richer screens (the daily board, the restock route) will need custom admin views and templates.
