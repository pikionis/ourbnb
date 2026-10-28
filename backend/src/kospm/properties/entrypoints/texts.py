"""What people read about the properties domain: labels and messages, translatable (el/en).

The domain reports facts in code (enum members, exception attributes); this module turns them
into sentences for the admin. Business rules never live here.
"""

from collections.abc import Iterable

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext
from django_stubs_ext import StrOrPromise

from kospm.properties.domain.checklist import ActivationRequirement, ProfileItem
from kospm.properties.domain.errors import (
    BankAccountAlreadyVerified,
    BankVerificationNotStarted,
    ChangeThroughTheIke,
    InvalidStatusTransition,
    InvalidValue,
    ListingNotRead,
    OwnerAlreadyRegistered,
    ProfileMustStayComplete,
    PropertyCodeTaken,
    PropertyNotReadyForActivation,
    TransferNotSentYet,
    WrongVerificationCode,
)
from kospm.properties.models import PropertyStatusChoices
from kospm.shared.unit_of_work import ConcurrencyError

REQUIREMENT_LABELS: dict[ActivationRequirement, StrOrPromise] = {
    ActivationRequirement.CONTRACT_SIGNED: gettext_lazy("signed contract"),
    ActivationRequirement.SUBLEASE_DECLARATION: gettext_lazy("sublease declaration number"),
    ActivationRequirement.AMA: gettext_lazy("AMA number"),
    ActivationRequirement.PROFILE_COMPLETE: gettext_lazy("complete profile"),
    ActivationRequirement.BANK_ACCOUNT_VERIFIED: gettext_lazy("verified bank account"),
}

PROFILE_LABELS: dict[ProfileItem, StrOrPromise] = {
    ProfileItem.ADDRESS: gettext_lazy("address"),
    ProfileItem.LOCATION: gettext_lazy("coordinates"),
    ProfileItem.DIRECTIONS_EL: gettext_lazy("directions (Greek)"),
    ProfileItem.DIRECTIONS_EN: gettext_lazy("directions (English)"),
    ProfileItem.EXTERIOR_PHOTO: gettext_lazy("exterior photo"),
    ProfileItem.LOCKBOX_PHOTO: gettext_lazy("lockbox photo"),
    ProfileItem.LOCKBOX_CODE: gettext_lazy("lockbox code for guests"),
    ProfileItem.AMENITIES: gettext_lazy("at least one amenity"),
}

# What to tell the user when the domain refuses a value (InvalidValue.field). Every field the
# domain names has a message here (tests/unit/properties/test_texts.py).
INVALID_VALUE_MESSAGES: dict[str, StrOrPromise] = {
    "name": gettext_lazy("Enter a name."),
    "phone": gettext_lazy("Enter a phone number."),
    "email": gettext_lazy("Enter a valid email address."),
    "afm": gettext_lazy("Enter a valid tax number (AFM): 9 digits with a correct check digit."),
    "iban": gettext_lazy("Enter a valid IBAN."),
    "holder_name": gettext_lazy(
        "Enter the account holder's name as the bank writes it (at most 70 characters)."
    ),
    "payee_check": gettext_lazy(
        "Choose the bank's answer; only “the name almost matches” takes the bank's spelling."
    ),
    "verification_code": gettext_lazy("The verification code has 6 digits."),
    "code": gettext_lazy(
        "Use 2 to 16 characters: Latin letters or digits, in groups joined by single hyphens "
        "(e.g. KOS-A1)."
    ),
    "location": gettext_lazy(
        "Enter both coordinates: latitude from -90 to 90 and longitude from -180 to 180, "
        "with at most 6 decimals."
    ),
    "map_url": gettext_lazy("The map link must be an https:// address."),
    "ical_feeds": gettext_lazy("Calendar links must be https:// addresses, one per platform."),
    "amenities": gettext_lazy("An amenity cannot be both included and not included."),
    "linen_par_level": gettext_lazy("The linen par level is at least one set."),
    "exterior_photo": gettext_lazy("Upload a photo: JPG, PNG, WebP or HEIC."),
    "lockbox_photo": gettext_lazy("Upload a photo: JPG, PNG, WebP or HEIC."),
    "contract_document": gettext_lazy("Upload the signed contract as a PDF."),
    "contract_draft": gettext_lazy("Upload the contract to sign as a PDF."),
    "signed_at": gettext_lazy("Enter the date and time the contract was signed."),
    "commission_rate": gettext_lazy(
        "The commission is a rate from 0 to below 1 (0.15 for 15 percent), with at most 4 decimals."
    ),
    "owner_cleaning_charge": gettext_lazy(
        "The cleaning charge is an amount in euros and cents, not negative."
    ),
    "sublease_declaration_number": gettext_lazy(
        "Enter the sublease declaration number. A recorded number can be corrected, not removed."
    ),
    "ama_number": gettext_lazy(
        "Enter the AMA number. A recorded number can be corrected, not removed."
    ),
    "listing_text": gettext_lazy("Paste the text of your listing, not its link."),
}


