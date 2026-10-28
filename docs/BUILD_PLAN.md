# BUILD_PLAN.md — KosPM

Build order follows value and risk: **operations first** (v1), then **guests** (v2), then **money,
compliance and portals** (v3). Each phase ends with working, tested, deployable software.

Work one phase per session. Tick boxes as tasks finish. Business rules: `docs/DOMAIN.md`.
Rules for how to code: `CLAUDE.md`.

---

## Target repository layout

```
kospm/
  CLAUDE.md
  Makefile
  docker-compose.yml            # local dev: postgres, backend
  .env.example
  docs/
    DOMAIN.md
    BUILD_PLAN.md
    adr/                        # 0001-modular-monolith.md, 0002-django-plus-pure-domain.md, ...
  backend/
    pyproject.toml              # uv-managed
    manage.py
    config/                     # settings (base/dev/prod), urls, wsgi
    src/kospm/
      shared/
        domain/                 # Money, Entity/Aggregate base, DomainEvent, Command, ids
        messagebus.py           # in-process bus (Cosmic Python ch. 8–10)
        unit_of_work.py         # abstract UoW (DjangoUnitOfWork lives in shared/adapters/)
        clock.py                # Clock port, SystemClock, FixedClock (tests)
        outbox/                 # outbox model + worker
        adapters/crypto.py      # Fernet encryption helpers
      properties/
      reservations/
      housekeeping/
      messaging/                # WhatsApp adapter, templates, webhook
      guests/                   # v2
      local_guide/              # v2
      finance/                  # v3
      compliance/               # v3
      owner_portal/             # v3 (read models + API)
      bootstrap.py              # wires handlers, repos, adapters (Cosmic Python ch. 13)
    tests/
      unit/  integration/  e2e/  fixtures/   # fixtures/ical/*.ics, fixtures/whatsapp/*.json
  frontend/
    owner-portal/               # v3, React + Vite + TypeScript
  website/                      # v3, Next.js public site
  deploy/
    docker-compose.prod.yml
    Caddyfile
    backup.sh
    crontab                     # scheduled jobs
```

## Key technical choices (record each as an ADR in phase 0)

| # | Decision | Choice |
|---|---|---|
| 0001 | Style | Modular monolith, DDD + hexagonal |
| 0002 | Backend | Python 3.12, Django 5, Django Ninja for JSON API, domain in pure Python |
| 0003 | Database | PostgreSQL 16 |
| 0004 | Background work | Management commands run by a scheduler container (supercronic); outbox worker every minute. No Celery/Redis in v1 |
| 0005 | Messaging | In-process synchronous message bus + transactional outbox for external side effects |
| 0006 | Back-office | Django admin (Greek/English) for admin user |
| 0007 | Cleaner UI | Server-rendered Django pages behind signed links (no login, no app). React not needed here |
| 0008 | Owner portal | React + Vite + TS (v3) against Django Ninja API |
| 0009 | Public website | Next.js (v3) for SEO, reading a small public API |
| 0010 | Hosting | Existing Hostinger VPS, Docker Compose, Caddy (auto HTTPS), daily off-site Postgres backup |
| 0011 | WhatsApp | Meta WhatsApp Cloud API; templates versioned in code |
| 0012 | Data sources | iCal + manual entry + CSV uploads only. No scraping, no stored third-party passwords |
| 0013 | Tooling | uv, ruff, mypy, pytest, import-linter, GitHub Actions CI |

---

# v1 — Operations

## Phase 0 — Repository, tooling, skeleton
- [x] Monorepo layout as above; `backend/` with uv, Django 5 project `config`, package `src/kospm`.
- [x] Settings split `base/dev/prod`, all secrets from env; `.env.example` documented.
- [x] `docker-compose.yml` with Postgres 16 and backend (hot reload).
- [x] ruff, mypy (strict for `*/domain/*`, `*/service_layer/*`), pytest + pytest-django, import-linter
      contracts expressing the dependency rules in `CLAUDE.md`.
- [x] `Makefile` targets: up, test, test-all, check, migrate, run-jobs.
- [x] GitHub Actions CI running `make check` with a Postgres service.
- [x] ADRs 0001–0013 written (one short file each: context, decision, consequences).
- [x] Django admin enabled, languages `el` and `en`, `TIME_ZONE="Europe/Athens"`, `USE_TZ=True`.

