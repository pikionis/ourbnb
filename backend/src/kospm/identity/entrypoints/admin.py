"""Django admin registration for users (ADR 0006: the back office is the Django admin).

Staff users are edited as Django's UserAdmin allows. Owner accounts are the identity domain's
aggregates, so the admin shows them read-only and never deletes them or sets their password:
owners choose their password through an emailed link, and the admin invites an owner from the
owner's page (properties).
"""

from typing import TYPE_CHECKING, Any

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext_lazy as _

from kospm.identity.models import User

if TYPE_CHECKING:
    from django.contrib.admin.options import _FieldsetSpec

OWNER_ACCOUNT_FIELDS = (
    "email",
    "account_status",
    "owner_id",
    "owner_registered",
    "language",
    "is_active",
    "last_login",
    "date_joined",
)


@admin.register(User)
class KosPMUserAdmin(UserAdmin[User]):
    list_display = ("username", "email", "account_status", "is_staff", "is_active")
    list_filter = ("account_status", "is_staff", "is_superuser", "is_active")

    def get_fieldsets(self, request: HttpRequest, obj: User | None = None) -> "_FieldsetSpec":
        if _is_owner_account(obj):
            return [(_("Owner portal account"), {"fields": OWNER_ACCOUNT_FIELDS})]
        return super().get_fieldsets(request, obj)

    def get_readonly_fields(self, request: HttpRequest, obj: User | None = None) -> Any:
        if _is_owner_account(obj):
            return OWNER_ACCOUNT_FIELDS
        return super().get_readonly_fields(request, obj)

    def has_delete_permission(self, request: HttpRequest, obj: User | None = None) -> bool:
        return not _is_owner_account(obj) and super().has_delete_permission(request, obj)

    def user_change_password(
        self, request: HttpRequest, id: str, form_url: str = ""
    ) -> HttpResponse:
        if _is_owner_account(self.get_object(request, id)):
            raise PermissionDenied("owners choose their password through an emailed link")
        return super().user_change_password(request, id, form_url)


def _is_owner_account(user: User | None) -> bool:
    return user is not None and user.account_id is not None
