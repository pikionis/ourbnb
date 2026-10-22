"""Identity generation.

The domain assigns ids itself instead of waiting for a database sequence: an aggregate has its id
from the moment it is created, so it can be referenced by other contexts (by ID, never by object)
and put in events before anything is saved.
"""

from uuid import UUID, uuid4


def new_id() -> UUID:
    """A new random identity."""
    return uuid4()
