"""Money (DOMAIN.md §2.5): Decimal, EUR, never float, rounded half-up at the end of a calculation.

A `# type: ignore[...]` line is also a static check: mypy must reject it (warn_unused_ignores).
"""

import copy
import dataclasses
import pickle
from decimal import Decimal

import pytest

from kospm.shared.domain import Money

# --- Construction -----------------------------------------------------------------------------


def test_money_is_built_from_str_int_or_decimal() -> None:
    assert Money("12.50").amount == Decimal("12.50")
    assert Money(12).amount == Decimal(12)
    assert Money(Decimal("0.1")).amount == Decimal("0.1")
    assert isinstance(Money(12).amount, Decimal)


def test_money_is_always_eur() -> None:
    assert Money.CURRENCY == "EUR"


@pytest.mark.parametrize("value", [0.1, 1.0, float("nan")])
def test_a_float_is_rejected(value: float) -> None:
    # 0.1 as a float is 0.1000000000000000055511151231257827…: the error must surface here.
    with pytest.raises(TypeError, match="float"):
        Money(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, False])
def test_a_bool_is_rejected_although_it_is_an_int(value: bool) -> None:
    with pytest.raises(TypeError, match="bool"):
        Money(value)


@pytest.mark.parametrize("value", [None, object(), [1], Money("1.00")])
def test_other_types_are_rejected(value: object) -> None:
    with pytest.raises(TypeError):
        Money(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["abc", "", "12,50", "NaN", "sNaN", "Infinity", "-Infinity"])
def test_a_string_that_is_not_a_finite_number_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="amount"):
        Money(value)


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_a_decimal_that_is_not_finite_is_rejected(value: Decimal) -> None:
    with pytest.raises(ValueError, match="amount"):
        Money(value)


def test_zero() -> None:
    assert Money.zero() == Money("0.00")
    assert Money.zero().amount == Decimal(0)


# --- Arithmetic -------------------------------------------------------------------------------


def test_money_adds_and_subtracts_money() -> None:
    assert Money("10.10") + Money("0.05") == Money("10.15")
    assert Money("10.10") - Money("0.15") == Money("9.95")
    assert Money("5.00") - Money("7.50") == Money("-2.50")


def test_decimal_arithmetic_has_no_float_surprises() -> None:
    assert Money("0.1") + Money("0.2") == Money("0.3")


def test_a_list_of_money_is_summed_from_money_zero() -> None:
    charges = [Money("12.00"), Money("35.00"), Money("40.00")]
    assert sum(charges, Money.zero()) == Money("87.00")


def test_money_plus_decimal_is_rejected() -> None:
    with pytest.raises(TypeError, match="Money"):
        Money("1.00") + Decimal("1")  # type: ignore[operator]


def test_money_plus_int_is_rejected() -> None:
    with pytest.raises(TypeError, match="Money"):
        Money("1.00") + 1  # type: ignore[operator]


def test_money_minus_int_is_rejected() -> None:
    with pytest.raises(TypeError, match="Money"):
        Money("1.00") - 1  # type: ignore[operator]


def test_decimal_plus_money_is_rejected() -> None:
    with pytest.raises(TypeError):
        Decimal("1") + Money("1.00")  # type: ignore[operator]


def test_int_minus_money_is_rejected() -> None:
    # Also why sum() needs the Money.zero() start value.
    with pytest.raises(TypeError):
        0 - Money("1.00")  # type: ignore[operator]


def test_negation() -> None:
    assert -Money("5.00") == Money("-5.00")
    assert -Money("-5.00") == Money("5.00")


def test_money_is_multiplied_by_a_decimal_or_an_int_on_either_side() -> None:
    assert Money("10.00") * Decimal("1.5") == Money("15.00")
    assert Money("2.50") * 3 == Money("7.50")
    assert 3 * Money("2.50") == Money("7.50")
    assert Decimal("0.5") * Money("3.00") == Money("1.50")


