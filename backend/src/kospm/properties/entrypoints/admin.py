"""Django admin of the properties context (ADR 0006).

Forms and actions send commands through the message bus; the admin never writes the tables, so
every rule is the domain's. Nothing is ever deleted: a property leaves by being offboarded.

A form save may send several commands (create, profile, contract, …). Django runs the save in
one transaction, and each command's Unit of Work nests in it as a savepoint: when the domain
refuses one command (normally already caught by the form's preview; at save time only a race,
such as a stale `version`), CommandRefused rolls back the whole save, so no half-saved form
remains, and the page shows why. Files uploaded by that save are deleted again. Actions and the
bank-code confirmation send one command per item, each in its own unit (ADR 0006).
"""

from typing import TYPE_CHECKING, Any

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from kospm.bootstrap import get_bus, invite_owner_to_portal, property_defaults
from kospm.properties import models
from kospm.properties.adapters.queries import missing_for_activation, profile_gaps
from kospm.properties.domain.commands import (
    ActivateProperty,
    ChangeOwnerIban,
    ConfirmBankAccount,
    DeactivateProperty,
    OffboardProperty,
    RegisterOwner,
    StartBankAccountVerification,
    UpdateOwnerDetails,
)
from kospm.properties.domain.value_objects import Iban
from kospm.properties.entrypoints.forms import OwnerForm, PropertyForm
from kospm.properties.entrypoints.texts import PROFILE_LABELS, REQUIREMENT_LABELS, describe
from kospm.shared.domain import Command, DomainError, new_id
from kospm.shared.unit_of_work import ConcurrencyError

if TYPE_CHECKING:
    from django.contrib.admin.options import _FieldsetSpec

STATUS_COLOURS = {
    models.PropertyStatusChoices.ONBOARDING: "#b45309",
    models.PropertyStatusChoices.ACTIVE: "#15803d",
    models.PropertyStatusChoices.INACTIVE: "#6b7280",
    models.PropertyStatusChoices.OFFBOARDED: "#374151",
}
BANK_COLOURS = {
    models.BankAccountStatusChoices.UNVERIFIED: "#b45309",
    models.BankAccountStatusChoices.PENDING: "#1d4ed8",
    models.BankAccountStatusChoices.VERIFIED: "#15803d",
}


