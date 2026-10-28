"""Ports of the reservations context besides its repository (hexagonal architecture).

- ICalFetcher reads a feed over the network (HttpICalFetcher), or from files in tests.
- ICalParser reads iCalendar content into classified events. The classification rules of each
  channel live in its adapter (DOMAIN §6).
- AdminAlerts tells the admin what needs them, through the outbox: messages leave only if the
  unit commits (ADR 0005).

A feed's URL carries a secret token: no port puts it in a message or a log.
"""

import abc
from dataclasses import dataclass
from datetime import datetime

from kospm.reservations.domain.value_objects import Channel, ImportedCalendarEvent, StayDates
from kospm.shared.outbox.service_layer.ports import AbstractOutbox


class FeedUnreadable(Exception):
    """A feed could not be fetched or read: network, HTTP status, size, or content that is not
    iCalendar. The message says why, for the logs, and never holds the feed's URL."""


@dataclass(frozen=True)
class FetchedFeed:
    """What the server answered: the content, or None when it said "not modified"."""

    content: bytes | None
    etag: str = ""
    last_modified: str = ""

    @property
    def not_modified(self) -> bool:
        return self.content is None


class ICalFetcher(abc.ABC):
    @abc.abstractmethod
    def fetch(self, url: str, *, etag: str = "", last_modified: str = "") -> FetchedFeed:
        """The feed at `url`; "not modified" when it still matches `etag` / `last_modified`.
        Raises FeedUnreadable."""


class ICalParser(abc.ABC):
    @abc.abstractmethod
    def parse(self, channel: Channel, content: bytes) -> list[ImportedCalendarEvent]:
        """The feed's events, classified by the channel's rules. Raises FeedUnreadable."""


class AdminAlerts(abc.ABC):
    @abc.abstractmethod
    def feed_failing(
        self,
        *,
        outbox: AbstractOutbox,
        property_code: str,
        property_name: str,
        channel: Channel,
        since: datetime,
    ) -> None:
        """A feed has kept failing for longer than the threshold (DOMAIN §6)."""

    @abc.abstractmethod
    def event_to_review(
        self,
        *,
        outbox: AbstractOutbox,
        property_code: str,
        property_name: str,
        channel: Channel,
        dates: StayDates,
        reason: str,
    ) -> None:
        """A feed event waits for the admin: unknown, or overlapping (DOMAIN §6)."""
