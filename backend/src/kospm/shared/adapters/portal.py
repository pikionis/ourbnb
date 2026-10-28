"""What every owner-portal page needs, whichever context renders it (ADR 0017).

- `portal_context`: a template context processor (the portal's name and home page).
- `client_ip`: the visitor's address, read behind the reverse proxy when the settings say so.
- `owner_page`: a view decorator that lets in only an owner's login and hands the view the id
  of that owner. It reads the id from the logged-in user row, so the pages of `properties`
  learn who is logged in without importing `identity` (contexts share ids only).
"""

import functools
from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.http.response import HttpResponseBase
from django.shortcuts import resolve_url
from django.views.decorators.cache import never_cache

type View = Callable[..., HttpResponseBase]


def owner_page(view: View) -> View:
    """The view gets `(request, owner_id, ...)`. Anonymous visitors go to the login page; a
    staff login is refused (403). Pages and files are never cached, so a shared phone's
    browser keeps no IBAN or key-box photo after logout."""

    @functools.wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        owner_id = current_owner_id(request)
        if owner_id is None:
            raise PermissionDenied("the owner portal is for owners' logins")
        return view(request, owner_id, *args, **kwargs)

    return login_required(never_cache(wrapper))


def current_owner_id(request: HttpRequest) -> UUID | None:
    """The owner the logged-in account belongs to, if it is an owner's login."""
    owner_id = getattr(request.user, "owner_id", None)
    return owner_id if request.user.is_authenticated and isinstance(owner_id, UUID) else None


def account_email(request: HttpRequest) -> str:
    """The logged-in account's email address (an owner registers with it)."""
    return str(getattr(request.user, "email", ""))


def portal_context(request: HttpRequest) -> dict[str, object]:
    return {
        "portal_name": settings.PORTAL_NAME,
        "portal_home": resolve_url(settings.LOGIN_REDIRECT_URL),
    }


def client_ip(request: HttpRequest) -> str:
    """The visitor's IP address (used to throttle repeated attempts).

    Behind Caddy (ADR 0010) every request comes from the proxy, so production reads the address
    the proxy appended last to the header named by PORTAL_CLIENT_IP_HEADER. Earlier entries of
    that header come from the visitor and are not trusted.
    """
    header = settings.PORTAL_CLIENT_IP_HEADER
    if header:
        forwarded = str(request.META.get(header, ""))
        last = forwarded.rsplit(",", 1)[-1].strip()
        if last:
            return last
    return str(request.META.get("REMOTE_ADDR", ""))
