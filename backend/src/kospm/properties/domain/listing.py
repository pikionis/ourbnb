"""Listing text an owner pastes, and the draft profile the AI reads from it (DOMAIN §5).

The AI only interprets the text into a draft (DOMAIN §2.4): the owner reviews the draft in the
profile form and saves it with the usual command. Only text is accepted, never a link: the
platform never fetches a listing (DOMAIN §2.1). A draft has no place for a key-box code.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from kospm.properties.domain.amenities import amenity_key, common_amenity
from kospm.properties.domain.errors import InvalidValue

_ONLY_A_LINK = re.compile(r"\s*(?:https?://|www\.)\S*\s*", re.IGNORECASE)
_MAX_ADDRESS = 300
_MAX_DIRECTIONS = 4000
_MAX_AMENITY = 80
_MAX_AMENITIES = 60
_TEXTS = ("address", "directions_el", "directions_en")


@dataclass(frozen=True, kw_only=True)
class ListingTextPolicy:
    """How much text one reading may send (configuration: cost and response time)."""

    max_characters: int = 20_000

    def __post_init__(self) -> None:
        if self.max_characters < 1:
            raise ValueError(f"max_characters must be at least 1, got {self.max_characters}")


@dataclass(frozen=True)
class ListingText:
    """What the owner pasted: the listing's text, not its link. Kept out of repr (and so out of
    logs and tracebacks): an owner may paste a key-box code with it."""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        text = self.value.strip()
        if not text or _ONLY_A_LINK.fullmatch(text):
            raise InvalidValue("paste the listing's text, not its link", field="listing_text")
        object.__setattr__(self, "value", text)


@dataclass(frozen=True, kw_only=True)
class ProfileFields:
    """The parts of a profile that listing text can fill in, as the owner has them now."""

    address: str = ""
    directions_el: str = ""
    directions_en: str = ""
    amenities_included: tuple[str, ...] = ()
    amenities_not_included: tuple[str, ...] = ()


@dataclass(frozen=True)
class FilledProfile:
    """A profile with its gaps filled in from a draft, and what came from the draft: the names
    of the texts and the amenities added (the owner is asked to check them)."""

    fields: ProfileFields
    texts: frozenset[str]
    amenities: frozenset[str]


@dataclass(frozen=True)
class ListingDraft:
    """Profile fields read from a listing, for the owner to check. Empty means "not found".

    An amenity is one amenity however it is written ("WiFi" is "Wi-Fi"); one the listing gives
    both ways is dropped, so the owner answers it.
    """

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
        both = _keys(included) & _keys(not_included)  # contradictory: the owner decides
        object.__setattr__(
            self, "amenities_included", tuple(i for i in included if amenity_key(i) not in both)
        )
        object.__setattr__(
            self,
            "amenities_not_included",
            tuple(i for i in not_included if amenity_key(i) not in both),
        )

    def fill_gaps(self, current: ProfileFields) -> FilledProfile:
        """`current` with its gaps filled in from this draft (design brief J6).

        Nothing the owner entered changes: a text is filled in only when it is empty, and an
        amenity is added only when the owner has not answered it either way. A common amenity
        is added by its common name, so it fills the owner's Yes / No question.
        """
        texts = {name: getattr(current, name) for name in _TEXTS}
        filled_texts = {name for name in _TEXTS if getattr(self, name) and not texts[name].strip()}
        texts.update({name: getattr(self, name) for name in filled_texts})
        answered = _keys((*current.amenities_included, *current.amenities_not_included))
        added: dict[bool, list[str]] = {True: [], False: []}
        for included, items in (
            (True, self.amenities_included),
            (False, self.amenities_not_included),
        ):
            for item in items:
                if amenity_key(item) not in answered:
                    added[included].append(common_amenity(item) or item)
                    answered.add(amenity_key(item))
        return FilledProfile(
            fields=ProfileFields(
                address=texts["address"],
                directions_el=texts["directions_el"],
                directions_en=texts["directions_en"],
                amenities_included=(*current.amenities_included, *added[True]),
                amenities_not_included=(*current.amenities_not_included, *added[False]),
            ),
            texts=frozenset(filled_texts),
            amenities=frozenset((*added[True], *added[False])),
        )


def _items(items: Iterable[str]) -> tuple[str, ...]:
    """Trimmed and short, each amenity once however written, at most _MAX_AMENITIES."""
    kept: dict[str, str] = {}
    for item in items:
        text = item.strip()[:_MAX_AMENITY]
        if amenity_key(text):  # blank or punctuation only: not an amenity
            kept.setdefault(amenity_key(text), text)
    return tuple(kept.values())[:_MAX_AMENITIES]


def _keys(items: Iterable[str]) -> set[str]:
    return {amenity_key(item) for item in items}
