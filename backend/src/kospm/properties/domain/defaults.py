"""Configuration objects of the properties context (CLAUDE.md: policies are configuration).

Bootstrap builds them from settings; tests build them directly. The defaults below are the
values of DOMAIN §5 and are what a fresh installation uses.
"""

from dataclasses import dataclass, field
from datetime import time
from decimal import Decimal

from kospm.shared.domain import Money


@dataclass(frozen=True, kw_only=True)
class PropertyDefaults:
    """What a new property and a new contract start with until someone changes them."""

    check_in_time: time = time(15, 0)
    check_out_time: time = time(11, 0)
    linen_par_level: int = 3
    commission_rate: Decimal = Decimal("0.15")
    owner_cleaning_charge: Money = field(default_factory=lambda: Money("40.00"))


@dataclass(frozen=True, kw_only=True)
class BankVerificationPolicy:
    """How many wrong codes a test transfer allows before a new transfer is needed."""

    max_attempts: int = 3

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {self.max_attempts}")
