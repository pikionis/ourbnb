# 0020 — Back-office screens: React on a Django Ninja API, with live updates over SSE

- Status: proposed. Waits for Petros's approval; when accepted, it amends 0006, 0008 and 0010.
- Date: 2026-11-05

## Context
ADR 0006 made the Django admin the back-office so that v1 would not wait months for a custom UI, and
it expected richer screens to need custom admin views. Petros now wants a modern, interactive
back-office with live data, stays on Django, and wants later growth to stay possible.

A throwaway prototype of the daily cleaning board (Phase 5) shows what such a screen needs:
- moving a cleaning to another person by dragging, with the domain's answer before the drop
  ("3rd cleaning", "needs approval", "at the limit");
- the domain's reason on the screen when a move is refused;
- changes that arrive by themselves: a finished cleaning, a new reservation, a reported issue;
- one list of what needs a decision, drawn from several contexts;
- the 14-day load per day against capacity, from the provisional plan and the overload forecast.

Limits: one developer, one VPS (ADR 0001, 0010), and v1 must not be delayed by months. Business rules
stay in the domain and are never written twice.

## Decision
**Screens.** A single-page app in `frontend/back-office/`: React, Vite and TypeScript, the toolchain
of the owner portal (ADR 0008).
- It is built to static files that Caddy serves, so no Node process runs on the server.
- It lives at `/admin/` on `ourbnb.gr`, and the Django admin moves to `/admin/system/` (ADR 0021).
- Next.js stays for the public website (ADR 0009). Screens behind a login gain nothing from
  server-side rendering or SEO.

**One screen at a time.**
- The first is the today/tomorrow board of Phase 5, in place of custom admin templates.
- The other admin tasks of Phase 5 (team and policy configuration, issues, linen stock, restocks)
  stay in the Django admin until a screen replaces them.
- The Django admin remains the fallback. Every command a new screen sends stays reachable from an
  admin action until that screen has proven itself in production.

**API.** Django Ninja endpoints in `<context>/entrypoints/api.py`, under `/api/office/`.
- Reads return read models (CQRS, Cosmic Python ch. 12) from `adapters/queries.py`.
- Writes are commands on the message bus, exactly as the admin sends them (ADR 0006). They carry the
  version the screen was showing (ADR 0016).
- A `DomainError` becomes a JSON error with a stable code and a translated message.
- **Previews.** A read endpoint asks the domain what a command would do, on an unsaved copy of the
  aggregate, as the admin forms already do. This is how a row lights up during a drag, with no rule
  repeated in TypeScript.
- Authentication is the Django session with CSRF on the same origin, staff only, and that is the
  default of every endpoint. No tokens are kept in browser storage.
- Contexts stay separate (ADR 0001): each has its own endpoints, and a screen that spans contexts,
  such as the list of what needs a decision, calls several.

**Live updates: notify, then refetch, over Server-Sent Events.**
1. After a commit the bus dispatches events as it does today (ADR 0005, 0014).
2. An event handler publishes a hint through a `LiveUpdates` port, e.g. "the schedule of 17/7
   changed". A hint carries ids and a topic, never business data.
3. The adapter sends it with PostgreSQL `NOTIFY`, because scheduled jobs run in another container
   than the web server (ADR 0004, 0010) and Postgres is already there.
4. Each web process holds one `LISTEN` connection and passes hints to its open streams at
   `/api/office/live/`.
5. The screen refetches the read model that the hint names.

Hints are not durable, on purpose. The data is safe in the database, so a lost hint only delays a
screen. A screen refetches when its stream reconnects, and polls slowly (about once a minute) as a
safety net. A failing hint handler is logged and never stops a business change (ADR 0005).

**Web server.** Long-lived streams must not hold a worker, so Django runs under an ASGI server
(Uvicorn) instead of gunicorn's sync workers. Persistent database connections are turned off under
ASGI, as Django's documentation requires, with psycopg's pool if measurements ask for one.

**New dependencies, each justified when added.**
- Python: `django-ninja` (already planned, ADR 0002) and `uvicorn`.
- Build time only: React, Vite, TypeScript and a data-fetching cache.
- No new service: no Redis and no Django Channels.

## Consequences
- Phase 4 does not change: it is pure domain and knows nothing about screens.
- Any later client, such as a phone app or the owner portal, reuses the same commands and rules.
- Node enters the repo in v1, not v3 as ADR 0008 says. `make check` and CI gain the front end's lint,
  type checks and tests.
- The first screen carries the setup cost (API authentication, build, stream, Caddy routes), so
  Phase 5 grows. The screens after it are cheaper.
- For a while two UIs send the same commands. Reviewers check that neither holds a business rule.
- The API is a new attack surface. Staff-only access is tested per endpoint. Lockbox codes never
  appear in the board's read models or in hints.
- **"Live" has a limit.** Airbnb and Booking are read by iCal every 30 minutes (DOMAIN §2, ADR 0012).
  Only what happens inside KosPM is immediate, and a screen must show when each feed was last read.
- Replacing `NOTIFY` with another transport, such as Redis, touches only the adapter behind
  `LiveUpdates`.
- Translations must keep one source. CLAUDE.md requires Django `gettext`; serving the screens' texts
  through Django's `djangojs` catalog is the first option to try in Phase 5.
- Serving several companies is not decided here. One installation per company would need no change.
- When accepted, these must follow: the status of 0006, 0008 and 0010, the ADR table and Phases 5
  and 7 of `BUILD_PLAN.md`, and an import-linter contract that keeps `ninja` in `entrypoints/`.

## Alternatives considered
- **A theme on the Django admin (e.g. django-unfold).** A cheap improvement for list and edit pages,
  worth trying on its own for the screens that stay in the admin. It does not give a timeline board.
- **Server-rendered pages with htmx and SSE.** Stays pure Python and needs less code, but leaves no API
  for later clients and hand-writes the drag and its state. React arrives with the portal anyway.
- **Next.js for these screens.** Adds a Node process at runtime with no benefit behind a login.
- **WebSockets with Django Channels and Redis.** Two-way traffic is not needed, since writes are
  ordinary commands, and it adds a service to run.
- **Polling only.** The simplest, but with visible lag and constant load. It stays as the safety net.
