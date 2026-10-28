# KosPM developer commands. All Python tooling runs from backend/ through uv.
#
# Portability: GNU make on Windows may run recipes with cmd.exe or with sh. Every recipe line is
# therefore a single `cd backend && ...` command with double quotes only, and each line runs in
# its own shell.

# Greek text in Windows consoles (cp1253/cp437) would otherwise crash or garble Python output.
export PYTHONUTF8 = 1

BACKEND := cd backend &&
RUN := $(BACKEND) uv run
MANAGE := $(RUN) python manage.py

.PHONY: install up down run test test-all lint fmt typecheck lint-imports migrations-check \
        check migrate makemigrations messages superuser run-jobs

## Set up / update the virtualenv from uv.lock
install:
	$(BACKEND) uv sync

## Docker Compose stack (postgres on host port 5433 + backend)
up:
	docker compose up --build

down:
	docker compose down

## Django development server (config.settings.dev, needs the repo-root .env)
run:
	$(MANAGE) runserver

## Unit tests only: fast, no database
test:
	$(RUN) pytest -m "not integration"

## All tests, including integration and e2e against PostgreSQL
test-all:
	$(RUN) pytest

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .

## Auto-fix lint findings (incl. import order), then format
fmt:
	$(RUN) ruff check --fix .
	$(RUN) ruff format .

typecheck:
	$(RUN) mypy

lint-imports:
	$(RUN) lint-imports

## Fails if a model change has no migration (warns, but still works, if PostgreSQL is down)
migrations-check:
	$(MANAGE) makemigrations --check --dry-run --settings=config.settings.test

## Everything CI runs: must be green before a task is done
check: lint typecheck lint-imports migrations-check test-all

migrate:
	$(MANAGE) migrate

makemigrations:
	$(MANAGE) makemigrations

## Compile the Greek translations (.po -> .mo). Babel runs through uvx: not a project dependency.
messages:
	$(BACKEND) uvx --from babel==2.17.0 pybabel compile -i locale/el/LC_MESSAGES/django.po -o locale/el/LC_MESSAGES/django.mo -l el

superuser:
	$(MANAGE) createsuperuser

## Scheduled jobs, run once (iCal sync, plan tomorrow, process outbox)
run-jobs:
	$(MANAGE) sync_calendars
	$(MANAGE) emit_stay_ended
	$(MANAGE) process_outbox
