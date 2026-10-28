"""Forms of the owner portal (ADR 0017; design brief J3 to J8).

Values are validated by the domain's value objects; the save itself by the domain, through the
command. The email is not a field: it is the owner's login (DOMAIN §5, owner portal).
"""

import re
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import Storage
from django.core.files.uploadedfile import UploadedFile
from django.db.models.fields.files import FileField
from django.utils.translation import gettext_lazy as _
from django_stubs_ext import StrOrPromise

from kospm.properties import models
from kospm.properties.domain.errors import InvalidValue
from kospm.properties.domain.property import Property
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


# --- properties (design brief J5, J7, J8) ---------------------------------------------------------

# Amenities offered as Yes / No (design brief §8). Stored by their English name, so the list
# reads the same in the admin and to the AI; shown translated.
STANDARD_AMENITIES: dict[str, StrOrPromise] = {
    "Wi-Fi": _("Wi-Fi"),
    "Air conditioning": _("Air conditioning"),
    "Heating": _("Heating"),
    "Kitchen": _("Kitchen"),
    "Washing machine": _("Washing machine"),
    "Dishwasher": _("Dishwasher"),
    "Free parking": _("Free parking"),
    "Pool": _("Pool"),
    "Sea view": _("Sea view"),
    "Balcony or terrace": _("Balcony or terrace"),
    "Baby cot": _("Baby cot"),
    "Hair dryer": _("Hair dryer"),
    "Iron": _("Iron"),
    "TV": _("TV"),
}
_COORDINATES = re.compile(r"\s*(-?[0-9]+(?:\.[0-9]+)?)\s*[,;]?\s+(-?[0-9]+(?:\.[0-9]+)?)\s*")
_MICRODEGREE = Decimal("0.000001")


def amenity_field(name: str) -> str:
    return "amenity_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class NewPropertyForm(forms.Form):
    name = _text(_("Name of the property"), max_length=200)


class _UploadsForm(forms.Form):
    """Uploaded files may not be larger than PORTAL_UPLOAD_MAX_MB (configuration)."""

    def _small_enough(self, name: str) -> UploadedFile | None:
        upload: UploadedFile | None = self.cleaned_data.get(name) or None
        limit_mb = int(settings.PORTAL_UPLOAD_MAX_MB)
        if upload is not None and (upload.size or 0) > limit_mb * 1024 * 1024:
            raise ValidationError(_("The file is larger than %(mb)s MB.") % {"mb": limit_mb})
        return upload


