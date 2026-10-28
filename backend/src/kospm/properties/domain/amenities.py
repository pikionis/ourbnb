"""The amenities every owner is asked about, as Yes / No (design brief §8).

Stored by these English names, so the list reads the same in the admin, in the owner portal
(which shows them translated) and to the AI that answers guests.
"""

import re

COMMON_AMENITIES: tuple[str, ...] = (
    "Wi-Fi",
    "Air conditioning",
    "Heating",
    "Kitchen",
    "Washing machine",
    "Dishwasher",
    "Free parking",
    "Pool",
    "Sea view",
    "Balcony or terrace",
    "Baby cot",
    "Hair dryer",
    "Iron",
    "TV",
)


def amenity_key(name: str) -> str:
    """Wi-Fi, WiFi and wifi are one amenity: its letters and digits, of any script and case."""
    return re.sub(r"[\W_]+", "", name.casefold())


_COMMON_BY_KEY = {amenity_key(name): name for name in COMMON_AMENITIES}


def common_amenity(name: str) -> str | None:
    """The common amenity `name` means, however it is written ("Hairdryer" is "Hair dryer")."""
    return _COMMON_BY_KEY.get(amenity_key(name))
