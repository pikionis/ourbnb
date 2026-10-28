"""The owner portal's property pages (ADR 0017; design brief J5 to J8).

Only the owner's own properties are found; another owner's code is "not found" (404). Changes
are previewed on an unsaved copy of the aggregate, as the admin does, so a refusal shows next to
its field before an upload is stored; the command then names the acting owner, and its handler
refuses a property that is no longer being set up. Key-box codes and pasted listing text are
kept out of error reports.
"""

from collections.abc import Iterable
from dataclasses import replace
from pathlib import PurePosixPath
from uuid import UUID

from django import forms
from django.contrib import messages
from django.core.files.storage import Storage
from django.core.files.uploadedfile import UploadedFile
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.debug import sensitive_post_parameters

from kospm.bootstrap import (
    get_bus,
    listing_extractor,
    listing_text_policy,
    listing_throttle,
    property_defaults,
)
from kospm.properties.adapters.queries import (
    OwnerProperty,
    owner_file,
    owner_overview,
    owner_property,
    owner_property_code,
)
from kospm.properties.domain.commands import (
    CreateProperty,
    RecordSubleaseDeclaration,
    SignContract,
    UpdatePropertyProfile,
)
from kospm.properties.domain.errors import InvalidValue, ListingNotRead
from kospm.properties.domain.listing import ListingDraft, ListingTextPolicy
from kospm.properties.domain.property import Property, PropertyStatus
from kospm.properties.entrypoints.portal.forms import (
    ContractUploadForm,
    ListingTextForm,
    NewPropertyForm,
    ProfileForm,
    SubleaseForm,
    fill_from_listing,
    store_upload,
)
from kospm.properties.entrypoints.texts import describe, profile_list
from kospm.properties.models import PropertyStatusChoices
from kospm.properties.service_layer.handlers import PropertyEdit, apply_edit
from kospm.properties.service_layer.listing import draft_from_listing
from kospm.shared.adapters.portal import owner_page
from kospm.shared.clock import SystemClock
from kospm.shared.domain import Command, DomainError, new_id
from kospm.shared.unit_of_work import ConcurrencyError

# Where a value the domain refuses (InvalidValue.field) is shown on the property forms.
FORM_FIELDS = {
    "name": "name",
    "location": "coordinates",
    "map_url": "map_url",
    "exterior_photo": "exterior_photo",
    "lockbox_photo": "lockbox_photo",
    "amenities": "other_not_included",
    "contract_document": "signed_contract",
    "sublease_declaration_number": "number",
}
PHOTOS = ("exterior_photo", "lockbox_photo")


@owner_page
def property_new(request: HttpRequest, owner_id: UUID) -> HttpResponse:
    if owner_overview(owner_id) is None:
        return redirect("portal:details")
    form = NewPropertyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        property_id = new_id()
        command = CreateProperty(
            property_id=property_id,
            owner_id=owner_id,
            name=form.cleaned_data["name"],
            acting_owner_id=owner_id,
        )
        if _sent(command, form):
            messages.success(request, _("Your property is added. Now complete its checklist."))
            return redirect("portal:property", code=owner_property_code(owner_id, property_id))
    return render(request, "portal/property_new.html", {"form": form})


@owner_page
def property_page(request: HttpRequest, owner_id: UUID, code: str) -> HttpResponse:
    owned = _owned(owner_id, code)
    return render(
        request,
        "portal/property.html",
        {**_frame(owned), "rows": _checklist(owned)},
    )


@sensitive_post_parameters("guest_lockbox_code", "cleaner_lockbox_code")
@owner_page
def property_profile(request: HttpRequest, owner_id: UUID, code: str) -> HttpResponse:
    owned = _owned(owner_id, code)
    prop = owned.prop
    form = ProfileForm(
        request.POST or None,
        request.FILES or None,
        initial=ProfileForm.initial_from(prop, owned.version),
    )
    if request.method == "POST" and _editable(prop) and form.is_valid():
        uploads = {name: form.cleaned_data.get(name) for name in PHOTOS}
        previewed = _profile_command(owner_id, prop, form, _preview_names(prop, uploads))
        if _previewed(prop, previewed, form):
            stored = _store(uploads)
            names = {name: stored[name][1] if name in stored else "" for name in PHOTOS}
            command = _profile_command(owner_id, prop, form, _photo_names(prop, names))
            if _sent(command, form):
                messages.success(request, _("The profile is saved."))
                return redirect("portal:property", code=prop.code.value)
            _delete(stored.values())
    return render(request, "portal/profile.html", {**_frame(owned), "form": form})