def test_money_times_a_float_is_rejected() -> None:
    with pytest.raises(TypeError, match="float"):
        Money("1.00") * 1.5  # type: ignore[operator]


def test_a_float_times_money_is_rejected() -> None:
    with pytest.raises(TypeError, match="float"):
        1.5 * Money("1.00")  # type: ignore[operator]


def test_money_times_a_bool_is_rejected() -> None:
    with pytest.raises(TypeError, match="bool"):
        Money("1.00") * True


def test_money_times_money_is_rejected() -> None:
    # EUR x EUR is not an amount of money.
    with pytest.raises(TypeError, match="Money"):
        Money("1.00") * Money("2.00")  # type: ignore[operator]


def test_money_times_a_string_is_rejected() -> None:
    with pytest.raises(TypeError):
        Money("1.00") * "2"  # type: ignore[operator]


def test_money_times_a_non_finite_decimal_is_rejected() -> None:
    with pytest.raises(ValueError, match="factor"):
        Money("1.00") * Decimal("NaN")


def test_percent_takes_the_percentage_itself() -> None:
    # percent(15) is 15 %; a contract rate stored as 0.15 is applied with `money * rate`.
    assert Money("1000.00").percent(15) == Money("150.00")
    assert Money("200.00").percent(Decimal("12.5")) == Money("25.00")
    assert Money("1000.00") * Decimal("0.15") == Money("1000.00").percent(15)


def test_percent_keeps_full_precision() -> None:
    assert Money("10.01").percent(Decimal("12.5")).amount == Decimal("1.25125")


def test_percent_of_a_float_is_rejected() -> None:
    with pytest.raises(TypeError, match="float"):
        Money("100.00").percent(1.5)  # type: ignore[arg-type]


def test_percent_of_a_bool_is_rejected() -> None:
    with pytest.raises(TypeError, match="bool"):
        Money("100.00").percent(True)


# --- Rounding ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("0.125", "0.13"),  # banker's rounding (ROUND_HALF_EVEN) would give 0.12
        ("0.135", "0.14"),
        ("2.675", "2.68"),  # float rounding would give 2.67 (2.675 is 2.67499999… as a float)
        ("0.124", "0.12"),
        ("-0.125", "-0.13"),  # half-up rounds ties away from zero
        ("12.345", "12.35"),
        ("1", "1.00"),
        ("1000", "1000.00"),
    ],
)
def test_rounded_is_half_up_to_the_cent(amount: str, expected: str) -> None:
    rounded = Money(amount).rounded()
    assert str(rounded.amount) == expected


def test_full_precision_is_kept_until_rounded() -> None:
    share = Money("10.00") * Decimal("0.3333")
    assert share.amount == Decimal("3.333")
    assert share != Money("3.33")
    assert share.rounded() == Money("3.33")


def test_rounding_happens_once_at_the_end_of_the_calculation() -> None:
    # Rounding each half cent first would give 0.02.
    half_cent = Money("0.005")
    assert (half_cent + half_cent).rounded() == Money("0.01")
    assert half_cent.rounded() + half_cent.rounded() == Money("0.02")


def test_is_rounded_tells_whether_the_amount_is_whole_cents() -> None:
    assert Money("1.00").is_rounded
    assert Money("1").is_rounded
    assert Money("1.010").is_rounded
    assert not Money("1.005").is_rounded
    assert (Money("10.00") * Decimal("0.3333")).rounded().is_rounded


# --- Equality, ordering, immutability ---------------------------------------------------------


def test_equality_is_numeric_and_equal_amounts_hash_equal() -> None:
    assert Money("1.0") == Money("1.00")
    assert hash(Money("1.0")) == hash(Money("1.00"))
    assert len({Money("1.0"), Money("1.00"), Money(1)}) == 1
    assert Money("1.00") != Money("1.01")


