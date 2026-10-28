"""The iCal adapters: the parser with each channel's rules, and the fetchers (DOMAIN §6).

Fixtures in tests/fixtures/ical/ follow each platform's format, with synthetic data.
"""

import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx2
import pytest

from kospm.reservations.adapters.ical import (
    FileICalFetcher,
    HttpICalFetcher,
    ICalendarParser,
    classify_airbnb,
    classify_booking,
)
from kospm.reservations.domain.value_objects import Channel, EventKind
from kospm.reservations.service_layer.ports import FeedUnreadable

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "ical"
URL = "https://www.airbnb.com/calendar/ical/1001.ics?s=SECRET-TOKEN"


def vevent(*lines: str) -> bytes:
    """A feed with one event made of `lines`."""
    body = "\r\n".join(("BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", *lines, "END:VEVENT"))
    return (body + "\r\nEND:VCALENDAR\r\n").encode()


def parse(channel: Channel, name: str) -> list[tuple[EventKind, date, date, str]]:
    events = ICalendarParser().parse(channel, (FIXTURES / name).read_bytes())
    return [
        (event.kind, event.dates.check_in, event.dates.check_out, event.confirmation_code)
        for event in events
    ]


class TestParser:
    def test_airbnb_reservations_with_their_codes_and_blocks(self) -> None:
        assert parse(Channel.AIRBNB, "airbnb.ics") == [
            (EventKind.RESERVATION, date(2026, 7, 12), date(2026, 7, 15), "HMTEST0001"),
            (EventKind.BLOCK, date(2026, 7, 20), date(2026, 7, 22), ""),
            (EventKind.RESERVATION, date(2026, 7, 26), date(2026, 8, 1), "HMTEST0002"),
        ]

    def test_booking_events_are_unknown(self) -> None:
        assert [kind for kind, *_ in parse(Channel.BOOKING, "booking.ics")] == [
            EventKind.UNKNOWN,
            EventKind.UNKNOWN,
        ]

    def test_the_uid_is_kept(self) -> None:
        (first, *_) = ICalendarParser().parse(
            Channel.AIRBNB, (FIXTURES / "airbnb.ics").read_bytes()
        )
        assert first.uid == "1a2b3c4d5e6f-0000000000000000000000000000000a@airbnb.com"

    def test_an_event_with_a_time_takes_its_date_in_athens(self) -> None:
        assert [(start, end) for _, start, end, _ in parse(Channel.AIRBNB, "times.ics")] == [
            (date(2026, 7, 12), date(2026, 7, 15)),
            (date(2026, 7, 20), date(2026, 7, 22)),  # 23:30 UTC is already the next day
        ]

    def test_an_event_that_cannot_be_read_makes_the_feed_unreadable(self) -> None:
        # Skipped instead, its reservation would be cancelled (DOMAIN §6: a failed read changes
        # nothing).
        with pytest.raises(FeedUnreadable):
            parse(Channel.AIRBNB, "malformed.ics")

    @pytest.mark.parametrize(
        "lines",
        [
            ("DTSTART;VALUE=DATE:20260712", "DTEND;VALUE=DATE:20260715"),  # no UID
            ("UID:a", "DTSTART;VALUE=DATE:20260715", "DTEND;VALUE=DATE:20260712"),  # backwards
            ("UID:a", "DTEND;VALUE=DATE:20260715"),  # no start
            ("UID:a", "DTSTART:notadate", "DTEND;VALUE=DATE:20260715"),
            ("UID:a", "DTSTART;VALUE=DATE:20260712", "DTSTART;VALUE=DATE:20260713"),
            ("UID:a", "DTSTART;VALUE=PERIOD:20260712T000000Z/P3D"),
            ("UID:" + "u" * 300, "DTSTART;VALUE=DATE:20260712", "DTEND;VALUE=DATE:20260715"),
        ],
    )
    def test_what_makes_an_event_unreadable(self, lines: tuple[str, ...]) -> None:
        with pytest.raises(FeedUnreadable):
            ICalendarParser().parse(Channel.AIRBNB, vevent(*lines))

    def test_an_event_may_give_its_length_instead_of_its_end(self) -> None:
        (event,) = ICalendarParser().parse(
            Channel.AIRBNB, vevent("UID:a", "DTSTART;VALUE=DATE:20260712", "DURATION:P3D")
        )
        assert (event.dates.check_in, event.dates.check_out) == (
            date(2026, 7, 12),
            date(2026, 7, 15),
        )

    def test_an_empty_calendar_has_no_events(self) -> None:
        assert parse(Channel.AIRBNB, "empty.ics") == []

    @pytest.mark.parametrize("content", [(FIXTURES / "not_ical.html").read_bytes(), b""])
    def test_what_is_not_a_calendar_is_unreadable(self, content: bytes) -> None:
        with pytest.raises(FeedUnreadable):
            ICalendarParser().parse(Channel.AIRBNB, content)