@sensitive_post_parameters("text")
@owner_page
def property_listing(request: HttpRequest, owner_id: UUID, code: str) -> HttpResponse:
    """J6: the profile form comes back filled in from the listing's text, not saved.

    The owner checks it and presses Save, which sends the profile form as usual.
    """
    owned = _owned(owner_id, code)
    prop = owned.prop
    policy = listing_text_policy()
    form = ListingTextForm(request.POST or None, max_characters=policy.max_characters)
    if request.method == "POST" and _editable(prop) and form.is_valid():
        draft = _read_listing(owner_id, form, policy)
        if draft is not None:
            initial, to_check = fill_from_listing(
                ProfileForm.initial_from(prop, owned.version), draft
            )
            return render(
                request,
                "portal/profile.html",
                {
                    **_frame(owned),
                    "form": ProfileForm(initial=initial),
                    "from_listing": True,
                    "to_check": to_check,
                },
            )
    return render(request, "portal/listing.html", {**_frame(owned), "form": form})


@owner_page
def property_contract(request: HttpRequest, owner_id: UUID, code: str) -> HttpResponse:
    owned = _owned(owner_id, code)
    prop = owned.prop
    form = ContractUploadForm(
        request.POST or None, request.FILES or None, initial={"version": owned.version}
    )
    if request.method == "POST" and _editable(prop) and form.is_valid():
        upload: UploadedFile = form.cleaned_data["signed_contract"]
        command = SignContract(
            property_id=prop.id,
            document=f"(upload) {upload.name}",
            expected_version=form.cleaned_data.get("version"),
            acting_owner_id=owner_id,
        )
        if _previewed(prop, command, form):
            storage, name = store_upload("contract_document", upload)
            if _sent(replace(command, document=name), form):
                messages.success(request, _("Thank you! The signed contract is uploaded."))
                return redirect("portal:property", code=prop.code.value)
            storage.delete(name)
    return render(request, "portal/contract.html", {**_frame(owned), "form": form})


@owner_page
def property_sublease(request: HttpRequest, owner_id: UUID, code: str) -> HttpResponse:
    owned = _owned(owner_id, code)
    prop = owned.prop
    form = SubleaseForm(
        request.POST or None,
        initial={"number": prop.sublease_declaration_number, "version": owned.version},
    )
    if request.method == "POST" and _editable(prop) and form.is_valid():
        command = RecordSubleaseDeclaration(
            property_id=prop.id,
            number=form.cleaned_data["number"],
            expected_version=form.cleaned_data.get("version"),
            acting_owner_id=owner_id,
        )
        if _sent(command, form):
            messages.success(request, _("The number of the sublease declaration is saved."))
            return redirect("portal:property", code=prop.code.value)
    return render(request, "portal/sublease.html", {**_frame(owned), "form": form})


@owner_page
def property_file(request: HttpRequest, owner_id: UUID, code: str, kind: str) -> FileResponse:
    """A file of the owner's property: shown to its owner only (DOMAIN §5, owner portal)."""
    file = owner_file(owner_id, code, kind)
    if file is None:
        raise Http404
    return FileResponse(
        file.open("rb"),
        as_attachment=kind.startswith("contract"),
        filename=PurePosixPath(file.name or "file").name,
    )


# --- helpers ------------------------------------------------------------------------------------


def _owned(owner_id: UUID, code: str) -> OwnerProperty:
    owned = owner_property(owner_id, code)
    if owned is None:
        raise Http404
    return owned


def _editable(prop: Property) -> bool:
    return prop.status is PropertyStatus.ONBOARDING


def _frame(owned: OwnerProperty) -> dict[str, object]:
    """What every property page shows: the property and whether the owner may change it."""
    prop = owned.prop
    return {
        "owned": owned,
        "prop": prop,
        "status": PropertyStatusChoices(prop.status.value).label,
        "editable": _editable(prop),
    }


def _checklist(owned: OwnerProperty) -> list[dict[str, object]]:
    """The activation checklist in onboarding order (DOMAIN §5), in the owner's words."""
    prop, code = owned.prop, owned.prop.code.value
    gaps = prop.profile_gaps()
    contract_text = (
        _("Signed")
        if prop.contract is not None
        else _("Download it, sign it and upload it")
        if prop.contract_draft is not None
        else _("We are preparing it")
    )
    return [
        {
            "title": _("Profile and check-in guide"),
            "done": not gaps,
            "text": _("Complete")
            if not gaps
            else _("Missing: %(items)s") % {"items": profile_list(gaps)},
            "url": reverse("portal:property_profile", args=[code]),
        },
        {
            "title": _("Contract"),
            "done": prop.contract is not None,
            "text": contract_text,
            "url": reverse("portal:property_contract", args=[code]),
        },
        {
            "title": _("Sublease declaration"),
            "done": bool(prop.sublease_declaration_number),
            "text": prop.sublease_declaration_number or _("Enter its number"),
            "url": reverse("portal:property_sublease", args=[code]),
        },
        {
            "title": _("AMA"),
            "done": bool(prop.ama_number),
            "text": prop.ama_number or _("We register it after your sublease declaration"),
            "url": None,
        },
        {
            "title": _("Bank account"),
            "done": owned.bank_account_verified,
            "text": _("Verified") if owned.bank_account_verified else _("Not verified yet"),
            "url": reverse("portal:bank"),
        },
    ]


