"""Django admin registration for users (ADR 0006: the back office is the Django admin)."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from kospm.identity.models import User

admin.site.register(User, UserAdmin)
