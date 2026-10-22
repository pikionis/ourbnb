"""Athens local time (DOMAIN.md §2.6: store UTC, display and reason in Europe/Athens).

Instants are aware datetimes, normally in UTC. Business rules speak in Athens wall-clock terms
("check-out at 11:00", "tomorrow's cleanings"), so these helpers convert between the two. Naive
datetimes are rejected everywhere: a datetime without a zone is ambiguous, and the bug it causes
appears only twice a year.
"""

from datetime import UTC, date, datetime, time
from typing import Final
from zoneinfo import ZoneInfo

ATHENS: Final = ZoneInfo("Europe/Athens")


def require_aware(dt: datetime) -> datetime:
    """Return `dt` unchanged, or raise ValueError if it is naive."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"naive datetime {dt!r}: an aware datetime (normally UTC) is required")
    return dt


def to_athens(dt: datetime) -> datetime:
    """The same instant, expressed in Athens local time."""
    return require_aware(dt).astimezone(ATHENS)


def athens_date(dt: datetime) -> date:
    """The calendar day in Athens at instant `dt` (22:30 UTC in July is already tomorrow)."""
    return to_athens(dt).date()


def athens_datetime(day: date, at: time) -> datetime:
    """The instant (aware, UTC) when Athens wall clocks show `day` at `at`.

    Twice a year the wall clock is not a one-to-one map; `fold=0` (PEP 495) decides:
    - spring-forward gap (e.g. 2026-03-29 03:30 does not exist): the offset in force before the
      change (+02:00) is used, so the result is 01:30 UTC, which is 04:30 on the wall;
    - autumn fold (e.g. 2026-10-25 03:30 happens twice): the first occurrence, still in summer
      time (+03:00), so 00:30 UTC. A `fold` set on `at` is ignored.
    The business times of DOMAIN.md (check-out 11:00, check-in 15:00, cleaning window 11:00-15:00)
    are far from that hour; the rule just makes the result deterministic.
    """
    if at.tzinfo is not None:
        raise ValueError(f"{at!r} must be a wall-clock time without a time zone")
    return datetime.combine(day, at.replace(fold=0), tzinfo=ATHENS).astimezone(UTC)
