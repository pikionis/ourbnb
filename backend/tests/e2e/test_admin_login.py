"""Phase 0 "done when": the Django admin works, in Greek (default) and English.

Its login sits at the first address bots try (ADR 0021), so repeated attempts are limited.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client

pytestmark = pytest.mark.django_db

ADMIN_USERNAME = "petros"
ADMIN_PASSWORD = "test-only-password-1234"  # throwaway credential for the test database only


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    cache.clear()  # throttling counts live in the cache, which outlives a test
    yield
    cache.clear()


@pytest.fixture
def superuser() -> None:
    get_user_model().objects.create_superuser(
        username=ADMIN_USERNAME, email="admin@example.com", password=ADMIN_PASSWORD
    )


def log_in(client: Client, password: str, *, username: str = ADMIN_USERNAME) -> int:
    response = client.post(
        "/admin/login/",
        {"username": username, "password": password, "next": "/admin/"},
    )
    return int(response.status_code)


@pytest.mark.usefixtures("superuser")
def test_repeated_wrong_passwords_stop_even_the_right_password(
    client: Client, settings: Any
) -> None:
    settings.PORTAL_THROTTLE_MAX_ATTEMPTS = 2
    assert log_in(client, "wrong") == 200
    assert log_in(client, "wrong") == 200

    assert log_in(client, ADMIN_PASSWORD) == 200  # the page again, not the redirect of a login
    assert client.get("/admin/").status_code == 302


@pytest.mark.usefixtures("superuser")
def test_the_limit_is_also_per_visitor_across_usernames(client: Client, settings: Any) -> None:
    settings.PORTAL_THROTTLE_MAX_ATTEMPTS = 2
    log_in(client, "wrong", username="someone")
    log_in(client, "wrong", username="someone-else")

    assert log_in(client, ADMIN_PASSWORD) == 200
    assert client.get("/admin/").status_code == 302


@pytest.mark.usefixtures("superuser")
def test_a_successful_login_forgets_the_wrong_passwords_of_that_username(
    client: Client, settings: Any
) -> None:
    settings.PORTAL_THROTTLE_MAX_ATTEMPTS = 3
    log_in(client, "wrong")
    log_in(client, "wrong")
    assert log_in(client, ADMIN_PASSWORD) == 302

    other_visitor = Client(REMOTE_ADDR="203.0.113.9")
    log_in(other_visitor, "wrong")
    log_in(other_visitor, "wrong")
    assert log_in(other_visitor, ADMIN_PASSWORD) == 302


@pytest.mark.usefixtures("superuser")
def test_superuser_logs_in_and_reaches_the_admin_index(client: Client) -> None:
    response = client.post(
        "/admin/login/",
        {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD, "next": "/admin/"},
    )

    assert response.status_code == 302
    assert response["Location"] == "/admin/"
    assert client.get("/admin/").status_code == 200


def test_anonymous_user_is_redirected_to_the_login_page(client: Client) -> None:
    response = client.get("/admin/")

    assert response.status_code == 302
    assert response["Location"].startswith("/admin/login/")


def test_login_page_is_in_greek_when_the_browser_asks_for_greek(client: Client) -> None:
    response = client.get("/admin/login/", HTTP_ACCEPT_LANGUAGE="el")

    assert response.status_code == 200
    assert response["Content-Language"] == "el"
    page = response.content.decode("utf-8")
    assert "Διαχείριση Django" in page  # "Django administration"
    assert "Σύνδεση" in page  # "Log in"


def test_login_page_is_in_english_when_the_browser_asks_for_english(client: Client) -> None:
    response = client.get("/admin/login/", HTTP_ACCEPT_LANGUAGE="en")

    assert response.status_code == 200
    assert response["Content-Language"] == "en"
    page = response.content.decode("utf-8")
    assert "Django administration" in page
    assert "Log in" in page


def test_greek_is_the_default_language_without_accept_language(client: Client) -> None:
    response = client.get("/admin/login/")

    assert response["Content-Language"] == "el"
