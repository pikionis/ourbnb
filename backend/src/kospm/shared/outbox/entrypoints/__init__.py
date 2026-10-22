"""Entrypoints of the outbox: the read-only Django admin and the `process_outbox` command.

Same convention as every context: the real code lives here; Django's discovery points
(`outbox/admin.py`, `outbox/management/commands/*.py`) are one-line re-exports of it.
"""
