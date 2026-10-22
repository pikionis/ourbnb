"""Shared-kernel adapters: Django and third-party implementations of the shared ports.

The Django Unit of Work and the Fernet encryption helpers live here. Domain and service-layer code
never imports this package (import-linter contracts); bootstrap and context adapters do.
"""
