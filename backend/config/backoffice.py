"""Callbacks of the back office's theme (django-unfold, settings.UNFOLD)."""

from typing import Any

from django.conf import settings
from django.utils.translation import gettext_lazy as _

# unfold's badge colours.
_LABELS = {
    "staging": (_("Staging"), "warning"),
    "development": (_("Development"), "info"),
}


def environment_label(request: Any) -> list[str] | None:
    """The badge at the top of every back-office page: none in production."""
    label = _LABELS.get(settings.KOSPM_ENV)
    if label is None:
        return None
    text, colour = label
    return [str(text), colour]