**Done when:** `make check` is green on an empty test, CI passes, admin login works locally.

## Phase 1 — Shared kernel
- [x] `Money` value object (Decimal, EUR, add/sub/multiply by Decimal, `percent()`, rounding half-up,
      no float accepted — raises `TypeError`).
- [x] `DomainEvent`, `Command` base dataclasses; `Aggregate` base with `events: list[DomainEvent]`.
- [x] `Clock` port with `SystemClock` and `FixedClock`; helpers for Athens local date/time.
- [x] `AbstractUnitOfWork`, `DjangoUnitOfWork` (transaction.atomic, collects events from seen aggregates).
- [x] `MessageBus` handling commands (one handler) and events (many handlers), with retries for events.
- [x] `bootstrap.py` wiring with dependency injection (Cosmic Python ch. 13); tests bootstrap with fakes.
- [x] Outbox: `OutboxMessage` model (id, channel, recipient, template, payload, status, attempts,
      created_at, sent_at), `enqueue()` inside UoW, `process_outbox` management command with
      exponential backoff. Sender is a port (`ConsoleSender` in dev, WhatsApp in phase 6).
- [x] Fernet crypto helper + `EncryptedTextField` for Django models.

**Tests:** Money arithmetic and rounding; bus routes events to all handlers; UoW rolls back on
exception; outbox retries and marks failures after N attempts.

## Phase 2 — Properties context
Domain (`properties/domain/`), DOMAIN §5:
- [x] `Owner` aggregate (name, email, phone, afm, bank_account, show_on_website=False,
      website_consent_requested); value objects `Afm` (check digit), `Email`, `Iban` (mod 97).
- [x] `BankAccount` with `UNVERIFIED → PENDING → VERIFIED`: start verification with a code,
      confirm with the code, limited wrong attempts (configuration), IBAN change resets it.
- [x] `Contract` value object (commission_rate 0.15, owner_cleaning_charge 40.00 as `Money`,
      signed_at, document) with defaults from configuration (`PropertyDefaults`).
- [x] `Property` aggregate with states `ONBOARDING → ACTIVE ⇄ INACTIVE`, any → `OFFBOARDED`;
      `CheckInGuide` (two lockbox codes), `Amenities`, `IcalFeed`s, `preferred_cleaner_id`,
      `linen_par_level=3`, lat/lng.
- [x] Methods: `update_profile()`, `sign_contract()`, `record_sublease_declaration()`,
      `assign_ama()`, `activate(owner_bank_account_verified)` (checklist; raises
      `PropertyNotReadyForActivation(missing=[...])`), `deactivate()`, `offboard()`,
      `missing_for_activation()` and `profile_gaps()` for the admin.
- [x] Events: `OwnerRegistered`, `BankAccountVerified`, `PropertyProfileCompleted`,
      `ContractSigned`, `SubleaseDeclared`, `AmaAssigned`, `PropertyActivated`,
      `PropertyDeactivated`, `PropertyReactivated`, `PropertyOffboarded`.

Service layer & adapters:
- [x] Commands + handlers for each step; `PropertiesUnitOfWork`; `DjangoOwnerRepository`,
      `DjangoPropertyRepository`.
- [x] Optimistic concurrency (ADR 0016): version column, conflict → `ConcurrencyError`, unchanged
      aggregates are not written.
- [x] Django admin: Owners (read-only inline properties, bank verification code and confirmation),
      Properties (filter Σε εξέλιξη / Ενεργά / Ανενεργά / Αποχώρησαν, "missing" column, fieldsets
      per onboarding step, status badge, actions Activate / Deactivate / Offboard showing missing
      items), lockbox codes stored encrypted and masked. The admin dispatches commands; it never
      writes the tables directly.
- [x] Handler on the first `PropertyActivated` → flag the owner to be asked for website consent
      (v3 shows it).

**Tests:** activation fails listing each missing item; activation succeeds when all present;
states move only along the allowed transitions (reactivation re-checks the checklist; offboarded is
final); one owner with many properties; unique property code, ΑΦΜ and email; bank verification
(right code, wrong codes up to the limit, IBAN change resets); concurrent update → conflict.

