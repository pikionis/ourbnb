"""Every text the code marks for translation has a Greek translation (CLAUDE.md: Greek and English).

The Greek catalogue is maintained by hand (locale/el/LC_MESSAGES/django.po, compiled with
`make messages`); this test reads the compiled catalogue the site uses and the marked texts from
the source (Python and templates), so a new untranslated label fails CI instead of showing up in
English.
"""

import ast
import gettext
import re
from pathlib import Path

from django.utils.translation.template import templatize

BACKEND = Path(__file__).resolve().parents[2]
SOURCES = (BACKEND / "src", BACKEND / "config")
TEMPLATE_ROOTS = (BACKEND / "src", BACKEND / "templates")
CATALOGUE = BACKEND / "locale" / "el" / "LC_MESSAGES" / "django.mo"
TRANSLATION_CALLS = frozenset({"_", "gettext", "gettext_lazy", "ngettext", "ngettext_lazy"})
SAME_IN_GREEK = frozenset({"IBAN", "WhatsApp", "Email", "email"})
# What Django's templatize() writes for {% translate %} and {% blocktranslate %}: gettext calls
# (ngettext for a counted blocktranslate) with Python string literals.
_LITERAL = r"""u?(?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")"""
_TEMPLATE_CALL = re.compile(rf"\b(n?gettext)\(\s*({_LITERAL})(?:\s*,\s*({_LITERAL}))?")


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


def template_texts() -> dict[tuple[str, ...], Path]:
    """msgid (or singular/plural pair) → first template that uses it."""
    found: dict[tuple[str, ...], Path] = {}
    for root in TEMPLATE_ROOTS:
        for path in sorted(root.rglob("*")):
            if path.suffix not in {".html", ".txt"} or "templates" not in path.parts:
                continue
            code = templatize(path.read_text(encoding="utf-8"), origin=str(path))
            for kind, first, second in _TEMPLATE_CALL.findall(code):
                texts = [ast.literal_eval(first)]
                if kind == "ngettext" and second:
                    texts.append(ast.literal_eval(second))
                found.setdefault(tuple(texts), path)
    return found


def test_the_source_marks_texts_for_translation() -> None:
    assert len(marked_texts()) > 50


def test_templates_are_read_too() -> None:
    texts = template_texts()
    assert ("Log in to the owner portal",) in texts
    assert any("%(email)s" in text for (text, *_) in texts)  # a {% blocktranslate %}


def test_every_marked_text_has_a_greek_translation() -> None:
    with CATALOGUE.open("rb") as compiled:
        catalogue = gettext.GNUTranslations(compiled)
    missing = []
    for texts, path in {**template_texts(), **marked_texts()}.items():
        if len(texts) == 2:
            translated = catalogue.ngettext(texts[0], texts[1], 2) != texts[1]
        else:
            translated = texts[0] in SAME_IN_GREEK or catalogue.gettext(texts[0]) != texts[0]
        if not translated:
            missing.append(f"{texts[0]!r} ({path.relative_to(BACKEND)})")
    assert missing == [], "add these to locale/el/LC_MESSAGES/django.po and run make messages"
