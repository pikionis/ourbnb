"""The owner's properties in the portal end to end (DOMAIN §5 owner portal, design brief J5 to
J8): add, profile with photos, profile from listing text, contract to sign, sublease declaration,
own files only."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import F
from django.test import Client
from django.urls import reverse

from kospm.properties import models
from kospm.properties.adapters.queries import owner_property
from kospm.properties.domain.checklist import ActivationRequirement
from kospm.properties.domain.listing import ListingDraft
from kospm.properties.entrypoints.portal import property_views
from tests.e2e.owners import (
    MARIA,
    add_property_in_admin,
    logged_in_owner,
    owner_form,
    register_owner_in_admin,
)
from tests.unit.properties.builders import OTHER_VALID_AFM, VALID_AFM, VALID_IBAN
from tests.unit.properties.fakes import FakeListingExtractor

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media_in_tmp(settings: Any, tmp_path: Path) -> None:
    settings.MEDIA_ROOT = tmp_path
    cache.clear()


@pytest.fixture
def assistant(monkeypatch: pytest.MonkeyPatch) -> FakeListingExtractor:
    """The Claude API replaced by a fake that answers with a known draft."""
    fake = FakeListingExtractor(
        ListingDraft(
            address="Λάμπη, Κως 853 00",
            directions_el="Δεύτερο στενό δεξιά μετά τον φούρνο.",
            directions_en="Second street on the right after the bakery.",
            amenities_included=("Wi-Fi", "Beach umbrellas"),
            amenities_not_included=("Pool",),
        )
    )
    monkeypatch.setattr(property_views, "listing_extractor", lambda: fake)
    return fake


LISTING = "Όμορφο σπίτι στη Λάμπη, 300 μέτρα από τη θάλασσα. Wi-Fi, ομπρέλες θαλάσσης."


def photo(name: str = "house.jpg") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"\xff\xd8\xff" + b"0" * 64, content_type="image/jpeg")


def pdf(name: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"%PDF-1.7 signed", content_type="application/pdf")


def registered(client: Client) -> models.Owner:
    client.post(
        reverse("portal:details"),
        {
            "name": "Μαρία Παπαδοπούλου",
            "phone": "+30 6900000000",
            "afm": VALID_AFM,
            "iban": VALID_IBAN,
            "holder_name": "PAPADOPOULOU MARIA",
        },
    )
    return models.Owner.objects.get(email=MARIA)


def add_property(client: Client, name: str = "Villa Elena") -> models.Property:
    response = client.post(reverse("portal:property_new"), {"name": name})
    assert response.status_code == 302
    return models.Property.objects.get(name=name)


def profile(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": "Villa Elena",
        "address": "Λάμπη, Κως 853 00",
        "coordinates": "36.8930123456, 27.2877",
        "map_url": "",
        "directions_el": "Από τον κεντρικό δρόμο, δεύτερο στενό δεξιά.",
        "directions_en": "From the main road, second street on the right.",
        "exterior_photo": photo("outside.jpg"),
        "lockbox_photo": photo("lockbox.png"),
        "guest_lockbox_code": "4711",
        "amenity_wi_fi": "yes",
        "amenity_pool": "no",
        "other_included": "Ομπρέλες θαλάσσης",
        "version": "0",
    }
    data.update(overrides)
    return data


def stored_files(media: Path) -> set[Path]:
    return {path for path in media.rglob("*") if path.is_file()}


def page(client: Client, name: str, code: str) -> str:
    return reverse(f"portal:{name}", args=[code])


class TestAddAndComplete:
    def test_the_whole_checklist_of_the_owner_leaves_only_the_ama_missing(
        self, admin_client: Client
    ) -> None:
        client = logged_in_owner()
        owner = registered(client)
        # The bank account, with the admin's test transfer and the owner's code.
        client.post(reverse("portal:bank"), {"action": "verify"})
        owner.refresh_from_db()
        admin_client.post(
            reverse("admin:properties_owner_change", args=[owner.pk]),
            owner_form(version=owner.version, payee_check="match"),
        )
        owner.refresh_from_db()
        code = owner.bank_verification_code
        client.post(reverse("portal:bank"), {"action": "code", "code": code})

        prop = add_property(client)
        assert prop.code == "KOS-001"
        saved = client.post(page(client, "property_profile", prop.code), profile())
        assert saved.status_code == 302, saved.content.decode()

        prop.refresh_from_db()
        admin_client.post(
            reverse("admin:properties_property_change", args=[prop.pk]),
            _admin_property_form(
                prop,
                contract_draft_document=pdf("contract.pdf"),
                contract_draft_commission_rate="0.18",
            ),
        )
        uploaded = client.post(
            page(client, "property_contract", prop.code),
            {"signed_contract": pdf("signed.pdf"), "version": str(_version(prop))},
        )
        assert uploaded.status_code == 302, uploaded.content.decode()
        client.post(
            page(client, "property_sublease", prop.code),
            {"number": "ΔΥ-2026-1", "version": str(_version(prop))},
        )

        owned = owner_property(owner.pk, prop.code)
        assert owned is not None
        assert owned.missing == [ActivationRequirement.AMA]
        prop.refresh_from_db()
        assert prop.amenities_included == ["Wi-Fi", "Ομπρέλες θαλάσσης"]
        assert prop.amenities_not_included == ["Pool"]
        assert (str(prop.lat), str(prop.lng)) == ("36.893012", "27.287700")
        assert prop.contract_commission_rate == Decimal("0.1800")  # the terms of the draft
        assert prop.guest_lockbox_code == "4711"

    def test_the_ikes_settings_stay_as_they_were(self) -> None:
        client = logged_in_owner()
        registered(client)
        prop = add_property(client)
        before = (prop.linen_par_level, prop.default_check_in_time, prop.ical_feeds)
        client.post(page(client, "property_profile", prop.code), profile())
        prop.refresh_from_db()
        assert (prop.linen_par_level, prop.default_check_in_time, prop.ical_feeds) == before

    def test_a_file_that_is_not_a_photo_is_refused_and_not_kept(self, tmp_path: Path) -> None:
        client = logged_in_owner()
        registered(client)
        prop = add_property(client)
        bad = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")
        response = client.post(
            page(client, "property_profile", prop.code), profile(exterior_photo=bad)
        )
        assert response.status_code == 200
        prop.refresh_from_db()
        assert not prop.exterior_photo
        assert not any(path.is_file() for path in tmp_path.rglob("*"))

    def test_nothing_to_upload_before_the_ike_offers_the_contract(self) -> None:
        client = logged_in_owner()
        registered(client)
        prop = add_property(client)
        content = client.get(page(client, "property_contract", prop.code)).content.decode()
        assert "Ετοιμάζουμε το συμβόλαιό σας" in content


class TestUploads:
    def test_a_recorded_contract_is_not_replaced_by_the_owner(self, admin_client: Client) -> None:
        client = logged_in_owner()
        registered(client)
        prop = add_property(client)
        change = reverse("admin:properties_property_change", args=[prop.pk])
        admin_client.post(change, _admin_property_form(prop, contract_draft_document=pdf("d.pdf")))
        prop.refresh_from_db()
        admin_client.post(  # signed on paper, with its own terms
            change,
            _admin_property_form(
                prop,
                contract_document=pdf("paper.pdf"),
                contract_commission_rate="0.12",
                contract_owner_cleaning_charge="30.00",
            ),
        )
        contract_page = page(client, "property_contract", prop.code)
        assert 'name="signed_contract"' not in client.get(contract_page).content.decode()

        refused = client.post(
            contract_page, {"signed_contract": pdf("mine.pdf"), "version": str(_version(prop))}
        )

        assert "συμβόλαιό σας έχει ανέβει" in refused.content.decode()
        prop.refresh_from_db()
        assert (prop.contract_commission_rate, prop.contract_owner_cleaning_charge) == (
            Decimal("0.1200"),
            Decimal("30.00"),
        )

    def test_a_refused_save_keeps_no_upload_and_shows_nothing_as_saved(
        self, admin_client: Client, tmp_path: Path
    ) -> None:
        client = logged_in_owner()
        registered(client)
        prop = add_property(client)
        admin_client.post(
            reverse("admin:properties_property_change", args=[prop.pk]),
            _admin_property_form(prop, contract_draft_document=pdf("contract.pdf")),
        )
        seen = _version(prop)  # the version the owner's pages show
        models.Property.objects.filter(pk=prop.pk).update(version=F("version") + 1)  # the IKE saved
        files = stored_files(tmp_path)

        contract = client.post(
            page(client, "property_contract", prop.code),
            {"signed_contract": pdf("signed.pdf"), "version": str(seen)},
        ).content.decode()
        profile_page = client.post(
            page(client, "property_profile", prop.code), profile(version=str(seen))
        ).content.decode()

        for html in (contract, profile_page):
            assert "Κάποιος άλλος το άλλαξε" in html
        assert "Το υπογεγραμμένο συμβόλαιο έχει ανέβει." not in contract
        assert "Υπάρχει αποθηκευμένη φωτογραφία." not in profile_page
        assert "Υπάρχει αποθηκευμένος κωδικός." not in profile_page
        assert stored_files(tmp_path) == files  # the refused uploads are not kept

    def test_a_file_over_the_size_limit_is_refused_and_not_kept(
        self, settings: Any, tmp_path: Path
    ) -> None:
        settings.PORTAL_UPLOAD_MAX_MB = 1
        client = logged_in_owner()
        registered(client)
        prop = add_property(client)
        files = stored_files(tmp_path)
        one_byte_too_big = SimpleUploadedFile(
            "big.jpg", b"\xff\xd8\xff" + b"0" * (1024 * 1024 - 2), content_type="image/jpeg"
        )

        response = client.post(
            page(client, "property_profile", prop.code), profile(exterior_photo=one_byte_too_big)
        )

        assert "μεγαλύτερο από 1 MB" in response.content.decode()
        assert stored_files(tmp_path) == files

    def test_the_owner_renames_the_property_and_cleaners_go_back_to_the_guests_code(
        self,
    ) -> None:
        client = logged_in_owner()
        owner = registered(client)
        prop = add_property(client)
        profile_page = page(client, "property_profile", prop.code)
        client.post(profile_page, profile(cleaner_lockbox_code="9999"))

        saved = client.post(
            profile_page,
            profile(
                name="Villa Elena Kos",
                exterior_photo="",
                lockbox_photo="",
                guest_lockbox_code="",
                cleaners_use_guest_code="on",
                version=str(_version(prop)),
            ),
        )

        assert saved.status_code == 302, saved.content.decode()
        owned = owner_property(owner.pk, prop.code)
        assert owned is not None
        assert owned.prop.name == "Villa Elena Kos"
        assert not owned.prop.check_in_guide.cleaner_lockbox_code
        assert owned.prop.check_in_guide.guest_lockbox_code == "4711"


class TestFillInFromListing:
    """J6: the owner pastes the listing's text; the profile comes back filled in, unsaved."""

    def test_the_profile_comes_back_filled_in_and_nothing_is_saved(
        self, assistant: FakeListingExtractor
    ) -> None:
        client = logged_in_owner()
        registered(client)
        prop = add_property(client)
        profile_page, listing_page = (
            page(client, "property_profile", prop.code),
            page(client, "property_listing", prop.code),
        )
        assert listing_page in client.get(profile_page).content.decode()
        version = _version(prop)

        response = client.post(listing_page, {"text": LISTING})

        html = response.content.decode()
        assert response.status_code == 200
        assert [listing.value for listing in assistant.read] == [LISTING]
        assert 'value="Λάμπη, Κως 853 00"' in html
        assert "Second street on the right after the bakery." in html
        assert "Beach umbrellas" in html
        assert html.count("badge-check") == 6  # each field that came from the text is marked
        assert f'action="{profile_page}"' in html  # Save sends the usual profile form
        assert _version(prop) == version  # nothing is saved until the owner saves
        assert prop.address == ""

    def test_a_link_is_refused_and_nothing_is_sent(self, assistant: FakeListingExtractor) -> None:
        client = logged_in_owner()
        registered(client)
        prop = add_property(client)

        response = client.post(
            page(client, "property_listing", prop.code),
            {"text": "https://www.airbnb.com/rooms/123"},
        )

        assert 'id="id_text_error"' in response.content.decode()
        assert assistant.read == []

    def test_without_the_assistant_the_owner_fills_in_the_profile_by_hand(self) -> None:
        client = logged_in_owner()  # the test settings have no API key
        registered(client)
        prop = add_property(client)

        response = client.post(page(client, "property_listing", prop.code), {"text": LISTING})

        assert "δεν μπόρεσε να διαβάσει την αγγελία σας" in response.content.decode()

    def test_the_readings_per_hour_are_limited(
        self, assistant: FakeListingExtractor, settings: Any
    ) -> None:
        settings.LISTING_READINGS_PER_HOUR = 1
        client = logged_in_owner()
        registered(client)
        prop = add_property(client)
        listing_page = page(client, "property_listing", prop.code)

        client.post(listing_page, {"text": LISTING})
        response = client.post(listing_page, {"text": LISTING})

        assert len(assistant.read) == 1
        assert "πολλές φορές" in response.content.decode()

    def test_after_the_set_up_nothing_is_read(self, assistant: FakeListingExtractor) -> None:
        client = logged_in_owner()
        registered(client)
        prop = add_property(client)
        models.Property.objects.filter(pk=prop.pk).update(status="active")

        response = client.post(page(client, "property_listing", prop.code), {"text": LISTING})

        assert response.status_code == 200
        assert assistant.read == []