## Phase 2b — Owner onboarding portal (before Phase 3)
Owners register and complete the checklist themselves (DOMAIN §5). Design brief:
`docs/design/owner-onboarding-brief.md`; decisions: ADR 0017 (pages), ADR 0018 (bank account).
- [x] Design brief; technology of the owner-facing pages decided (ADR 0017, amends ADR 0008):
      server-rendered Django pages, Django auth.
- [x] Bank account verification decided with an ADR (0018): the admin's manual test transfer,
      checked by the bank's payee check (VoP); an automatic sender later behind the same port,
      which only enqueues the transfer in the outbox (ADR 0005).
- [x] Owner registration and login (email + password via Django auth, email verification, password
      reset, invitation of owners registered by the admin); an owner account is linked to one
      `Owner`. Emails through the outbox (`DjangoEmailSender`); login, sign-up and reset throttled.
- [x] Portal shell (layout, language toggle, owner-scoped access) and the checklist dashboard.
- [x] Owner details (step 1) and bank account: holder name, `PENDING → TRANSFER_SENT → VERIFIED`
      with the payee check recorded by the admin; IBAN locked in the portal once verified.
- [x] Properties: add (code assigned automatically), profile form with photo uploads, files served
      only to their owner; owner edits only while `ONBOARDING`.
- [x] Contract: the admin uploads the contract to sign (`ContractDraft`); the owner downloads it and
      uploads the signed PDF (signature done by the owner, e.g. on gov.gr — never with their
      credentials on our side). Sublease declaration number.
- [x] Paste listing text → AI extracts profile fields (`ListingTextExtractor` port, Claude adapter)
      → owner reviews. Never fetch a platform URL (DOMAIN §2.1).

**Tests:** sign-up → confirmation link from the outbox → login → details → property → the checklist
shows only the ΑΜΑ missing; an owner never sees another owner's data (404); emailed links work once
and expire; `NO_MATCH` stops the verification; a code is refused before the transfer is sent; the
portal refuses an IBAN change once verified and property edits after activation; the AI draft never
contains lockbox codes and nothing is saved until the owner saves.

## Phase 3 — Reservations context & iCal sync
Domain:
- [x] `ReservationCalendar` aggregate, one per property, with `Reservation` entities (DOMAIN §6).
      `Channel` enum. Overlap check `ReservationCalendar.accept(...)`, raising
      `OverlappingReservation`.
- [ ] Properties → reservations: `PropertyCalendarSettingsChanged` carries the code, name, ACTIVE,
      default times and feeds into the calendar's own copy. A command announces the existing
      properties.
- [x] Events `ReservationImported`, `ReservationRescheduled`, `ReservationCancelled`, `StayEnded`,
      `CalendarEventNeedsReview`, `CalendarFeedFailing`.
- [x] `CalendarDiff` domain service: given stored reservations and imported events → list of events
      (new / rescheduled / cancelled). Pure function, heavily unit-tested.

Adapters:
- [ ] `ICalFetcher` port; `HttpICalFetcher` (httpx2, timeout, ETag support) and `FileICalFetcher` (tests).
- [ ] `ICalParser` (library `icalendar`) → `ImportedCalendarEvent`; per-channel classifiers
      (`AirbnbClassifier`, `BookingClassifier`) deciding reservation vs block vs unknown. An unknown
      event that mirrors another channel's reservation is a block; the admin's answers are
      remembered by UID.
- [ ] Admin alerts (feed failing, event to review, overlap) by WhatsApp to `ADMIN_WHATSAPP_NUMBER`
      through the outbox.
- [ ] Management command `sync_calendars` (all active properties); scheduled every 30 min.
- [ ] Feed health (DOMAIN §6): a failed or empty-with-future-reservations sync changes nothing;
      `CalendarFeedFailing` after the alert threshold (configuration, default 2 h) → one admin
      WhatsApp alert per incident; admin action "Confirm empty calendar".
- [ ] Management command `emit_stay_ended` daily at 12:00 Athens.
- [ ] Admin: reservations list with filters (property, channel, dates, status), manual create/edit
      (channel DIRECT), "review queue" for unclassified calendar events, edit check-in/out times.

