"""The owner portal: dashboard, details and bank account (ADR 0017; design brief J3, J4).

Every page is the logged-in owner's own (`owner_page`), and every command it sends names that
owner as the acting owner, so the handlers refuse anything else (defence in depth). An account
whose owner has not registered yet sees only the registration (onboarding step 1).
"""

from uuid import UUID

from django import forms
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from kospm.bootstrap import get_bus
from kospm.properties.adapters.queries import OwnerOverview, owner_overview
from kospm.properties.domain.commands import (
    ChangeBankAccount,
    ConfirmBankAccount,
    RegisterOwner,
    StartBankAccountVerification,
    UpdateOwnerDetails,
)
from kospm.properties.domain.errors import InvalidValue, OwnerAlreadyRegistered
from kospm.properties.domain.owner import BankAccountStatus
from kospm.properties.entrypoints.portal.forms import (
    BankAccountForm,
    CodeForm,
    DetailsForm,
    RegistrationForm,
)
from kospm.properties.entrypoints.portal.texts import (
    ALREADY_REGISTERED_HINT,
    BANK_STATUS,
    PAYEE_CHECK_REFUSED,
    payee_check_refused,
)
from kospm.properties.entrypoints.texts import REQUIREMENT_LABELS, describe
from kospm.properties.models import PropertyStatusChoices
from kospm.shared.adapters.portal import account_email, owner_page
from kospm.shared.domain import Command, DomainError
from kospm.shared.unit_of_work import ConcurrencyError

# Where a refused value is shown (InvalidValue.field → form field).
FORM_FIELDS = {"name": "name", "phone": "phone", "afm": "afm", "iban": "iban"}


@owner_page
def dashboard(request: HttpRequest, owner_id: UUID) -> HttpResponse:
    overview = owner_overview(owner_id)
    return render(
        request,
        "portal/dashboard.html",
        {
            "overview": overview,
            "bank_status": BANK_STATUS[overview.bank.status] if overview else "",
            "properties": [
                {
                    "summary": summary,
                    "status": PropertyStatusChoices(summary.status.value).label,
                    "missing": [REQUIREMENT_LABELS[item] for item in summary.missing],
                }
                for summary in (overview.properties if overview else ())
            ],
        },
    )


@owner_page
def details(request: HttpRequest, owner_id: UUID) -> HttpResponse:
    overview = owner_overview(owner_id)
    if overview is None:
        return _register(request, owner_id)
    form = DetailsForm(
        request.POST or None,
        initial={"name": overview.name, "phone": overview.phone, "version": overview.version},
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        command = UpdateOwnerDetails(
            owner_id=owner_id,
            name=data["name"],
            email=overview.email,  # the login: changed through the IKE
            phone=data["phone"],
            expected_version=data.get("version"),
            acting_owner_id=owner_id,
        )
        if _sent(command, form):
            messages.success(request, _("Your details are saved."))
            return redirect("portal:dashboard")
    context = {"form": form, "overview": overview, "email": overview.email}
    return render(request, "portal/details.html", context)


@owner_page
def bank(request: HttpRequest, owner_id: UUID) -> HttpResponse:
    overview = owner_overview(owner_id)
    if overview is None:
        return redirect("portal:details")
    account_form = BankAccountForm(initial=_account_initial(overview))
    code_form = CodeForm()
    action = request.POST.get("action") if request.method == "POST" else None
    if action == "account":
        account_form = BankAccountForm(request.POST)
        if account_form.is_valid():
            data = account_form.cleaned_data
            command = ChangeBankAccount(
                owner_id=owner_id,
                iban=data["iban"],
                holder_name=data["holder_name"],
                expected_version=data.get("version"),
                acting_owner_id=owner_id,
            )
            if _sent(command, account_form):
                messages.success(request, _("Your bank account is saved."))
                return redirect("portal:bank")
    elif action == "verify":
        verify = StartBankAccountVerification(owner_id=owner_id, acting_owner_id=owner_id)
        try:
            get_bus().handle(verify)
        except (DomainError, ConcurrencyError) as error:
            messages.error(request, describe(error))
        else:
            messages.success(request, _("We will send you the €0.01 test transfer."))
        return redirect("portal:bank")
    elif action == "code":
        code_form = CodeForm(request.POST)
        if code_form.is_valid():
            confirm = ConfirmBankAccount(
                owner_id=owner_id, code=code_form.cleaned_data["code"], acting_owner_id=owner_id
            )
            if _sent(confirm, code_form, field="code"):
                messages.success(request, _("Your bank account is verified. Thank you!"))
                return redirect("portal:bank")
        overview = owner_overview(owner_id) or overview  # a wrong code was counted
    return render(
        request,
        "portal/bank.html",
        {
            "overview": overview,
            "bank": overview.bank,
            "bank_status": BANK_STATUS[overview.bank.status],
            "payee_check_refused": payee_check_refused(overview.bank.payee_check)
            and overview.bank.status is BankAccountStatus.UNVERIFIED,
            "payee_check_refused_text": PAYEE_CHECK_REFUSED,
            "editable": overview.bank.status is not BankAccountStatus.VERIFIED,
            "account_form": account_form,
            "code_form": code_form,
        },
    )


# --- helpers ------------------------------------------------------------------------------------


def _register(request: HttpRequest, owner_id: UUID) -> HttpResponse:
    """Onboarding step 1, with the id the account reserved and the account's email."""
    email = account_email(request)
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        command = RegisterOwner(
            owner_id=owner_id,
            name=data["name"],
            email=email,
            phone=data["phone"],
            afm=data["afm"],
            iban=data["iban"],
            holder_name=data["holder_name"],
        )
        try:
            get_bus().handle(command)
        except OwnerAlreadyRegistered as error:
            # Never linked by itself to an existing owner (DOMAIN §5): the IKE invites them.
            form.add_error(None, f"{describe(error)} {ALREADY_REGISTERED_HINT}")
        except InvalidValue as error:
            form.add_error(FORM_FIELDS.get(error.field), describe(error))
        except (DomainError, ConcurrencyError) as error:
            form.add_error(None, describe(error))
        else:
            messages.success(request, _("Thank you! Your details are saved."))
            return redirect("portal:dashboard")
    return render(request, "portal/details.html", {"form": form, "overview": None, "email": email})


def _sent(command: Command, form: forms.Form, *, field: str | None = None) -> bool:
    """Send a form's command; a refusal becomes a form error in the domain's words."""
    try:
        get_bus().handle(command)
    except InvalidValue as error:
        form.add_error(field or FORM_FIELDS.get(error.field), describe(error))
    except (DomainError, ConcurrencyError) as error:
        form.add_error(field, describe(error))
    else:
        return True
    return False


def _account_initial(overview: OwnerOverview) -> dict[str, object]:
    return {
        "iban": overview.bank.iban,
        "holder_name": overview.bank.holder_name,
        "version": overview.version,
    }
