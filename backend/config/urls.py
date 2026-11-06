"""Root URL configuration."""

from django.contrib import admin
from django.urls import include, path

from config.health import healthz
from kospm.properties.entrypoints.lead import owner_lead

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    # Where the public site's form already posts: the site needs no edit at the switch (ADR 0021).
    path("api/lead.php", owner_lead, name="owner_lead"),
    # The owner portal (ADR 0017): account pages of identity, onboarding pages of properties.
    path("owner/", include("kospm.identity.entrypoints.urls")),
    path("owner/", include("kospm.properties.entrypoints.portal.urls")),
    # The language toggle of the portal pages (set_language).
    path("i18n/", include("django.conf.urls.i18n")),
]
