# 0016 — Optimistic concurrency with version numbers

- Status: accepted
- Date: 2026-10-23

## Context
Two units of work can load the same aggregate at the same time: the admin edits a property while
the iCal sync or a cleaner's page changes related data, or two admins click at once. Under
PostgreSQL's READ COMMITTED both units read the same row, and the one that commits last silently
overwrites the other's change (a lost update). The Phase 1 review found that `persist_seen` writes
back every aggregate a unit has seen, so even an aggregate that was only read could overwrite a
newer change. Petros chose to rule this out before Phase 2.

## Decision
Optimistic concurrency, as in Cosmic Python ch. 7 ("version numbers"), implemented in the
repositories so the domain stays free of persistence concerns:
- Every aggregate table has an integer `version` column.
- When a repository loads an aggregate it remembers, for the current unit, the version it read
  and a snapshot of the row values.
- On commit (`persist_seen`), an aggregate whose row values equal the snapshot is **not written**.
  A changed one is written with
  `UPDATE … SET …, version = version + 1 WHERE id = … AND version = <version read>`.
- If that update matches no row, another unit changed the aggregate first: the repository raises
  `ConcurrencyError` and the unit rolls back, so nothing of it is committed or published.
- Command callers (admin, API) report "changed by someone else, reload and try again". Event
  handlers are retried by the message bus (ADR 0014), and each retry loads the newer version.
- Forms close the gap between showing and saving: a change form carries the version it was
  rendered with, and the first command of the save passes it as `expected_version`. The
  repository's `get(id, expected_version=v)` raises `ConcurrencyError` if the stored version
  differs, so a form left open while someone else saved cannot overwrite their change. An
  aggregate loaded this way is confirmed at commit even if the command changed nothing
  (`UPDATE … SET version = v WHERE id = … AND version = v`, no bump): a save that raced another
  is refused, and the row stays held until the save's transaction ends, so the save's later
  commands need no check of their own.
- The shared base `kospm.shared.adapters.versioned_repository.VersionedDjangoRepository` gives
  every context this behaviour; `ConcurrencyError` lives in `kospm.shared.unit_of_work`.

## Consequences
- No locks are held while a person edits a form; conflicts are rare and are detected at commit.
- A conflict costs a retry or a reload, never a silent overwrite.
- Units that only read an aggregate no longer write it, which also removes needless UPDATEs.
- Every new aggregate table must include `version` and use the shared base repository.
- Pessimistic locking (`SELECT … FOR UPDATE`) stays for queue-like work only (the outbox,
  ADR 0005).
- A unit that only reads another aggregate gets no guarantee about it: if a rule ever needs one
  ("an active property always has a verified account"), it is a new business rule with its own
  mechanism, not a lock added in passing.
