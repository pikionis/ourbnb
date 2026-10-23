"""Every text the code marks for translation has a Greek translation (CLAUDE.md: Greek and English).

The Greek catalogue is maintained by hand (locale/el/LC_MESSAGES/django.po, compiled with
`make messages`); this test reads the compiled catalogue the site uses and the marked texts from
the source, so a new untranslated label fails CI instead of showing up in English.
"""

import ast
import gettext
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SOURCES = (BACKEND / "src", BACKEND / "config")
CATALOGUE = BACKEND / "locale" / "el" / "LC_MESSAGES" / "django.mo"
TRANSLATION_CALLS = frozenset({"_", "gettext", "gettext_lazy", "ngettext", "ngettext_lazy"})
SAME_IN_GREEK = frozenset({"IBAN", "WhatsApp", "Email", "email"})


def marked_texts() -> dict[tuple[str, ...], Path]:
    """msgid (or singular/plural pair) → first file that uses it."""
    found: dict[tuple[str, ...], Path] = {}
    for root in SOURCES:
        for path in sorted(root.rglob("*.py")):
            if "migrations" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in TRANSLATION_CALLS
                ):
                    continue
                texts = [
                    arg.value
                    for arg in node.args
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                ]
                if texts:
                    plural = node.func.id.startswith("ngettext")
                    found.setdefault(tuple(texts[:2]) if plural else (texts[0],), path)
    return found


def test_the_source_marks_texts_for_translation() -> None:
    assert len(marked_texts()) > 50


def test_every_marked_text_has_a_greek_translation() -> None:
    with CATALOGUE.open("rb") as compiled:
        catalogue = gettext.GNUTranslations(compiled)
    missing = []
    for texts, path in marked_texts().items():
        if len(texts) == 2:
            translated = catalogue.ngettext(texts[0], texts[1], 2) != texts[1]
        else:
            translated = texts[0] in SAME_IN_GREEK or catalogue.gettext(texts[0]) != texts[0]
        if not translated:
            missing.append(f"{texts[0]!r} ({path.relative_to(BACKEND)})")
    assert missing == [], "add these to locale/el/LC_MESSAGES/django.po and run make messages"