**Tests (fixtures in `tests/fixtures/ical/`):** first import creates reservations; second identical
import emits nothing (idempotent); changed dates → rescheduled; removed future event → cancelled;
removed past event → no cancellation; overlap → alert, not saved; block events ignored; unknown →
review queue; check-out day may equal next check-in day; fetch error → nothing changes; empty feed
while future reservations exist → nothing cancelled; failing ≥ threshold → exactly one alert, none
repeated while still failing, a new one after recovery and a new failure; admin-confirmed empty feed
→ future reservations cancelled.

## Phase 4 — Housekeeping domain (core algorithm, pure TDD)
Everything here is pure Python, no Django. This is the heart of v1.
- [ ] `TeamMember` (id, name, kind CLEANER/STANDBY, daily_limit, escalation_order, phone, language).
- [ ] `EscalationPolicy` (target_per_cleaner=2, max_cleaner_normal=3, emergency_limit=4,
      standby order) — configuration object.
- [ ] `CleaningWindow` (11:00–15:00), configurable.
- [ ] `CleaningTask` (DOMAIN §9) + `TaskPriority` classification P1–P5 from deadline vs day.
- [ ] `CleaningTaskDeriver`: from a property's reservations → tasks with `available_from` and
      `deadline`; recompute on import/reschedule/cancel (pure function, returns add/update/remove).
- [ ] `plan_day(day, tasks, team, policy, preferences, allow_emergency=False) -> DailySchedule`.
- [ ] `DailySchedule` aggregate with invariants (limits, no duplicates, unassigned mandatory → alert).
- [ ] `plan_horizon(start, days, tasks, team, policy, preferences, previous) -> list[DailySchedule]`:
      the provisional plan (DOMAIN §9 Publishing) — plans days in order, rolls flexible tasks forward,
      keeps the still-valid assignments of `previous`; horizon (14 days) is configuration.
- [ ] `forecast_overload(days, tasks, team, policy) -> list[OverloadWarning]`.
- [ ] `LinenStock` aggregate + `RestockPlanner.urgency(stock, upcoming_checkouts, horizon=3)`.
- [ ] `Issue` aggregate: `REPORTED → APPROVED | REJECTED → RESOLVED`; `approve(cost, owner_visible)`.

**Required test scenarios for `plan_day`** (write them first, as a table-driven test file):
1. 4 mandatory tasks, 2 cleaners → 2+2, no standby used.
2. 3 mandatory tasks → 2+1 (balance), never 3+0.
3. 5 mandatory → 2+2 + Mother gets 1.
4. 7 mandatory → 2+2 + Mother 2 + Third 1.
5. 9 mandatory → 2+2 + Mother 2 + Third 1 + Petros 2.
6. 11 mandatory → standby full, then cleaners' 3rd → 3+3.
7. 12 mandatory, `allow_emergency=False` → 1 UNASSIGNED + alert; with `True` → a cleaner gets a 4th.
8. Early check-in task is sequence 1 for its assignee.
9. Late check-in task may be scheduled after 15:00 and does not consume a 11–15 slot when others need it.
10. Flexible (check-in tomorrow) task: assigned today only if a cleaner has < 2; never to standby; else
    rolls to tomorrow.
11. Empty-after task (P5) goes last and rolls over when the day is full.
12. Preferred cleaner gets her property when balance allows; balance wins over preference.
13. Task with `available_from` after the window (late check-out) is not scheduled before it.
14. Deterministic output: same input → same schedule (stable sorting by deadline, then property code).

**Other tests:** deriver handles back-to-back stays, gaps, cancellations, reschedules; overload
forecast warns at capacity − 1; restock urgency urgent/normal/none cases; `plan_horizon` rolls an
unassigned flexible task to the next day, a new booking changes only the assignments it must, and
the same input gives the same provisional plan.

## Phase 5 — Housekeeping application layer
- [ ] ORM models + repositories for tasks, schedules, team, linen stock, issues, restocks.
- [ ] Event handlers: `ReservationImported/Rescheduled/Cancelled` → re-derive tasks for that property
      → refresh the provisional plan → if affected day is already published → re-plan and enqueue
      "schedule changed" to affected people.
- [ ] Command `plan_tomorrow` at 18:00 Athens: fix D+1 from the provisional plan, persist, enqueue one
      WhatsApp per person with their list and one signed link per task.
