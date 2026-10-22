"""KosPM: property management for short-term rentals on Kos.

A modular monolith (ADR 0001). Every subpackage is a bounded context from docs/DOMAIN.md §4
(properties, reservations, housekeeping, ...) laid out as hexagonal layers
(domain / service_layer / adapters / entrypoints), plus `shared`, the shared kernel that every
context may use. Contexts never import each other: they talk through the message bus and by IDs.
The import-linter contracts in pyproject.toml enforce these rules.
"""
