"""The public site's form posts here (ADR 0021): what it sends and the answers it reads.

The page has no CSRF token and its script reads `ok` and `message`; without JavaScript the browser
follows a redirect back to the page. These are the answers of the PHP handler this one replaces.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client

from kospm.shared.clock import SystemClock
from kospm.shared.outbox.models import OutboxMessage

pytestmark = pytest.mark.django_db

URL = "/api/lead.php"
FORM = {
    "area": "Ψαλίδι",
    "bedrooms": "2",
    "online": "no",
    "name": "Μαρία",
    "phone": "694 000 0000",
    "website": "",
}


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    cache.clear()  # throttling counts live in the cache, which outlives a test
    yield
    cache.clear()


@pytest.fixture
def site() -> Client:
    """A browser on the static page: Django checks CSRF, and the page carries no token."""
    return Client(enforce_csrf_checks=True)


def post_json(client: Client, **changes: Any) -> Any:
    return client.post(URL, {**FORM, **changes}, HTTP_ACCEPT="application/json")


def test_a_lead_is_accepted_without_a_csrf_token_and_queued_for_the_ike(
    site: Client, settings: Any
) -> None:
    response = post_json(site)

    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    assert response.json() == {
        "ok": True,
        "message": "Ευχαριστούμε! Θα σε πάρουμε τηλέφωνο σύντομα.",
    }
    queued = OutboxMessage.objects.get()
    assert queued.recipient == settings.LEAD_NOTIFY_EMAIL
    assert queued.payload["subject"] == "Νέο αίτημα εκτίμησης: Ψαλίδι"
    assert "694 000 0000" in queued.payload["body"]


def test_the_page_is_refused_a_get(site: Client) -> None:
    response = site.get(URL, HTTP_ACCEPT="application/json")

    assert response.status_code == 405
    assert response.json()["ok"] is False


def test_a_wrong_phone_number_is_refused_in_the_forms_words(site: Client) -> None:
    response = post_json(site, phone="not a phone")

    assert response.status_code == 422
    assert response.json() == {"ok": False, "message": "Συμπλήρωσε όνομα και ένα σωστό τηλέφωνο."}
    assert not OutboxMessage.objects.exists()


def test_a_bot_that_fills_the_hidden_field_hears_ok_and_nothing_is_sent(site: Client) -> None:
    response = post_json(site, website="https://spam.example")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert not OutboxMessage.objects.exists()


def test_a_form_sent_within_three_seconds_of_loading_hears_ok_and_nothing_is_sent(
    site: Client,
) -> None:
    just_now = int(SystemClock().now().timestamp())

    response = post_json(site, ts=str(just_now))

    assert response.json()["ok"] is True
    assert not OutboxMessage.objects.exists()


def test_a_form_filled_in_at_a_human_pace_is_sent(site: Client) -> None:
    a_minute_ago = int(SystemClock().now().timestamp()) - 60

    post_json(site, ts=str(a_minute_ago))

    assert OutboxMessage.objects.count() == 1


def test_a_device_whose_clock_runs_ahead_does_not_lose_a_lead(site: Client) -> None:
    an_hour_ahead = int(SystemClock().now().timestamp()) + 3600

    post_json(site, ts=str(an_hour_ahead))

    assert OutboxMessage.objects.count() == 1


def test_a_nonsense_timestamp_does_not_stop_a_lead(site: Client) -> None:
    post_json(site, ts="yesterday")

    assert OutboxMessage.objects.count() == 1


def test_a_visitor_who_keeps_sending_is_stopped(site: Client, settings: Any) -> None:
    settings.PORTAL_THROTTLE_MAX_ATTEMPTS = 2

    assert post_json(site).status_code == 200
    assert post_json(site).status_code == 200
    refused = post_json(site)

    assert refused.status_code == 429
    assert refused.json()["ok"] is False
    assert OutboxMessage.objects.count() == 2


def test_without_javascript_the_browser_returns_to_the_form_with_the_outcome(site: Client) -> None:
    accepted = site.post(URL, FORM)
    refused = site.post(URL, {**FORM, "phone": "x"})

    assert (accepted.status_code, accepted["Location"]) == (303, "/?lead=ok#ektimisi")
    assert (refused.status_code, refused["Location"]) == (303, "/?lead=error#ektimisi")
