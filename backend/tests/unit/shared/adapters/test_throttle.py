"""Throttle: repeated attempts are refused after the configured limit (login, sign-up, reset)."""

from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache.backends.locmem import LocMemCache

from kospm.shared.adapters.throttle import Throttle, ThrottlePolicy
from kospm.shared.clock import FixedClock

START = datetime(2026, 11, 6, 10, 0, tzinfo=UTC)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(START)


@pytest.fixture
def throttle(clock: FixedClock) -> Throttle:
    # A fresh cache per test: LocMemCache shares its contents by name.
    cache = LocMemCache(f"throttle-test-{id(clock)}", {})
    return Throttle("login", ThrottlePolicy(max_attempts=3), cache=cache, clock=clock)


def test_allows_attempts_up_to_the_limit_then_refuses(throttle: Throttle) -> None:
    assert [throttle.hit("ip:1.2.3.4") for _ in range(4)] == [True, True, True, False]


def test_counts_each_key_on_its_own(throttle: Throttle) -> None:
    for _ in range(3):
        throttle.hit("email:a@example.com")
    assert throttle.hit("email:b@example.com") is True


def test_one_key_over_its_limit_refuses_the_attempt(throttle: Throttle) -> None:
    for _ in range(3):
        throttle.hit("email:a@example.com")
    assert throttle.hit("ip:5.6.7.8", "email:a@example.com") is False


def test_reset_forgets_the_attempts(throttle: Throttle) -> None:
    for _ in range(4):
        throttle.hit("email:a@example.com")
    throttle.reset("email:a@example.com")
    assert throttle.hit("email:a@example.com") is True


def test_the_window_starts_with_the_first_attempt_and_later_ones_do_not_move_it(
    throttle: Throttle, clock: FixedClock
) -> None:
    for _ in range(4):
        throttle.hit("ip:1.2.3.4")

    clock.advance(timedelta(minutes=14))
    assert throttle.hit("ip:1.2.3.4") is False

    clock.advance(timedelta(minutes=1, seconds=1))
    assert throttle.hit("ip:1.2.3.4") is True


def test_a_visitor_already_stopped_counts_against_no_other_key(throttle: Throttle) -> None:
    for _ in range(4):
        throttle.hit("ip:1.2.3.4")

    # Made-up usernames from a stopped visitor write nothing, and lock nobody out.
    for _ in range(5):
        assert throttle.hit("ip:1.2.3.4", "username:petros") is False

    assert [throttle.hit("username:petros") for _ in range(4)] == [True, True, True, False]


@pytest.mark.parametrize("policy", [{"max_attempts": 0}, {"window": timedelta(0)}])
def test_a_policy_needs_a_positive_limit_and_window(policy: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="must be"):
        ThrottlePolicy(**policy)  # type: ignore[arg-type]