def _profile_command(
    owner_id: UUID, prop: Property, form: ProfileForm, photos: dict[str, str]
) -> UpdatePropertyProfile:
    """The owner's profile, with the IKE's settings unchanged (DOMAIN §5, owner portal)."""
    data = form.cleaned_data
    lat, lng = data["coordinates"] or (None, None)
    included, not_included = form.amenities()
    return UpdatePropertyProfile(
        property_id=prop.id,
        name=prop.name,
        address=data["address"],
        lat=lat,
        lng=lng,
        directions_el=data.get("directions_el", ""),
        directions_en=data.get("directions_en", ""),
        map_url=data.get("map_url", ""),
        exterior_photo=photos["exterior_photo"],
        lockbox_photo=photos["lockbox_photo"],
        guest_lockbox_code=data.get("guest_lockbox_code") or None,
        cleaner_lockbox_code=data.get("cleaner_lockbox_code") or None,
        amenities_included=included,
        amenities_not_included=not_included,
        ical_feeds=tuple((feed.channel.value, feed.url) for feed in prop.ical_feeds),
        default_check_in_time=prop.default_check_in_time,
        default_check_out_time=prop.default_check_out_time,
        linen_par_level=prop.linen_par_level,
        preferred_cleaner_id=prop.preferred_cleaner_id,
        expected_version=data.get("version"),
        acting_owner_id=owner_id,
    )


def _read_listing(
    owner_id: UUID, form: ListingTextForm, policy: ListingTextPolicy
) -> ListingDraft | None:
    """The draft read from the pasted text, or None with the reason on the form."""
    if not listing_throttle().hit(f"owner:{owner_id}"):
        form.add_error(
            None,
            _(
                "You have asked for this many times in the last hour. Fill in the profile "
                "yourself, or try again later."
            ),
        )
        return None
    try:
        return draft_from_listing(
            form.cleaned_data["text"], extractor=listing_extractor(), policy=policy
        )
    except InvalidValue as error:
        form.add_error("text", describe(error))
    except ListingNotRead as error:
        form.add_error(None, describe(error))
    return None


def _preview_names(prop: Property, uploads: dict[str, UploadedFile | None]) -> dict[str, str]:
    """Photo names for the preview: a new upload by its file name, else the stored photo."""
    names = {name: f"(upload) {upload.name}" for name, upload in uploads.items() if upload}
    return _photo_names(prop, names)


def _photo_names(prop: Property, new: dict[str, str]) -> dict[str, str]:
    guide = prop.check_in_guide
    stored = {"exterior_photo": guide.exterior_photo, "lockbox_photo": guide.lockbox_photo}
    return {name: new.get(name) or stored[name] for name in PHOTOS}


def _previewed(prop: Property, command: PropertyEdit, form: forms.Form) -> bool:
    """Apply the command to the unsaved copy: the domain's refusal becomes a form error."""
    try:
        apply_edit(prop, command, property_defaults=property_defaults(), now=SystemClock().now())
    except InvalidValue as error:
        form.add_error(_field(form, error.field), describe(error))
    except DomainError as error:
        form.add_error(None, describe(error))
    else:
        return True
    return False


def _sent(command: Command, form: forms.Form) -> bool:
    try:
        get_bus().handle(command)
    except InvalidValue as error:
        form.add_error(_field(form, error.field), describe(error))
    except (DomainError, ConcurrencyError) as error:
        form.add_error(None, describe(error))
    else:
        return True
    return False


def _field(form: forms.Form, refused: str) -> str | None:
    field = FORM_FIELDS.get(refused)
    return field if field in form.fields else None


def _store(uploads: dict[str, UploadedFile | None]) -> dict[str, tuple[Storage, str]]:
    return {name: store_upload(name, upload) for name, upload in uploads.items() if upload}


def _delete(stored: Iterable[tuple[Storage, str]]) -> None:
    """Remove the uploads of a save the domain refused: no orphan files."""
    for storage, name in stored:
        storage.delete(name)
