"""Shared kernel: the small set of building blocks every bounded context may depend on.

It must stay small and stable: only concepts that are truly shared (Money, Clock, domain base
classes, Unit of Work, message bus, outbox). It never imports a bounded context.
"""