- [ ] Person schedule page `/s/<signed-token>/`: provisional days for the next 14 days, no lockbox
      codes, Greek/English, mobile-first, no login.
- [ ] Command `forecast_overload` daily 08:00 → admin alert (WhatsApp/email to admin) for next 30 days,
      with suggested properties to set "closed to arrival".
- [ ] Cleaner task page `/c/<signed-token>/` (Django `TimestampSigner`, valid until end of planned
      day + 1): property name, Google Maps link, time slot + reason, lockbox code only on planned date,
      checklist, big **Done** and **Report problem** (photo upload + text). Greek/English toggle,
      mobile-first, no login. Rate-limited.
- [ ] `complete_cleaning(task_id)` → `CleaningCompleted` → linen −1; (v2 adds guest "home ready").
- [ ] `report_issue(task_id, photo, text)` → `IssueReported` → admin notified.
- [ ] Admin: today/tomorrow board per person, manual reassignment (re-validates invariants), team &
      policy config, issues approve/reject with cost, linen stock, record restock.
- [ ] Restock list for driver: urgent/normal properties ordered by a route (nearest-neighbour from a
      configurable start point using lat/lng) + one Google Maps directions link with waypoints.
      Routing is a port (`RoutePlanner`) so a real optimiser can replace it later.

**Done when:** with fixtures for 10 properties and 2 weeks of reservations, running `run-jobs`
produces correct schedules, the cleaner page completes tasks, stock decreases, and the admin board
shows everything.

## Phase 6 — WhatsApp messaging adapter
- [ ] `MessageSender` port; `WhatsAppCloudSender` (Graph API, token from env), `ConsoleSender` (dev).
- [ ] `templates.py`: template names, languages (el, en), parameter order — cleaner daily schedule,
      schedule changed, admin overload alert, admin issue reported, admin calendar feed failing,
      admin calendar event to review (unknown or overlapping).
      Script `whatsapp_sync_templates`
      to create/update templates via API (run manually by Petros with his token).
- [ ] Inbound webhook `/webhooks/whatsapp/`: verify token handshake, validate `X-Hub-Signature-256`,
      store raw message, emit `InboundMessageReceived` (used by guests context in v2).
- [ ] Respect the 24 h customer-service window: free text only inside it, templates otherwise.
- [ ] Outbox worker uses the WhatsApp sender in prod.

**Tests:** template parameter rendering; signature validation accepts/rejects; webhook idempotency
(same message id twice → one event); outbox chooses template vs free text by window.

## Phase 7 — Deploy v1 to the VPS
- [ ] `deploy/docker-compose.prod.yml`: postgres (volume), backend (gunicorn), scheduler
      (supercronic with `deploy/crontab`), Caddy reverse proxy with automatic HTTPS. Isolated network
      and ports so the existing app on the VPS is not affected.
- [ ] `deploy/backup.sh`: nightly `pg_dump`, encrypted, uploaded off-site (S3-compatible, e.g.
      Backblaze B2); keep 30 daily / 12 monthly; documented restore test.
- [ ] Owners' uploads (photos, contracts; from the Phase 2b review): the admin opens them through
      a staff-only view (media is never served publicly); they are backed up with the database,
      not only `pg_dump`; replaced files are deleted on a schedule (retention of replaced signed
      contracts decided with Petros).
- [ ] Request limits: Caddy `request_body max_size` above `PORTAL_UPLOAD_MAX_MB`; the gunicorn
      timeout longer than twice `LISTING_EXTRACTOR_TIMEOUT_SECONDS` (ADR 0019).
- [ ] Health endpoint, structured logging, error reporting (Sentry free tier, optional). If Sentry
      is used: scrub key-box codes, IBANs and pasted listing text, and send no local variables or
      request bodies.
- [ ] `docs/RUNBOOK.md`: deploy, rollback, restore, rotate secrets, add a property, add a team member.
- [ ] Production smoke test: real iCal of one property, plan tomorrow, receive WhatsApp on test phone.

### v1 acceptance
Admin onboards properties, calendars sync automatically, cleaners receive tomorrow's plan on WhatsApp
at 18:00, open their links, mark Done, report problems; admin sees overload warnings, linen stock and
the restock route.

---

# v2 — Guests

