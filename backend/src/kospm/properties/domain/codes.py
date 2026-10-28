"""The automatic codes of properties added by owners (DOMAIN §5, owner portal).

A code is fixed for life and guests quote it, so a new one is never a reused one: the next
number is one more than the highest number in use with the prefix. Prefix and width are
configuration (validation details, Phase 2b).
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from kospm.properties.domain.value_objects import PropertyCode

_PREFIX = re.compile(r"[A-Z0-9]+")


@dataclass(frozen=True, kw_only=True)
class PropertyCodeSeries:
    """Codes `<prefix>-<number>`, the number padded to `digits` (e.g. KOS-014)."""

    prefix: str = "KOS"
    digits: int = 3

    def __post_init__(self) -> None:
        prefix = self.prefix.strip().upper()
        # The longest code is 16 characters: leave room for a hyphen and the number.
        if not _PREFIX.fullmatch(prefix) or len(prefix) + 1 + self.digits > 16:
            raise ValueError(f"the code prefix {self.prefix!r} cannot make valid property codes")
        if self.digits < 1:
            raise ValueError(f"digits must be at least 1, got {self.digits}")
        object.__setattr__(self, "prefix", prefix)

    def next_code(self, taken: Iterable[PropertyCode]) -> PropertyCode:
        pattern = re.compile(rf"{re.escape(self.prefix)}-([0-9]+)")
        numbers = [int(match[1]) for code in taken if (match := pattern.fullmatch(code.value))]
        return PropertyCode(f"{self.prefix}-{max(numbers, default=0) + 1:0{self.digits}d}")
