"""DjangoUnitOfWork against PostgreSQL (Cosmic Python ch. 6 and Appendix D).

BUILD_PLAN Phase 1: "UoW rolls back on exception". Most tests run inside pytest-django's test
transaction, where the unit's atomic block is a savepoint; the `transaction=True` tests check
the outermost case, with a real COMMIT.
"""

import contextlib
import threading
from datetime import UTC, datetime
from uuid import UUID

import pytest
from django.db import DEFAULT_DB_ALIAS, DatabaseError, IntegrityError, connection, connections
from django.db.transaction import TransactionManagementError

from kospm.shared.clock import FixedClock
from kospm.shared.domain import new_id
from kospm.shared.outbox import models
from kospm.shared.outbox.adapters import DjangoOutbox
from kospm.shared.outbox.domain import OutboxChannel, OutboxMessage, OutboxStatus
from tests.uow_testapp.domain import Widget, WidgetRestocked
from tests.uow_testapp.models import WidgetRow
from tests.uow_testapp.repository import WidgetUnitOfWork

NOW = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)
MESSAGE = OutboxMessage(
    channel=OutboxChannel.WHATSAPP,
    recipient="+306900000001",
    template="cleaning_assigned",
    payload={"cleaner": "Μαρία", "property": "KOS-A1"},
)


class BoomError(Exception):
    pass


@pytest.fixture
def uow() -> WidgetUnitOfWork:
    return WidgetUnitOfWork(outbox=DjangoOutbox(FixedClock(NOW)))


def a_widget_row(quantity: int = 10) -> WidgetRow:
    return WidgetRow.objects.create(id=new_id(), name="towels", quantity=quantity)


def quantity_of(widget_id: UUID) -> int:
    return WidgetRow.objects.get(pk=widget_id).quantity


def in_atomic_block() -> bool:
    # A function, not the attribute: mypy would narrow the attribute after the first assert.
    return connection.in_atomic_block


def outbox_count_from_another_connection() -> int:
    """Count outbox rows through a second connection: it sees committed data only."""
    counts: list[int] = []
    errors: list[BaseException] = []

    def count() -> None:
        try:
            counts.append(models.OutboxMessage.objects.count())
        except BaseException as error:
            errors.append(error)
        finally:
            connection.close()  # this thread's own connection

    thread = threading.Thread(target=count)
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive(), "the counting thread did not finish"
    assert errors == []
    return counts[0]


# --- outbox messages commit or roll back with the unit ------------------------------------------


@pytest.mark.django_db
def test_enqueue_then_commit_stores_the_message(uow: WidgetUnitOfWork) -> None:
    with uow:
        uow.outbox.enqueue(MESSAGE)
        uow.commit()

    row = models.OutboxMessage.objects.get()
    assert row.status == OutboxStatus.PENDING
    assert row.recipient == "+306900000001"
    assert row.payload == {"cleaner": "Μαρία", "property": "KOS-A1"}
    assert row.created_at == NOW
    assert row.next_attempt_at == NOW


@pytest.mark.django_db
def test_an_exception_rolls_the_unit_back_and_propagates(uow: WidgetUnitOfWork) -> None:
    def enqueue_then_fail() -> None:
        with uow:
            uow.outbox.enqueue(MESSAGE)
            raise BoomError

    with pytest.raises(BoomError):
        enqueue_then_fail()

    assert not models.OutboxMessage.objects.exists()


@pytest.mark.django_db
def test_an_exception_after_commit_still_rolls_back(uow: WidgetUnitOfWork) -> None:
    def commit_then_fail() -> None:
        with uow:
            uow.outbox.enqueue(MESSAGE)
            uow.commit()
            raise BoomError

    with pytest.raises(BoomError):
        commit_then_fail()

    assert not models.OutboxMessage.objects.exists()


@pytest.mark.django_db
def test_leaving_the_unit_without_commit_rolls_back(uow: WidgetUnitOfWork) -> None:
    with uow:
        uow.outbox.enqueue(MESSAGE)

    assert not models.OutboxMessage.objects.exists()


# --- aggregates: persist_seen (Appendix D) -----------------------------------------------------


@pytest.mark.django_db
def test_an_added_aggregate_is_stored_on_commit(uow: WidgetUnitOfWork) -> None:
    widget = Widget(new_id(), name="sheets")
    with uow:
        uow.widgets.add(widget)
        widget.restock(4)
        uow.commit()

    assert quantity_of(widget.id) == 4
    assert list(uow.collect_new_events()) == [WidgetRestocked(widget_id=widget.id, quantity=4)]


@pytest.mark.django_db
def test_a_loaded_aggregate_is_saved_on_commit_without_calling_save(
    uow: WidgetUnitOfWork,
) -> None:
    row = a_widget_row(quantity=10)
    with uow:
        widget = uow.widgets.get(row.id)
        widget.restock(5)
        uow.commit()

    assert quantity_of(row.id) == 15
    assert list(uow.collect_new_events()) == [WidgetRestocked(widget_id=row.id, quantity=15)]


@pytest.mark.django_db
def test_changes_without_commit_are_not_saved_and_their_events_are_dropped(
    uow: WidgetUnitOfWork,
) -> None:
    row = a_widget_row(quantity=10)
    with uow:
        widget = uow.widgets.get(row.id)
        widget.restock(5)

    assert quantity_of(row.id) == 10
    assert widget.events == []
    assert list(uow.collect_new_events()) == []


