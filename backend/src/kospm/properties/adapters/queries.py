"""Read side of the properties context: what a stored property still misses (CQRS-lite).

The admin list (and later the owner portal) asks the domain, not a copy of its rules: rows are
mapped to aggregates and the aggregates answer.
"""

from kospm.properties import models
from kospm.properties.adapters.repository import owner_to_domain, property_to_domain
from kospm.properties.domain.checklist import ActivationRequirement, ProfileItem


def missing_for_activation(row: models.Property) -> list[ActivationRequirement]:
    """Checklist items the property still misses (needs `owner` loaded: select_related)."""
    verified = owner_to_domain(row.owner).bank_account_verified
    return property_to_domain(row).missing_for_activation(owner_bank_account_verified=verified)


def profile_gaps(row: models.Property) -> list[ProfileItem]:
    return property_to_domain(row).profile_gaps()
