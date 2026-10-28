"""PasswordHasher adapter: Django's configured hashers (PASSWORD_HASHERS)."""

from django.contrib.auth.hashers import make_password

from kospm.identity.service_layer.ports import PasswordHasher


class DjangoPasswordHasher(PasswordHasher):
    def hash(self, password: str) -> str:
        return make_password(password)
