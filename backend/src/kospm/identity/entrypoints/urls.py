"""URLs of the account pages, under /owner/ (ADR 0017)."""

from django.urls import path

from kospm.identity.entrypoints import views

app_name = "identity"

urlpatterns = [
    path("login/", views.OwnerLoginView.as_view(), name="login"),
    path("logout/", views.OwnerLogoutView.as_view(), name="logout"),
    path("signup/", views.sign_up, name="signup"),
    path("signup/sent/", views.sign_up_sent, name="signup_sent"),
    path("verify/<uuid:account_id>/<str:token>/", views.confirm_email, name="confirm"),
    path(
        "invitation/<uuid:account_id>/<str:token>/",
        views.accept_invitation,
        name="invitation",
    ),
    path("password/forgot/", views.password_forgot, name="password_forgot"),
    path("password/forgot/sent/", views.password_forgot_sent, name="password_forgot_sent"),
    path(
        "password/reset/<uuid:account_id>/<str:token>/",
        views.reset_password,
        name="password_reset",
    ),
    path("privacy/", views.privacy, name="privacy"),
]