class CommandRefused(Exception):
    """The domain refused a command while a form was saved; the change view reports it."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def send(*commands: Command) -> None:
    bus = get_bus()
    for command in commands:
        bus.handle(command)


def send_or_refuse(*commands: Command) -> None:
    """Send commands from a form save; a refusal becomes CommandRefused (rolls the page back)."""
    try:
        send(*commands)
    except (DomainError, ConcurrencyError) as error:
        raise CommandRefused(describe(error)) from error


def badge(text: str, colour: str) -> SafeString:
    return format_html(
        '<span style="background:{};color:#fff;border-radius:999px;padding:2px 10px;'
        'font-size:11px;white-space:nowrap">{}</span>',
        colour,
        text,
    )


class CommandModelAdmin[M: models.Owner | models.Property](admin.ModelAdmin[M]):
    """Shared behaviour: refusals reported on the form page, nothing deletable."""

    def changeform_view(
        self,
        request: HttpRequest,
        object_id: str | None = None,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except CommandRefused as refused:
            # The admin's own transaction has rolled back: nothing of this save remains.
            self.message_user(request, refused.message, messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())

    def has_delete_permission(self, request: HttpRequest, obj: M | None = None) -> bool:
        return False


# --- owners --------------------------------------------------------------------------------------


class PropertyInline(admin.TabularInline[models.Property, models.Owner]):
    model = models.Property
    fields = ("code", "name", "status_badge")
    readonly_fields = ("code", "name", "status_badge")
    extra = 0
    max_num = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request: HttpRequest, obj: models.Owner | None = None) -> bool:
        return False

    @admin.display(description=gettext_lazy("status"))
    def status_badge(self, obj: models.Property) -> SafeString:
        status = models.PropertyStatusChoices(obj.status)
        return badge(str(status.label), STATUS_COLOURS[status])


@admin.register(models.Owner)
class OwnerAdmin(CommandModelAdmin[models.Owner]):
    form = OwnerForm
    list_display = ("name", "email", "afm", "bank_account_badge", "property_count")
    search_fields = ("name", "email", "afm")
    inlines = (PropertyInline,)
    actions = ("start_bank_verification", "invite_to_portal")

    def get_fieldsets(
        self, request: HttpRequest, obj: models.Owner | None = None
    ) -> "_FieldsetSpec":
        if obj is None:
            return [(None, {"fields": ("name", "email", "phone", "afm", "iban")})]
        return [
            (None, {"fields": ("name", "email", "phone", "afm", "version")}),
            (
                _("Bank account"),
                {"fields": ("iban", "bank_account_badge", "bank_transfer", "verification_code")},
            ),
            (_("Public website"), {"fields": ("show_on_website", "website_consent_requested")}),
        ]

    def get_readonly_fields(
        self, request: HttpRequest, obj: models.Owner | None = None
    ) -> tuple[str, ...]:
        if obj is None:
            return ()
        return (
            "afm",
            "bank_account_badge",
            "bank_transfer",
            "show_on_website",
            "website_consent_requested",
        )

    def save_model(
        self, request: HttpRequest, obj: models.Owner, form: OwnerForm, change: bool
    ) -> None:
        data = form.cleaned_data
        if not change:
            obj.id = new_id()
            send_or_refuse(
                RegisterOwner(
                    owner_id=obj.id,
                    name=data["name"],
                    email=data["email"],
                    phone=data["phone"],
                    afm=data["afm"],
                    iban=data["iban"],
                )
            )
            return
        # Only the first command checks the form's version; see forms.py.
        version: int | None = data.get("version")
        commands: list[Command] = []
        if {"name", "email", "phone"} & set(form.changed_data):
            commands.append(
                UpdateOwnerDetails(
                    owner_id=obj.pk,
                    name=data["name"],
                    email=data["email"],
                    phone=data["phone"],
                    expected_version=version,
                )
            )
            version = None
        if "iban" in form.changed_data:
            commands.append(
                ChangeOwnerIban(owner_id=obj.pk, iban=data["iban"], expected_version=version)
            )
        send_or_refuse(*commands)
        if data.get("verification_code"):
            self._confirm_bank_account(request, obj, data["verification_code"])

    def _confirm_bank_account(self, request: HttpRequest, obj: models.Owner, code: str) -> None:
        try:
            send(ConfirmBankAccount(owner_id=obj.pk, code=code))
        except (DomainError, ConcurrencyError) as error:
            # Not a refusal of the save: a wrong attempt is recorded and must stay recorded.
            self.message_user(request, describe(error), messages.WARNING)
        else:
            self.message_user(request, _("The bank account is verified."), messages.SUCCESS)

    @admin.action(description=gettext_lazy("Start the bank account verification (test transfer)"))
    def start_bank_verification(
        self, request: HttpRequest, queryset: QuerySet[models.Owner]
    ) -> None:
        for owner in queryset:
            try:
                send(StartBankAccountVerification(owner_id=owner.pk))
            except (DomainError, ConcurrencyError) as error:
                self.message_user(request, f"{owner.name}: {describe(error)}", messages.ERROR)
                continue
            owner.refresh_from_db()
            self.message_user(request, self._transfer_instructions(owner), messages.SUCCESS)

    @admin.action(description=gettext_lazy("Invite to the owner portal (email)"))
    def invite_to_portal(self, request: HttpRequest, queryset: QuerySet[models.Owner]) -> None:
        """The identity context emails the invitation (DOMAIN §5, owner portal); an owner who
        already logs in gets a reminder to log in instead. Identity's refusal is reported here
        (a domain error of that context: properties does not know its kinds)."""
        for owner in queryset:
            try:
                invite_owner_to_portal(owner_id=owner.pk, email=owner.email)
            except (DomainError, ConcurrencyError):
                self.message_user(
                    request,
                    _(
                        "%(name)s: no invitation was sent. %(email)s cannot be this owner's "
                        "login: another login uses it, or it is too long."
                    )
                    % {"name": owner.name, "email": owner.email},
                    messages.ERROR,
                )
                continue
            self.message_user(
                request,
                _("%(name)s: invitation emailed to %(email)s.")
                % {"name": owner.name, "email": owner.email},
                messages.SUCCESS,
            )

    @admin.display(description=gettext_lazy("bank account"))
    def bank_account_badge(self, obj: models.Owner) -> SafeString:
        status = models.BankAccountStatusChoices(obj.bank_account_status)
        return badge(str(status.label), BANK_COLOURS[status])

    @admin.display(description=gettext_lazy("test transfer"))
    def bank_transfer(self, obj: models.Owner) -> str:
        if obj.bank_account_status != models.BankAccountStatusChoices.PENDING:
            return "—"
        return self._transfer_instructions(obj)

    @admin.display(description=gettext_lazy("properties"))
    def property_count(self, obj: models.Owner) -> int:
        return obj.properties.count()

    @staticmethod
    def _transfer_instructions(owner: models.Owner) -> str:
        return _(
            "%(name)s: send €0.01 to %(iban)s with reference %(code)s, then enter the code the "
            "owner reads on their statement."
        ) % {
            "name": owner.name,
            "iban": Iban(owner.iban).formatted(),
            "code": owner.bank_verification_code,
        }


# --- properties ----------------------------------------------------------------------------------


@admin.register(models.Property)
class PropertyAdmin(CommandModelAdmin[models.Property]):
    form = PropertyForm
    list_display = ("code", "name", "owner", "status_badge", "missing")
    list_filter = ("status",)
    list_select_related = ("owner",)
    search_fields = ("code", "name", "owner__name")
    actions = ("activate_properties", "deactivate_properties", "offboard_properties")

    def get_fieldsets(
        self, request: HttpRequest, obj: models.Property | None = None
    ) -> "_FieldsetSpec":
        heading: tuple[str, ...] = ("owner", "code", "name")
        if obj is not None:
            heading = (*heading, "status_badge", "checklist", "version")
        return [
            (None, {"fields": heading}),
            (_("Location"), {"fields": ("address", "lat", "lng")}),
            (
                _("Check-in guide"),
                {
                    "fields": (
                        "directions_el",
                        "directions_en",
                        "map_url",
                        "exterior_photo",
                        "lockbox_photo",
                        "guest_lockbox_code_state",
                        "guest_lockbox_code_new",
                        "cleaner_lockbox_code_state",
                        "cleaner_lockbox_code_new",
                        "cleaner_uses_guest_code",
                    )
                },
            ),
            (
                _("Amenities"),
                {"fields": ("amenities_included_text", "amenities_not_included_text")},
            ),
            (
                _("Operations"),
                {
                    "fields": (
                        "default_check_in_time",
                        "default_check_out_time",
                        "linen_par_level",
                        "airbnb_ical_url",
                        "booking_ical_url",
                    )
                },
            ),
            (
                _("Contract and legal"),
                {
                    "fields": (
                        "contract_document",
                        "contract_signed_at",
                        "contract_commission_rate",
                        "contract_owner_cleaning_charge",
                        "sublease_declaration_number",
                        "ama_number",
                    )
                },
            ),
        ]

    def get_readonly_fields(
        self, request: HttpRequest, obj: models.Property | None = None
    ) -> tuple[str, ...]:
        shown = ("guest_lockbox_code_state", "cleaner_lockbox_code_state")
        if obj is None:
            return shown
        return ("owner", "code", "status_badge", "checklist", *shown)

    def get_changeform_initial_data(self, request: HttpRequest) -> dict[str, Any]:
        defaults = property_defaults()
        return {
            **super().get_changeform_initial_data(request),
            "default_check_in_time": defaults.check_in_time,
            "default_check_out_time": defaults.check_out_time,
            "linen_par_level": defaults.linen_par_level,
        }

    def has_change_permission(
        self, request: HttpRequest, obj: models.Property | None = None
    ) -> bool:
        if obj is not None and obj.status == models.PropertyStatusChoices.OFFBOARDED:
            return False  # final: shown, never changed
        return super().has_change_permission(request, obj)

    def save_model(
        self, request: HttpRequest, obj: models.Property, form: PropertyForm, change: bool
    ) -> None:
        property_id = obj.pk if change else new_id()
        try:
            send_or_refuse(*form.commands(property_id))
        except Exception:
            form.discard_stored_files()  # the save rolls back: its files must go too
            raise
        obj.id = property_id

    # --- actions ----------------------------------------------------------------------------

    @admin.action(description=gettext_lazy("Activate (checks the checklist)"))
    def activate_properties(
        self, request: HttpRequest, queryset: QuerySet[models.Property]
    ) -> None:
        self._apply(request, queryset, ActivateProperty, _("%(code)s: active."))

    @admin.action(description=gettext_lazy("Deactivate"))
    def deactivate_properties(
        self, request: HttpRequest, queryset: QuerySet[models.Property]
    ) -> None:
        self._apply(request, queryset, DeactivateProperty, _("%(code)s: inactive."))

    @admin.action(description=gettext_lazy("Offboard (final)"))
    def offboard_properties(
        self, request: HttpRequest, queryset: QuerySet[models.Property]
    ) -> None:
        self._apply(request, queryset, OffboardProperty, _("%(code)s: offboarded."))

    def _apply(
        self,
        request: HttpRequest,
        queryset: QuerySet[models.Property],
        command: type[ActivateProperty] | type[DeactivateProperty] | type[OffboardProperty],
        done: str,
    ) -> None:
        for prop in queryset:
            try:
                send(command(property_id=prop.pk))
            except (DomainError, ConcurrencyError) as error:
                self.message_user(request, f"{prop.code}: {describe(error)}", messages.ERROR)
            else:
                self.message_user(request, done % {"code": prop.code}, messages.SUCCESS)

    # --- displays ---------------------------------------------------------------------------

    @admin.display(description=gettext_lazy("status"), ordering="status")
    def status_badge(self, obj: models.Property) -> SafeString:
        status = models.PropertyStatusChoices(obj.status)
        return badge(str(status.label), STATUS_COLOURS[status])

    @admin.display(description=gettext_lazy("missing for activation"))
    def missing(self, obj: models.Property) -> SafeString:
        if obj.status == models.PropertyStatusChoices.OFFBOARDED:
            return format_html("{}", "—")
        items = missing_for_activation(obj)
        if not items:
            return format_html("{}", "✓")
        return format_html_join(
            ", ",
            '<span data-missing="{}">{}</span>',
            ((item.value, REQUIREMENT_LABELS[item]) for item in items),
        )

    @admin.display(description=gettext_lazy("checklist"))
    def checklist(self, obj: models.Property) -> SafeString:
        items = missing_for_activation(obj)
        gaps = profile_gaps(obj)
        if not items:
            return format_html("{}", _("Everything is in place."))
        missing = format_html_join(
            "", '<li data-missing="{}">{}</li>', ((i.value, REQUIREMENT_LABELS[i]) for i in items)
        )
        profile = format_html_join(", ", "{}", ((PROFILE_LABELS[g],) for g in gaps))
        if gaps:
            return format_html(
                "<ul>{}</ul><p>{}: {}</p>", missing, _("Profile still needs"), profile
            )
        return format_html("<ul>{}</ul>", missing)

    @admin.display(description=gettext_lazy("lockbox code for guests"))
    def guest_lockbox_code_state(self, obj: models.Property) -> str:
        return _code_state(obj.guest_lockbox_code)

    @admin.display(description=gettext_lazy("lockbox code for cleaners"))
    def cleaner_lockbox_code_state(self, obj: models.Property) -> str:
        if obj.cleaner_lockbox_code:
            return _code_state(obj.cleaner_lockbox_code)
        return str(_("same as the guests' code"))


def _code_state(code: str | None) -> str:
    """Never the code itself (DOMAIN §2.3): only whether one is stored."""
    return "••••" if code else "—"
