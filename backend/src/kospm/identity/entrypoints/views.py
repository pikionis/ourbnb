"""The account pages of the owner portal (ADR 0017; design brief J1, J2, J9).

Views translate a request into a command for the bus and the outcome into a page; the rules are
the domain's. Every answer about an email address reads the same whether or not the address has
an account: what differs is only the email that address receives.

Emailed links: the first request stores the link's token in the session and redirects to the
same page without it (as Django's password reset does), so the token stays out of later URLs,
the Referer header and the history. Nothing changes on a GET: a mail scanner that opens a link
confirms nothing; the owner presses a button.
"""

import contextlib
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import translation
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters

from kospm.bootstrap import account_tokens, get_bus, portal_throttle
from kospm.identity.adapters.queries import linked_account
from kospm.identity.domain.account import AccountLink, Language, OwnerAccount
from kospm.identity.domain.commands import (
    AcceptInvitation,
    ConfirmEmail,
    RequestPasswordReset,
    ResendConfirmation,
    ResetPassword,
    SignUpOwner,
)
from kospm.identity.domain.errors import EmailAlreadyInUse, InvalidLink
from kospm.identity.entrypoints.forms import EmailForm, NewPasswordForm, OwnerLoginForm, SignUpForm
from kospm.identity.entrypoints.texts import THROTTLED, describe
from kospm.shared.adapters.portal import client_ip
from kospm.shared.domain import new_id
from kospm.shared.unit_of_work import ConcurrencyError

# The address just signed up, shown on the "check your email" page.
SIGNUP_EMAIL = "identity.signup_email"
# Stands in the URL for a link's token once the token is in the session.
LINK_PLACEHOLDER = "continue"


class OwnerLoginView(LoginView):
    form_class = OwnerLoginForm
    template_name = "identity/login.html"
    redirect_authenticated_user = True


class OwnerLogoutView(LogoutView):
    next_page = "identity:login"


@never_cache
@sensitive_post_parameters("password1", "password2")
def sign_up(request: HttpRequest) -> HttpResponse:
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        if not portal_throttle("signup").hit(f"ip:{client_ip(request)}", f"email:{email}"):
            form.add_error(None, str(THROTTLED))
        else:
            command = SignUpOwner(
                account_id=new_id(),
                owner_id=new_id(),
                email=email,
                password=form.password,
                language=_language(),
            )
            # A staff login using the address: answer as for any other address.
            with contextlib.suppress(EmailAlreadyInUse):
                get_bus().handle(command)
            request.session[SIGNUP_EMAIL] = email
            return redirect("identity:signup_sent")
    return render(request, "identity/signup.html", {"form": form})


def sign_up_sent(request: HttpRequest) -> HttpResponse:
    """ "Check your email", with a form that mails the link again."""
    email = request.session.get(SIGNUP_EMAIL, "")
    form = EmailForm(request.POST or None, initial={"email": email})
    if request.method == "POST" and form.is_valid():
        address = form.cleaned_data["email"]
        if not portal_throttle("resend").hit(f"ip:{client_ip(request)}", f"email:{address}"):
            form.add_error(None, str(THROTTLED))
        else:
            get_bus().handle(ResendConfirmation(email=address))
            messages.success(request, _("If this address has an account, we sent it a new link."))
            return redirect("identity:signup_sent")
    return render(request, "identity/signup_sent.html", {"form": form, "email": email})


@never_cache
def confirm_email(request: HttpRequest, account_id: UUID, token: str) -> HttpResponse:
    """The confirmation link: a page with a button; pressing it confirms the address."""
    link = AccountLink.CONFIRMATION
    if token != LINK_PLACEHOLDER:
        return _keep_token(request, "identity:confirm", link, account_id, token)
    token = request.session.get(_session_key(link, account_id), "")
    account = linked_account(account_id, link, token, account_tokens())
    if account is None:
        return _invalid_link(request)
    if request.method == "POST":
        try:
            get_bus().handle(ConfirmEmail(account_id=account_id, token=token))
        except (InvalidLink, ConcurrencyError):  # used meanwhile, e.g. pressed twice
            return _invalid_link(request)
        request.session.pop(_session_key(link, account_id), None)
        messages.success(request, _("Your email address is confirmed. You can log in."))
        return redirect("identity:login")
    return render(request, "identity/confirm.html", {"email": account.email.value})