class TestClassifiers:
    @pytest.mark.parametrize(
        ("summary", "kind"),
        [
            ("Reserved", EventKind.RESERVATION),
            ("Airbnb (Not available)", EventKind.BLOCK),
            ("Not available", EventKind.BLOCK),
            ("Something else", EventKind.UNKNOWN),
        ],
    )
    def test_airbnb(self, summary: str, kind: EventKind) -> None:
        assert classify_airbnb(summary, "")[0] is kind

    def test_an_airbnb_reservation_without_its_link_has_no_code(self) -> None:
        assert classify_airbnb("Reserved", "") == (EventKind.RESERVATION, "")

    def test_booking_never_says(self) -> None:
        assert classify_booking("CLOSED - Not available", "") == (EventKind.UNKNOWN, "")


def fetcher(
    handler: object, *, max_bytes: int = 1000, monotonic: Callable[[], float] = time.monotonic
) -> HttpICalFetcher:
    transport = httpx2.MockTransport(handler)  # type: ignore[arg-type]
    return HttpICalFetcher(
        timeout=5,
        max_bytes=max_bytes,
        client=httpx2.Client(transport=transport, follow_redirects=True),
        monotonic=monotonic,
    )


class TestHttpFetcher:
    def test_reads_the_feed_with_its_etag(self) -> None:
        def api(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200, content=b"BEGIN:VCALENDAR", headers={"ETag": '"v1"', "Last-Modified": "x"}
            )

        fetched = fetcher(api).fetch(URL)
        assert (fetched.content, fetched.etag, fetched.last_modified) == (
            b"BEGIN:VCALENDAR",
            '"v1"',
            "x",
        )

    def test_asks_whether_the_feed_changed(self) -> None:
        seen: list[httpx2.Request] = []

        def api(request: httpx2.Request) -> httpx2.Response:
            seen.append(request)
            return httpx2.Response(304)

        fetched = fetcher(api).fetch(URL, etag='"v1"', last_modified="Fri, 10 Jul 2026")
        assert fetched.not_modified
        assert fetched.etag == '"v1"'
        assert seen[0].headers["If-None-Match"] == '"v1"'
        assert seen[0].headers["If-Modified-Since"] == "Fri, 10 Jul 2026"

    @pytest.mark.parametrize("status", [401, 404, 500, 503])
    def test_an_error_status_is_unreadable(self, status: int) -> None:
        with pytest.raises(FeedUnreadable, match=f"HTTP {status}"):
            fetcher(lambda request: httpx2.Response(status)).fetch(URL)

    def test_a_feed_too_large_is_unreadable(self) -> None:
        with pytest.raises(FeedUnreadable, match="larger than"):
            fetcher(lambda request: httpx2.Response(200, content=b"x" * 2000)).fetch(URL)

    def test_a_network_error_never_shows_the_url(self) -> None:
        def api(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError(f"cannot reach {request.url}", request=request)

        with pytest.raises(FeedUnreadable) as refused:
            fetcher(api).fetch(URL)
        assert str(refused.value) == "ConnectError"
        assert refused.value.__cause__ is None
        assert refused.value.__suppress_context__

    def test_only_https(self) -> None:
        with pytest.raises(FeedUnreadable, match="https"):
            fetcher(lambda request: httpx2.Response(200)).fetch("http://example.com/a.ics")

    def test_a_redirect_to_http_is_never_sent(self) -> None:
        sent: list[str] = []

        def api(request: httpx2.Request) -> httpx2.Response:
            sent.append(request.url.scheme)
            if request.url.scheme == "https":
                return httpx2.Response(302, headers={"Location": "http://example.com/a.ics?s=t"})
            return httpx2.Response(200, content=b"BEGIN:VCALENDAR")

        with pytest.raises(FeedUnreadable, match="redirected"):
            fetcher(api).fetch(URL)
        assert sent == ["https"]  # the token never travelled in clear text

    def test_a_validator_too_long_to_store_is_dropped(self) -> None:
        def api(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200, content=b"BEGIN:VCALENDAR", headers={"ETag": '"' + "e" * 300 + '"'}
            )

        assert fetcher(api).fetch(URL).etag == ""  # no "not modified" check, but no failure

    def test_a_server_sending_too_slowly_is_unreadable(self) -> None:
        clock = iter(range(0, 1000, 100))  # every look at the clock: 100 s later

        def api(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, content=b"BEGIN:VCALENDAR")

        with pytest.raises(FeedUnreadable, match="slowly"):
            fetcher(api, monotonic=lambda: float(next(clock))).fetch(URL)

    def test_no_cookie_goes_from_one_feed_to_the_next(self) -> None:
        cookies: list[str | None] = []

        def api(request: httpx2.Request) -> httpx2.Response:
            cookies.append(request.headers.get("Cookie"))
            return httpx2.Response(
                200, content=b"BEGIN:VCALENDAR", headers={"Set-Cookie": "session=abc; Path=/"}
            )

        reader = fetcher(api)
        reader.fetch(URL)
        reader.fetch(URL)
        assert cookies == [None, None]


class TestFileFetcher:
    def test_reads_a_file_and_knows_when_it_is_unchanged(self) -> None:
        files = FileICalFetcher({URL: FIXTURES / "airbnb.ics"})
        first = files.fetch(URL)
        assert first.content == (FIXTURES / "airbnb.ics").read_bytes()
        assert files.fetch(URL, etag=first.etag).not_modified

    def test_an_unknown_feed_is_unreadable(self) -> None:
        with pytest.raises(FeedUnreadable):
            FileICalFetcher({}).fetch(URL)
