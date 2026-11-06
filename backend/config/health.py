"""The address the deploy and the containers ask whether the application is alive (Phase 7)."""

import logging

from django.db import DatabaseError, connection
from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)


def healthz(request: HttpRequest) -> HttpResponse:
    try:
        _ask_the_database()
    except DatabaseError:
        # The reason goes to the logs only: this address is public.
        logger.exception("health check: the database does not answer")
        response = HttpResponse("unavailable", status=503, content_type="text/plain")
    else:
        response = HttpResponse("ok", content_type="text/plain")
    response["Cache-Control"] = "no-store"
    return response


def _ask_the_database() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
