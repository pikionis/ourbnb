"""The amenities every owner is asked about, as Yes / No (design brief §8).

Stored by these English names, so the list reads the same in the admin, in the owner portal
(which shows them translated) and to the AI that answers guests.
"""

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