@never_cache
@sensitive_post_parameters("password1", "password2")
def accept_invitation(request: HttpRequest, account_id: UUID, token: str) -> HttpResponse:
    return _set_password(
        request,
        account_id,
        token,
        link=AccountLink.INVITATION,
        view="identity:invitation",
        title=_("Choose your password"),
        done=_("Your password is set. You can log in."),
    )


@never_cache
@sensitive_post_parameters("password1", "password2")
def reset_password(request: HttpRequest, account_id: UUID, token: str) -> HttpResponse:
    return _set_password(
        request,
        account_id,
        token,
        link=AccountLink.PASSWORD_RESET,
        view="identity:password_reset",
        title=_("Choose a new password"),
        done=_("Your new password is set. You can log in."),
    )


def password_forgot(request: HttpRequest) -> HttpResponse:
    form = EmailForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        address = form.cleaned_data["email"]
        if not portal_throttle("reset").hit(f"ip:{client_ip(request)}", f"email:{address}"):
            form.add_error(None, str(THROTTLED))
        else:
            get_bus().handle(RequestPasswordReset(email=address))
            return redirect("identity:password_forgot_sent")
    return render(request, "identity/password_forgot.html", {"form": form})


def password_forgot_sent(request: HttpRequest) -> HttpResponse:
    return render(request, "identity/password_forgot_sent.html")


def privacy(request: HttpRequest) -> HttpResponse:
    return render(request, "identity/privacy.html")


# --- helpers ------------------------------------------------------------------------------------


def _set_password(
    request: HttpRequest,
    account_id: UUID,
    token: str,
    *,
    link: AccountLink,
    view: str,
    title: str,
    done: str,
) -> HttpResponse:
    """The page behind an invitation or a password-reset link: a new password, typed twice."""
    if token != LINK_PLACEHOLDER:
        return _keep_token(request, view, link, account_id, token)
    token = request.session.get(_session_key(link, account_id), "")
    account = linked_account(account_id, link, token, account_tokens())
    if account is None:
        return _invalid_link(request)
    form = NewPasswordForm(request.POST or None, email=account.email.value)
    if request.method == "POST" and form.is_valid():
        command_type = AcceptInvitation if link is AccountLink.INVITATION else ResetPassword
        try:
            get_bus().handle(
                command_type(
                    account_id=account_id,
                    token=token,
                    password=form.password,
                    language=_language(),
                )
            )
        except (InvalidLink, ConcurrencyError):  # used meanwhile, e.g. submitted twice
            return _invalid_link(request)
        request.session.pop(_session_key(link, account_id), None)
        messages.success(request, done)
        return redirect("identity:login")
    return render(request, "identity/set_password.html", _password_page(account, form, title))


def _password_page(account: OwnerAccount, form: NewPasswordForm, title: str) -> dict[str, object]:
    return {"form": form, "title": title, "email": account.email.value}


def _keep_token(
    request: HttpRequest, view: str, link: AccountLink, account_id: UUID, token: str
) -> HttpResponse:
    request.session[_session_key(link, account_id)] = token
    return redirect(view, account_id=account_id, token=LINK_PLACEHOLDER)


def _session_key(link: AccountLink, account_id: UUID) -> str:
    return f"identity.link.{link.value}.{account_id}"


def _invalid_link(request: HttpRequest) -> HttpResponse:
    return render(
        request, "identity/link_invalid.html", {"message": describe(InvalidLink())}, status=400
    )


def _language() -> str:
    """The language the visitor reads the portal in: their emails will use it too."""
    code = (translation.get_language() or "").split("-")[0]
    return code if code in {language.value for language in Language} else Language.GREEK.value