# What the owner is told when the portal leaves a change to the IKE (ChangeThroughTheIke.item).
CHANGE_THROUGH_THE_IKE: dict[str, StrOrPromise] = {
    "bank_account": gettext_lazy(
        "Your bank account is verified: to change it, contact us. This protects your payouts."
    ),
    "email": gettext_lazy("Your email address is your login: to change it, contact us."),
    "property": gettext_lazy("This property is no longer being set up: to change it, contact us."),
}


def requirement_list(items: Iterable[ActivationRequirement]) -> str:
    return ", ".join(str(REQUIREMENT_LABELS[item]) for item in items)


def profile_list(items: Iterable[ProfileItem]) -> str:
    return ", ".join(str(PROFILE_LABELS[item]) for item in items)


def describe(error: Exception) -> str:
    """A sentence for the admin about a refused command; unknown errors keep their own text."""
    if isinstance(error, InvalidValue):
        return str(INVALID_VALUE_MESSAGES.get(error.field, error))
    if isinstance(error, PropertyNotReadyForActivation):
        return _("Cannot be activated yet. Missing: %(items)s.") % {
            "items": requirement_list(error.missing)
        }
    if isinstance(error, ProfileMustStayComplete):
        return _("A property that has worked must keep a complete profile. Missing: %(items)s.") % {
            "items": profile_list(error.gaps)
        }
    if isinstance(error, InvalidStatusTransition):
        return _("Not possible while the property is %(status)s.") % {
            "status": PropertyStatusChoices(error.status).label
        }
    if isinstance(error, OwnerAlreadyRegistered):
        if error.field == "afm":
            return _("An owner with this tax number (AFM) is already registered.")
        return _("An owner with this email is already registered.")
    if isinstance(error, PropertyCodeTaken):
        return _("The code %(code)s is already used by another property.") % {"code": error.code}
    if isinstance(error, WrongVerificationCode):
        if error.attempts_left:
            return ngettext(
                "Wrong code. %(count)d attempt left.",
                "Wrong code. %(count)d attempts left.",
                error.attempts_left,
            ) % {"count": error.attempts_left}
        return _("Wrong code. Send a new test transfer.")
    if isinstance(error, BankVerificationNotStarted):
        return _("Start the verification first: send the test transfer.")
    if isinstance(error, TransferNotSentYet):
        return _("The test transfer has not been sent yet.")
    if isinstance(error, ChangeThroughTheIke):
        return str(CHANGE_THROUGH_THE_IKE.get(error.item, error))
    if isinstance(error, BankAccountAlreadyVerified):
        return _("The bank account is already verified.")
    if isinstance(error, ListingNotRead):
        return _(
            "The assistant could not read your listing right now. Fill in the profile yourself, "
            "or try again later."
        )
    if isinstance(error, ConcurrencyError):
        return _("Someone else changed this in the meantime. Reload the page and try again.")
    return str(error)