@pytest.mark.django_db
def test_an_exception_discards_aggregate_changes_and_events(uow: WidgetUnitOfWork) -> None:
    row = a_widget_row(quantity=10)
    loaded: list[Widget] = []

    def restock_then_fail() -> None:
        with uow:
            widget = uow.widgets.get(row.id)
            loaded.append(widget)
            widget.restock(5)
            uow.outbox.enqueue(MESSAGE)
            raise BoomError

    with pytest.raises(BoomError):
        restock_then_fail()

    assert quantity_of(row.id) == 10
    assert not models.OutboxMessage.objects.exists()
    assert loaded[0].events == []
    assert list(uow.collect_new_events()) == []


@pytest.mark.django_db
def test_an_exception_after_commit_discards_aggregate_changes_and_events(
    uow: WidgetUnitOfWork,
) -> None:
    # The COMMIT is deferred to the end of the block, so this unit never committed: its events
    # must not reach the bus (ADR 0014: a rolled-back change never publishes an event).
    row = a_widget_row(quantity=10)
    loaded: list[Widget] = []

    def restock_commit_then_fail() -> None:
        with uow:
            widget = uow.widgets.get(row.id)
            loaded.append(widget)
            widget.restock(5)
            uow.commit()
            raise BoomError

    with pytest.raises(BoomError):
        restock_commit_then_fail()

    assert quantity_of(row.id) == 10
    assert loaded[0].events == []
    assert list(uow.collect_new_events()) == []


@pytest.mark.django_db
def test_loading_an_aggregate_twice_in_one_unit_keeps_the_change(uow: WidgetUnitOfWork) -> None:
    # Identity map: the second load returns the object already seen in this unit, so a stale
    # copy cannot overwrite the change on commit, and the event matches the stored state.
    row = a_widget_row(quantity=10)
    with uow:
        first = uow.widgets.get(row.id)
        first.restock(4)
        second = uow.widgets.get(row.id)
        uow.commit()

    assert second is first
    assert quantity_of(row.id) == 14
    assert list(uow.collect_new_events()) == [WidgetRestocked(widget_id=row.id, quantity=14)]


# --- misuse is refused --------------------------------------------------------------------------


@pytest.mark.django_db
def test_entering_a_unit_that_is_already_open_raises(uow: WidgetUnitOfWork) -> None:
    def enter_twice() -> None:
        with uow:
            uow.outbox.enqueue(MESSAGE)
            with uow:
                uow.commit()

    with pytest.raises(RuntimeError, match="re-entrant"):
        enter_twice()

    assert not models.OutboxMessage.objects.exists()


@pytest.mark.django_db
def test_the_same_unit_of_work_can_run_one_unit_after_another(uow: WidgetUnitOfWork) -> None:
    with uow:
        uow.outbox.enqueue(MESSAGE)
    with uow:
        uow.outbox.enqueue(MESSAGE)
        uow.commit()
    with uow:
        uow.outbox.enqueue(MESSAGE)
        uow.commit()

    assert models.OutboxMessage.objects.count() == 2


@pytest.mark.django_db
def test_commit_refuses_a_transaction_that_django_will_roll_back(uow: WidgetUnitOfWork) -> None:
    # A caught database error marks the atomic block for rollback. Leaving the block would then
    # roll back silently, so commit() must fail instead of reporting success (and letting the
    # bus publish events of work that never happened).
    existing = a_widget_row()

    def swallow_an_integrity_error_then_commit() -> None:
        with uow:
            uow.outbox.enqueue(MESSAGE)
            with contextlib.suppress(IntegrityError):
                uow.widgets.add(Widget(existing.id, name="duplicate"))
            uow.commit()

    with pytest.raises(TransactionManagementError, match="aborted"):
        swallow_an_integrity_error_then_commit()

    assert not models.OutboxMessage.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_commit_refuses_a_transaction_that_postgresql_has_aborted(uow: WidgetUnitOfWork) -> None:
    # A caught error from a read or a raw query (a NOWAIT lock, a statement timeout) does not
    # set Django's rollback flag, but PostgreSQL has aborted the transaction and would answer the
    # COMMIT with a silent ROLLBACK. commit() must fail instead of reporting success.
    def swallow_a_read_error_then_commit() -> None:
        with uow:
            uow.outbox.enqueue(MESSAGE)
            with contextlib.suppress(DatabaseError), connection.cursor() as cursor:
                cursor.execute("SELECT 1/0")
            uow.commit()

    with pytest.raises(TransactionManagementError, match="aborted"):
        swallow_a_read_error_then_commit()

    assert not models.OutboxMessage.objects.exists()


# --- the outermost unit: a real COMMIT ---------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_outermost_unit_commits_for_real_when_the_block_exits(
    uow: WidgetUnitOfWork,
) -> None:
    with uow:
        uow.outbox.enqueue(MESSAGE)
        assert in_atomic_block()
        uow.commit()
        # Deferred commit: commit() only marks the unit; COMMIT runs when the block exits.
        assert outbox_count_from_another_connection() == 0

    assert not in_atomic_block()
    assert connection.get_autocommit()
    assert outbox_count_from_another_connection() == 1


@pytest.mark.django_db(transaction=True)
def test_a_failed_commit_propagates_and_discards_the_events(
    uow: WidgetUnitOfWork, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = a_widget_row(quantity=10)
    loaded: list[Widget] = []

    def failing_commit() -> None:
        raise DatabaseError("COMMIT failed")

    def restock_and_commit() -> None:
        with uow:
            widget = uow.widgets.get(row.id)
            loaded.append(widget)
            widget.restock(5)
            uow.commit()

    with monkeypatch.context() as patch:
        patch.setattr(connections[DEFAULT_DB_ALIAS], "commit", failing_commit)
        with pytest.raises(DatabaseError, match="COMMIT failed"):
            restock_and_commit()

    assert quantity_of(row.id) == 10
    assert loaded[0].events == []
    assert list(uow.collect_new_events()) == []
