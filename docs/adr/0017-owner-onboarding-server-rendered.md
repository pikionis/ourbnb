# 0017 — Owner onboarding pages: server-rendered Django with Django auth (amends 0008)

- Status: accepted
- Date: 2026-10-28

## Context
In Phase 2b owners register, confirm their email, complete the activation checklist and upload
photos and their signed contract (DOMAIN §5, `docs/design/owner-onboarding-brief.md`). This
happens before v1 is finished. ADR 0008 planned a React single-page app for the v3 portal, a
read-heavy one, and kept Node out of v1 and v2.

The onboarding pages are a different kind of UI:
- they are mostly forms, with file uploads;
- the domain validates each save on an unsaved copy of the aggregate, as the admin does (ADR 0006);
- they must work on old phones and weak connections, in Greek and English.

## Decision
- **Pages.** Server-rendered Django pages (templates and Django forms) under `/owner/`.
  - Mobile first, and they work without JavaScript; any script is a small progressive
    enhancement.
  - One hand-written stylesheet, and no third-party scripts, fonts or CDNs.
- **Where the code lives.**
  - The account pages (sign-up, email verification, invitation, login, logout, password reset) are
    entrypoints of `identity`.
  - The onboarding pages are entrypoints of `properties` (`properties/entrypoints/portal/`).
  - The shared layout is in `backend/templates/portal/`.
- **Authentication.** Django auth with sessions, email + password, and CSRF on every form.
  - An owner account is an `identity.User` row linked to its owner by `owner_id`: an id, not a
    foreign key, because contexts are independent (ADR 0001, 0014).
  - Pages of `properties` read that id through `kospm.shared.adapters.portal`, never by importing
    `identity`.
- **Writes.** The pages send the same commands as the admin.
  - A command sent from the portal names the acting owner.
  - Its handler refuses another owner's property or account, and the edits DOMAIN §5 keeps for the
    IKE. This holds even though the page queries are already scoped to the owner.
- **Reads.** Pages read through owner-scoped queries that ask the domain what is missing
  (CQRS-lite, as the admin does).
- **Files.** Uploaded files are served by a view that checks ownership. Media is never public.
- **Emails.** Verification, invitation and reset emails are enqueued in the outbox in the unit that
  needs them (ADR 0005). The worker delivers them through Django's email backend: SMTP in
  production, the console in development, memory in tests.

## Consequences
- v1 and v2 stay pure Python and Node does not enter the repository, as ADR 0008 intended. Page
  tests use Django's test client.
- ADR 0008 is amended: owner authentication (Django auth, email + password, password reset) is
  built now. Phase 12 decides whether the v3 portal keeps these pages or rebuilds them in React;
  the accounts, the login and the commands stay either way.
- Richer interactions, such as a map picker or drag-and-drop uploads, can only be added as
  progressive enhancement.
- Login, sign-up and reset are throttled through Django's cache.
  - The default local-memory cache counts per process.
  - The deploy (Phase 7) configures a shared cache (the database cache) so the limits hold across
    workers.
- Links in emails are bearer secrets. They work once and expire (configuration). The outbox keeps
  the email until it is sent, so the database holds a valid link until then; database access is
  already full access.
