"""Base exception for broken business rules."""


class DomainError(Exception):
    """A business rule refused an operation (e.g. activating a property that is not ready).

    Each context subclasses it with a specific, glossary-named error. Entrypoints can map the whole
    family to a user-facing error, while programming errors stay ordinary exceptions.
    """
