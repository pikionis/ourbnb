"""iCalendar adapters of the reservations context (DOMAIN §6, ADR 0012: iCal is an allowed source).

- ICalendarParser reads a feed with the `icalendar` library and classifies each event with its
  channel's rules (CLASSIFIERS). Only the UID, dates, kind and confirmation code are kept. An event
  it cannot read makes the whole feed unreadable: skipped, its reservation would be cancelled.
- HttpICalFetcher reads a feed over HTTPS; FileICalFetcher reads it from files (tests, trials).

A feed's URL carries a secret token: errors name their kind, never the URL, and it never travels
over plain http.
"""

import hashlib
import re
import time
from collections.abc import Callable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx2
import icalendar

from kospm.reservations import models
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

type Classifier = Callable[[str, str], tuple[EventKind, str]]

_AIRBNB_CODE = re.compile(r"/reservations/details/([A-Z0-9]{6,20})")
# What the tables can hold. A longer UID makes the feed unreadable; a longer ETag or Last-Modified
# is dropped (the server is then asked for the whole feed every time).
MAX_UID = models.Reservation._meta.get_field("external_uid").max_length or 255
MAX_ETAG = models.CalendarFeed._meta.get_field("etag").max_length or 255
MAX_LAST_MODIFIED = models.CalendarFeed._meta.get_field("last_modified").max_length or 64


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
        return [_event(component, classify) for component in calendar.walk("VEVENT")]


def _event(component: Any, classify: Classifier) -> ImportedCalendarEvent:
    """One event, read whole or not at all (DOMAIN §6: a failed read changes nothing). Its end is
    DTEND, or DTSTART plus DURATION; an all-day event with neither lasts one day (RFC 5545)."""
    try:
        uid = str(component.get("UID", "")).strip()
        if not uid or len(uid) > MAX_UID:
            raise ValueError("no usable UID")
        dates = StayDates(_day(component.start), _day(component.end))
        summary = str(component.get("SUMMARY", ""))
        description = str(component.get("DESCRIPTION", ""))
    except Exception as error:  # data from outside: any surprise means an unreadable feed
        raise FeedUnreadable(f"a calendar event cannot be read ({type(error).__name__})") from None
    kind, code = classify(summary, description)
    return ImportedCalendarEvent(uid=uid, dates=dates, kind=kind, confirmation_code=code)


def _day(value: date | datetime) -> date:
    """An event's date. One with a time of day takes its date in Athens (DOMAIN §6)."""
    if isinstance(value, datetime):
        return athens_date(value) if value.tzinfo is not None else value.date()
    return value


class HttpICalFetcher(ICalFetcher):
    """Reads a feed over HTTPS:
    - every request goes over https, redirects included: one to http is refused before it is sent;
    - a timeout for each wait, a deadline for the whole feed and a size limit;
    - "not modified" is asked with the ETag and Last-Modified of the last accepted read;
    - no cookie goes from one feed to the next.
    """

    def __init__(
        self,
        *,
        timeout: float,
        max_bytes: int,
        client: httpx2.Client | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client or httpx2.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "KosPM calendar sync"},
        )
        hooks = self._client.event_hooks
        self._client.event_hooks = {**hooks, "request": [*hooks.get("request", []), _https_only]}
        self._max_bytes = max_bytes
        self._deadline = 3 * timeout  # a server sending a few bytes at a time
        self._monotonic = monotonic

    def fetch(self, url: str, *, etag: str = "", last_modified: str = "") -> FetchedFeed:
        if not url.startswith("https://"):
            raise FeedUnreadable("not an https link")
        headers = {"If-None-Match": etag} if etag else {}
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        self._client.cookies.clear()
        started = self._monotonic()
        try:
            with self._client.stream("GET", url, headers=headers) as response:
                if response.status_code == 304:
                    return FetchedFeed(content=None, etag=etag, last_modified=last_modified)
                if response.status_code != 200:
                    raise FeedUnreadable(f"HTTP {response.status_code}")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > self._max_bytes:
                        raise FeedUnreadable(f"larger than {self._max_bytes} bytes")
                    if self._monotonic() - started > self._deadline:
                        raise FeedUnreadable("the server sends too slowly")
                return FetchedFeed(
                    content=bytes(content),
                    etag=_fitting(response.headers.get("ETag", ""), MAX_ETAG),
                    last_modified=_fitting(
                        response.headers.get("Last-Modified", ""), MAX_LAST_MODIFIED
                    ),
                )
        except (httpx2.HTTPError, httpx2.InvalidURL) as error:
            # `from None`: the library's message and traceback hold the URL.
            raise FeedUnreadable(type(error).__name__) from None


def _https_only(request: httpx2.Request) -> None:
    """Called before every request, redirects included: the URL carries a secret token."""
    if request.url.scheme != "https":
        raise FeedUnreadable("redirected away from https")


def _fitting(value: str, limit: int) -> str:
    return value if len(value) <= limit else ""


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
