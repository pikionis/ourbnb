# 0014 — Unit of Work per bounded context, the bus collects events, bootstrap wires handlers

- Status: accepted
- Date: 2026-10-22

## Context
ADR 0005 chose an in-process message bus and a transactional outbox, and left the wiring to
Phase 1. Ten bounded contexts (DOMAIN §4) must:
- each change their own aggregates inside one transaction;
- react to each other's events without importing each other (ADR 0001);
- publish an event only if the change that raised it really committed.

## Decision
- **One Unit of Work per bounded context** (Cosmic Python ch. 6). Each context's `service_layer`
  declares its abstract UoW (a subclass of `kospm.shared.unit_of_work.AbstractUnitOfWork`) and its
  repository ports (`TrackingRepository` subclasses). The Django implementations live in that
  context's `adapters/`, built on `kospm.shared.adapters.django_unit_of_work.DjangoUnitOfWork`.
  Every UoW also carries the `outbox` port (ADR 0005).
- **Deferred commit inside `transaction.atomic`.** `with uow:` opens an atomic block. `commit()`
  writes back the aggregates the repositories handed out ("seen") and marks the unit committed;
  the real COMMIT happens when the block exits, so `uow.commit()` is the last statement of the
  block. Leaving without `commit()`, or with an exception, rolls back and **discards the events
  of the seen aggregates**. A failed COMMIT discards them too. A commit that PostgreSQL would
  turn into a rollback (the transaction was aborted by a caught database error) raises instead.
  Every UoW, the test fakes included, is not re-entrant: a nested `with uow:` raises
  RuntimeError.
- **Identity map per unit.** Within one unit a repository hands out one object per aggregate:
  loading it twice returns the object already seen, so a stale copy can never overwrite a change
  on commit.
- **The bus collects events, the UoW does not publish them** (Cosmic Python ch. 9 moved event
  collection from the UoW to the bus). After every handler call, successful or not, `MessageBus`
  collects the new events from **all** registered UoWs (one per context) and appends them to its
  queue, first in, first out. Events are therefore dispatched only after the atomic block
  committed, and **every committed unit's events are published** in the cascade of the message
  that caused them: a UoW keeps them when it starts another unit before the bus collected them
  (a handler that runs several units), and a command that fails after one of its units committed
  has those events handled before its error propagates.
- **Commands and events are `@dataclass(frozen=True, kw_only=True)`** (the base classes in
  `kospm.shared.domain.messages`). Frozen: a message is a fact or a request that nobody may alter
  in flight. Keyword-only: a subclass can add fields, with or without defaults, without the
  positional-order trap of dataclass inheritance, and call sites name every field. This refines
  CLAUDE.md's `dataclass(frozen=True)` for messages; `tests/unit/test_architecture.py` checks
  every message class.
- **Event handler retries:** each event handler is attempted up to `EventRetryPolicy.max_attempts`
  times (default 3, no sleep); each failed attempt is logged, the last one with its traceback,
  and the failure is then swallowed so the other handlers still run. Commands are never retried
  and their errors propagate.
- **Bootstrap** (`kospm/bootstrap.py`, Cosmic Python ch. 13) is the composition root. Each context
  contributes a `ContextWiring` (its UoW, handlers and extra dependencies). Handler parameters
  after the message are injected **by name**, per context; `uow` and `clock` are reserved and
  always injected. An unknown parameter or a command handled by two contexts fails **at
  startup**, not on the first message. `get_bus()` keeps **one bus per thread**, because a UoW
  holds the state of the unit in progress. The outbox worker is wired here too
  (`build_outbox_worker`, from the `OUTBOX_*` settings). Its defaults, a configuration object
  (`OutboxRetryPolicy`) that the settings override: 5 failed attempts before FAILED, the first
  retry after 1 minute, the wait doubled after each failure and capped at 1 hour (retries after
  1, 2, 4 and 8 minutes), 100 messages per run.
- **Architecture checks for the shared kernel** (amending the contract list of ADR 0013): the
  per-context layers contract also covers `kospm.shared.outbox`, which is laid out like a context;
  the "Service layer" contract also applies to `kospm.shared.messagebus`, `unit_of_work` and
  `clock`, which are service-layer machinery. `tests/unit/test_architecture.py` follows imports
  transitively: a `domain` reaches only the standard library, `kospm.shared.domain` and its own
  domain; a `service_layer` (and the three modules above) reaches only the standard library and
  such pure kospm modules.
- **No `ATOMIC_REQUESTS`.** Inside an outer request-wide transaction the UoW's "commit" would only
  release a savepoint, and the bus could publish events for work that is rolled back later.
- **Cross-context integration.** Contexts never import each other. Bootstrap, the only module
  allowed to see two contexts (import-linter top layer), translates a foreign event into the
  consuming context's own command or handler input, for example `ReservationImported` →
  housekeeping's `RederiveCleaningTasks`. How contexts share message templates and integrate
  with messaging is decided in Phase 5/6.

Rejected:
- **One shared UoW for all contexts**: it couples every context's repositories into one object
  and one transaction, which the bounded contexts exist to avoid.
- **The UoW publishes its own events after commit** (CLAUDE.md's first wording): the UoW would
  depend on the bus, and a cascade would nest handlers inside the publishing call.

## Consequences
- A handler changes one context's aggregates in one transaction. Work in another context happens
  in a later handler with its own transaction, so cross-context consistency is eventual.
- Unit tests run handlers with `FakeUnitOfWork` and `FixedClock` and no database; bootstrap tests
  wire fake contexts. Wiring mistakes surface in the first test that bootstraps. The fakes behave
  like the Django adapters where handlers could tell the difference: the commit is deferred to
  the end of the block, a nested `with uow:` raises, and `uow.outbox.enqueue()` outside a unit
  raises.
- Code that calls a handler inside an outer atomic block (Django admin `save_model`, a custom
  view) would publish events before the outer COMMIT. Entrypoints must call the bus outside any
  atomic block.
- In-process events are not durable (ADR 0005): a crash between the COMMIT and the event handler
  loses that reaction. Scheduled jobs that recompute from state limit the impact.
- A new context adds a `ContextWiring` to `default_contexts()` and, if it consumes another
  context's events, a translation function in bootstrap.
