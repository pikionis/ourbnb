"""Owner accounts end to end (DOMAIN §5 owner portal, ADR 0017): the pages, the bus, PostgreSQL
and the outbox. Links are taken from the emails waiting in the outbox, as an owner would click
them."""

import re
from typing import Any

import pytest
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from kospm.identity.models import User
from kospm.properties import models as properties_models
from kospm.shared.outbox.models import OutboxMessage
from tests.unit.properties.builders import VALID_AFM, VALID_IBAN

pytestmark = pytest.mark.django_db

MARIA = "maria@example.com"
PASSWORD = "a long passphrase 4 Kos"
LINK = re.compile(r"https://portal\.test(/owner/\S+/)")


@pytest.fixture(autouse=True)
def fresh_throttle() -> None:
    cache.clear()  # throttling counts live in the cache, which outlives a test


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


def signed_up_and_confirmed(client: Client) -> None:
    sign_up(client)
    confirm(client, emails_to(MARIA)[0])


def log_in(client: Client, email: str = MARIA, password: str = PASSWORD) -> Any:
    return client.post(reverse("identity:login"), {"username": email, "password": password})


def register_owner_in_admin(admin_client: Client, email: str = MARIA) -> properties_models.Owner:
    added = admin_client.post(
        reverse("admin:properties_owner_add"),
        {
            "name": "Μαρία Παπαδοπούλου",
            "email": email,
            "phone": "+30 6900000000",
            "afm": VALID_AFM,
            "iban": VALID_IBAN,
            "properties-TOTAL_FORMS": "0",
            "properties-INITIAL_FORMS": "0",
            "properties-MIN_NUM_FORMS": "0",
            "properties-MAX_NUM_FORMS": "0",
        },
    )
    assert added.status_code == 302
    return properties_models.Owner.objects.get(email=email)


def invite(admin_client: Client, owner: properties_models.Owner) -> list[str]:
    response = admin_client.post(
        reverse("admin:properties_owner_changelist"),
        {"action": "invite_to_portal", "_selected_action": [str(owner.pk)]},
    )
    return messages_of(response)


class TestSignUp:
    def test_sign_up_confirm_and_log_in(self, client: Client) -> None:
        response = sign_up(client, " Maria@Example.com ")
        assert response.status_code == 302
        assert response["Location"] == reverse("identity:signup_sent")

        (email,) = emails_to(MARIA)
        assert email.template == "identity.confirmation"
        assert confirm(client, email)["Location"] == reverse("identity:login")

        logged_in = log_in(client)
        assert logged_in.status_code == 302
        assert logged_in["Location"] == "/owner/"
        user = User.objects.get(username=MARIA)
        assert user.account_id is not None
        assert user.owner_id is not None

    def test_a_mail_scanner_opening_the_link_confirms_nothing(self, client: Client) -> None:
        sign_up(client)
        scanner = Client()
        page = open_link(scanner, link_in(emails_to(MARIA)[0]))
        assert scanner.get(page).status_code == 200
        assert User.objects.get(username=MARIA).account_status == "unconfirmed"

    def test_the_confirmation_link_works_once(self, client: Client) -> None:
        sign_up(client)
        email = emails_to(MARIA)[0]
        confirm(client, email)
        again = client.get(open_link(client, link_in(email)))
        assert again.status_code == 400
        assert "Ο σύνδεσμος έληξε ή χρησιμοποιήθηκε ήδη" in again.content.decode()

    def test_an_unconfirmed_owner_is_told_to_confirm_first(self, client: Client) -> None:
        sign_up(client)
        response = log_in(client)
        assert response.status_code == 200
        assert "Επιβεβαιώστε πρώτα" in response.content.decode()

    def test_the_answer_never_tells_whether_an_address_has_an_account(self, client: Client) -> None:
        User.objects.create_user(username="staff@example.com", password=PASSWORD)
        answers = [sign_up(client)["Location"] for _ in range(2)]
        answers.append(sign_up(client, "staff@example.com")["Location"])
        assert set(answers) == {reverse("identity:signup_sent")}
        assert User.objects.filter(account_id__isnull=False).count() == 1
        assert [email.template for email in emails_to(MARIA)] == [
            "identity.confirmation",
            "identity.confirmation",
        ]

    def test_a_weak_or_mistyped_password_is_refused_on_the_form(self, client: Client) -> None:
        weak = sign_up(client, password="12345678")
        assert weak.status_code == 200
        mistyped = client.post(
            reverse("identity:signup"),
            {"email": MARIA, "password1": PASSWORD, "password2": PASSWORD + "x"},
        )
        assert "Οι δύο κωδικοί διαφέρουν." in mistyped.content.decode()
        assert not User.objects.filter(account_id__isnull=False).exists()

    def test_emails_follow_the_language_the_owner_signed_up_in(self, client: Client) -> None:
        client.post(reverse("set_language"), {"language": "en"})
        sign_up(client)
        (email,) = emails_to(MARIA)
        assert email.payload["subject"] == "Confirm your email address"

    def test_signing_up_one_address_again_and_again_is_throttled(
        self, client: Client, settings: Any
    ) -> None:
        settings.PORTAL_THROTTLE_MAX_ATTEMPTS = 2
        for _ in range(2):
            Client(REMOTE_ADDR="10.0.0.1").post(
                reverse("identity:signup"),
                {"email": MARIA, "password1": PASSWORD, "password2": PASSWORD},
            )
        response = Client(REMOTE_ADDR="10.0.0.2").post(
            reverse("identity:signup"),
            {"email": MARIA, "password1": PASSWORD, "password2": PASSWORD},
        )
        assert "Πολλές προσπάθειες" in response.content.decode()
        assert len(emails_to(MARIA)) == 2


