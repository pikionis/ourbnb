"""URLs of the owner portal's pages of properties, under /owner/ (ADR 0017)."""

from django.urls import path

from kospm.properties.entrypoints.portal import property_views, views

app_name = "portal"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("details/", views.details, name="details"),
    path("bank/", views.bank, name="bank"),
    path("properties/new/", property_views.property_new, name="property_new"),
    path("properties/<str:code>/", property_views.property_page, name="property"),
    path(
        "properties/<str:code>/profile/",
        property_views.property_profile,
        name="property_profile",
    ),
    path(
        "properties/<str:code>/contract/",
        property_views.property_contract,
        name="property_contract",
    ),
    path(
        "properties/<str:code>/sublease/",
        property_views.property_sublease,
        name="property_sublease",
    ),
    path(
        "properties/<str:code>/files/<str:kind>/",
        property_views.property_file,
        name="property_file",
    ),
]