class ProfileForm(_UploadsForm):
    """The property's profile and check-in guide (onboarding step 2)."""

    address = _text(_("Address"), max_length=300, autocomplete="street-address")
    coordinates = forms.CharField(
        label=_("Coordinates"),
        required=False,
        max_length=60,
        widget=forms.TextInput(attrs={"inputmode": "decimal", "autocomplete": "off"}),
        help_text=_(
            "In Google Maps, press and hold on the house and copy the two numbers, e.g. "
            "36.89301, 27.28770."
        ),
    )
    map_url = forms.URLField(
        label=_("Map link for guests (optional)"), required=False, assume_scheme="https"
    )
    directions_el = forms.CharField(
        label=_("Directions in Greek"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("How guests find the house from the main road, and where the key box is."),
    )
    directions_en = forms.CharField(
        label=_("Directions in English"), required=False, widget=forms.Textarea(attrs={"rows": 4})
    )
    exterior_photo = forms.FileField(
        label=_("Photo of the outside"),
        required=False,
        widget=forms.FileInput(attrs={"accept": "image/*"}),
    )
    lockbox_photo = forms.FileField(
        label=_("Photo of the key box"),
        required=False,
        widget=forms.FileInput(attrs={"accept": "image/*"}),
    )
    guest_lockbox_code = forms.CharField(
        label=_("Key box code for guests"),
        required=False,
        max_length=32,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off"}),
        help_text=_("It is not shown again after saving. Leave it empty to keep the saved one."),
    )
    cleaner_lockbox_code = forms.CharField(
        label=_("Key box code for cleaners, if different (optional)"),
        required=False,
        max_length=32,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off"}),
    )
    other_included = forms.CharField(
        label=_("Other amenities the house has (one per line)"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    other_not_included = forms.CharField(
        label=_("Other amenities the house does not have (one per line)"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    version = _version()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for name, label in STANDARD_AMENITIES.items():
            self.fields[amenity_field(name)] = forms.ChoiceField(
                label=label,
                required=False,
                choices=[("yes", _("Yes")), ("no", _("No"))],
                widget=forms.RadioSelect,
            )

    @property
    def amenity_fields(self) -> list[forms.BoundField]:
        return [self[amenity_field(name)] for name in STANDARD_AMENITIES]

    @staticmethod
    def initial_from(prop: Property, version: int) -> dict[str, Any]:
        guide, amenities = prop.check_in_guide, prop.amenities
        location = prop.location
        initial: dict[str, Any] = {
            "address": prop.address,
            "coordinates": f"{location.lat}, {location.lng}" if location is not None else "",
            "map_url": guide.map_url,
            "directions_el": guide.directions_el,
            "directions_en": guide.directions_en,
            "other_included": "\n".join(
                item for item in amenities.included if item not in STANDARD_AMENITIES
            ),
            "other_not_included": "\n".join(
                item for item in amenities.not_included if item not in STANDARD_AMENITIES
            ),
            "version": version,
        }
        for name in STANDARD_AMENITIES:
            if name in amenities.included:
                initial[amenity_field(name)] = "yes"
            elif name in amenities.not_included:
                initial[amenity_field(name)] = "no"
        return initial

    def clean_coordinates(self) -> tuple[Decimal, Decimal] | None:
        text = str(self.cleaned_data.get("coordinates") or "").strip()
        if not text:
            return None
        match = _COORDINATES.fullmatch(text)
        if match is None:
            raise ValidationError(
                _("Write the two numbers as Google Maps shows them, e.g. 36.89301, 27.28770.")
            )
        # More than 6 decimals (about 10 cm) are rounded: the domain keeps 6 (validation details).
        lat, lng = (
            Decimal(number).quantize(_MICRODEGREE, rounding=ROUND_HALF_UP)
            for number in match.groups()
        )
        return lat, lng

    def clean_exterior_photo(self) -> UploadedFile | None:
        return self._small_enough("exterior_photo")

    def clean_lockbox_photo(self) -> UploadedFile | None:
        return self._small_enough("lockbox_photo")

    def amenities(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """What the house has and has not, as the domain stores them."""
        data = self.cleaned_data
        included = [n for n in STANDARD_AMENITIES if data.get(amenity_field(n)) == "yes"]
        not_included = [n for n in STANDARD_AMENITIES if data.get(amenity_field(n)) == "no"]
        included += _lines(data.get("other_included", ""))
        not_included += _lines(data.get("other_not_included", ""))
        return tuple(included), tuple(not_included)


class ContractUploadForm(_UploadsForm):
    signed_contract = forms.FileField(
        label=_("The signed contract (PDF)"),
        widget=forms.FileInput(attrs={"accept": "application/pdf"}),
    )
    version = _version()

    def clean_signed_contract(self) -> UploadedFile | None:
        return self._small_enough("signed_contract")


class SubleaseForm(forms.Form):
    number = _text(_("Number of the sublease declaration"), max_length=64, autocomplete="off")
    version = _version()


def store_upload(field_name: str, upload: UploadedFile) -> tuple[Storage, str]:
    """Store an upload where the property's file field keeps it; returns where it went."""
    field = models.Property._meta.get_field(field_name)
    assert isinstance(field, FileField)
    name = field.storage.save(
        field.generate_filename(None, upload.name or "upload"), upload, max_length=field.max_length
    )
    return field.storage, name


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]
