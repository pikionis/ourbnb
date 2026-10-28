"""Listing text an owner pastes, and the draft profile the AI reads from it (DOMAIN §5).

The AI only interprets the text into a draft (DOMAIN §2.4): the owner reviews the draft in the
profile form and saves it with the usual command. Only text is accepted, never a link: the
platform never fetches a listing (DOMAIN §2.1). A draft has no place for a key-box code.
"""

import re
from dataclasses import dataclass

from kospm.properties.domain.errors import InvalidValue

_ONLY_A_LINK = re.compile(r"\s*(?:https?://|www\.)\S*\s*", re.IGNORECASE)
_MAX_ADDRESS = 300
_MAX_DIRECTIONS = 4000
_MAX_AMENITY = 80
_MAX_AMENITIES = 60


@dataclass(frozen=True, kw_only=True)
class ListingTextPolicy:
    """How much text one reading may send (configuration: cost and response time)."""

    max_characters: int = 20_000

    def __post_init__(self) -> None:
        if self.max_characters < 1:
            raise ValueError(f"max_characters must be at least 1, got {self.max_characters}")


@dataclass(frozen=True)
class ListingText:
    """What the owner pasted: the listing's text, not its link."""

    value: str

    def __post_init__(self) -> None:
        text = self.value.strip()
        if not text or _ONLY_A_LINK.fullmatch(text):
            raise InvalidValue("paste the listing's text, not its link", field="listing_text")
        object.__setattr__(self, "value", text)


@dataclass(frozen=True)
class ListingDraft:
    """Profile fields read from a listing, for the owner to check. Empty means "not found"."""

    address: str = ""
    directions_el: str = ""
    directions_en: str = ""
    amenities_included: tuple[str, ...] = ()
    amenities_not_included: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "address", self.address.strip()[:_MAX_ADDRESS])
        object.__setattr__(self, "directions_el", self.directions_el.strip()[:_MAX_DIRECTIONS])
        object.__setattr__(self, "directions_en", self.directions_en.strip()[:_MAX_DIRECTIONS])
        included = _items(self.amenities_included)
        not_included = _items(self.amenities_not_included)
        both = set(included) & set(not_included)  # contradictory: the owner decides
        object.__setattr__(self, "amenities_included", tuple(i for i in included if i not in both))
        object.__setattr__(
            self, "amenities_not_included", tuple(i for i in not_included if i not in both)
        )


def _items(items: tuple[str, ...]) -> tuple[str, ...]:
    """Trimmed, short, without blanks or repeats, at most _MAX_AMENITIES."""
    kept = dict.fromkeys(item.strip()[:_MAX_AMENITY] for item in items if item.strip())
    return tuple(kept)[:_MAX_AMENITIES]
