"""Composition root (Cosmic Python ch. 13): the one place where handlers meet their adapters.

Handlers declare what they need as parameters after the message, for example
`def assign_cleaning(cmd, uow, clock)`. Bootstrap binds those parameters by name once, at
startup, so handlers stay plain functions that unit tests call with fakes (FakeUnitOfWork,
FixedClock). Production code gets the wired bus from `get_bus()`.

Each bounded context contributes a ContextWiring: its own Unit of Work, its handlers and its
extra dependencies. A handler sees its context's `uow`, the shared `clock` and its context's
dependencies, nothing else. All contexts share one bus, which collects events from every
context's Unit of Work, so an event raised in one context reaches the handlers of the others
(DOMAIN §4.1). This is the only module allowed to import several contexts (import-linter top
layer), so translating one context's event into another context's command will live here
(Phase 3+).

Wiring mistakes (an unknown dependency, a command handled twice) fail at startup, not on the
first message that needs the handler.

The outbox worker is not a bus handler: the `process_outbox` command (ADR 0004) runs it on a
schedule. `build_outbox_worker()` wires it here as well, turning the OUTBOX_* settings into
configuration objects (CLAUDE.md: policies are configuration, not constants).
"""

import functools
import inspect
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from kospm.properties.adapters.bank_verification import ManualBankAccountVerifier
from kospm.properties.adapters.unit_of_work import DjangoPropertiesUnitOfWork
from kospm.properties.domain.defaults import BankVerificationPolicy, PropertyDefaults
from kospm.properties.service_layer import handlers as properties_handlers
from kospm.shared.clock import Clock, SystemClock
from kospm.shared.domain import Command, DomainEvent, Money
from kospm.shared.messagebus import (
    DEFAULT_EVENT_RETRY_POLICY,
    EventRetryPolicy,
    Handler,
    MessageBus,
    qualified_name,
)
from kospm.shared.outbox.adapters import (
    ConsoleSender,
    DjangoOutbox,
    DjangoOutboxUnitOfWork,
    TextStream,
)
from kospm.shared.outbox.domain import OutboxRetryPolicy
from kospm.shared.outbox.service_layer.ports import MessageSender
from kospm.shared.outbox.service_layer.worker import (
    OutboxRunReport,
    OutboxUnitOfWork,
    process_outbox,
)
from kospm.shared.unit_of_work import AbstractUnitOfWork

# Injected into every handler by bootstrap. A context may not redefine them: the bus collects
# events only from the context's own `uow`, and all contexts must agree on what "now" is.
RESERVED_DEPENDENCIES = frozenset({"uow", "clock"})