def test_money_is_never_equal_to_a_bare_number() -> None:
    assert Money("1.00") != Decimal("1")
    assert Money("1.00") != 1  # type: ignore[comparison-overlap]


def test_money_is_ordered_by_amount() -> None:
    assert Money("1.00") < Money("1.01")
    assert Money("1.01") >= Money("1.010")
    assert max(Money("40.00"), Money("35.00"), Money("12.00")) == Money("40.00")
    assert sorted([Money("2"), Money("-1"), Money("0")]) == [Money("-1"), Money("0"), Money("2")]


def test_money_is_not_comparable_with_a_bare_number() -> None:
    with pytest.raises(TypeError):
        _ = Money("1.00") < 1  # type: ignore[operator]


def test_money_is_not_comparable_with_a_decimal() -> None:
    with pytest.raises(TypeError):
        _ = Money("1.00") >= Decimal("1")  # type: ignore[operator]


@pytest.mark.parametrize("amount", ["0", "-0.00", "12.50"])
def test_money_has_no_truth_value(amount: str) -> None:
    # Decimal(0) is falsy, so `if fee:` would read as "fee is not zero" to some and as "fee is not
    # None" to others: refused, compare explicitly instead.
    with pytest.raises(TypeError, match="truth value"):
        bool(Money(amount))


def test_money_is_immutable() -> None:
    money = Money("1.00")
    with pytest.raises(dataclasses.FrozenInstanceError):
        money.amount = Decimal("2.00")  # type: ignore[misc]


def test_money_has_no_room_for_extra_attributes() -> None:
    with pytest.raises(AttributeError):
        Money("1.00").note = "tip"  # type: ignore[attr-defined]


def test_money_survives_copy_and_pickle() -> None:
    money = Money("12.345")
    assert copy.deepcopy(money) == money
    assert pickle.loads(pickle.dumps(money)) == money


# --- Display ----------------------------------------------------------------------------------


def test_str_shows_the_rounded_amount_and_the_currency() -> None:
    assert str(Money("12.345")) == "12.35 EUR"
    assert str(Money("1")) == "1.00 EUR"
    assert str(Money("-12.5")) == "-12.50 EUR"


def test_str_never_shows_a_negative_zero() -> None:
    assert str(Money("-0.001")) == "0.00 EUR"


def test_repr_keeps_full_precision() -> None:
    assert repr(Money("12.345")) == "Money('12.345')"


# --- DOMAIN.md §10 worked example (the Phase 10 acceptance test, in plain Money) ----------------


def test_domain_worked_example_owner_share_and_ike_net() -> None:
    accommodation_price = Money("1000.00")  # A
    guest_cleaning_fee = Money("30.00")
    platform_fee_percent = 15  # "platform fee 15 % on everything"
    commission_rate = Decimal("0.15")  # Contract.commission_rate
    owner_cleaning_charge = Money("40.00")  # Contract.owner_cleaning_charge x 1 cleaning
    laundry_cost = Money("12.00")
    cleaner_pay = Money("35.00")

    platform_fee_on_accommodation = accommodation_price.percent(platform_fee_percent)
    platform_fee_on_cleaning_fee = guest_cleaning_fee.percent(platform_fee_percent)
    ike_commission = accommodation_price * commission_rate

    owner_share = (
        accommodation_price - platform_fee_on_accommodation - ike_commission - owner_cleaning_charge
    ).rounded()
    ike_net = (
        ike_commission
        + owner_cleaning_charge
        + guest_cleaning_fee
        - platform_fee_on_cleaning_fee
        - laundry_cost
        - cleaner_pay
    ).rounded()

    assert platform_fee_on_accommodation.rounded() == Money("150.00")
    assert platform_fee_on_cleaning_fee.rounded() == Money("4.50")
    assert ike_commission.rounded() == Money("150.00")
    assert owner_share == Money("660.00")
    assert ike_net == Money("168.50")
    assert str(owner_share) == "660.00 EUR"
    assert str(ike_net) == "168.50 EUR"
