"""Root URL configuration."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # The owner portal (ADR 0017): account pages of identity.
    path("owner/", include("kospm.identity.entrypoints.urls")),
    # The language toggle of the portal pages (set_language).
    path("i18n/", include("django.conf.urls.i18n")),
]
