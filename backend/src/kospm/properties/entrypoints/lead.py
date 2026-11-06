"""The public site's form posts here (ADR 0021). It replaces the site's PHP handler, answer for
answer.

The page is static, so it has no CSRF token, and nothing here depends on a login: the endpoint only
queues a message to the IKE. Bots are turned away the way the form was built for: a hidden field
they fill in, and a timestamp that shows the form was sent within seconds of loading. Both hear
"ok" and send nothing, so they learn nothing. The limit per visitor stops the rest.
"""

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.http.response import HttpResponseBase
from django.utils import translation
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt

from kospm.bootstrap import get_bus, portal_throttle
from kospm.properties.domain.commands import SubmitOwnerLead
from kospm.properties.domain.errors import InvalidValue
from kospm.shared.adapters.portal import client_ip
from kospm.shared.clock import SystemClock

# A person needs longer than this to fill in the form.
_FASTEST_HUMAN_SECONDS = 3


@csrf_exempt
def owner_lead(request: HttpRequest) -> HttpResponseBase:
    wants_json = "application/json" in request.headers.get("Accept", "")
    with translation.override("el"):  # the site's only language
        ok, message, status = _handle(request)
    return _answer(ok, message, status, wants_json=wants_json)


def _handle(request: HttpRequest) -> tuple[bool, str, int]:
    if request.method != "POST":
        return False, _("Invalid request."), 405
    form = request.POST
    if form.get("website") or _sent_too_fast(form.get("ts", "")):
        return True, "ok", 200
    if not portal_throttle("lead").hit(f"ip:{client_ip(request)}"):
        return False, _("Too many requests. Please call us."), 429
    try:
        get_bus().handle(
            SubmitOwnerLead(
                name=form.get("name", ""),
                phone=form.get("phone", ""),
                area=form.get("area", ""),
                bedrooms=form.get("bedrooms", ""),
                online=form.get("online", ""),
            )
        )
    except InvalidValue:
        return False, _("Enter your name and a correct phone number."), 422
    return True, _("Thank you! We will call you soon."), 200


def _sent_too_fast(loaded_at: str) -> bool:
    try:
        seconds = int(loaded_at)
    except ValueError:
        return False  # no JavaScript, or nonsense: never a reason to lose a lead
    elapsed = SystemClock().now().timestamp() - seconds
    # A device whose clock runs ahead shows a negative time: a person, not a bot.
    return seconds > 0 and 0 <= elapsed < _FASTEST_HUMAN_SECONDS


def _answer(ok: bool, message: str, status: int, *, wants_json: bool) -> HttpResponse:
    if wants_json:
        response: HttpResponse = JsonResponse(
            {"ok": ok, "message": message},
            status=status,
            json_dumps_params={"ensure_ascii": False},
        )
    else:
        response = HttpResponse(status=303)
        response["Location"] = f"/?lead={'ok' if ok else 'error'}#ektimisi"
    response["Cache-Control"] = "no-store"
    return response
