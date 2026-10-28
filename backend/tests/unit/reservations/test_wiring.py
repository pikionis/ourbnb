"""Bootstrap wires the reservations context from the settings (CLAUDE.md: policies are
configuration) and translates properties' announcement into reservations' own command."""

from collections.abc import Callable
from datetime import time, timedelta

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from kospm.bootstrap import (
    default_contexts,
    feed_health_policy,
    ical_fetcher,
    reservations_dependencies,
    update_calendar_when_settings_changed,
)
from kospm.properties.domain.events import PropertyCalendarSettingsChanged
from kospm.reservations.adapters.alerts import OutboxAdminAlerts
from kospm.reservations.adapters.ical import HttpICalFetcher, ICalendarParser
from kospm.reservations.domain.commands import AddDirectReservation, SyncCalendarFeed
from kospm.reservations.domain.policies import FeedHealthPolicy
from kospm.reservations.domain.value_objects import Channel
from kospm.shared.clock import SystemClock
from tests.unit.reservations.builders import AIRBNB_URL, PROPERTY_ID
from tests.unit.reservations.fakes import FakeReservationsUnitOfWork


def test_the_settings_become_the_policy_and_the_adapters() -> None:
    dependencies = reservations_dependencies()
    assert dependencies["feed_health"] == FeedHealthPolicy(alert_after=timedelta(hours=2))
    assert isinstance(dependencies["ical_fetcher"], HttpICalFetcher)
    assert isinstance(dependencies["ical_parser"], ICalendarParser)
    assert isinstance(dependencies["admin_alerts"], OutboxAdminAlerts)


@override_settings(ICAL_ALERT_AFTER_MINUTES=60)
def test_the_alert_threshold_is_configuration() -> None:
    assert feed_health_policy() == FeedHealthPolicy(alert_after=timedelta(hours=1))


@pytest.mark.parametrize(
    ("build", "setting"),
    [
        (feed_health_policy, {"ICAL_ALERT_AFTER_MINUTES": 0}),
        (ical_fetcher, {"ICAL_MAX_BYTES": 0}),
        (ical_fetcher, {"ICAL_FETCH_TIMEOUT_SECONDS": "soon"}),
    ],
)
def test_invalid_settings_fail_at_startup(
    build: Callable[[], object], setting: dict[str, object]
) -> None:
    with override_settings(**setting), pytest.raises(ImproperlyConfigured):
        build()


def test_the_production_bus_handles_the_reservations_messages() -> None:
    contexts = {context.name: context for context in default_contexts(SystemClock())}
    reservations = contexts["reservations"]
    assert {SyncCalendarFeed, AddDirectReservation} <= set(reservations.command_handlers)
    assert PropertyCalendarSettingsChanged in reservations.event_handlers


def test_properties_announcement_keeps_the_copy() -> None:
    uow = FakeReservationsUnitOfWork()
    update_calendar_when_settings_changed(
        PropertyCalendarSettingsChanged(
            property_id=PROPERTY_ID,
            code="KOS-001",
            name="Villa Elena",
            active=True,
            check_in_time=time(15),
            check_out_time=time(11),
            ical_feeds=(("airbnb", AIRBNB_URL),),
        ),
        uow,
    )
    (calendar,) = uow.calendars.all()
    assert calendar.syncs
    assert calendar.feed(Channel.AIRBNB).url == AIRBNB_URL