## Phase 8 — Guests context
- [ ] `GuestStay` aggregate per reservation, states per DOMAIN §7; created on `ReservationImported`.
- [ ] `GuestMatcher` domain service: property code + check-in date → match / none / ambiguous.
- [ ] Conversation state machine driving the bot: confirm name/dates → ask ID → send check-in info →
      offer local guide. Admin escalation on ambiguity.
- [ ] Guest ID stored encrypted (only declaration fields); lockbox release invariant (≥ ID_VERIFIED and
      on/after arrival day from configurable hour).
- [ ] Messages: welcome, check-in info (with photos), "home ready" on `CleaningCompleted`, check-out
      reminder (evening before), review request (day after).
- [ ] Early check-in / late check-out requests → admin approval → `ReservationTimesChanged` →
      housekeeping re-plans.
- [ ] Admin inbox: conversations, escalations, take-over (pause bot for a guest).
- [ ] Copy-paste listing text → AI extracts amenities into `Amenities` for admin review.

## Phase 9 — AI assistant adapter & local guide
- [ ] `LocalGuideEntry` model + admin, categories per DOMAIN §8.
- [ ] `GuestAssistant` port; `ClaudeGuestAssistant` adapter (Anthropic API, model configurable).
      Context = amenities, non-secret guide fields, local guide entries, reservation facts.
      Tools exposed to the model are read-only lookups plus *proposals* (`propose_early_checkin`,
      `escalate_to_admin`). It never receives the lockbox code.
- [ ] Human-like reply delay (configurable range), language matching (el/en at minimum).
- [ ] Evaluation set: 30 typical guest questions with expected behaviour (answer / escalate);
      run as a test with a recorded/fake model in CI and against the real model manually.

### v2 acceptance
A guest who taps the link in the platform message is identified, verified, receives check-in info on
arrival day, gets recommendations, and is told when the home is ready; uncertain cases reach the admin.

---

# v3 — Money, compliance, portals

## Phase 10 — Finance
- [ ] `BookingStatement` per reservation (DOMAIN §10) with line items; `CommissionPolicy` from contract.
- [ ] Platform payout CSV import (Airbnb, Booking) → actual platform fees per reservation; mismatches to
      a review queue.
- [ ] `OwnerCharge` from approved issues; cleaning charge per completed cleaning.
- [ ] `OwnerPayout` monthly by check-out month; `CALCULATED → APPROVED → PAID`; command
      `calculate_payouts --month YYYY-MM`.
- [ ] Climate resilience fee as pass-through, rates per season in config.
- [ ] Accounting export CSV per month, emailed to the accountant.

**Acceptance test:** the worked example in DOMAIN §10 (owner 660.00 €, IKE 168.50 €); cancellation with
payment; stay spanning two months belongs to the check-out month; owner with 3 properties gets one payout.

## Phase 11 — Compliance
- [ ] `StayDeclaration` per stay, `DeclarationDue` with deadline = 20th of the month after check-out.
- [ ] `AmendmentRequired` on cancellation after submission.
- [ ] Monthly export for manual submission; admin marks submitted with AADE reference.
- [ ] Deadline reminders; retention purge job for guest identity data.

## Phase 12 — Owner portal
- [ ] Owner authentication: reuse the login built in Phase 2b.
- [ ] Read-model API (Django Ninja): properties & onboarding status, reservations, statements, payouts,
      approved charges, documents, website consent toggle.
- [ ] React + Vite + TS app, Greek/English, mobile-friendly.

## Phase 13 — Public website
- [ ] Next.js site (Greek/English): services, how it works, pricing model, contact form.
- [ ] Public API: count of managed properties, owners with `show_on_website=True` (name/logo),
      testimonials (admin-managed).
- [ ] SEO basics: metadata, sitemap, Open Graph, local business schema for Kos.

---

## Backlog / later
- Automatic bank-account verification: Revolut Business API adapter (ADR 0018); open banking
  (Enable Banking) if onboarding volume grows.
- Owner reminders while the sublease declaration is missing (DOMAIN §5, step 4); admin
  notifications when an owner completes onboarding steps.
- WhatsApp templates content (Greek/English) — to be written with Petros.
- Viber channel adapter.
- Channel manager adapter (if volume grows).
- Optimised multi-stop routing service.
- Partner commissions from local guide.
- Automated AADE submission (only through an official interface, if one becomes available).
