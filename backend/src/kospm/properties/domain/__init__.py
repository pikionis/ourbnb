"""The properties domain model: pure Python, no Django (CLAUDE.md dependency rules).

- `owner`: the Owner aggregate and its bank account verification.
- `property`: the Property aggregate, its states and the activation checklist.
- `value_objects`: validated values (property code, ΑΦΜ, IBAN, contract, check-in guide, ...).
- `checklist`: the names of checklist items and profile gaps.
- `events`, `commands`, `errors`, `defaults` (configuration objects).
"""
