"""The profile form filled in from a listing draft (design brief J6).

The draft only fills what the owner has not entered yet, and every field it fills is marked
"check this"; nothing here saves anything, and no key-box code is ever filled in.
"""

from typing import Any

from kospm.properties.domain.amenities import COMMON_AMENITIES
from kospm.properties.domain.listing import ListingDraft
from kospm.properties.entrypoints.portal.forms import STANDARD_AMENITIES, fill_from_listing

EMPTY: dict[str, Any] = {
    "address": "",
    "coordinates": "",
    "map_url": "",
    "directions_el": "",
    "directions_en": "",
    "other_included": "",
    "other_not_included": "",
    "version": 3,
}


def test_the_portal_asks_about_the_common_amenities() -> None:
    assert tuple(STANDARD_AMENITIES) == COMMON_AMENITIES


def test_the_draft_fills_the_empty_fields_and_marks_them() -> None:
    draft = ListingDraft(
        address="Λάμπη, Κως",
        directions_el="Δεύτερο στενό δεξιά.",
        directions_en="Second street on the right.",
        amenities_included=("Wi-Fi", "Netflix", "Beach umbrellas"),
        amenities_not_included=("Pool",),
    )

    initial, to_check = fill_from_listing(EMPTY, draft)

    assert initial["address"] == "Λάμπη, Κως"
    assert initial["directions_el"] == "Δεύτερο στενό δεξιά."
    assert initial["directions_en"] == "Second street on the right."
    assert initial["amenity_wi_fi"] == "yes"
    assert initial["amenity_pool"] == "no"
    assert initial["other_included"] == "Netflix\nBeach umbrellas"
    assert initial["version"] == 3  # the save still checks for a change in the meantime
    assert to_check == {
        "address",
        "directions_el",
        "directions_en",
        "amenity_wi_fi",
        "amenity_pool",
        "other_included",
    }


def test_what_the_owner_entered_stays() -> None:
    entered = {
        **EMPTY,
        "address": "Ψαλίδι, Κως",
        "amenity_pool": "yes",
        "other_included": "Netflix",
    }
    draft = ListingDraft(address="Λάμπη", amenities_not_included=("Pool", "netflix"))

    initial, to_check = fill_from_listing(entered, draft)

    assert initial["address"] == "Ψαλίδι, Κως"
    assert initial["amenity_pool"] == "yes"
    assert (initial["other_included"], initial["other_not_included"]) == ("Netflix", "")
    assert to_check == set()


def test_the_common_amenities_are_recognised_however_they_are_written() -> None:
    draft = ListingDraft(amenities_included=("WiFi", "air-conditioning", "tv"))

    initial, to_check = fill_from_listing(EMPTY, draft)

    assert {name: initial[name] for name in to_check} == {
        "amenity_wi_fi": "yes",
        "amenity_air_conditioning": "yes",
        "amenity_tv": "yes",
    }
    assert initial["other_included"] == ""


def test_new_amenities_are_added_after_the_owners_own() -> None:
    entered = {**EMPTY, "other_not_included": "Ασανσέρ"}
    draft = ListingDraft(amenities_not_included=("Elevator", "Ασανσέρ", "Gym"))

    initial, to_check = fill_from_listing(entered, draft)

    assert initial["other_not_included"] == "Ασανσέρ\nElevator\nGym"
    assert to_check == {"other_not_included"}


def test_the_key_box_codes_and_the_photos_are_never_filled_in() -> None:
    initial, _ = fill_from_listing(EMPTY, ListingDraft(address="Λάμπη"))

    filled = {name for name, value in initial.items() if value}
    assert filled.isdisjoint(
        {"guest_lockbox_code", "cleaner_lockbox_code", "exterior_photo", "lockbox_photo"}
    )
