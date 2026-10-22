"""Phase 0 "done when": the Django admin works, in Greek (default) and English."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

pytestmark = pytest.mark.django_db

ADMIN_USERNAME = "petros"
ADMIN_PASSWORD = "test-only-password-1234"  # throwaway credential for the test database only


@pytest.fixture
def superuser() -> None:
    get_user_model().objects.create_superuser(
        username=ADMIN_USERNAME, email="admin@example.com", password=ADMIN_PASSWORD
    )


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
