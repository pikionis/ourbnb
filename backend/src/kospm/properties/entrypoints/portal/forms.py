"""Forms of the owner portal's details and bank pages (ADR 0017; design brief J3, J4).

Values are validated by the domain's value objects; the save itself by the domain, through the
command. The email is not a field: it is the owner's login (DOMAIN §5, owner portal).
"""

from collections.abc import Callable

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django_stubs_ext import StrOrPromise

from kospm.properties.domain.errors import InvalidValue
from kospm.properties.domain.value_objects import AccountHolderName, Afm, Iban
from kospm.properties.entrypoints.texts import describe


def _checked(make: Callable[[], str]) -> str:
    """The normalised value from a value object, or a form error in the domain's words."""
    try:
        return make()
    except InvalidValue as error:
        raise ValidationError(describe(error)) from error


def _text(label: StrOrPromise, *, max_length: int, **attrs: str) -> forms.CharField:
    return forms.CharField(label=label, max_length=max_length, widget=forms.TextInput(attrs=attrs))


def _version() -> forms.IntegerField:
    return forms.IntegerField(required=False, min_value=0, widget=forms.HiddenInput)


class _BankAccountFields(forms.Form):
    iban = _text(_("IBAN"), max_length=42, autocomplete="off", spellcheck="false")
    holder_name = forms.CharField(
        label=_("Account holder"),
        max_length=70,
        help_text=_(
            "Write the name exactly as your bank holds it, often in Latin capitals "
            "(e.g. PAPADOPOULOU MARIA)."
        ),
    )

    def clean_iban(self) -> str:
        return _checked(lambda: Iban(self.cleaned_data["iban"]).value)

    def clean_holder_name(self) -> str:
        return _checked(lambda: AccountHolderName(self.cleaned_data["holder_name"]).value)


class RegistrationForm(_BankAccountFields):
    """Onboarding step 1: the owner's details and bank account."""

    name = _text(_("Full name"), max_length=200, autocomplete="name")
    phone = _text(_("Mobile phone"), max_length=32, autocomplete="tel", inputmode="tel")
    afm = forms.CharField(
        label=_("Tax number (AFM)"),
        max_length=11,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
        help_text=_("We need it for your contract and your payouts."),
    )
    field_order = ("name", "phone", "afm", "iban", "holder_name")

    def clean_afm(self) -> str:
        return _checked(lambda: Afm(self.cleaned_data["afm"]).value)


class DetailsForm(forms.Form):
    name = _text(_("Full name"), max_length=200, autocomplete="name")
    phone = _text(_("Mobile phone"), max_length=32, autocomplete="tel", inputmode="tel")
    version = _version()


class BankAccountForm(_BankAccountFields):
    version = _version()


class CodeForm(forms.Form):
    code = forms.CharField(
        label=_("Code"),
        min_length=6,
        max_length=6,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code"}),
        help_text=_("The 6-digit code in the reference of our €0.01 transfer."),
    )
