"""A lead from the public site reaches the IKE through the outbox (ADR 0005, ADR 0021)."""

from datetime import UTC, datetime

import pytest

from kospm.bootstrap import ContextWiring, bootstrap
from kospm.properties.domain.commands import SubmitOwnerLead
from kospm.properties.domain.errors import InvalidValue
from kospm.properties.domain.lead import LeadFormOptions
from kospm.properties.service_layer.handlers import COMMAND_HANDLERS
from kospm.shared.clock import FixedClock
from kospm.shared.messagebus import MessageBus
from tests.unit.properties.fakes import FakeLeadMailer, FakePropertiesUnitOfWork

NOW = datetime(2026, 11, 6, 9, 30, tzinfo=UTC)


@pytest.fixture
def uow() -> FakePropertiesUnitOfWork:
    return FakePropertiesUnitOfWork()


@pytest.fixture
def mailer() -> FakeLeadMailer:
    return FakeLeadMailer()


@pytest.fixture
def bus(uow: FakePropertiesUnitOfWork, mailer: FakeLeadMailer) -> MessageBus:
    return bootstrap(
        clock=FixedClock(NOW),
        contexts=[
            ContextWiring(
                name="properties",
                uow=uow,
                command_handlers={SubmitOwnerLead: COMMAND_HANDLERS[SubmitOwnerLead]},
                event_handlers={},
                dependencies={
                    "lead_mailer": mailer,
                    "lead_form": LeadFormOptions(areas=("Ψαλίδι",), bedrooms=("1", "2")),
                },
            )
        ],
    )


def submit(**changes: str) -> SubmitOwnerLead:
    form = {
        "name": "Μαρία",
        "phone": "6940000000",
        "area": "Ψαλίδι",
        "bedrooms": "2",
        "online": "no",
    }
    return SubmitOwnerLead(**{**form, **changes})


def test_a_lead_is_mailed_only_once_the_unit_commits(
    bus: MessageBus, uow: FakePropertiesUnitOfWork, mailer: FakeLeadMailer
) -> None:
    bus.handle(submit())

    assert uow.committed
    assert [message.recipient for message in uow.outbox.sent] == ["ike@example.com"]
    assert mailer.seen[0][1] == NOW


def test_a_refused_lead_sends_nothing(
    bus: MessageBus, uow: FakePropertiesUnitOfWork, mailer: FakeLeadMailer
) -> None:
    with pytest.raises(InvalidValue):
        bus.handle(submit(phone="not a phone"))

    assert uow.outbox.sent == []
    assert mailer.seen == []