_MESSAGE_KINDS = frozenset(
    {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
)
_INJECTABLE_KINDS = frozenset(
    {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
)


class MissingDependencyError(Exception):
    """A handler asks for a dependency that its context does not provide."""


class DuplicateCommandHandlerError(Exception):
    """Two contexts handle the same command type, but a command has exactly one handler."""


@dataclass(frozen=True, kw_only=True)
class ContextWiring:
    """What one bounded context plugs into the bus. Handlers take the message first."""

    name: str
    uow: AbstractUnitOfWork
    command_handlers: Mapping[type[Command], Callable[..., None]] = field(default_factory=dict)
    event_handlers: Mapping[type[DomainEvent], Sequence[Callable[..., None]]] = field(
        default_factory=dict
    )
    dependencies: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        reserved = sorted(RESERVED_DEPENDENCIES.intersection(self.dependencies))
        if reserved:
            raise ValueError(
                f"context {self.name!r} may not redefine {', '.join(reserved)}: "
                "bootstrap injects them"
            )


def inject_dependencies(
    handler: Callable[..., None], dependencies: Mapping[str, object]
) -> Handler:
    """Bind every parameter after the first (the message) by name (Cosmic Python ch. 13).

    A parameter with a default keeps it when `dependencies` lacks that name. Any other missing
    name raises MissingDependencyError, so the mistake surfaces at startup.
    """
    name = qualified_name(handler)
    parameters = list(inspect.signature(handler).parameters.values())
    if not parameters or parameters[0].kind not in _MESSAGE_KINDS:
        raise TypeError(f"{name} must take the message as its first positional parameter")

    bound: dict[str, object] = {}
    missing: list[str] = []
    for parameter in parameters[1:]:
        if parameter.kind not in _INJECTABLE_KINDS:
            raise TypeError(
                f"{name}: cannot inject {parameter.kind.description} parameter "
                f"{parameter.name!r}; declare each dependency as a named parameter"
            )
        if parameter.name in dependencies:
            bound[parameter.name] = dependencies[parameter.name]
        elif parameter.default is inspect.Parameter.empty:
            missing.append(parameter.name)
    if missing:
        raise MissingDependencyError(
            f"{name} needs {', '.join(missing)}, but only "
            f"{', '.join(sorted(dependencies)) or 'nothing'} is available"
        )

    injected = functools.partial(handler, **bound)
    # Copy __name__, __qualname__, __module__ and __doc__ so bus logs name the real handler.
    functools.update_wrapper(injected, handler)
    return injected


def bootstrap(
    *,
    clock: Clock | None = None,
    contexts: Sequence[ContextWiring] | None = None,
    retry_policy: EventRetryPolicy | None = None,
) -> MessageBus:
    """Build the message bus: every handler of every context, with its dependencies bound.

    Tests pass fakes (`contexts`, a FixedClock). The defaults are the production wiring.
    """
    if clock is None:
        clock = SystemClock()
    if contexts is None:
        contexts = default_contexts(clock)

    command_handlers: dict[type[Command], Handler] = {}
    command_owners: dict[type[Command], str] = {}
    event_handlers: dict[type[DomainEvent], list[Handler]] = {}
    for context in contexts:
        dependencies = {"uow": context.uow, "clock": clock, **context.dependencies}
        for command_type, handler in context.command_handlers.items():
            if command_type in command_owners:
                raise DuplicateCommandHandlerError(
                    f"command {qualified_name(command_type)} is handled by both context "
                    f"{command_owners[command_type]!r} and context {context.name!r}"
                )
            command_owners[command_type] = context.name
            command_handlers[command_type] = _inject(context, handler, dependencies)
        for event_type, handlers in context.event_handlers.items():
            event_handlers.setdefault(event_type, []).extend(
                _inject(context, handler, dependencies) for handler in handlers
            )

    return MessageBus(
        uows=[context.uow for context in contexts],
        command_handlers=command_handlers,
        event_handlers=event_handlers,
        retry_policy=DEFAULT_EVENT_RETRY_POLICY if retry_policy is None else retry_policy,
    )


def default_contexts(clock: Clock) -> list[ContextWiring]:
    """The production wiring of every bounded context. `clock` is for their adapters."""
    return [
        ContextWiring(
            name="properties",
            uow=DjangoPropertiesUnitOfWork(outbox=DjangoOutbox(clock)),
            command_handlers=properties_handlers.COMMAND_HANDLERS,
            event_handlers=properties_handlers.EVENT_HANDLERS,
            dependencies=properties_dependencies(),
        )
    ]


# --- Properties (DOMAIN §5) ---------------------------------------------------------------------


def properties_dependencies() -> dict[str, object]:
    """The configuration objects and adapters of the properties handlers, from the settings."""
    return {
        "property_defaults": property_defaults(),
        "bank_verification": _bank_verification_policy(),
        # The admin sends the test transfer by hand until a provider is chosen (Phase 2b).
        "bank_account_verifier": ManualBankAccountVerifier(),
    }


def property_defaults() -> PropertyDefaults:
    """The configured defaults of new properties and contracts (forms show and preview them)."""
    try:
        return PropertyDefaults(
            check_in_time=time.fromisoformat(settings.PROPERTY_DEFAULT_CHECK_IN_TIME),
            check_out_time=time.fromisoformat(settings.PROPERTY_DEFAULT_CHECK_OUT_TIME),
            linen_par_level=int(settings.PROPERTY_DEFAULT_LINEN_PAR_LEVEL),
            commission_rate=Decimal(settings.CONTRACT_DEFAULT_COMMISSION_RATE),
            owner_cleaning_charge=Money(settings.CONTRACT_DEFAULT_OWNER_CLEANING_CHARGE),
        )
    except (ArithmeticError, TypeError, ValueError) as error:
        raise ImproperlyConfigured(
            "invalid property defaults (PROPERTY_DEFAULT_*, CONTRACT_DEFAULT_*): "
            f"{type(error).__name__}: {error}"
        ) from error


def _bank_verification_policy() -> BankVerificationPolicy:
    try:
        return BankVerificationPolicy(max_attempts=int(settings.BANK_VERIFICATION_MAX_ATTEMPTS))
    except ValueError as error:
        raise ImproperlyConfigured(f"invalid BANK_VERIFICATION_MAX_ATTEMPTS: {error}") from error


# One bus per thread: a Unit of Work holds the state of the unit in progress (seen aggregates,
# the open transaction), so two request threads must never share one.
_thread_local = threading.local()


def get_bus() -> MessageBus:
    """The production bus of the calling thread, bootstrapped on first use."""
    bus: MessageBus | None = getattr(_thread_local, "bus", None)
    if bus is None:
        bus = bootstrap()
        _thread_local.bus = bus
    return bus


def _inject(
    context: ContextWiring, handler: Callable[..., None], dependencies: Mapping[str, object]
) -> Handler:
    try:
        return inject_dependencies(handler, dependencies)
    except MissingDependencyError as error:
        error.add_note(f"while wiring context {context.name!r}")
        raise


# --- The outbox worker (ADR 0004, 0005) ---------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class OutboxWorker:
    """process_outbox with its dependencies bound: what the `process_outbox` command runs."""

    uow: OutboxUnitOfWork
    sender: MessageSender
    clock: Clock
    policy: OutboxRetryPolicy
    batch_size: int

    def run(self) -> OutboxRunReport:
        """Deliver up to `batch_size` due messages, one short transaction each."""
        return process_outbox(
            uow=self.uow,
            sender=self.sender,
            clock=self.clock,
            policy=self.policy,
            batch_size=self.batch_size,
        )


def build_outbox_worker(
    *, stdout: TextStream | None = None, clock: Clock | None = None
) -> OutboxWorker:
    """Wire the outbox worker from the OUTBOX_* settings, read when called.

    `stdout` is where the console sender prints (a command passes its own `self.stdout`; None
    means the process's stdout). Invalid settings raise ImproperlyConfigured before any message
    is claimed. Building queries nothing; only `run()` touches the database.
    """
    if clock is None:
        clock = SystemClock()
    return OutboxWorker(
        uow=DjangoOutboxUnitOfWork(outbox=DjangoOutbox(clock)),
        sender=_outbox_sender(stdout),
        clock=clock,
        policy=_outbox_retry_policy(),
        batch_size=_outbox_batch_size(),
    )


def _outbox_sender(stdout: TextStream | None) -> MessageSender:
    name = settings.OUTBOX_SENDER
    if name == "console":
        return ConsoleSender(stdout)
    # The WhatsApp sender arrives in Phase 6 (ADR 0011).
    raise ImproperlyConfigured(f"OUTBOX_SENDER={name!r} is not a known sender; use 'console'")


def _outbox_retry_policy() -> OutboxRetryPolicy:
    try:
        return OutboxRetryPolicy(
            max_attempts=settings.OUTBOX_MAX_ATTEMPTS,
            base_delay=timedelta(seconds=settings.OUTBOX_BASE_DELAY_SECONDS),
            factor=settings.OUTBOX_BACKOFF_FACTOR,
            max_delay=timedelta(seconds=settings.OUTBOX_MAX_DELAY_SECONDS),
        )
    except ValueError as error:
        raise ImproperlyConfigured(
            "invalid outbox retry settings (OUTBOX_MAX_ATTEMPTS, OUTBOX_BASE_DELAY_SECONDS, "
            f"OUTBOX_BACKOFF_FACTOR, OUTBOX_MAX_DELAY_SECONDS): {error}"
        ) from error


def _outbox_batch_size() -> int:
    batch_size = settings.OUTBOX_BATCH_SIZE
    if batch_size < 1:
        raise ImproperlyConfigured(f"OUTBOX_BATCH_SIZE must be at least 1, got {batch_size}")
    return batch_size
