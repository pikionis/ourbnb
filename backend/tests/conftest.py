"""Test-suite wiring: markers follow the directory a test lives in.

- tests/unit/         fast, no database (fakes only). Using the database here is an error.
- tests/integration/  real PostgreSQL           -> marker `integration`
- tests/e2e/          through an entrypoint     -> markers `integration` and `e2e`

`make test` runs `-m "not integration"`; `make test-all` / `make check` run everything.
"""

from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent

# pytest-django fixtures that open the test database (directly or through `db`).
_DB_FIXTURES = frozenset(
    {"db", "transactional_db", "django_db_reset_sequences", "django_db_serialized_rollback"}
)


def _suite_of(item: pytest.Item) -> str | None:
    """Return the first directory under tests/ that contains the item ("unit", "e2e", ...)."""
    try:
        relative = item.path.resolve().relative_to(TESTS_DIR)
    except ValueError:
        return None
    return relative.parts[0] if len(relative.parts) > 1 else None


def _uses_database(item: pytest.Item) -> bool:
    if item.get_closest_marker("django_db") is not None:
        return True
    fixturenames: tuple[str, ...] = tuple(getattr(item, "fixturenames", ()))
    return not _DB_FIXTURES.isdisjoint(fixturenames)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        suite = _suite_of(item)
        if suite in {"integration", "e2e"}:
            item.add_marker(pytest.mark.integration)
        if suite == "e2e":
            item.add_marker(pytest.mark.e2e)
        if suite == "unit" and _uses_database(item):
            raise pytest.UsageError(
                f"{item.nodeid}: unit tests must not use the database "
                "(use fakes, or move the test to tests/integration)."
            )
