"""Forms of the account pages (ADR 0017).

Email addresses are validated by the domain's value object, passwords by Django's configured
validators (AUTH_PASSWORD_VALIDATORS). Login uses Django's AuthenticationForm: an owner's
username is their email address (see `identity.models`).
"""

from collections.abc import Callable
from typing import Any

from django import forms
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from unfold.forms import AuthenticationForm as UnfoldAuthenticationForm

from kospm.bootstrap import portal_throttle
from kospm.identity.adapters.queries import is_unconfirmed_login
from kospm.identity.domain.account import Email
from kospm.identity.domain.errors import InvalidValue
from kospm.identity.entrypoints.texts import THROTTLED, describe
from kospm.shared.adapters.portal import client_ip


def _checked(make: Callable[[], str]) -> str:
    """The normalised value from a value object, or a form error in the domain's words."""
    try:
        return make()
    except InvalidValue as error:
        raise ValidationError(describe(error)) from error


def _email_field() -> forms.CharField:
    return forms.CharField(
        label=_("Email"),
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )


class EmailForm(forms.Form):
    """One email address: to resend a confirmation or to ask for a new password."""

    email = _email_field()

    def clean_email(self) -> str:
        return _checked(lambda: Email(self.cleaned_data["email"]).value)


class NewPasswordForm(forms.Form):
    """A new password, typed twice and checked by Django's password validators."""

    password1 = forms.CharField(
        label=_("Password"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label=_("Password again"),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args: Any, email: str = "", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._email = email
        # The rules, shown before the owner types (brief §11), in the page's language.
        self.fields[
            "password1"
        ].help_text = password_validation.password_validators_help_text_html()

    @property
    def password(self) -> str:
        password: str = self.cleaned_data["password1"]
        return password

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        first, second = data.get("password1"), data.get("password2")
        if first and second and first != second:
            self.add_error("password2", _("The two passwords are different."))
        elif first:
            email = data.get("email") or self._email
            # An unsaved user, only for Django's similarity validator to compare with.
            owner = get_user_model()(username=email, email=email)
            try:
                password_validation.validate_password(first, user=owner)
            except ValidationError as error:
                self.add_error("password1", error)
        return data


class SignUpForm(NewPasswordForm):
    email = _email_field()
    field_order = ("email", "password1", "password2")

    def clean_email(self) -> str:
        return _checked(lambda: Email(self.cleaned_data["email"]).value)


class OwnerLoginForm(AuthenticationForm):
    """Login by email address. Refused, with the same words, for a wrong password, an unknown
    address and a staff login (staff use the admin); throttled per address and per visitor."""

    username = forms.CharField(
        label=_("Email"),
        max_length=254,
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}),
    )
    # Django's API: the form reads this class attribute (never mutated).
    error_messages = {  # noqa: RUF012
        **AuthenticationForm.error_messages,
        "invalid_login": _("Wrong email or password."),
        "unconfirmed": _(
            "Confirm your email address first: open the link we emailed you, or ask for a new "
            "one below."
        ),
        "throttled": THROTTLED,
    }

    def clean(self) -> dict[str, Any]:
        email = str(self.cleaned_data.get("username") or "").strip().lower()
        self.cleaned_data["username"] = email
        throttle = portal_throttle("login")
        keys = (f"ip:{client_ip(self.request)}", f"email:{email}") if self.request else ()
        if email and keys and not throttle.hit(*keys):
            raise ValidationError(self.error_messages["throttled"], code="throttled")
        data = super().clean()
        throttle.reset(f"email:{email}")
        return data

    def confirm_login_allowed(self, user: Any) -> None:
        if getattr(user, "account_id", None) is None:
            raise self.get_invalid_login_error()
        super().confirm_login_allowed(user)

    def get_invalid_login_error(self) -> ValidationError:
        email = str(self.cleaned_data.get("username") or "")
        password = str(self.cleaned_data.get("password") or "")
        if email and password and is_unconfirmed_login(email, password):
            return ValidationError(self.error_messages["unconfirmed"], code="unconfirmed")
        return super().get_invalid_login_error()


class AdminLoginForm(UnfoldAuthenticationForm, AdminAuthenticationForm):
    """The Django admin's login, throttled per username and per visitor: `/admin/` is the first
    address bots try (ADR 0021). It says the same words as the portal when it refuses."""

    # Django's API: the form reads this class attribute (never mutated).
    error_messages = {  # noqa: RUF012
        **AdminAuthenticationForm.error_messages,
        "throttled": THROTTLED,
    }

    def clean(self) -> dict[str, Any]:
        username = str(self.cleaned_data.get("username") or "").strip().lower()
        throttle = portal_throttle("admin-login")
        keys = (f"ip:{client_ip(self.request)}", f"username:{username}") if self.request else ()
        if username and keys and not throttle.hit(*keys):
            raise ValidationError(self.error_messages["throttled"], code="throttled")
        data = super().clean()
        throttle.reset(f"username:{username}")
        return data
