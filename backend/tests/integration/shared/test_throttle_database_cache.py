"""The throttle on the cache production uses (config.settings.prod), not the tests' LocMemCache.

DatabaseCache has no `incr` of its own: Django's fallback rewrites the key with the default five
minutes. Counted that way, ten attempts, five minutes' wait and ten more would all pass.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache import caches
from django.core.management import call_command
from django.db import connection
from django.test import override_settings

from kospm.shared.adapters.throttle import Throttle, ThrottlePolicy
from kospm.shared.clock import FixedClock

pytestmark = pytest.mark.django_db

TABLE = "kospm_test_cache"
START = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(START)


@pytest.fixture
def throttle(clock: FixedClock) -> Iterator[Throttle]:
    database_cache = {
        "default": {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": TABLE,
        }
    }
    with override_settings(CACHES=database_cache):
        call_command("createcachetable", verbosity=0)
        yield Throttle(
            "login",
            ThrottlePolicy(max_attempts=3, window=timedelta(minutes=15)),
            cache=caches["default"],
            clock=clock,
        )


def test_the_limit_holds_for_the_whole_window(throttle: Throttle, clock: FixedClock) -> None:
    assert [throttle.hit("ip:1.2.3.4") for _ in range(4)] == [True, True, True, False]

    clock.advance(timedelta(minutes=6))
    assert throttle.hit("ip:1.2.3.4") is False

    clock.advance(timedelta(minutes=9, seconds=1))
    assert throttle.hit("ip:1.2.3.4") is True


def test_the_row_lives_as_long_as_its_window(throttle: Throttle) -> None:
    for _ in range(3):
        throttle.hit("ip:1.2.3.4")

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT expires - now() FROM {TABLE}")
        (remaining,) = cursor.fetchone()

    assert remaining > timedelta(minutes=14)
