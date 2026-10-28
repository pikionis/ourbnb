"""The identity domain model: owner accounts of the owner portal (DOMAIN §5, ADR 0017).

Pure Python, no Django (CLAUDE.md dependency rules).

- `account`: the OwnerAccount aggregate, its email address, states and emailed links.
- `policies`: configuration objects (how long emailed links work).
- `events`, `commands`, `errors`.
"""
