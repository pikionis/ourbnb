"""Limits on repeated attempts (login, sign-up, password reset), counted in Django's cache.

The count lives in the cache configured in settings: per process with the default local-memory
cache, shared by all workers with the database cache of production (config.settings.prod, ADR
0017). Keys are hashed, so no email address or IP address is stored in the cache.

Each key's window ends a fixed time after its first attempt, and that end is stored with the count.
`cache.incr` will not do: DatabaseCache has no `incr` of its own, and Django's fallback restarts the
key at the default five minutes on every hit. The count is read and then written, so attempts at
the very same instant may count as one, which is close enough for a limit on guessing.
"""

import hashlib
import math
from dataclasses import dataclass
from datetime import timedelta

from django.core.cache import BaseCache, caches

from kospm.shared.clock import Clock, SystemClock


@dataclass(frozen=True, kw_only=True)
class ThrottlePolicy:
    """At most `max_attempts` per key within one `window` (a configuration object)."""

    max_attempts: int = 10
    window: timedelta = timedelta(minutes=15)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {self.max_attempts}")
        if self.window <= timedelta(0):
            raise ValueError(f"window must be positive, got {self.window}")


class Throttle:
    """Counts attempts per key; the window starts with a key's first attempt."""

    def __init__(
        self,
        name: str,
        policy: ThrottlePolicy,
        *,
        cache: BaseCache | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._name = name
        self._policy = policy
        self._cache = cache if cache is not None else caches["default"]
        self._clock = clock if clock is not None else SystemClock()

    def hit(self, *keys: str) -> bool:
        """Count one attempt per key, in order; False at the first key over its limit.

        Later keys are then not counted. Callers name the visitor first, so a visitor already
        stopped writes no row per made-up address and cannot lock anyone else out.
        """
        return all(self._count(key) <= self._policy.max_attempts for key in keys)

    def reset(self, *keys: str) -> None:
        """Forget the attempts of these keys (e.g. after a successful login)."""
        self._cache.delete_many([self._cache_key(key) for key in keys])

    def _count(self, key: str) -> int:
        """One more attempt within the key's window, or the first of a new window."""
        cache_key = self._cache_key(key)
        now = self._clock.now().timestamp()
        stored = self._cache.get(cache_key)
        if stored is not None and stored[1] > now:
            count, window_ends = stored
        else:
            count, window_ends = 0, now + self._policy.window.total_seconds()
        count += 1
        self._cache.set(cache_key, (count, window_ends), timeout=math.ceil(window_ends - now))
        return int(count)

    def _cache_key(self, key: str) -> str:
        digest = hashlib.sha256(key.encode()).hexdigest()
        return f"kospm:throttle:{self._name}:{digest}"
