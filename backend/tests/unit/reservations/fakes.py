"""In-memory fakes of the reservations ports (Cosmic Python ch. 3: fakes, not mocks)."""

from collections.abc import Callable, Iterable
from uuid import UUID

from kospm.reservations.domain.calendar import ReservationCalendar
from kospm.reservations.domain.errors import CalendarNotFound
from kospm.reservations.domain.value_objects import Channel, ImportedCalendarEvent
from kospm.reservations.service_layer.ports import (
    FeedUnreadable,
    FetchedFeed,
    ICalFetcher,
    ICalParser,
)
from kospm.reservations.service_layer.unit_of_work import (
    CalendarRepository,
    ReservationsUnitOfWork,
)
from tests.fakes import FakeUnitOfWorkBase


class FakeCalendarRepository(CalendarRepository):
    """Records the `expected_version` of every `get`, so tests check that forms pass theirs."""

    def __init__(self, calendars: Iterable[ReservationCalendar] = ()) -> None:
        super().__init__()
        self._calendars = {calendar.id: calendar for calendar in calendars}
        self.expected_versions: list[int | None] = []

    def _add(self, calendar: ReservationCalendar) -> None:
        self._calendars[calendar.id] = calendar

    def get(self, property_id: UUID, *, expected_version: int | None = None) -> ReservationCalendar:
        self.expected_versions.append(expected_version)
        try:
            return self._track(self._calendars[property_id])
        except KeyError:
            raise CalendarNotFound(f"no calendar for property {property_id}") from None

    def find(self, property_id: UUID) -> ReservationCalendar | None:
        calendar = self._calendars.get(property_id)
        return None if calendar is None else self._track(calendar)

    def all(self) -> list[ReservationCalendar]:
        """Every stored calendar, untracked: for assertions."""
        return list(self._calendars.values())


class FakeReservationsUnitOfWork(FakeUnitOfWorkBase, ReservationsUnitOfWork):
    calendars: FakeCalendarRepository

    def __init__(self, calendars: Iterable[ReservationCalendar] = ()) -> None:
        super().__init__()
        self.calendars = FakeCalendarRepository(calendars)


class FakeICalFetcher(ICalFetcher):
    """Answers each URL as told: a feed's content, "not modified", or unreadable."""

    def __init__(self) -> None:
        self.answers: dict[str, FetchedFeed | FeedUnreadable] = {}
        self.requests: list[tuple[str, str, str]] = []
        self.while_fetching: Callable[[], None] | None = None  # what happens meanwhile

    def fetch(self, url: str, *, etag: str = "", last_modified: str = "") -> FetchedFeed:
        self.requests.append((url, etag, last_modified))
        if self.while_fetching is not None:
            self.while_fetching()
        answer = self.answers[url]
        if isinstance(answer, FeedUnreadable):
            raise answer
        return answer


class FakeICalParser(ICalParser):
    """A feed's content names its prepared events: b"airbnb-1" → [...]."""

    def __init__(self) -> None:
        self.feeds: dict[bytes, list[ImportedCalendarEvent]] = {}

    def parse(self, channel: Channel, content: bytes) -> list[ImportedCalendarEvent]:
        try:
            return self.feeds[content]
        except KeyError:
            raise FeedUnreadable("not an iCalendar file") from None
