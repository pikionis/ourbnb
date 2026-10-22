"""ORM models of the identity context (infrastructure only, no business rules)."""

from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """A login account: the Admin today, Owners of the owner portal from v3.

    A custom user model from day one because Django cannot swap AUTH_USER_MODEL after the first
    migration without hand-written data migrations. It adds no fields yet; roles come later.
    """
