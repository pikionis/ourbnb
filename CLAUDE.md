# CLAUDE.md — rules for working in this repository

You are building **KosPM**, a property-management platform for short-term rentals on Kos.
Read these before writing any code:

1. `docs/DOMAIN.md` — business rules, glossary, contexts. **Source of truth.**
2. `docs/BUILD_PLAN.md` — phases, tasks and acceptance criteria. Work on **one phase at a time**.
3. `docs/adr/` — architecture decisions already taken. Do not reverse them silently.

The product owner is Petros (Greek-speaking developer, learning DDD from *Architecture Patterns with
Python* / cosmicpython.com). Explain non-obvious design choices briefly in PR descriptions or commit
messages, referring to the book's patterns by name (Repository, Unit of Work, Aggregate, Message Bus…).

---

## Architecture (non-negotiable)

- **Modular monolith**, one Django project, one Postgres database, one deploy.
- **DDD + hexagonal (ports & adapters)**, following *Cosmic Python* and its Appendix D (Django).
- Each bounded context is a package under `backend/src/kospm/<context>/` with this layout:

```
<context>/
  domain/            # pure Python: entities, value objects, aggregates, events, commands, domain services
  service_layer/     # command/event handlers, unit of work interface
  adapters/          # repositories, Django ORM mapping, external APIs (iCal, WhatsApp, maps…)
  entrypoints/       # API endpoints (Django Ninja), webhooks, management commands, admin
  models.py          # Django ORM models (infrastructure only — no business rules here)
  apps.py
```

### Dependency rules (enforced by import-linter in CI)
- `domain/` imports **only** the standard library, `kospm.shared.domain`, and its own context's
  `domain/`. **Never** Django, never another context, never an adapter.
- `service_layer/` imports its own `domain/` and abstract ports. Never Django ORM directly.
- Contexts talk to each other **only** through events/commands on the message bus and by IDs.
- `adapters/` and `entrypoints/` may import Django and third-party libraries.

### Patterns
- Repositories return **domain objects**, not Django models. Mapping lives in `adapters/repository.py`
  (`to_domain()` / `from_domain()`).
- One **Unit of Work** per command handler (`with uow: ... uow.commit()`), wrapping `transaction.atomic`.
- Aggregates collect domain events in `self.events`; the in-process **message bus**
  (`kospm.shared.messagebus`) collects them from the UoW after commit.
- Side effects to the outside world (WhatsApp, email) go through the **outbox** table and are sent by
  a worker — never inside a domain object, never inside the DB transaction.
- Time comes from an injected `Clock` port. Never call `datetime.now()` in domain or service code.
- Money is `kospm.shared.domain.Money` (wraps `Decimal`, EUR). **Never float.**
- Policies that the business may change (team limits, escalation order, commission rates, linen par
  level, cleaning window) are **configuration objects**, not constants in algorithms.

---

## Workflow for every task

1. Read the phase in `BUILD_PLAN.md` and the related sections in `DOMAIN.md`.
2. Propose a short plan (files to create/change, tests to write). Wait for approval on larger changes.
3. **TDD**: write a failing unit test against the domain first, then the code, then refactor.
   - Unit tests for domain and service layer use **fake repositories and fake adapters**, no DB.
   - Integration tests for repositories/adapters use Postgres (pytest marker `integration`).
   - A few end-to-end tests per phase hit the API or management command.
4. Run `make check` (ruff, mypy, import-linter, pytest) — must be green before you finish.
5. Update `BUILD_PLAN.md` checkboxes for the task you completed.
6. Commit with a clear message: `housekeeping: plan_day assigns standby before 3rd cleaning`.

## When to stop and ask
- A business rule is missing, ambiguous, or conflicts with `DOMAIN.md`.
- You would need to store a password, scrape a website, or automate a login. **Never do these.**
- You want to change an ADR, add a new infrastructure dependency, or a new bounded context.
- Anything touching real money flows, guest identity data, or the AADE declarations.

## Coding conventions
- Python 3.12, type hints everywhere, `mypy --strict` on `domain/` and `service_layer/`.
- `dataclass(frozen=True)` for value objects and events; plain classes for entities/aggregates.
- Names in code follow the glossary in `DOMAIN.md` §3 exactly.
- Code, comments, identifiers: English. User-facing texts: Greek **and** English (i18n via Django
  `gettext`; WhatsApp templates in `messaging/templates.py`).
- Timezone: store UTC (`USE_TZ=True`), business logic in `Europe/Athens` via the Clock.
- Secrets only from environment variables (`.env`, never committed). Sensitive fields (guest ID
  numbers, lockbox codes) encrypted with Fernet (`kospm.shared.adapters.crypto`).
- No new dependency without a one-line justification in the PR/commit.

## Commands
```
make up          # docker compose up (postgres, backend)
make test        # pytest (unit only, fast)
make test-all    # pytest including integration
make check       # ruff + mypy + import-linter + tests
make migrate     # django migrations
make run-jobs    # run scheduled jobs once (sync iCal, plan tomorrow, process outbox)
```

## Project tooling in `.claude/`
- `/phase <n>`, `/explain <x>`, `/domain-change <rule>` — slash commands; follow their steps.
- Skill `ddd-hexagonal` — load it before writing code inside a bounded context.
- Agent `architecture-reviewer` — run it at the end of every phase, before committing.
- Sessions start in plan mode: present the plan, wait for approval, then implement.
- Petros reads Greek best: summaries and explanations to him in Greek; code and docs in English.