class TestOwnDataOnly:
    def test_another_owners_property_and_files_are_not_found(self, admin_client: Client) -> None:
        other = register_owner_in_admin(
            admin_client, email="nikos@example.com", afm=OTHER_VALID_AFM
        )
        nikos_property = add_property_in_admin(admin_client, other, code="KOS-N1", name="Του Νίκου")
        admin_client.post(
            reverse("admin:properties_property_change", args=[nikos_property.pk]),
            _admin_property_form(nikos_property, contract_draft_document=pdf("nikos.pdf")),
        )
        nikos_property.refresh_from_db()
        assert nikos_property.contract_draft_document  # a real file: only the owner check refuses
        client = logged_in_owner()
        registered(client)
        for name in (
            "property",
            "property_profile",
            "property_listing",
            "property_contract",
            "property_sublease",
        ):
            assert client.get(page(client, name, "KOS-N1")).status_code == 404
        file_page = reverse("portal:property_file", args=["KOS-N1", "contract_draft_document"])
        assert client.get(file_page).status_code == 404

    def test_only_the_owner_opens_their_files(self) -> None:
        client = logged_in_owner()
        registered(client)
        prop = add_property(client)
        client.post(page(client, "property_profile", prop.code), profile())
        mine = reverse("portal:property_file", args=[prop.code, "exterior_photo"])
        opened = client.get(mine)
        assert opened.status_code == 200
        assert "no-store" in opened["Cache-Control"]  # not kept by a shared phone's browser
        assert Client().get(mine).status_code == 302  # to the login
        wrong_kind = reverse("portal:property_file", args=[prop.code, "guest_lockbox_code"])
        assert client.get(wrong_kind).status_code == 404

    def test_after_the_set_up_the_owner_changes_nothing(self) -> None:
        client = logged_in_owner()
        registered(client)
        prop = add_property(client)
        models.Property.objects.filter(pk=prop.pk).update(status="active")
        response = client.post(
            page(client, "property_sublease", prop.code), {"number": "X", "version": "0"}
        )
        assert response.status_code == 200
        prop.refresh_from_db()
        assert prop.sublease_declaration_number == ""


def _version(prop: models.Property) -> int:
    prop.refresh_from_db()
    return prop.version


def _admin_property_form(prop: models.Property, **overrides: Any) -> dict[str, Any]:
    """The admin's property form as the change page posts it, unchanged but for `overrides`."""
    data: dict[str, Any] = {
        "owner": str(prop.owner_id),
        "code": prop.code,
        "name": prop.name,
        "address": prop.address,
        "lat": str(prop.lat or ""),
        "lng": str(prop.lng or ""),
        "default_check_in_time": prop.default_check_in_time.strftime("%H:%M"),
        "default_check_out_time": prop.default_check_out_time.strftime("%H:%M"),
        "linen_par_level": str(prop.linen_par_level),
        "directions_el": prop.directions_el,
        "directions_en": prop.directions_en,
        "map_url": prop.map_url,
        "amenities_included_text": "\n".join(prop.amenities_included),
        "amenities_not_included_text": "\n".join(prop.amenities_not_included),
        "version": str(prop.version),
    }
    data.update(overrides)
    return data
