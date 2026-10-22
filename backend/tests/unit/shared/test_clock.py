"""Clock port (CLAUDE.md: time comes from an injected Clock, never datetime.now())."""

from datetime import UTC, date, datetime, time, timedelta, timezone

import pytest

from kospm.shared.clock import Clock, FixedClock, SystemClock
from kospm.shared.domain import ATHENS


def test_clock_is_an_abstract_port() -> None:
    with pytest.raises(TypeError):
        Clock()  # type: ignore[abstract]


def test_system_clock_returns_aware_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is UTC
    assert now.year >= 2026


def test_fixed_clock_returns_the_instant_it_was_given() -> None:
    instant = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)
    clock = FixedClock(instant)
    assert clock.now() == instant
    assert clock.now() == clock.now()


def test_fixed_clock_normalises_other_offsets_to_utc() -> None:
    clock = FixedClock(datetime(2026, 7, 11, 12, 0, tzinfo=timezone(timedelta(hours=3))))
    assert clock.now() == datetime(2026, 7, 11, 9, 0, tzinfo=UTC)
    assert clock.now().tzinfo is UTC


def test_fixed_clock_rejects_naive_datetimes() -> None:
    naive = datetime(2026, 7, 11, 9, 0)  # noqa: DTZ001 - the point of the test
    with pytest.raises(ValueError, match="naive"):
        FixedClock(naive)
    clock = FixedClock(datetime(2026, 7, 11, 9, 0, tzinfo=UTC))
    with pytest.raises(ValueError, match="naive"):
        clock.set(naive)


def test_fixed_clock_can_be_set_and_advanced() -> None:
    clock = FixedClock(datetime(2026, 7, 11, 9, 0, tzinfo=UTC))
    clock.advance(timedelta(minutes=90))
    assert clock.now() == datetime(2026, 7, 11, 10, 30, tzinfo=UTC)
    clock.set(datetime(2026, 8, 1, 6, 0, tzinfo=UTC))
    assert clock.now() == datetime(2026, 8, 1, 6, 0, tzinfo=UTC)


def test_fixed_clock_at_athens_wall_clock_time() -> None:
    clock = FixedClock.at_athens(date(2026, 7, 11), time(11, 0))
    assert clock.now() == datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    assert clock.now_athens().time() == time(11, 0)
    assert clock.now_athens().tzinfo is ATHENS


def test_today_athens_crosses_midnight_before_utc_does() -> None:
    clock = FixedClock(datetime(2026, 7, 11, 20, 59, tzinfo=UTC))
    assert clock.today_athens() == date(2026, 7, 11)
    clock.advance(timedelta(minutes=1))  # 21:00 UTC = 00:00 in Athens (summer)
    assert clock.today_athens() == date(2026, 7, 12)
    assert clock.now().date() == date(2026, 7, 11)


def test_today_athens_in_winter() -> None:
    clock = FixedClock(datetime(2026, 1, 15, 22, 0, tzinfo=UTC))  # 00:00 in Athens (UTC+2)
    assert clock.today_athens() == date(2026, 1, 16)
