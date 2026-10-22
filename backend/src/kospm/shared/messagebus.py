"""In-process, synchronous message bus (Cosmic Python ch. 8-10, ADR 0005). Pure Python.

Entrypoints hand a message to `MessageBus.handle`, which routes it and everything it causes:

- A **Command** has exactly one handler, chosen by the command's exact type. A command nobody
  handles is a wiring bug (NoHandlerForCommandError). Handler errors propagate to the caller,
  who asked for the action and must learn that it failed. Commands are never retried.
- A **DomainEvent** goes to every handler subscribed to its exact type, in registration order.
  The fact has already happened, so one failing reaction must not cancel the others: each
  handler is attempted up to `EventRetryPolicy.max_attempts` times, then its failure is logged
  and swallowed. Attempts are immediate (no sleep), because the bus runs inside a request or job.
- After every handler call, successful or not, the bus collects the new events of **all** Units
  of Work (one per bounded context) and appends them to its queue. The queue is first in, first
  out, so cascades run breadth first. A unit that rolled back has already discarded its events,
  so only committed facts are ever published, and every committed fact is published in the
  cascade of the message that caused it, even if its handler failed afterwards. A command that
  fails after one of its units committed therefore has those events handled first; then its
  error propagates.

Handlers receive only the message: bootstrap binds their other dependencies (uow, clock, ...)
beforehand (Cosmic Python ch. 13). Keep `uow.commit()` the last statement of the `with uow:`
block (see kospm.shared.unit_of_work).

Logs name message types, never message fields: events may carry guest data (DOMAIN §2.3).
"""

import logging
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from kospm.shared.domain import Command, DomainEvent, Message
from kospm.shared.unit_of_work import AbstractUnitOfWork

logger = logging.getLogger(__name__)

# A handler whose dependencies are already bound (bootstrap): it takes only the message.
type Handler = Callable[[Any], None]


class NoHandlerForCommandError(Exception):
    """A command was sent that no bounded context handles: a wiring bug."""


@dataclass(frozen=True, kw_only=True)
class EventRetryPolicy:
    """How many times an event handler is attempted before its failure is swallowed.

    A configuration object (CLAUDE.md), not a constant inside the bus.
    """

    max_attempts: int = 3

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {self.max_attempts}")


DEFAULT_EVENT_RETRY_POLICY = EventRetryPolicy()


class MessageBus:
    """Routes commands and events to their handlers (Cosmic Python ch. 9 and 10)."""

    def __init__(
        self,
        *,
        uows: Sequence[AbstractUnitOfWork],
        command_handlers: Mapping[type[Command], Handler],
        event_handlers: Mapping[type[DomainEvent], Sequence[Handler]],
        retry_policy: EventRetryPolicy = DEFAULT_EVENT_RETRY_POLICY,
    ) -> None:
        # Copies: later changes to the caller's collections must not rewire a running bus.
        self._uows = tuple(uows)
        self._command_handlers = dict(command_handlers)
        self._event_handlers = {
            event_type: tuple(handlers) for event_type, handlers in event_handlers.items()
        }
        self._retry_policy = retry_policy

    def handle(self, message: Message) -> None:
        """Handle `message`, then every event it causes, until the queue is empty."""
        _require_message(message)
        # A local queue, not an attribute: each call handles its own cascade.
        queue: deque[DomainEvent] = deque()
        try:
            if isinstance(message, Command):
                self._handle_command(message, queue)
            else:
                self._handle_event(message, queue)
        except Exception:
            # The command failed, but what it committed before failing happened: publish it.
            self._handle_cascade(queue)
            raise
        self._handle_cascade(queue)

    def _handle_cascade(self, queue: deque[DomainEvent]) -> None:
        while queue:
            self._handle_event(queue.popleft(), queue)

    def _handle_command(self, command: Command, queue: deque[DomainEvent]) -> None:
        handler = self._command_handlers.get(type(command))
        if handler is None:
            raise NoHandlerForCommandError(
                f"no handler is registered for command {qualified_name(type(command))}"
            )
        logger.debug(
            "handling command %s with %s", qualified_name(type(command)), qualified_name(handler)
        )
        try:
            handler(command)
        finally:
            # Also after a failure: a unit that committed before it is a fact.
            queue.extend(self._collect_new_events())

    def _handle_event(self, event: DomainEvent, queue: deque[DomainEvent]) -> None:
        for handler in self._event_handlers.get(type(event), ()):
            self._attempt(handler, event, queue)

    def _attempt(self, handler: Handler, event: DomainEvent, queue: deque[DomainEvent]) -> None:
        """Call `handler` until one attempt succeeds, at most max_attempts times."""
        max_attempts = self._retry_policy.max_attempts
        for attempt in range(1, max_attempts + 1):
            logger.debug(
                "handling event %s with %s", qualified_name(type(event)), qualified_name(handler)
            )
            try:
                handler(event)
            except Exception as error:  # broad on purpose: other reactions must still run
                if attempt < max_attempts:
                    logger.warning(
                        "event handler %s failed on attempt %d of %d for %s, retrying: %r",
                        qualified_name(handler),
                        attempt,
                        max_attempts,
                        qualified_name(type(event)),
                        error,
                    )
                else:
                    logger.exception(
                        "event handler %s failed on all %d attempts for %s, giving up",
                        qualified_name(handler),
                        max_attempts,
                        qualified_name(type(event)),
                    )
            else:
                return
            finally:
                # After every attempt: one that failed after committing a unit still made a fact.
                queue.extend(self._collect_new_events())

    def _collect_new_events(self) -> Iterator[DomainEvent]:
        for uow in self._uows:
            yield from uow.collect_new_events()


def _require_message(message: object) -> None:
    # Typed `object` on purpose: mypy rejects non-messages statically, this guards at runtime.
    if not isinstance(message, DomainEvent | Command):
        raise TypeError(f"the bus handles a DomainEvent or a Command, not {type(message).__name__}")


def qualified_name(obj: object) -> str:
    """`module.qualname` of a handler or message type, for logs and error messages."""
    module = getattr(obj, "__module__", None)
    qualname = getattr(obj, "__qualname__", None)
    if module is None or qualname is None:
        return repr(obj)
    return f"{module}.{qualname}"
