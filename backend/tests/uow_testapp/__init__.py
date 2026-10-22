"""Test-only Django app: a small aggregate table for the DjangoUnitOfWork integration tests.

Installed only by config.settings.test. It has no migrations package on purpose: the test runner
creates its tables directly (syncdb) and `makemigrations --check` ignores it.
"""
