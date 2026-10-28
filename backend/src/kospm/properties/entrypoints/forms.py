"""Admin forms of the properties context.

They validate with the domain, never with rules of their own:
- single values through the value objects (`clean_<field>`);
- the whole save by applying its commands to an unsaved copy of the aggregate (`clean`), so a
  refusal such as "an active property must keep a complete profile" or "a contract needs its
  signed PDF" is shown as a form error, next to the field concerned, before anything is saved.
They also build the commands that the admin sends on save.

A hidden `version` field carries the version the form was rendered with. The first command of a
save checks it (ADR 0016): if someone saved the same owner or property in the meantime, the save
is refused instead of silently overwriting their change. The first command's commit confirms the
version with an UPDATE even when it changes nothing, and that UPDATE holds the row until the
admin's transaction ends; so the commands after it, in the same transaction, need no check.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.storage import Storage
from django.core.files.uploadedfile import UploadedFile
from django.db.models.fields.files import FieldFile, FileField
from django.utils.translation import gettext_lazy as _

from kospm.bootstrap import property_defaults
from kospm.properties import models
from kospm.properties.adapters.repository import property_to_domain
from kospm.properties.domain.commands import (
    AssignAma,
    CreateProperty,
    OfferContract,
    RecordSubleaseDeclaration,
    SignContract,
    UpdatePropertyProfile,
)
from kospm.properties.domain.errors import InvalidValue
from kospm.properties.domain.property import Property
from kospm.properties.domain.value_objects import (
    AccountHolderName,
    Afm,
    Email,
    Iban,
    IcalChannel,
    IcalFeed,
    PropertyCode,
)
from kospm.properties.entrypoints.texts import describe
from kospm.properties.service_layer.handlers import PropertyEdit, apply_edit
from kospm.shared.clock import SystemClock
from kospm.shared.domain import Command, DomainError, new_id

CONTRACT_FIELDS = (
    "contract_document",
    "contract_signed_at",
    "contract_commission_rate",
    "contract_owner_cleaning_charge",
)
DRAFT_FIELDS = (
    "contract_draft_document",
    "contract_draft_commission_rate",
    "contract_draft_owner_cleaning_charge",
)
LEGAL_NUMBER_FIELDS = ("sublease_declaration_number", "ama_number")

# Where a value the domain refuses (InvalidValue.field) is shown on the property form.
PROPERTY_FORM_FIELDS = {
    "name": "name",
    "location": "lat",
    "map_url": "map_url",
    "exterior_photo": "exterior_photo",
    "lockbox_photo": "lockbox_photo",
    "amenities": "amenities_not_included_text",
    "linen_par_level": "linen_par_level",
    "contract_document": "contract_document",
    "contract_draft": "contract_draft_document",
    "signed_at": "contract_signed_at",
    "commission_rate": "contract_commission_rate",
    "owner_cleaning_charge": "contract_owner_cleaning_charge",
    "sublease_declaration_number": "sublease_declaration_number",
    "ama_number": "ama_number",
}


def _checked(make: Callable[[], str]) -> str:
    """The normalised value from a value object, or a form error in the domain's words."""
    try:
        return make()
    except InvalidValue as error:
        raise ValidationError(describe(error)) from error


def _version_field() -> forms.IntegerField:
    return forms.IntegerField(required=False, min_value=0, widget=forms.HiddenInput)


class OwnerForm(forms.ModelForm[models.Owner]):
    payee_check = forms.ChoiceField(
        label=_("test transfer sent: the bank's payee check"),
        required=False,
        choices=[("", "—"), *models.PayeeCheckChoices.choices],
        help_text=_("What e-banking answered when you sent the €0.01 (ADR 0018)."),
    )
    payee_check_name = forms.CharField(
        label=_("name returned by the bank"),
        required=False,
        max_length=70,
        help_text=_("Only for “the name almost matches”: the bank's spelling of the name."),
    )
    verification_code = forms.CharField(
        label=_("code of the test transfer"),
        required=False,
        max_length=6,
        help_text=_("The 6 digits the owner read on their bank statement."),
    )
    version = _version_field()

    class Meta:
        model = models.Owner
        fields = ("name", "email", "phone", "afm", "iban", "bank_holder_name")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.initial.setdefault("version", self.instance.version)

    def clean_email(self) -> str:
        return _checked(lambda: Email(self.cleaned_data["email"]).value)

    def clean_afm(self) -> str:
        return _checked(lambda: Afm(self.cleaned_data["afm"]).value)

    def clean_iban(self) -> str:
        return _checked(lambda: Iban(self.cleaned_data["iban"]).value)

    def clean_bank_holder_name(self) -> str:
        return _checked(lambda: AccountHolderName(self.cleaned_data["bank_holder_name"]).value)


