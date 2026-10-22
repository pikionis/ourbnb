# 0013 — Tooling: uv, ruff, mypy, pytest, import-linter, make, GitHub Actions

- Status: accepted
- Date: 2026-10-22

## Context
The architecture rules (ADR 0001, 0002) only hold if a machine checks them on every change.
Development happens on Windows 11 without Docker, and CI runs on Linux.

## Decision
- **uv** manages Python 3.12, the dependencies and `backend/uv.lock` (`uv_build` backend). CI runs
  `uv sync --locked`, and every dependency gets a one-line justification.
- **ruff** lints and formats. It bans system-clock calls (`datetime.now`, `date.today`,
  `timezone.now`, …; TID251) everywhere except `kospm/shared/clock.py`.
- **mypy**, with django-stubs pinning a compatible version, has **`strict = true` set globally**.
  `strict` set in a per-module override silently turns strict on everywhere, so we set it
  globally and relax only `kospm.*.migrations.*` (errors ignored) and `tests.*` (untyped defs).
- **pytest + pytest-django**: `tests/unit/` uses fakes and no DB (asking for one is an error);
  `tests/integration/` and `tests/e2e/` are auto-marked `integration` and run on PostgreSQL.
- **import-linter** enforces four contracts (`backend/pyproject.toml`):
  1. top-level layers: `bootstrap` above the independent contexts, which sit above `shared`.
     Contexts are `|` siblings, so they cannot import each other; `exhaustive = true`, so a new
     top-level package fails until it is declared. Only `entrypoints` may import `bootstrap`;
  2. per-context layers: `entrypoints` > `adapters` > `models` > `service_layer` > `domain`;
  3. "Domain is pure": forbids Django and the listed third-party packages, `bootstrap`, the shared
     infrastructure (`clock`, `messagebus`, `unit_of_work`, `outbox`, `shared.adapters`) and any
     `service_layer`, `adapters`, `entrypoints` or `models`;
  4. "Service layer": forbids Django and the listed third-party packages, `bootstrap`, and any
     `adapters`, `entrypoints` or `models` (abstract ports live in the service layer itself).

  Forbidden lists are deny-lists, so a unit test (Phase 1) additionally asserts that every
  external import of a `domain` or `service_layer` module is from the standard library.
  Phase 1 extended contracts 2 and 4 to the shared kernel and made that test transitive: see
  ADR 0014, "Architecture checks for the shared kernel".
- **GNU make** (`ezwinports.make` on Windows): `make check` = lint + typecheck + lint-imports +
  migrations-check + test-all. Recipes are only `cd backend && uv run …`, so they work under
  cmd.exe and sh, and they set `PYTHONUTF8=1`. **GitHub Actions** runs `make check` on `postgres:16`.

## Consequences
- **Rule:** when you add a third-party dependency, add its root package to the forbidden lists
  of the "Domain is pure" and "Service layer" import-linter contracts.
- `make check` needs PostgreSQL locally (the Windows PG18 service, ADR 0003). Strict typing
  covers adapters too, so untyped libraries need stubs or a narrow override.
- All ten contexts and `bootstrap` are pre-declared as optional layers, so adding a context means
  creating its package; the layer list itself changes only when the context map (DOMAIN §4) does.
