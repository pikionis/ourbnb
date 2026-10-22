# 0004 — Background work: management commands on a scheduler container

- Status: accepted
- Date: 2026-10-22

## Context
v1 needs a few periodic jobs (BUILD_PLAN phases 1–5), all in `Europe/Athens` time:
- process the outbox;
- sync iCal feeds every 30 minutes;
- emit `StayEnded` at 12:00;
- forecast overload at 08:00;
- plan tomorrow at 18:00.

Volume is small (tens of properties). A task queue (Celery with Redis or RabbitMQ) would add two
more moving parts to operate, monitor and back up.

## Decision
Every job is a Django management command, which is an entrypoint that dispatches to the service
layer. In production, a **scheduler container** built from the same image as the backend runs the
commands with **supercronic**, following `deploy/crontab`. The outbox worker (`process_outbox`)
runs **every minute**. There is no Celery and no Redis in v1. Locally, `make run-jobs` runs the
jobs once.

## Consequences
- There is one image and no broker. Each job can be tested with `call_command()` in e2e tests.
- Jobs must be **idempotent** and safe to re-run or overlap. An identical iCal feed emits nothing,
  and the outbox claims rows with `SKIP LOCKED`.
- The schedule bounds latency, so an outbound WhatsApp message can wait up to about a minute.
- `manage.py` defaults to `config.settings.dev`, so the scheduler (and any production
  `manage.py` run) must set `DJANGO_SETTINGS_MODULE=config.settings.prod`.
- The scheduler container runs with `TZ=Europe/Athens`. The commands take "today" and "tomorrow"
  from the injected Clock, not from the cron trigger.
- A missed run (for example, the container was down) is not replayed. Jobs work from current
  state, so running the job again by hand catches up.
- Sub-minute latency or heavy parallel work would need a new ADR.
