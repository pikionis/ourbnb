"""The properties admin end to end (ADR 0006): forms and actions send commands, never write rows.

Each test posts what the admin's pages post and checks the stored rows and the messages shown.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import translation

from kospm.properties import models
from kospm.properties.entrypoints.texts import describe
from kospm.shared.unit_of_work import ConcurrencyError
from tests.unit.properties.builders import (
    OTHER_VALID_AFM,
    OTHER_VALID_IBAN,
    VALID_AFM,
    VALID_IBAN,
)

pytestmark = pytest.mark.django_db

OWNER_ADD = reverse("admin:properties_owner_add")
OWNERS = reverse("admin:properties_owner_changelist")
PROPERTY_ADD = reverse("admin:properties_property_add")
PROPERTIES = reverse("admin:properties_property_changelist")


@pytest.fixture(autouse=True)
def media_in_tmp(settings: Any, tmp_path: Path) -> None:
    settings.MEDIA_ROOT = tmp_path


def messages_of(response: Any) -> list[str]:
    return [str(message) for message in get_messages(response.wsgi_request)]


def owner_form(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": "Μαρία Παπαδοπούλου",
        "email": "Maria@Example.com",
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


def add_owner(client: Client, **overrides: Any) -> models.Owner:
    response = client.post(OWNER_ADD, owner_form(**overrides))
    assert response.status_code == 302, response.content.decode()[:3000]
    return models.Owner.objects.get(afm=overrides.get("afm", VALID_AFM))


def property_form(owner: models.Owner, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "owner": str(owner.pk),
        "code": "kos-a1",
        "name": "Σπίτι Αιγαίου",
        "address": "",
        "lat": "",
        "lng": "",
        "default_check_in_time": "15:00",
        "default_check_out_time": "11:00",
        "linen_par_level": "3",
        "directions_el": "",
        "directions_en": "",
        "map_url": "",
        "guest_lockbox_code_new": "",
        "cleaner_lockbox_code_new": "",
        "amenities_included_text": "",
        "amenities_not_included_text": "",
        "airbnb_ical_url": "",
        "booking_ical_url": "",
        "contract_signed_at_0": "",
        "contract_signed_at_1": "",
        "contract_commission_rate": "",
        "contract_owner_cleaning_charge": "",
        "sublease_declaration_number": "",
        "ama_number": "",
    }
    data.update(overrides)
    return data


def complete_property_form(owner: models.Owner, **overrides: Any) -> dict[str, Any]:
    data = property_form(
        owner,
        address="Βασιλέως Παύλου 12, Κως",
        lat="36.893300",
        lng="27.288900",
        directions_el="Δεύτερο στενό δεξιά.",
        directions_en="Second street on the right.",
        exterior_photo=SimpleUploadedFile("exterior.jpg", b"jpg"),
        lockbox_photo=SimpleUploadedFile("lockbox.jpg", b"jpg"),
        guest_lockbox_code_new="4711",
        amenities_included_text="Wi-Fi\nΚλιματισμός",
        contract_document=SimpleUploadedFile("contract.pdf", b"%PDF-1.4"),
        sublease_declaration_number="ΔΥ-2026-000123",
        ama_number="00001234567",
    )
    data.update(overrides)
    return data


def add_property(client: Client, owner: models.Owner, **overrides: Any) -> models.Property:
    data = property_form(owner, **overrides)
    response = client.post(PROPERTY_ADD, data)
    assert response.status_code == 302, response.content.decode()[:3000]
    return models.Property.objects.get(code=str(data["code"]).strip().upper())


def change_property(client: Client, prop: models.Property, data: dict[str, Any]) -> Any:
    data = {key: value for key, value in data.items() if key not in {"owner", "code"}}
    return client.post(reverse("admin:properties_property_change", args=[prop.pk]), data)


def run_action(client: Client, url: str, action: str, pk: UUID) -> Any:
    return client.post(url, {"action": action, "_selected_action": [str(pk)]}, follow=True)


def verify_bank_account(client: Client, owner: models.Owner) -> None:
    run_action(client, OWNERS, "start_bank_verification", owner.pk)
    owner.refresh_from_db()
    response = client.post(
        reverse("admin:properties_owner_change", args=[owner.pk]),
        owner_form(payee_check="match", verification_code=owner.bank_verification_code),
    )
    assert response.status_code == 302


class TestOwners:
    def test_registers_an_owner(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        assert owner.email == "maria@example.com"
        assert owner.bank_account_status == "unverified"
        assert owner.version == 0

    @pytest.mark.parametrize(
        ("field", "value"),
        [("afm", "123456789"), ("iban", "GR16 0110 1250 0000 0001 2300 696"), ("email", "x")],
    )
    def test_invalid_values_are_form_errors(
        self, admin_client: Client, field: str, value: str
    ) -> None:
        response = admin_client.post(OWNER_ADD, owner_form(**{field: value}))
        assert response.status_code == 200
        assert field in response.context["adminform"].form.errors
        assert not models.Owner.objects.exists()

    def test_the_afm_identifies_one_owner(self, admin_client: Client) -> None:
        add_owner(admin_client)
        response = admin_client.post(OWNER_ADD, owner_form(email="other@example.com"))
        assert response.status_code == 200
        assert "afm" in response.context["adminform"].form.errors

    def test_bank_verification_with_the_code_of_the_test_transfer(
        self, admin_client: Client
    ) -> None:
        owner = add_owner(admin_client)
        started = run_action(admin_client, OWNERS, "start_bank_verification", owner.pk)
        owner.refresh_from_db()
        assert owner.bank_account_status == "pending"
        assert any(owner.bank_verification_code in m for m in messages_of(started))

        change = reverse("admin:properties_owner_change", args=[owner.pk])
        too_early = admin_client.post(change, owner_form(verification_code="000000"), follow=True)
        assert any("δεν έχει σταλεί" in m for m in messages_of(too_early))

        bank_name = "PAPADOPOULOU MARIA K"
        sent = admin_client.post(
            change,
            owner_form(payee_check="close_match", payee_check_name=bank_name),
            follow=True,
        )
        owner.refresh_from_db()
        assert owner.bank_account_status == "transfer_sent"
        assert owner.bank_holder_name == bank_name  # the bank's own spelling
        assert sent.status_code == 200

        wrong = admin_client.post(
            change, owner_form(bank_holder_name=bank_name, verification_code="000000"), follow=True
        )
        owner.refresh_from_db()
        assert owner.bank_verification_failed_attempts == 1
        assert any("000000" not in m and "2" in m for m in messages_of(wrong))

        admin_client.post(
            change,
            owner_form(bank_holder_name=bank_name, verification_code=owner.bank_verification_code),
        )
        owner.refresh_from_db()
        assert owner.bank_account_status == "verified"

    def test_no_match_sends_nothing_and_the_verification_starts_over(
        self, admin_client: Client
    ) -> None:
        owner = add_owner(admin_client)
        run_action(admin_client, OWNERS, "start_bank_verification", owner.pk)
        change = reverse("admin:properties_owner_change", args=[owner.pk])
        admin_client.post(change, owner_form(payee_check="no_match"))
        owner.refresh_from_db()
        assert (owner.bank_account_status, owner.bank_payee_check) == ("unverified", "no_match")


class TestProperties:
    def test_adds_a_property_in_progress(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner)
        assert (prop.code, prop.status, prop.owner_id) == ("KOS-A1", "onboarding", owner.pk)

    def test_a_code_is_used_once(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        add_property(admin_client, owner)
        response = admin_client.post(PROPERTY_ADD, property_form(owner, code="KOS-A1"))
        assert response.status_code == 200
        assert "code" in response.context["adminform"].form.errors

    def test_the_list_shows_what_is_missing(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        add_property(admin_client, owner)
        page = admin_client.get(PROPERTIES, {"status__exact": "onboarding"}).content.decode()
        assert "KOS-A1" in page
        assert 'data-missing="ama"' in page
        assert 'data-missing="bank_account_verified"' in page

    def test_activation_lists_the_missing_items_then_succeeds(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner)

        refused = run_action(admin_client, PROPERTIES, "activate_properties", prop.pk)
        prop.refresh_from_db()
        assert prop.status == "onboarding"
        assert any("KOS-A1" in m for m in messages_of(refused))

        response = change_property(admin_client, prop, complete_property_form(owner))
        assert response.status_code == 302, response.content.decode()[:3000]
        verify_bank_account(admin_client, owner)

        run_action(admin_client, PROPERTIES, "activate_properties", prop.pk)
        prop.refresh_from_db()
        owner.refresh_from_db()
        assert prop.status == "active"
        assert prop.contract_document.name.startswith("contracts/")
        assert owner.website_consent_requested is True

    def test_the_lockbox_code_is_never_shown(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner)
        change_property(admin_client, prop, complete_property_form(owner))
        page = admin_client.get(
            reverse("admin:properties_property_change", args=[prop.pk])
        ).content.decode()
        assert "4711" not in page

    def test_an_empty_lockbox_field_keeps_the_stored_code(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner)
        change_property(admin_client, prop, complete_property_form(owner))
        change_property(
            admin_client,
            prop,
            complete_property_form(owner, guest_lockbox_code_new="", name="Νέο όνομα"),
        )
        prop.refresh_from_db()
        assert (prop.name, prop.guest_lockbox_code) == ("Νέο όνομα", "4711")

    def test_deactivate_reactivate_and_offboard(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner)
        change_property(admin_client, prop, complete_property_form(owner))
        verify_bank_account(admin_client, owner)
        run_action(admin_client, PROPERTIES, "activate_properties", prop.pk)

        run_action(admin_client, PROPERTIES, "deactivate_properties", prop.pk)
        prop.refresh_from_db()
        assert prop.status == "inactive"
        run_action(admin_client, PROPERTIES, "activate_properties", prop.pk)
        prop.refresh_from_db()
        assert prop.status == "active"
        run_action(admin_client, PROPERTIES, "offboard_properties", prop.pk)
        prop.refresh_from_db()
        assert prop.status == "offboarded"

        change = reverse("admin:properties_property_change", args=[prop.pk])
        assert admin_client.post(change, complete_property_form(owner)).status_code == 403

    def test_an_active_property_keeps_a_complete_profile(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner)
        change_property(admin_client, prop, complete_property_form(owner))
        verify_bank_account(admin_client, owner)
        run_action(admin_client, PROPERTIES, "activate_properties", prop.pk)

        response = change_property(admin_client, prop, complete_property_form(owner, address=""))
        assert response.status_code == 200
        assert response.context["adminform"].form.errors
        prop.refresh_from_db()
        assert prop.address != ""

    def test_one_owner_with_many_properties(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        add_owner(admin_client, afm=OTHER_VALID_AFM, email="nikos@example.com")
        for code in ("KOS-A1", "KOS-A2", "KOS-B1"):
            add_property(admin_client, owner, code=code)
        page = admin_client.get(
            reverse("admin:properties_owner_change", args=[owner.pk])
        ).content.decode()
        assert all(code in page for code in ("KOS-A1", "KOS-A2", "KOS-B1"))
        assert owner.properties.count() == 3

    def test_nothing_can_be_deleted(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner)
        delete = reverse("admin:properties_property_delete", args=[prop.pk])
        assert admin_client.post(delete, {"post": "yes"}).status_code == 403
        assert models.Property.objects.filter(pk=prop.pk).exists()


class TestFormsAskTheDomain:
    """The form previews every command of a save on the aggregate (forms.py): refusals show next
    to the field concerned, before anything is stored."""

    def test_a_contract_needs_its_signed_pdf(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner)
        response = change_property(
            admin_client, prop, property_form(owner, contract_commission_rate="0.18")
        )
        assert response.status_code == 200
        assert "contract_document" in response.context["adminform"].form.errors

    def test_the_commission_rate_is_below_one(self, admin_client: Client, settings: Any) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner)
        response = change_property(
            admin_client,
            prop,
            property_form(
                owner,
                contract_commission_rate="1.5",
                contract_document=SimpleUploadedFile("contract.pdf", b"%PDF-1.4"),
            ),
        )
        assert response.status_code == 200
        assert "contract_commission_rate" in response.context["adminform"].form.errors
        assert stored_files(settings) == []  # a preview stores nothing

    def test_a_contract_is_a_pdf(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner)
        response = change_property(
            admin_client,
            prop,
            property_form(owner, contract_document=SimpleUploadedFile("contract.docx", b"PK")),
        )
        assert response.status_code == 200
        assert "contract_document" in response.context["adminform"].form.errors

    def test_a_photo_is_an_image(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner)
        response = change_property(
            admin_client,
            prop,
            property_form(owner, exterior_photo=SimpleUploadedFile("door.pdf", b"%PDF-1.4")),
        )
        assert response.status_code == 200
        assert "exterior_photo" in response.context["adminform"].form.errors

    def test_a_wrong_booking_link_is_shown_on_the_booking_field(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner)
        response = change_property(
            admin_client,
            prop,
            property_form(owner, booking_ical_url="http://admin.booking.com/ical/x.ics"),
        )
        assert response.status_code == 200
        assert list(response.context["adminform"].form.errors) == ["booking_ical_url"]

    def test_a_long_file_name_is_shortened_to_fit(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner)
        name = (
            "Συμφωνητικό υπεκμίσθωσης " * 3 + "ακινήτου Κως 2026.pdf"
        )  # fits 100 alone, not with the folder
        response = change_property(
            admin_client,
            prop,
            property_form(owner, contract_document=SimpleUploadedFile(name, b"%PDF-1.4")),
        )
        assert response.status_code == 302, response.content.decode()[:3000]
        prop.refresh_from_db()
        assert prop.contract_document.name.endswith(".pdf")
        assert len(prop.contract_document.name) <= 100

    def test_a_recorded_number_can_be_corrected_not_removed(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner, ama_number="00001234567")
        corrected = change_property(admin_client, prop, property_form(owner, ama_number="7654321"))
        assert corrected.status_code == 302
        removed = change_property(admin_client, prop, property_form(owner, ama_number=""))
        assert removed.status_code == 200
        assert "ama_number" in removed.context["adminform"].form.errors
        prop.refresh_from_db()
        assert prop.ama_number == "7654321"

    def test_cleaners_can_go_back_to_the_guests_code(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner)
        change_property(admin_client, prop, property_form(owner, cleaner_lockbox_code_new="9999"))
        prop.refresh_from_db()
        assert prop.cleaner_lockbox_code == "9999"
        change_property(admin_client, prop, property_form(owner, cleaner_uses_guest_code="on"))
        prop.refresh_from_db()
        assert not prop.cleaner_lockbox_code

    def test_a_new_cleaner_code_or_the_guests_code_not_both(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner)
        response = change_property(
            admin_client,
            prop,
            property_form(owner, cleaner_lockbox_code_new="9999", cleaner_uses_guest_code="on"),
        )
        assert response.status_code == 200
        assert "cleaner_lockbox_code_new" in response.context["adminform"].form.errors


class TestStaleForms:
    """A form saved after someone else saved the same record is refused (ADR 0016)."""

    def test_the_page_carries_the_version(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        page = admin_client.get(change_url(owner)).content.decode()
        assert 'name="version" value="0"' in page

    def test_a_stale_owner_form_does_not_overwrite(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        admin_client.post(change_url(owner), owner_form(name="Μαρία Π.", version="0"))
        stale = admin_client.post(
            change_url(owner), owner_form(phone="+30 6911111111", version="0"), follow=True
        )
        owner.refresh_from_db()
        assert (owner.name, owner.phone, owner.version) == ("Μαρία Π.", "+30 6900000000", 1)
        assert concurrency_message() in messages_of(stale)

    def test_a_stale_iban_change_is_refused(self, admin_client: Client) -> None:
        owner = add_owner(admin_client)
        admin_client.post(change_url(owner), owner_form(name="Μαρία Π.", version="0"))
        stale = admin_client.post(
            change_url(owner),
            owner_form(
                name="Μαρία Π.", email="maria@example.com", iban=OTHER_VALID_IBAN, version="0"
            ),
            follow=True,
        )
        owner.refresh_from_db()
        assert owner.iban == VALID_IBAN.replace(" ", "")
        assert concurrency_message() in messages_of(stale)

    def test_a_stale_property_form_is_refused_and_its_uploads_removed(
        self, admin_client: Client, settings: Any
    ) -> None:
        owner = add_owner(admin_client)
        prop = add_property(admin_client, owner)
        rendered = str(prop.version)
        change_property(admin_client, prop, property_form(owner, name="Πρώτη", version=rendered))
        stale = change_property(admin_client, prop, complete_property_form(owner, version=rendered))
        assert stale.status_code == 302
        prop.refresh_from_db()
        assert (prop.name, prop.address) == ("Πρώτη", "")
        assert stored_files(settings) == []


def change_url(record: models.Owner | models.Property) -> str:
    return reverse(f"admin:properties_{record._meta.model_name}_change", args=[record.pk])


def stored_files(settings: Any) -> list[Path]:
    return [path for path in Path(settings.MEDIA_ROOT).rglob("*") if path.is_file()]


def concurrency_message() -> str:
    with translation.override("el"):
        return describe(ConcurrencyError())
