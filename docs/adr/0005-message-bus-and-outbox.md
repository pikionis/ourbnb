# 0005 — In-process message bus and transactional outbox

- Status: accepted
- Date: 2026-10-22

## Context
Contexts react to each other's events (DOMAIN.md §4.1). For example, a reservation import creates
cleaning tasks and a guest stay, and a completed cleaning updates linen, finance and guests. Some
reactions reach the outside world (WhatsApp, email). An external call made inside a DB transaction
can go wrong in two ways:
- it sends a message for work that is later rolled back;
- a crash after the commit loses the message.

## Decision
- An **in-process, synchronous message bus** (`kospm.shared.messagebus`, Cosmic Python ch. 8–10):
  - A command has exactly one handler, and its errors propagate to the caller.
  - An event goes to all of its handlers. Each event handler is retried a configured number of
    times. After that, the failure is logged and swallowed so the other handlers still run.
- Aggregates record events in `self.events`. After a handler's Unit of Work commits, the bus
  collects those events and dispatches them. Events from a rolled-back unit are discarded.
  Wiring details (one UoW per context, bootstrap, cross-context events) are decided in Phase 1
  and recorded in a dedicated ADR (0014).
- External side effects go through a **transactional outbox**:
  - The handler enqueues an `OutboxMessage` in the same transaction as its aggregate changes.
  - The `process_outbox` worker (ADR 0004) sends it through a `MessageSender` port, with
    exponential backoff, and marks it FAILED after N attempts.

## Consequences
- An external message is sent **only** if the business change committed, and a crash does not lose
  it. Delivery is **at-least-once**: a crash between the send and "mark sent" sends the message
  again, so every message must be harmless if it arrives twice.
- Domain objects and handlers never call WhatsApp or email directly, and tests assert on outbox rows.
- In-process events are not durable. If the process dies after a commit but before an event
  handler runs, that reaction is lost. Scheduled jobs that recompute from state reduce the impact.
- Retry and backoff policies are configuration objects, not constants inside algorithms.
