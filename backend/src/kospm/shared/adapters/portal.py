"""What every owner-portal page needs, whichever context renders it (ADR 0017).

- `portal_context`: a template context processor (the portal's name and home page).
- `client_ip`: the visitor's address, read behind the reverse proxy when the settings say so.
"""

from django.conf import settings
from django.http import HttpRequest
from django.shortcuts import resolve_url


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
