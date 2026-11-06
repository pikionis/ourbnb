"""A request for an estimate from the public site's form (ADR 0021).

Someone with a home asks us to call. They are not an owner yet, so nothing is stored as an Owner:
the lead is mailed to the IKE, who calls them. Values the form does not offer count as not stated
(None), so a bot cannot put free text in the subject of an email.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from kospm.properties.domain.errors import InvalidValue

_MAX_NAME = 100
_MAX_PHONE = 30
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]+")
_PHONE = re.compile(rf"[0-9+()\-\s]{{6,{_MAX_PHONE}}}")


class ListedOnline(StrEnum):
    """Whether the home is already on Booking.com or Airbnb. Values are the form's."""

    NO = "no"
    ONE = "one"
    BOTH = "both"


@dataclass(frozen=True, kw_only=True)
class LeadFormOptions:
    """What the site's form offers (a configuration object): it changes with the site."""

    areas: tuple[str, ...]
    bedrooms: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.areas:
            raise ValueError("the form must offer areas")
        if not self.bedrooms:
            raise ValueError("the form must offer bedrooms")


@dataclass(frozen=True, kw_only=True)
class OwnerLead:
    name: str
    phone: str
    area: str | None
    bedrooms: str | None
    listed_online: ListedOnline | None

    @classmethod
    def from_form(
        cls,
        *,
        name: str,
        phone: str,
        area: str,
        bedrooms: str,
        online: str,
        options: LeadFormOptions,
    ) -> Self:
        """The lead a form asks for; raises InvalidValue when we could not call them back."""
        name = _clean(name)[:_MAX_NAME]
        phone = _clean(phone)
        if not name:
            raise InvalidValue("a lead needs a name", field="name")
        if not _PHONE.fullmatch(phone):
            raise InvalidValue("a lead needs a phone number", field="phone")
        area, bedrooms = area.strip(), bedrooms.strip()
        return cls(
            name=name,
            phone=phone,
            area=area if area in options.areas else None,
            bedrooms=bedrooms if bedrooms in options.bedrooms else None,
            listed_online=_listed_online(online),
        )


def _clean(value: str) -> str:
    """One line of text: line breaks and control characters become a space."""
    return _CONTROL_CHARACTERS.sub(" ", value).strip()


def _listed_online(value: str) -> ListedOnline | None:
    try:
        return ListedOnline(value.strip())
    except ValueError:
        return None