class PropertyForm(forms.ModelForm[models.Property]):
    guest_lockbox_code_new = forms.CharField(
        label=_("new lockbox code for guests"),
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text=_("Leave empty to keep the stored code."),
    )
    cleaner_lockbox_code_new = forms.CharField(
        label=_("new lockbox code for cleaners"),
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text=_("Leave empty to keep it. Without one, cleaners use the guests' code."),
    )
    cleaner_uses_guest_code = forms.BooleanField(
        label=_("cleaners use the guests' code again"),
        required=False,
        help_text=_("Removes the cleaners' own code."),
    )
    amenities_included_text = forms.CharField(
        label=_("amenities included"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("One per line."),
    )
    amenities_not_included_text = forms.CharField(
        label=_("amenities not included"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("One per line."),
    )
    map_url = forms.URLField(label=_("map link"), required=False, assume_scheme="https")
    airbnb_ical_url = forms.URLField(
        label=_("Airbnb calendar (iCal link)"), required=False, assume_scheme="https"
    )
    booking_ical_url = forms.URLField(
        label=_("Booking.com calendar (iCal link)"), required=False, assume_scheme="https"
    )
    version = _version_field()

    class Meta:
        model = models.Property
        fields = (
            "owner",
            "code",
            "name",
            "address",
            "lat",
            "lng",
            "default_check_in_time",
            "default_check_out_time",
            "linen_par_level",
            "directions_el",
            "directions_en",
            "map_url",
            "exterior_photo",
            "lockbox_photo",
            *DRAFT_FIELDS,
            *CONTRACT_FIELDS,
            *LEGAL_NUMBER_FIELDS,
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        row = self.instance
        self.stored_files: list[tuple[Storage, str]] = []
        self.initial.setdefault("version", row.version)
        self.initial.setdefault("amenities_included_text", "\n".join(row.amenities_included))
        self.initial.setdefault(
            "amenities_not_included_text", "\n".join(row.amenities_not_included)
        )
        feeds = {feed["channel"]: feed["url"] for feed in row.ical_feeds}
        self.initial.setdefault("airbnb_ical_url", feeds.get(IcalChannel.AIRBNB.value, ""))
        self.initial.setdefault("booking_ical_url", feeds.get(IcalChannel.BOOKING.value, ""))

    @property
    def adding(self) -> bool:
        return self.instance._state.adding

    def clean_code(self) -> str:
        return _checked(lambda: PropertyCode(self.cleaned_data["code"]).value)

    def clean_airbnb_ical_url(self) -> str:
        return self._ical_url(IcalChannel.AIRBNB, "airbnb_ical_url")

    def clean_booking_ical_url(self) -> str:
        return self._ical_url(IcalChannel.BOOKING, "booking_ical_url")

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        if data.get("cleaner_uses_guest_code") and data.get("cleaner_lockbox_code_new"):
            self.add_error(
                "cleaner_lockbox_code_new",
                _("Enter a new code or tick “cleaners use the guests' code again”, not both."),
            )
        if self.errors:
            return data  # judge the whole only when every value is valid
        preview = self._preview()
        try:
            for edit in self._edits(preview.id, preview=True, version=None):
                apply_edit(preview, edit, property_defaults=property_defaults(), now=_now())
        except InvalidValue as error:
            field = PROPERTY_FORM_FIELDS.get(error.field)
            self.add_error(field if field in self.fields else None, describe(error))
        except DomainError as error:
            raise ValidationError(describe(error)) from error
        return data

    # --- commands ---------------------------------------------------------------------------

    def commands(self, property_id: UUID) -> list[Command]:
        """What saving this form means, in the order the bus must handle it.

        New uploads are stored now (their names go into the commands): if the save then fails,
        the admin calls `discard_stored_files`.
        """
        data = self.cleaned_data
        if not self.adding:
            return [*self._edits(property_id, preview=False, version=data.get("version"))]
        create = CreateProperty(
            property_id=property_id, owner_id=data["owner"].pk, code=data["code"], name=data["name"]
        )
        return [create, *self._edits(property_id, preview=False, version=None)]

    def discard_stored_files(self) -> None:
        for storage, name in self.stored_files:
            storage.delete(name)
        self.stored_files.clear()

    def _edits(
        self, property_id: UUID, *, preview: bool, version: int | None
    ) -> list[PropertyEdit]:
        data = self.cleaned_data
        edits: list[PropertyEdit] = [self._profile_command(property_id, preview, version)]
        if any(name in self.changed_data for name in DRAFT_FIELDS):
            edits.append(
                OfferContract(
                    property_id=property_id,
                    document=self._file_name("contract_draft_document", preview=preview),
                    commission_rate=data.get("contract_draft_commission_rate"),
                    owner_cleaning_charge=data.get("contract_draft_owner_cleaning_charge"),
                )
            )
        if any(name in self.changed_data for name in CONTRACT_FIELDS):
            edits.append(
                SignContract(
                    property_id=property_id,
                    document=self._file_name("contract_document", preview=preview),
                    signed_at=data.get("contract_signed_at"),
                    commission_rate=data.get("contract_commission_rate"),
                    owner_cleaning_charge=data.get("contract_owner_cleaning_charge"),
                )
            )
        # Sent whenever the field changed, also to empty: the domain refuses removing a number.
        if "sublease_declaration_number" in self.changed_data:
            edits.append(
                RecordSubleaseDeclaration(
                    property_id=property_id, number=data["sublease_declaration_number"]
                )
            )
        if "ama_number" in self.changed_data:
            edits.append(AssignAma(property_id=property_id, ama_number=data["ama_number"]))
        return edits

    def _profile_command(
        self, property_id: UUID, preview: bool, version: int | None
    ) -> UpdatePropertyProfile:
        data = self.cleaned_data
        feeds = tuple(
            (channel.value, data[field])
            for channel, field in (
                (IcalChannel.AIRBNB, "airbnb_ical_url"),
                (IcalChannel.BOOKING, "booking_ical_url"),
            )
            if data.get(field)
        )
        cleaner_code = (
            ""  # no own code: cleaners use the guests' code
            if data.get("cleaner_uses_guest_code")
            else data.get("cleaner_lockbox_code_new") or None
        )
        return UpdatePropertyProfile(
            property_id=property_id,
            name=data["name"],
            address=data.get("address", ""),
            lat=data.get("lat"),
            lng=data.get("lng"),
            directions_el=data.get("directions_el", ""),
            directions_en=data.get("directions_en", ""),
            map_url=data.get("map_url", ""),
            exterior_photo=self._file_name("exterior_photo", preview=preview),
            lockbox_photo=self._file_name("lockbox_photo", preview=preview),
            guest_lockbox_code=data.get("guest_lockbox_code_new") or None,
            cleaner_lockbox_code=cleaner_code,
            amenities_included=_lines(data.get("amenities_included_text", "")),
            amenities_not_included=_lines(data.get("amenities_not_included_text", "")),
            ical_feeds=feeds,
            default_check_in_time=data["default_check_in_time"],
            default_check_out_time=data["default_check_out_time"],
            linen_par_level=data["linen_par_level"],
            preferred_cleaner_id=self.instance.preferred_cleaner_id,
            expected_version=version,
        )

    # --- helpers ----------------------------------------------------------------------------

    def _preview(self) -> Property:
        """An unsaved copy of the aggregate to apply the change to."""
        if not self.adding:
            return property_to_domain(self.instance)
        return Property.create(
            property_id=new_id(),
            owner_id=self.cleaned_data["owner"].pk,
            code=PropertyCode(self.cleaned_data["code"]),
            name=self.cleaned_data["name"],
            defaults=property_defaults(),
        )

    def _ical_url(self, channel: IcalChannel, name: str) -> str:
        url: str = self.cleaned_data[name]
        return _checked(lambda: IcalFeed(channel=channel, url=url).url) if url else ""

    def _file_name(self, name: str, *, preview: bool) -> str:
        """The storage name of a file field; a new upload is stored unless previewing."""
        value = self.cleaned_data.get(name)
        if isinstance(value, UploadedFile):
            if preview:
                return f"(upload) {value.name}"
            # As the model field would store it: its upload_to, and a name that fits its column.
            field = models.Property._meta.get_field(name)
            assert isinstance(field, FileField)
            stored = field.storage.save(
                field.generate_filename(self.instance, value.name or ""),
                value,
                max_length=field.max_length,
            )
            self.stored_files.append((field.storage, stored))
            return stored
        if isinstance(value, FieldFile) and value.name:
            return value.name
        return ""


def _lines(text: str) -> tuple[str, ...]:
    return tuple(line for line in text.splitlines() if line.strip())


def _now() -> datetime:
    """Now, for a preview only: a contract without a signing time is signed "now"."""
    return SystemClock().now()
