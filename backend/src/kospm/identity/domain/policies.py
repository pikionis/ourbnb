"""Configuration objects of the identity context (CLAUDE.md: policies are configuration).

Bootstrap builds them from settings; tests build them directly.
"""

from dataclasses import dataclass
from datetime import timedelta

from kospm.identity.domain.account import AccountLink


@dataclass(frozen=True, kw_only=True)
class LinkLifetimes:
    """How long an emailed link works (DOMAIN §5: links work once and expire)."""

    confirmation: timedelta = timedelta(days=3)
    invitation: timedelta = timedelta(days=3)
    password_reset: timedelta = timedelta(days=1)

    def __post_init__(self) -> None:
        for link in AccountLink:
            if self.of(link) <= timedelta(0):
                raise ValueError(f"the lifetime of a {link} link must be positive")

    def of(self, link: AccountLink) -> timedelta:
        lifetime: timedelta = getattr(self, link.value)
        return lifetime
