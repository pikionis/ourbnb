"""Names of what a property may still miss before it can work (DOMAIN §5, activation checklist).

Their order is the order the checklist is shown in. Entrypoints translate them for people; the
domain only reports them.
"""

from enum import StrEnum


class ActivationRequirement(StrEnum):
    """An item of the activation checklist."""

    CONTRACT_SIGNED = "contract_signed"
    SUBLEASE_DECLARATION = "sublease_declaration"
    AMA = "ama"
    PROFILE_COMPLETE = "profile_complete"
    BANK_ACCOUNT_VERIFIED = "bank_account_verified"


class ProfileItem(StrEnum):
    """A part of the property profile that must be filled in before activation."""

    ADDRESS = "address"
    LOCATION = "location"
    DIRECTIONS_EL = "directions_el"
    DIRECTIONS_EN = "directions_en"
    EXTERIOR_PHOTO = "exterior_photo"
    LOCKBOX_PHOTO = "lockbox_photo"
    LOCKBOX_CODE = "lockbox_code"
    AMENITIES = "amenities"
