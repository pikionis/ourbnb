"""Listing text read by the AI into a draft profile (DOMAIN §5 owner portal; §2.1, §2.4).

The AI only reads the text the owner pasted: no link is ever fetched, nothing is saved until
the owner saves the profile, and a draft never carries a key-box code.
"""

import pytest

from kospm.properties.domain.errors import InvalidValue, ListingNotRead
from kospm.properties.domain.listing import ListingDraft, ListingText, ListingTextPolicy
from kospm.properties.service_layer.listing import draft_from_listing
from tests.unit.properties.fakes import FakeListingExtractor

POLICY = ListingTextPolicy(max_characters=200)


class TestListingText:
    @pytest.mark.parametrize("text", ["", "   ", "https://www.airbnb.com/rooms/123", " www.x.gr "])
    def test_is_text_not_a_link_and_not_empty(self, text: str) -> None:
        with pytest.raises(InvalidValue) as refused:
            ListingText(text)
        assert refused.value.field == "listing_text"

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

    def test_keeps_a_bounded_number_of_amenities(self) -> None:
        draft = ListingDraft(amenities_included=tuple(f"item {n}" for n in range(100)))
        assert len(draft.amenities_included) == 60


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
