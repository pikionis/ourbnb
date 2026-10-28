"""Policies of the reservations context: configuration objects, not constants (CLAUDE.md)."""

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True, kw_only=True)
class FeedHealthPolicy:
    """When a failing calendar feed alerts the admin (DOMAIN §6): after `alert_after` of failed
    syncs, counted from the first one. Default 2 h, i.e. about 4 syncs."""

    alert_after: timedelta = timedelta(hours=2)

    def __post_init__(self) -> None:
        if self.alert_after <= timedelta(0):
            raise ValueError(f"alert_after must be positive, got {self.alert_after}")
