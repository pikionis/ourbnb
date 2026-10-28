"""The owner portal end to end (DOMAIN §5 owner portal, ADR 0017/0018): an owner registers,
verifies the bank account with the admin's test transfer, and sees only their own data."""

from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from kospm.identity.models import User
from kospm.properties import models
from tests.e2e.owners import (
    MARIA,
    logged_in_owner,
    messages_of,
    owner_form,
    register_owner_in_admin,
)
from tests.unit.properties.builders import OTHER_VALID_AFM, OTHER_VALID_IBAN, VALID_AFM, VALID_IBAN

pytestmark = pytest.mark.django_db

DASHBOARD = reverse("portal:dashboard")
DETAILS = reverse("portal:details")
BANK = reverse("portal:bank")


@pytest.fixture(autouse=True)
def fresh_throttle() -> None:
    cache.clear()


def registration(**overrides: Any) -> dict[str, Any]:
    data = {
        "name": "Μαρία Παπαδοπούλου",
        "phone": "+30 6900000000",
        "afm": VALID_AFM,
        "iban": VALID_IBAN,
        "holder_name": "papadopoulou   maria",
    }
    data.update(overrides)
    return data


def registered_owner() -> tuple[Client, models.Owner]:
    client = logged_in_owner()
    assert client.post(DETAILS, registration())["Location"] == DASHBOARD
    return client, models.Owner.objects.get(email=MARIA)


def admin_records_transfer(admin_client: Client, owner: models.Owner, result: str) -> None:
    owner.refresh_from_db()
    admin_client.post(
        reverse("admin:properties_owner_change", args=[owner.pk]),
        owner_form(
            bank_holder_name=owner.bank_holder_name, version=owner.version, payee_check=result
        ),
    )
    owner.refresh_from_db()


class TestAccess:
    def test_anonymous_visitors_are_sent_to_log_in(self, client: Client) -> None:
        response = client.get(DASHBOARD)
        assert response.status_code == 302
        assert response["Location"].startswith(reverse("identity:login"))

    def test_a_staff_login_is_not_an_owner(self, admin_client: Client) -> None:
        assert admin_client.get(DASHBOARD).status_code == 403


class TestRegistration:
    def test_a_new_account_is_asked_for_its_details_first(self) -> None:
        page = logged_in_owner().get(DASHBOARD).content.decode()
        assert DETAILS in page
        assert BANK not in page

    def test_the_owner_registers_with_the_id_and_email_of_the_account(self) -> None:
        client, owner = registered_owner()
        user = User.objects.get(username=MARIA)
        assert owner.pk == user.owner_id
        assert owner.bank_holder_name == "papadopoulou maria"
        assert owner.bank_account_status == "unverified"
        assert user.owner_registered is True  # identity heard OwnerRegistered (bootstrap)
        assert "Μαρία Παπαδοπούλου" in client.get(DASHBOARD).content.decode()

    def test_a_tax_number_registered_by_the_admin_is_refused_with_contact_us(
        self, admin_client: Client
    ) -> None:
        register_owner_in_admin(admin_client, email="other@example.com")
        client = logged_in_owner()
        response = client.post(DETAILS, registration())
        assert response.status_code == 200
        assert "Επικοινωνήστε μαζί μας" in response.content.decode()
        assert models.Owner.objects.count() == 1  # only the admin's

    def test_details_change_but_the_login_email_stays(self) -> None:
        client, owner = registered_owner()
        saved = client.post(DETAILS, {"name": "Μαρία Π.", "phone": "+30 6911111111"})
        assert saved["Location"] == DASHBOARD
        owner.refresh_from_db()
        assert (owner.name, owner.phone, owner.email) == ("Μαρία Π.", "+30 6911111111", MARIA)


class TestBankAccount:
    def test_verification_with_the_admins_test_transfer_and_the_code(
        self, admin_client: Client
    ) -> None:
        client, owner = registered_owner()
        client.post(BANK, {"action": "verify"})
        owner.refresh_from_db()
        assert owner.bank_account_status == "pending"
        assert 'action" value="code"' not in client.get(BANK).content.decode()

        admin_records_transfer(admin_client, owner, "match")
        assert owner.bank_account_status == "transfer_sent"
        assert 'value="code"' in client.get(BANK).content.decode()

        wrong = client.post(BANK, {"action": "code", "code": "000000"})
        assert wrong.status_code == 200
        done = client.post(BANK, {"action": "code", "code": owner.bank_verification_code})
        assert done["Location"] == BANK
        owner.refresh_from_db()
        assert owner.bank_account_status == "verified"

    def test_a_verified_account_is_changed_only_through_the_ike(self, admin_client: Client) -> None:
        client, owner = registered_owner()
        client.post(BANK, {"action": "verify"})
        admin_records_transfer(admin_client, owner, "match")
        client.post(BANK, {"action": "code", "code": owner.bank_verification_code})

        page = client.get(BANK).content.decode()
        assert 'value="account"' not in page
        refused = client.post(
            BANK,
            {"action": "account", "iban": OTHER_VALID_IBAN, "holder_name": "SOMEONE ELSE"},
        )
        assert refused.status_code == 200
        owner.refresh_from_db()
        assert (owner.iban, owner.bank_account_status) == (
            VALID_IBAN.replace(" ", ""),
            "verified",
        )

    def test_no_match_tells_the_owner_to_check_the_name(self, admin_client: Client) -> None:
        client, owner = registered_owner()
        client.post(BANK, {"action": "verify"})
        admin_records_transfer(admin_client, owner, "no_match")
        assert owner.bank_account_status == "unverified"
        assert "δεν αναγνώρισε" in client.get(BANK).content.decode()

    def test_the_owner_corrects_the_account_before_it_is_verified(self) -> None:
        client, owner = registered_owner()
        saved = client.post(
            BANK,
            {"action": "account", "iban": OTHER_VALID_IBAN, "holder_name": "MARIA PAPADOPOULOU"},
        )
        assert saved["Location"] == BANK
        owner.refresh_from_db()
        assert owner.bank_holder_name == "MARIA PAPADOPOULOU"

    def test_no_code_before_the_transfer_is_sent(self) -> None:
        client, _ = registered_owner()
        client.post(BANK, {"action": "verify"})
        response = client.post(BANK, {"action": "code", "code": "123456"})
        assert "δεν έχει σταλεί" in response.content.decode()


class TestOwnData:
    def test_an_owner_sees_only_their_own_properties(self, admin_client: Client) -> None:
        other = register_owner_in_admin(
            admin_client, email="nikos@example.com", afm=OTHER_VALID_AFM
        )
        admin_client.post(
            reverse("admin:properties_property_add"),
            {"owner": str(other.pk), "code": "KOS-N1", "name": "Σπίτι του Νίκου"},
        )
        client, _ = registered_owner()
        page = client.get(DASHBOARD).content.decode()
        assert "KOS-N1" not in page
        assert "Σπίτι του Νίκου" not in page

    def test_messages_never_name_another_owner(self, admin_client: Client) -> None:
        client, _ = registered_owner()
        response = client.post(BANK, {"action": "verify"}, follow=True)
        assert all("nikos" not in message for message in messages_of(response))
