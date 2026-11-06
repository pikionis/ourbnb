"""The address the deploy and the containers ask whether the application is alive."""

import pytest
from django.db import DatabaseError
from django.test import Client


@pytest.mark.django_db
def test_healthy_when_the_database_answers(client: Client) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.content == b"ok"
    assert response["Cache-Control"] == "no-store"


def test_unhealthy_when_the_database_does_not_answer(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_database() -> None:
        raise DatabaseError("connection refused")

    monkeypatch.setattr("config.health._ask_the_database", no_database)

    response = client.get("/healthz")

    assert response.status_code == 503
    # What failed stays in the logs: this address is public.
    assert b"connection refused" not in response.content
