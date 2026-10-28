"""Throttle: repeated attempts are refused after the configured limit (login, sign-up, reset)."""

from datetime import timedelta

import pytest
from django.core.cache.backends.locmem import LocMemCache

from kospm.shared.adapters.throttle import Throttle, ThrottlePolicy


@pytest.fixture
def throttle() -> Throttle:
    cache = LocMemCache("throttle-test", {})
    return Throttle("login", ThrottlePolicy(max_attempts=3), cache=cache)


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


@pytest.mark.parametrize("policy", [{"max_attempts": 0}, {"window": timedelta(0)}])
def test_a_policy_needs_a_positive_limit_and_window(policy: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="must be"):
        ThrottlePolicy(**policy)  # type: ignore[arg-type]
