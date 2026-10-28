"""Steps an owner (or the admin) takes in the pages, shared by the portal's end-to-end tests.

Links are taken from the emails waiting in the outbox, as an owner would click them.
"""

import re
from typing import Any

from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from kospm.properties import models as properties_models
from kospm.shared.outbox.models import OutboxMessage
from tests.unit.properties.builders import VALID_AFM, VALID_IBAN

MARIA = "maria@example.com"
PASSWORD = "a long passphrase 4 Kos"
LINK = re.compile(r"https://portal\.test(/owner/\S+/)")


def emails_to(address: str) -> list[OutboxMessage]:
    return list(OutboxMessage.objects.filter(recipient=address).order_by("created_at"))


def link_in(message: OutboxMessage) -> str:
    match = LINK.search(message.payload["body"])
    assert match is not None, message.payload["body"]
    return match.group(1)


def open_link(client: Client, link: str) -> str:
    """Click an emailed link: the page keeps its token and moves to a URL without it."""
    response = client.get(link)
    assert response.status_code == 302
    page: str = response["Location"]
    assert "continue" in page
    return page


def confirm(client: Client, message: OutboxMessage) -> Any:
    page = open_link(client, link_in(message))
    assert client.get(page).status_code == 200
    return client.post(page)


def choose_password(client: Client, message: OutboxMessage, password: str = PASSWORD) -> Any:
    page = open_link(client, link_in(message))
    assert client.get(page).status_code == 200
    return client.post(page, {"password1": password, "password2": password})


def messages_of(response: Any) -> list[str]:
    return [str(message) for message in get_messages(response.wsgi_request)]


def sign_up(client: Client, email: str = MARIA, password: str = PASSWORD) -> Any:
    return client.post(
        reverse("identity:signup"),
        {"email": email, "password1": password, "password2": password},
    )


def log_in(client: Client, email: str = MARIA, password: str = PASSWORD) -> Any:
    return client.post(reverse("identity:login"), {"username": email, "password": password})


def logged_in_owner(email: str = MARIA) -> Client:
    """A browser of an owner who signed up, confirmed the address and logged in."""
    client = Client()
    sign_up(client, email)
    confirm(client, emails_to(email)[0])
    assert log_in(client, email)["Location"] == reverse("portal:dashboard")
    return client


def owner_form(**overrides: Any) -> dict[str, Any]:
    """The admin's owner form, as the admin page posts it."""
    data: dict[str, Any] = {
        "name": "Μαρία Παπαδοπούλου",
        "email": MARIA,
        "phone": "+30 6900000000",
        "afm": VALID_AFM,
        "iban": VALID_IBAN,
        "bank_holder_name": "PAPADOPOULOU MARIA",
        "properties-TOTAL_FORMS": "0",
        "properties-INITIAL_FORMS": "0",
        "properties-MIN_NUM_FORMS": "0",
        "properties-MAX_NUM_FORMS": "0",
    }
    data.update(overrides)
    return data


def register_owner_in_admin(admin_client: Client, **overrides: Any) -> properties_models.Owner:
    data = owner_form(**overrides)
    added = admin_client.post(reverse("admin:properties_owner_add"), data)
    assert added.status_code == 302
    return properties_models.Owner.objects.get(email=data["email"])


def add_property_in_admin(
    admin_client: Client, owner: properties_models.Owner, *, code: str, name: str
) -> properties_models.Property:
    """A property the admin adds for an owner, through the admin's whole add form."""
    data = {
        "owner": str(owner.pk),
        "code": code,
        "name": name,
        "default_check_in_time": "15:00",
        "default_check_out_time": "11:00",
        "linen_par_level": "3",
        "contract_signed_at_0": "",
        "contract_signed_at_1": "",
    }
    added = admin_client.post(reverse("admin:properties_property_add"), data)
    assert added.status_code == 302, added.content.decode()[:2000]
    return properties_models.Property.objects.get(code=code)


def invite(admin_client: Client, owner: properties_models.Owner) -> list[str]:
    response = admin_client.post(
        reverse("admin:properties_owner_changelist"),
        {"action": "invite_to_portal", "_selected_action": [str(owner.pk)]},
    )
    return messages_of(response)
