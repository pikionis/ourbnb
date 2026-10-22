# 0015 — Money: full precision through arithmetic, explicit rounding at the end

- Status: accepted
- Date: 2026-10-22

## Context
DOMAIN §2.5: money is `Decimal`, never `float`, all amounts in EUR, "rounded half-up to 2
decimals at the end of each calculation". Statements and payouts (Phase 10) chain several steps
(commission, platform fee, owner share). Rounding every intermediate value drifts by cents: two
half cents rounded separately give 0.02, added first and rounded once they give 0.01. A float,
or a bare number where an amount was meant, must fail where it enters, not in a payout.

## Decision
`kospm.shared.domain.Money` is a frozen Value Object holding a `Decimal` amount, currency EUR.
- **Full precision** through arithmetic: `+` and `-` between Money values, unary `-`, and `*` by
  a `Decimal` or an `int` keep every digit (the default decimal context, 28 significant digits).
- **Explicit rounding:** `rounded()` applies `ROUND_HALF_UP` to 0.01 and is called once, at the end
  of each calculation, never on intermediate values. `is_rounded` tells whether an amount is a
  whole number of cents.
- **Percentages:** `percent(15)` means 15 %. A rate stored as a fraction (a contract's commission
  `0.15`) is applied with `money * Decimal("0.15")`.
- **Refused at runtime:** a `float` or a `bool` (TypeError) in the constructor or as a factor;
  arithmetic or ordering with a bare number (TypeError); a malformed string, NaN or infinity
  (ValueError); a truth test such as `if fee:` (TypeError), because it would mean "not zero"
  with Decimal habits but "not None" for an optional amount: write `fee != Money.zero()` or
  `fee is not None`. The operator signatures stay narrow, so mypy rejects most misuse statically
  too (`__bool__` returns `NoReturn`, so code behind a truth test is flagged as unreachable).
- **Equality is numeric:** `Money("1.0") == Money("1.00")`, and both hash alike.
- **Persistence:** adapters store only rounded amounts (`assert money.is_rounded` before writing a
  `DecimalField(max_digits=…, decimal_places=2)`), so the database never holds a value that a
  later read would silently round.

## Consequences
- Calculations read like the business rule, and the single `rounded()` call marks where DOMAIN
  §2.5 applies. The DOMAIN §10 worked example (owner 660.00, IKE 168.50) is a unit test.
- Forgetting `rounded()` before storing fails loudly at the adapter instead of truncating cents.
- `sum()` needs the start value `Money.zero()`, because `0 + Money` is a TypeError by design.
- Only EUR exists. A second currency would need a new ADR (currency field, no mixed arithmetic).
- Arithmetic follows the thread's decimal context; nothing in KosPM may change its precision.
