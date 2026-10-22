"""The Clock port: the only way domain and service code learn the current time.

Handlers receive a Clock by dependency injection (bootstrap, Cosmic Python ch. 13), domain objects
receive plain datetimes. Tests use FixedClock and therefore never depend on when they run. This is
the only module allowed to read the system clock (ruff TID251 bans it everywhere else).

Pure Python: no Django (django.utils.timezone is not needed, USE_TZ only concerns the ORM).
"""

import abc
from datetime import UTC, date, datetime, time, timedelta
from typing import Self

from kospm.shared.domain.local_time import athens_date, athens_datetime, require_aware, to_athens


class Clock(abc.ABC):
    """Port: tells the current instant."""

    @abc.abstractmethod
    def now(self) -> datetime:
        """The current instant, aware, in UTC."""

    def now_athens(self) -> datetime:
        """The current instant in Athens local time."""
        return to_athens(self.now())

    def today_athens(self) -> date:
        """Today's date in Athens (business days are Athens days, not UTC days)."""
        return athens_date(self.now())


class SystemClock(Clock):
    """The real clock, wired in production by bootstrap."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock(Clock):
    """A clock that only moves when told to: for tests and for replaying a past day."""

    def __init__(self, at: datetime) -> None:
        self._now = _utc(at)

    @classmethod
    def at_athens(cls, day: date, at: time) -> Self:
        """A clock frozen at `day` `at` on Athens wall clocks."""
        return cls(athens_datetime(day, at))

    def now(self) -> datetime:
        return self._now

    def set(self, at: datetime) -> None:
        self._now = _utc(at)

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def _utc(at: datetime) -> datetime:
    return require_aware(at).astimezone(UTC)
