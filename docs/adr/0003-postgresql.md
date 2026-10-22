# 0003 — PostgreSQL 16

- Status: accepted
- Date: 2026-10-22

## Context
The system needs transactions that cover an aggregate and its outbox rows. It also needs row
locking for the outbox worker (`SELECT … FOR UPDATE SKIP LOCKED`), JSON payloads, partial indexes
and correct `timestamptz` handling, because we store UTC and reason in `Europe/Athens`. Volume is
modest and fits one VPS. Petros' Windows development machine already runs PostgreSQL 18 as a
service on port 5432 and has no Docker.

## Decision
PostgreSQL 16 is the reference version in CI (a `postgres:16` service) and in production. There is
no SQLite fallback. Unit tests never touch a database, and integration and e2e tests always run on
PostgreSQL.

Local development on Petros' Windows machine uses the installed **PostgreSQL 18** service, with a
role `kospm` (LOGIN CREATEDB) and a database `kospm`. `docker-compose.yml` runs `postgres:16` and
publishes it on host port **5433**, because the Windows service holds 5432. Databases are always
created as `UTF8` from `template0`. The pytest database is named by `KOSPM_TEST_DB`
(default `test_kospm`).

## Consequences
- We use only features available in 16. If 18 behaves differently, CI on 16 is the reference.
- Collations differ between Windows PG18 and Linux PG16, so tests **never assert database sort
  order** of text. They sort in Python or compare sets.
- Creating databases from `template0` with `UTF8` keeps Greek text safe whatever the server's
  default encoding is.
- The `kospm` role needs CREATEDB so pytest-django can create and drop the test database.
- Production data lives in one Docker volume. Backups are covered by ADR 0010.
