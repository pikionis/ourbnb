"""Limits on repeated attempts (login, sign-up, password reset), counted in Django's cache.

The count lives in the cache configured in settings: per process with the default local-memory
cache, shared by all workers with the database cache that the deploy configures (Phase 7, ADR
0017). Keys are hashed, so no email address or IP address is stored in the cache.
"""

import hashlib
from dataclasses import dataclass
from datetime import timedelta

from django.core.cache import BaseCache, caches


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
        self, name: str, policy: ThrottlePolicy, *, cache: BaseCache | None = None
    ) -> None:
        self._name = name
        self._policy = policy
        self._cache = cache if cache is not None else caches["default"]

    def hit(self, *keys: str) -> bool:
        """Count one attempt for every key; False if any of them is over its limit."""
        timeout = int(self._policy.window.total_seconds())
        allowed = True
        for key in keys:
            cache_key = self._cache_key(key)
            self._cache.add(cache_key, 0, timeout=timeout)
            try:
                count = self._cache.incr(cache_key)
            except ValueError:  # expired between add and incr
                self._cache.set(cache_key, 1, timeout=timeout)
                count = 1
            if count > self._policy.max_attempts:
                allowed = False
        return allowed

    def reset(self, *keys: str) -> None:
        """Forget the attempts of these keys (e.g. after a successful login)."""
        self._cache.delete_many([self._cache_key(key) for key in keys])

    def _cache_key(self, key: str) -> str:
        digest = hashlib.sha256(key.encode()).hexdigest()
        return f"kospm:throttle:{self._name}:{digest}"
