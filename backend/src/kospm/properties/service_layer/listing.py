"""A draft profile from listing text (DOMAIN §5, owner portal): a query, not a command.

Nothing is stored and no aggregate changes: the draft only fills in the profile form, and the
owner's save sends the usual UpdatePropertyProfile. The text is checked before it leaves:
never a link (DOMAIN §2.1), never longer than the policy allows.
"""

from kospm.properties.domain.errors import InvalidValue
from kospm.properties.domain.listing import ListingDraft, ListingText, ListingTextPolicy
from kospm.properties.service_layer.ports import ListingTextExtractor


def draft_from_listing(
    text: str, *, extractor: ListingTextExtractor, policy: ListingTextPolicy
) -> ListingDraft:
    listing = ListingText(text)
    if len(listing.value) > policy.max_characters:
        raise InvalidValue(
            f"listing text longer than {policy.max_characters} characters", field="listing_text"
        )
    return extractor.extract(listing)
