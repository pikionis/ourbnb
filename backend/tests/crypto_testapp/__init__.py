"""Test-only Django app: a model with an EncryptedTextField, for the crypto integration tests.

Installed only by config.settings.test. It has no migrations package on purpose: the test runner
creates its tables directly (syncdb) and `makemigrations --check` ignores it.
"""
