"""Money: the Value Object for every amount in KosPM (DOMAIN.md §2.5; Cosmic Python ch. 1).

- An amount is a `Decimal` in EUR. A `float` is refused everywhere (TypeError): a binary float
  cannot hold 0.10 exactly, and the error must surface where the float enters, not in a payout.
  `bool` is refused too, although Python treats it as an int.
- Arithmetic keeps full precision (the 28 significant digits of the default decimal context).
  `rounded()` rounds half-up to the cent and is called once, at the end of each calculation
  (owner share, IKE net...), never on intermediate values: rounding every step drifts by cents.
- `percent(15)` is 15 %. A rate stored as a fraction (`Contract.commission_rate = 0.15`) is
  applied with `money * rate`.
- Money combines only with Money (`+`, `-`, comparisons) and scales only by a Decimal or an int.
  A bare number on the other side is a TypeError: it is usually a missing `Money(...)`.
- Equality is numeric: `Money("1.0") == Money("1.00")`, and both hash alike.
- Money has no truth value (TypeError): `if fee:` must be `fee != Money.zero()` or
  `fee is not None`, whichever is meant.

The runtime checks live in helpers that take `object`, so the operator signatures stay narrow
and mypy still rejects `Money("1.00") + 1` statically; the checks guard untyped callers.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import ClassVar, Final, NoReturn, final

_CENT: Final = Decimal("0.01")


@final  # Equality and ordering assume the exact class: a subclass would break value semantics.
# No `slots=True`: on Python 3.12 a frozen slotted dataclass answers `money.note = ...` with a
# confusing `TypeError: super(type, obj)` instead of FrozenInstanceError.
@dataclass(frozen=True, init=False, order=True)
class Money:
    """An amount of euros. Build it from a Decimal, an int or a str: `Money("12.50")`."""

    amount: Decimal
    CURRENCY: ClassVar[str] = "EUR"

    def __init__(self, amount: Decimal | int | str) -> None:
        # Frozen dataclass: the one assignment goes through object.__setattr__.
        object.__setattr__(self, "amount", _to_amount(amount))

    @classmethod
    def zero(cls) -> "Money":
        """0 EUR, also the start value for `sum(amounts, Money.zero())`."""
        return Money(0)

    def __add__(self, other: "Money") -> "Money":
        return Money(self.amount + _require_money(other).amount)

    def __sub__(self, other: "Money") -> "Money":
        return Money(self.amount - _require_money(other).amount)

    def __neg__(self) -> "Money":
        return Money(-self.amount)

    def __mul__(self, factor: Decimal | int) -> "Money":
        return Money(self.amount * _to_factor(factor, "Money factor"))

    def __rmul__(self, factor: Decimal | int) -> "Money":
        return self * factor

    def percent(self, rate: Decimal | int) -> "Money":
        """`rate` percent of this amount: `Money("1000.00").percent(15) == Money("150.00")`."""
        return Money(self.amount * _to_factor(rate, "percentage") / 100)

    def rounded(self) -> "Money":
        """Half-up to the cent (0.125 -> 0.13, -0.125 -> -0.13), at the end of a calculation."""
        return Money(self.amount.quantize(_CENT, rounding=ROUND_HALF_UP))

    @property
    def is_rounded(self) -> bool:
        """True when the amount is a whole number of cents."""
        return self.amount == self.rounded().amount

    def __bool__(self) -> NoReturn:
        # `if fee:` is ambiguous: "not zero" (Decimal habits) or "not None" (an optional amount).
        # Refused at runtime; `NoReturn` also makes mypy flag the code behind such a test as
        # unreachable.
        raise TypeError(
            "Money has no truth value: compare explicitly, e.g. `amount != Money.zero()` "
            "or `amount is not None`"
        )

    def __str__(self) -> str:
        cents = self.rounded().amount
        if cents.is_zero():
            cents = cents.copy_abs()  # never display "-0.00 EUR"
        return f"{cents:f} {self.CURRENCY}"

    def __repr__(self) -> str:
        # Full precision, unlike __str__: a repr must not hide the unrounded digits.
        return f"Money('{self.amount}')"


def _reject_float_and_bool(value: object, what: str) -> None:
    # bool first: it is a subclass of int, so later isinstance(value, int) checks would accept it.
    if isinstance(value, bool):
        raise TypeError(f"{what} cannot be a bool ({value!r})")
    if isinstance(value, float):
        raise TypeError(f"{what} cannot be a float ({value!r}): use a Decimal or an exact str")


def _to_amount(value: object) -> Decimal:
    _reject_float_and_bool(value, "a Money amount")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, str):
        try:
            amount = Decimal(value)
        except InvalidOperation:
            raise ValueError(
                f"invalid Money amount {value!r}: expected a decimal number such as '12.50'"
            ) from None
    else:
        raise TypeError(
            f"a Money amount must be a Decimal, an int or a str, not {type(value).__name__}"
        )
    if not amount.is_finite():
        raise ValueError(f"invalid Money amount {value!r}: it must be a finite number")
    return amount


def _to_factor(value: object, what: str) -> Decimal:
    _reject_float_and_bool(value, f"a {what}")
    if isinstance(value, Decimal):
        factor = value
    elif isinstance(value, int):
        factor = Decimal(value)
    else:
        # Includes Money: EUR x EUR is not an amount of money.
        raise TypeError(f"a {what} must be a Decimal or an int, not {type(value).__name__}")
    if not factor.is_finite():
        raise ValueError(f"invalid {what} {value!r}: it must be a finite number")
    return factor


def _require_money(value: object) -> Money:
    if not isinstance(value, Money):
        raise TypeError(
            f"Money combines only with Money, not {type(value).__name__}: "
            "wrap the amount in Money(...)"
        )
    return value