class TestLogin:
    def test_wrong_password_and_unknown_address_read_the_same(self, client: Client) -> None:
        signed_up_and_confirmed(client)
        wrong = log_in(client, password="not it")
        unknown = log_in(client, email="nobody@example.com")
        for response in (wrong, unknown):
            assert response.status_code == 200
            assert "Λάθος email ή κωδικός." in response.content.decode()

    def test_a_staff_login_does_not_open_the_owner_portal(self, client: Client) -> None:
        User.objects.create_user(username="staff@example.com", password=PASSWORD, is_staff=True)
        response = log_in(client, email="staff@example.com")
        assert "Λάθος email ή κωδικός." in response.content.decode()

    def test_repeated_attempts_are_throttled(self, client: Client, settings: Any) -> None:
        settings.PORTAL_THROTTLE_MAX_ATTEMPTS = 2
        for _ in range(2):
            log_in(client, password="guess")
        response = log_in(client)
        assert "Πολλές προσπάθειες" in response.content.decode()

    def test_logging_out_takes_a_post(self, client: Client) -> None:
        signed_up_and_confirmed(client)
        log_in(client)
        assert client.get(reverse("identity:logout")).status_code == 405
        assert client.post(reverse("identity:logout"))["Location"] == reverse("identity:login")


class TestPasswordReset:
    def test_a_reset_link_sets_a_new_password_once(self, client: Client) -> None:
        signed_up_and_confirmed(client)
        sent = client.post(reverse("identity:password_forgot"), {"email": MARIA})
        assert sent["Location"] == reverse("identity:password_forgot_sent")
        reset = emails_to(MARIA)[-1]
        assert reset.template == "identity.password_reset"

        new = "another long passphrase 7"
        done = choose_password(client, reset, new)
        assert done["Location"] == reverse("identity:login")
        assert log_in(client, password=new)["Location"] == "/owner/"
        assert client.get(open_link(client, link_in(reset))).status_code == 400

    def test_an_unknown_address_reads_the_same_and_gets_nothing(self, client: Client) -> None:
        response = client.post(reverse("identity:password_forgot"), {"email": "x@example.com"})
        assert response["Location"] == reverse("identity:password_forgot_sent")
        assert emails_to("x@example.com") == []


class TestInvitation:
    def test_the_admin_invites_a_registered_owner_who_chooses_a_password(
        self, client: Client, admin_client: Client
    ) -> None:
        owner = register_owner_in_admin(admin_client)
        assert "η πρόσκληση στάλθηκε στο maria@example.com" in " ".join(invite(admin_client, owner))

        (invitation,) = emails_to(MARIA)
        assert invitation.template == "identity.invitation"
        choose_password(client, invitation)
        assert User.objects.get(username=MARIA).owner_id == owner.pk
        assert log_in(client)["Location"] == "/owner/"
        # The link worked once.
        assert client.get(open_link(client, link_in(invitation))).status_code == 400

    def test_the_admin_learns_when_identity_refuses_the_invitation(
        self, admin_client: Client
    ) -> None:
        owner = register_owner_in_admin(admin_client)
        User.objects.create_user(username=MARIA, password=PASSWORD)  # a staff login took it
        shown = " ".join(invite(admin_client, owner))
        assert "δεν στάλθηκε πρόσκληση" in shown
        assert emails_to(MARIA) == []

    @pytest.mark.parametrize("confirmed", [False, True])
    def test_someone_elses_sign_up_with_the_owners_address_gets_no_access(
        self, client: Client, admin_client: Client, confirmed: bool
    ) -> None:
        stranger = Client()
        sign_up(stranger, password="the stranger's password 1")
        if confirmed:  # e.g. a mail scanner pressed nothing, but the owner clicked by mistake
            confirm(stranger, emails_to(MARIA)[0])
        owner = register_owner_in_admin(admin_client)
        invite(admin_client, owner)

        assert (
            "Λάθος email ή κωδικός."
            in log_in(stranger, password="the stranger's password 1").content.decode()
        )
        invitation = emails_to(MARIA)[-1]
        assert invitation.template == "identity.invitation"
        choose_password(client, invitation)
        assert log_in(client)["Location"] == "/owner/"
        assert User.objects.get(username=MARIA).owner_id == owner.pk

    def test_the_admin_never_sets_an_owners_password(self, admin_client: Client) -> None:
        sign_up(Client())
        user = User.objects.get(username=MARIA)
        # Django names this view after its own auth app, whatever the user model's app.
        page = reverse("admin:auth_user_password_change", args=[user.pk])
        assert admin_client.get(page).status_code == 403

    def test_staff_never_read_the_links_in_emails(self, admin_client: Client) -> None:
        sign_up(Client())
        (email,) = emails_to(MARIA)
        page = admin_client.get(reverse("admin:outbox_outboxmessage_change", args=[email.pk]))
        assert page.status_code == 200
        assert "/owner/verify/" not in page.content.decode()
