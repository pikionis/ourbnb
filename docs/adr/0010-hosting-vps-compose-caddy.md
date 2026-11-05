# 0010 — Hosting: existing Hostinger VPS, Docker Compose, Caddy

- Status: accepted; amended by 0021 (Caddy also serves the public site, all under ourbnb.gr)
- Date: 2026-10-22

## Context
The IKE already rents a Hostinger VPS that runs another application. Load is small: tens of
properties and a handful of users. We need HTTPS, scheduled jobs, PostgreSQL and reliable backups.
One person operates all of it, and the existing app must not be disturbed.

## Decision
Deploy with `deploy/docker-compose.prod.yml` on the existing VPS. The stack has four services:
- `postgres`, with a named volume;
- `backend` (gunicorn);
- `scheduler` (supercronic, ADR 0004);
- **Caddy**, a reverse proxy with automatic HTTPS.

The stack runs on its own **isolated Docker network**. Only Caddy publishes ports, and Postgres is
never exposed publicly. Secrets live in `deploy/.env` on the server and are never committed.

`deploy/backup.sh` runs a nightly `pg_dump`, **encrypts** it and uploads it **off-site**
(S3-compatible storage, e.g. Backblaze B2). It keeps 30 daily and 12 monthly copies. The deploy is
built in Phase 7 and documented in `docs/RUNBOOK.md`.

## Consequences
- The setup is cheap and simple: one host and one `docker compose up -d`.
- The VPS is a single point of failure, and restoring from backup is the recovery path. The
  **restore procedure is tested** regularly, not just the backup.
- If the existing app already binds ports 80/443, Caddy must either front both apps or sit behind
  the existing proxy. This is checked before the first deploy.
- The backup encryption key is kept off the VPS. Losing that key means losing the backups.
- Container resource limits protect the existing app from KosPM load spikes.
