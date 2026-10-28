"""Listing text read by the AI into a draft profile (DOMAIN §5 owner portal; §2.1, §2.4).

The AI only reads the text the owner pasted: no link is ever fetched, nothing is saved until
the owner saves the profile, and a draft never carries a key-box code.
"""

import pytest

from kospm.properties.domain.errors import InvalidValue, ListingNotRead
from kospm.properties.domain.listing import (
    ListingDraft,
    ListingText,
    ListingTextPolicy,
    ProfileFields,
)
from kospm.properties.service_layer.listing import draft_from_listing
from tests.unit.properties.fakes import FakeListingExtractor

POLICY = ListingTextPolicy(max_characters=200)


class TestListingText:
    @pytest.mark.parametrize("text", ["", "   ", "https://www.airbnb.com/rooms/123", " www.x.gr "])
    def test_is_text_not_a_link_and_not_empty(self, text: str) -> None:
        with pytest.raises(InvalidValue) as refused:
            ListingText(text)
        assert refused.value.field == "listing_text"

    def test_the_text_stays_out_of_its_repr(self) -> None:
        assert "4711" not in repr(ListingText("A house in Lambi. The key box code is 4711."))

    def test_a_text_that_mentions_a_link_is_still_text(self) -> None:
        text = "Σπίτι 2 υπνοδωματίων με θέα. Δείτε επίσης https://example.com/house"
        assert ListingText(text).value == text


class TestListingDraft:
    def test_is_trimmed_and_capped(self) -> None:
        draft = ListingDraft(
            address="  Λάμπη  ",
            directions_el="α" * 5000,
            amenities_included=(" Wi-Fi ", "Wi-Fi", "", "Pool"),
        )
        assert draft.address == "Λάμπη"
        assert len(draft.directions_el) == 4000
        assert draft.amenities_included == ("Wi-Fi", "Pool")

    def test_an_amenity_said_both_ways_is_left_to_the_owner(self) -> None:
        draft = ListingDraft(amenities_included=("Pool", "TV"), amenities_not_included=("Pool",))
        assert (draft.amenities_included, draft.amenities_not_included) == (("TV",), ())

    def test_an_amenity_said_both_ways_however_written_is_left_to_the_owner(self) -> None:
        draft = ListingDraft(amenities_included=("WiFi", "TV"), amenities_not_included=("Wi-Fi",))
        assert (draft.amenities_included, draft.amenities_not_included) == (("TV",), ())

    def test_one_amenity_however_written_is_kept_once(self) -> None:
        draft = ListingDraft(amenities_included=("Wi-Fi", "WiFi", "wi fi", "—"))
        assert draft.amenities_included == ("Wi-Fi",)

    def test_keeps_a_bounded_number_of_amenities(self) -> None:
        draft = ListingDraft(amenities_included=tuple(f"item {n}" for n in range(100)))
        assert len(draft.amenities_included) == 60


class TestFillingTheGaps:
    """The draft fills only what the owner left empty (DOMAIN §5, validation details)."""

    def test_what_the_owner_entered_stays(self) -> None:
        current = ProfileFields(address="Ψαλίδι, Κως", amenities_included=("Pool",))
        draft = ListingDraft(
            address="Λάμπη",
            directions_en="Second street on the right.",
            amenities_included=("TV",),
            amenities_not_included=("pool", "Gym"),
        )

        filled = draft.fill_gaps(current)

        assert filled.fields == ProfileFields(
            address="Ψαλίδι, Κως",
            directions_en="Second street on the right.",
            amenities_included=("Pool", "TV"),
            amenities_not_included=("Gym",),
        )
        assert filled.texts == {"directions_en"}
        assert filled.amenities == {"TV", "Gym"}

    def test_a_common_amenity_takes_its_common_name(self) -> None:
        filled = ListingDraft(amenities_included=("wifi", "Hairdryer")).fill_gaps(ProfileFields())
        assert filled.fields.amenities_included == ("Wi-Fi", "Hair dryer")
        assert filled.amenities == {"Wi-Fi", "Hair dryer"}

    def test_the_owners_text_is_never_shortened(self) -> None:
        current = ProfileFields(directions_el="α" * 5000)
        filled = ListingDraft(directions_el="β").fill_gaps(current)
        assert filled.fields.directions_el == "α" * 5000
        assert filled.texts == frozenset()


class TestDraftFromListing:
    def test_the_extractor_reads_the_pasted_text(self) -> None:
        extractor = FakeListingExtractor()
        draft = draft_from_listing("Σπίτι στη Λάμπη.", extractor=extractor, policy=POLICY)
        assert draft.address == "Λάμπη, Κως"
        assert [listing.value for listing in extractor.read] == ["Σπίτι στη Λάμπη."]

    def test_a_link_is_never_sent_anywhere(self) -> None:
        extractor = FakeListingExtractor()
        with pytest.raises(InvalidValue):
            draft_from_listing("https://www.airbnb.com/rooms/1", extractor=extractor, policy=POLICY)
        assert extractor.read == []

    def test_too_long_a_text_is_refused_before_it_is_sent(self) -> None:
        extractor = FakeListingExtractor()
        with pytest.raises(InvalidValue) as refused:
            draft_from_listing("α" * 201, extractor=extractor, policy=POLICY)
        assert refused.value.field == "listing_text"
        assert extractor.read == []

    def test_the_policy_needs_a_positive_limit(self) -> None:
        with pytest.raises(ValueError, match="max_characters"):
            ListingTextPolicy(max_characters=0)

    def test_not_read_is_a_domain_answer(self) -> None:
        assert issubclass(ListingNotRead, Exception)
