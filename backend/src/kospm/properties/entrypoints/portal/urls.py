"""URLs of the owner portal's pages of properties, under /owner/ (ADR 0017)."""

from django.urls import path

from kospm.properties.entrypoints.portal import views

app_name = "portal"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("details/", views.details, name="details"),
    path("bank/", views.bank, name="bank"),
]
