"""DOMAIN.md §2.6: store UTC, reason in Europe/Athens."""

from datetime import UTC, date, datetime, time, timedelta, timezone

import pytest

from kospm.shared.domain import ATHENS, athens_date, athens_datetime, require_aware, to_athens


def test_athens_is_utc_plus_3_in_summer() -> None:
    noon_utc = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    assert to_athens(noon_utc).utcoffset() == timedelta(hours=3)
    assert to_athens(noon_utc).hour == 15


def test_athens_is_utc_plus_2_in_winter() -> None:
    noon_utc = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    assert to_athens(noon_utc).utcoffset() == timedelta(hours=2)
    assert to_athens(noon_utc).hour == 14


def test_to_athens_keeps_the_instant() -> None:
    instant = datetime(2026, 7, 11, 22, 30, tzinfo=UTC)
    assert to_athens(instant) == instant
    assert to_athens(instant).tzinfo is ATHENS


def test_late_utc_evening_is_already_the_next_day_in_athens() -> None:
    # A check-out "today" in UTC can be tomorrow's cleaning day on Kos.
    assert athens_date(datetime(2026, 7, 11, 22, 30, tzinfo=UTC)) == date(2026, 7, 12)
    assert athens_date(datetime(2026, 7, 11, 20, 59, tzinfo=UTC)) == date(2026, 7, 11)


def test_athens_date_accepts_any_aware_offset() -> None:
    new_york = timezone(timedelta(hours=-4))
    assert athens_date(datetime(2026, 7, 11, 18, 0, tzinfo=new_york)) == date(2026, 7, 12)


def test_athens_wall_clock_becomes_an_aware_utc_datetime() -> None:
    check_in = athens_datetime(date(2026, 7, 11), time(15, 0))
    assert check_in == datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    assert check_in.tzinfo is UTC
    assert athens_datetime(date(2026, 1, 15), time(11, 0)) == datetime(
        2026, 1, 15, 9, 0, tzinfo=UTC
    )


def test_spring_forward_gap_resolves_with_the_offset_before_the_change() -> None:
    # 2026-03-29: Athens clocks jump 03:00 -> 04:00, so 03:30 never exists on the wall.
    # fold=0 uses the pre-transition offset (+02:00): the instant is 01:30 UTC = 04:30 EEST.
    gap = athens_datetime(date(2026, 3, 29), time(3, 30))
    assert gap == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)
    assert to_athens(gap).time() == time(4, 30)


def test_autumn_fold_picks_the_first_occurrence() -> None:
    # 2026-10-25: Athens clocks fall back 04:00 -> 03:00, so 03:30 happens twice.
    # fold=0 picks the first one, still in summer time (+03:00): 00:30 UTC.
    fold = athens_datetime(date(2026, 10, 25), time(3, 30))
    assert fold == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    assert athens_datetime(date(2026, 10, 25), time(3, 30, fold=1)) == fold


def test_naive_datetimes_are_rejected() -> None:
    naive = datetime(2026, 7, 11, 12, 0)  # noqa: DTZ001 - the point of the test
    with pytest.raises(ValueError, match="naive"):
        require_aware(naive)
    with pytest.raises(ValueError, match="naive"):
        to_athens(naive)
    with pytest.raises(ValueError, match="naive"):
        athens_date(naive)


def test_require_aware_returns_its_argument() -> None:
    instant = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    assert require_aware(instant) is instant


def test_athens_datetime_rejects_a_time_with_its_own_zone() -> None:
    with pytest.raises(ValueError, match="wall-clock"):
        athens_datetime(date(2026, 7, 11), time(15, 0, tzinfo=UTC))
