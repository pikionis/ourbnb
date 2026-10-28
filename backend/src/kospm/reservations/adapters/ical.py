"""iCalendar adapters of the reservations context (DOMAIN §6, ADR 0012: iCal is an allowed source).

- ICalendarParser reads a feed with the `icalendar` library and classifies each event with its
  channel's rules (CLASSIFIERS). Only the UID, dates, kind and confirmation code are kept.
- HttpICalFetcher reads a feed over HTTPS; FileICalFetcher reads it from files (tests, trials).

A feed's URL carries a secret token: errors name their kind, never the URL.
"""

import hashlib
import logging
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx2
import icalendar

from kospm.reservations.domain.errors import InvalidValue
from kospm.reservations.domain.value_objects import (
    Channel,
    EventKind,
    ImportedCalendarEvent,
    StayDates,
)
from kospm.reservations.service_layer.ports import (
    FeedUnreadable,
    FetchedFeed,
    ICalFetcher,
    ICalParser,
)
from kospm.shared.domain import athens_date

logger = logging.getLogger(__name__)

type Classifier = Callable[[str, str], tuple[EventKind, str]]

_AIRBNB_CODE = re.compile(r"/reservations/details/([A-Z0-9]{6,20})")


def classify_airbnb(summary: str, description: str) -> tuple[EventKind, str]:
    """Airbnb marks a reservation "Reserved", with its link (and so its confirmation code) in the
    description, and closed dates "Airbnb (Not available)"."""
    title = summary.strip().casefold()
    if title == "reserved":
        found = _AIRBNB_CODE.search(description)
        return EventKind.RESERVATION, found.group(1) if found else ""
    if "not available" in title:
        return EventKind.BLOCK, ""
    return EventKind.UNKNOWN, ""


def classify_booking(summary: str, description: str) -> tuple[EventKind, str]:
    """Booking.com marks every event "CLOSED - Not available": a reservation and closed dates
    look alike, so the admin answers (DOMAIN §6)."""
    return EventKind.UNKNOWN, ""


CLASSIFIERS: Mapping[Channel, Classifier] = {
    Channel.AIRBNB: classify_airbnb,
    Channel.BOOKING: classify_booking,
}


class ICalendarParser(ICalParser):
    def parse(self, channel: Channel, content: bytes) -> list[ImportedCalendarEvent]:
        try:
            calendar = icalendar.Calendar.from_ical(content)
        except Exception as error:  # data from outside: any failure means an unreadable feed
            raise FeedUnreadable(f"not an iCalendar file ({type(error).__name__})") from None
        if getattr(calendar, "name", None) != "VCALENDAR":
            raise FeedUnreadable("not an iCalendar file")
        classify = CLASSIFIERS[Channel(channel)]
        events = (_event(component, classify) for component in calendar.walk("VEVENT"))
        return [event for event in events if event is not None]


def _event(component: Any, classify: Classifier) -> ImportedCalendarEvent | None:
    """One event, or None for an event without a UID or valid dates (skipped, logged)."""
    uid = str(component.get("UID", "")).strip()
    start, end = component.get("DTSTART"), component.get("DTEND")
    if not uid or start is None or end is None:
        logger.warning("a calendar event without a UID or dates was skipped")
        return None
    try:
        dates = StayDates(_day(start.dt), _day(end.dt))
    except InvalidValue:
        logger.warning("calendar event %s ends before it starts: skipped", uid)
        return None
    kind, code = classify(str(component.get("SUMMARY", "")), str(component.get("DESCRIPTION", "")))
    return ImportedCalendarEvent(uid=uid, dates=dates, kind=kind, confirmation_code=code)


def _day(value: date | datetime) -> date:
    """An event's date. One with a time of day takes its date in Athens (DOMAIN §6)."""
    if isinstance(value, datetime):
        return athens_date(value) if value.tzinfo is not None else value.date()
    return value


class HttpICalFetcher(ICalFetcher):
    """Reads a feed over HTTPS, with a timeout and a size limit. It asks "not modified" with the
    ETag and Last-Modified of the last accepted read."""

    def __init__(
        self, *, timeout: float, max_bytes: int, client: httpx2.Client | None = None
    ) -> None:
        self._client = client or httpx2.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "KosPM calendar sync"},
        )
        self._max_bytes = max_bytes

    def fetch(self, url: str, *, etag: str = "", last_modified: str = "") -> FetchedFeed:
        if not url.startswith("https://"):
            raise FeedUnreadable("not an https link")
        headers = {"If-None-Match": etag} if etag else {}
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        try:
            with self._client.stream("GET", url, headers=headers) as response:
                if response.url.scheme != "https":
                    raise FeedUnreadable("redirected away from https")
                if response.status_code == 304:
                    return FetchedFeed(content=None, etag=etag, last_modified=last_modified)
                if response.status_code != 200:
                    raise FeedUnreadable(f"HTTP {response.status_code}")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > self._max_bytes:
                        raise FeedUnreadable(f"larger than {self._max_bytes} bytes")
                return FetchedFeed(
                    content=bytes(content),
                    etag=response.headers.get("ETag", ""),
                    last_modified=response.headers.get("Last-Modified", ""),
                )
        except (httpx2.HTTPError, httpx2.InvalidURL) as error:
            # `from None`: the library's message and traceback hold the URL.
            raise FeedUnreadable(type(error).__name__) from None


class FileICalFetcher(ICalFetcher):
    """Feeds read from files, by URL (tests and local trials). It answers "not modified" when a
    file still matches the ETag of the last read."""

    def __init__(self, files: Mapping[str, Path]) -> None:
        self._files = dict(files)

    def fetch(self, url: str, *, etag: str = "", last_modified: str = "") -> FetchedFeed:
        try:
            content = self._files[url].read_bytes()
        except (KeyError, OSError) as error:
            raise FeedUnreadable(f"no file for this feed ({type(error).__name__})") from None
        tag = f'"{hashlib.sha256(content).hexdigest()[:16]}"'
        if tag == etag:
            return FetchedFeed(content=None, etag=tag)
        return FetchedFeed(content=content, etag=tag)
