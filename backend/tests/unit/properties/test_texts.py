"""Every value the domain can refuse has a sentence for the admin (entrypoints/texts.py)."""

import re
from pathlib import Path

import pytest
from django.utils import translation

from kospm.properties.domain.errors import InvalidValue
from kospm.properties.entrypoints.texts import INVALID_VALUE_MESSAGES, describe

CONTEXT = Path(__file__).parents[3] / "src" / "kospm" / "properties"
# InvalidValue(..., field="x") and _required(value, "x") name the refused field.
FIELD_NAMES = re.compile(r'field="([a-z_]+)"|_required\([^,()]+, "([a-z_]+)"\)')


def refused_fields() -> set[str]:
    found: set[str] = set()
    for layer in ("domain", "service_layer"):
        for path in (CONTEXT / layer).glob("*.py"):
            for match in FIELD_NAMES.finditer(path.read_text(encoding="utf-8")):
                found.add(match.group(1) or match.group(2))
    return found


def test_the_scan_finds_the_fields() -> None:
    assert {"afm", "iban", "location", "ama_number"} <= refused_fields()


def test_every_refused_field_has_a_message() -> None:
    assert refused_fields() - set(INVALID_VALUE_MESSAGES) == set()


@pytest.mark.parametrize(
    ("language", "expected"),
    [("en", "Enter a valid IBAN."), ("el", "Γράψε έγκυρο IBAN.")],
)
def test_a_refused_value_is_described_in_the_reader_s_language(
    language: str, expected: str
) -> None:
    with translation.override(language):
        assert describe(InvalidValue("mod 97 check failed", field="iban")) == expected


def test_a_field_without_a_message_keeps_the_domain_s_text() -> None:
    assert describe(InvalidValue("something new", field="unknown")) == "something new"
