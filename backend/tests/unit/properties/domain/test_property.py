"""The Property aggregate: activation checklist and state transitions (DOMAIN §5)."""

from datetime import time
from typing import Any

import pytest

from kospm.properties.domain.checklist import ActivationRequirement, ProfileItem
from kospm.properties.domain.defaults import PropertyDefaults
from kospm.properties.domain.errors import (
    InvalidStatusTransition,
    InvalidValue,
    ProfileMustStayComplete,
    PropertyNotReadyForActivation,
)
from kospm.properties.domain.events import (
    AmaAssigned,
    ContractSigned,
    PropertyActivated,
    PropertyCalendarSettingsChanged,
    PropertyDeactivated,
    PropertyOffboarded,
    PropertyProfileCompleted,
    PropertyReactivated,
    SubleaseDeclared,
)
from kospm.properties.domain.property import Property, PropertyStatus
from kospm.properties.domain.value_objects import Amenities, IcalChannel, IcalFeed, PropertyCode
from kospm.shared.domain import DomainEvent, new_id
from tests.unit.properties.builders import (
    airbnb_feed,
    complete_guide,
    complete_profile,
    new_property,
    ready_property,
    signed_contract,
)

ALL_REQUIREMENTS = [
    ActivationRequirement.CONTRACT_SIGNED,
    ActivationRequirement.SUBLEASE_DECLARATION,
    ActivationRequirement.AMA,
    ActivationRequirement.PROFILE_COMPLETE,
    ActivationRequirement.BANK_ACCOUNT_VERIFIED,
]


def active_property() -> Property:
    prop = ready_property()
    prop.activate(owner_bank_account_verified=True)
    prop.events.clear()
    return prop


def settings_announced(events: list[DomainEvent]) -> list[PropertyCalendarSettingsChanged]:
    return [event for event in events if isinstance(event, PropertyCalendarSettingsChanged)]


class TestCreation:
    def test_a_new_property_is_onboarding_with_the_configured_defaults(self) -> None:
        prop = new_property()
        assert prop.status is PropertyStatus.ONBOARDING
        assert (prop.default_check_in_time, prop.default_check_out_time) == (time(15), time(11))
        assert prop.linen_par_level == 3
        assert prop.events == []

    def test_needs_a_name(self) -> None:
        with pytest.raises(InvalidValue):
            new_property().update_profile(**complete_profile(name=" "))


class TestReservationsCopy:
    """The reservations context keeps a copy of a property's calendar settings (DOMAIN §4.1)."""

    def test_a_new_property_is_announced(self) -> None:
        prop = Property.create(
            property_id=new_id(),
            owner_id=new_id(),
            code=PropertyCode("KOS-A1"),
            name="Σπίτι Αιγαίου",
            defaults=PropertyDefaults(),
        )
        assert prop.events == [
            PropertyCalendarSettingsChanged(
                property_id=prop.id,
                code="KOS-A1",
                name="Σπίτι Αιγαίου",
                active=False,
                check_in_time=time(15),
                check_out_time=time(11),
                ical_feeds=(),
            )
        ]

    def test_new_feeds_name_or_times_are_announced(self) -> None:
        prop = new_property()
        prop.update_profile(**complete_profile(ical_feeds=(airbnb_feed(),)))
        (announced,) = settings_announced(prop.events)
        assert announced.ical_feeds == (("airbnb", airbnb_feed().url),)
        prop.events.clear()
        prop.update_profile(
            **complete_profile(ical_feeds=(airbnb_feed(),), default_check_in_time=time(14))
        )
        assert [settings.check_in_time for settings in settings_announced(prop.events)] == [
            time(14)
        ]

    def test_other_profile_changes_are_not_announced(self) -> None:
        prop = new_property()
        prop.update_profile(**complete_profile())
        prop.events.clear()
        prop.update_profile(**complete_profile(address="Ψαλίδι, Κως"))
        assert settings_announced(prop.events) == []

    def test_offboarding_a_property_never_activated_changes_nothing_for_reservations(
        self,
    ) -> None:
        prop = new_property()
        prop.offboard()
        assert settings_announced(prop.events) == []


class TestActivationChecklist:
    def test_a_new_property_misses_every_item(self) -> None:
        prop = new_property()
        assert prop.missing_for_activation(owner_bank_account_verified=False) == ALL_REQUIREMENTS

    def test_activation_fails_listing_each_missing_item(self) -> None:
        prop = new_property()
        with pytest.raises(PropertyNotReadyForActivation) as refused:
            prop.activate(owner_bank_account_verified=False)
        assert list(refused.value.missing) == ALL_REQUIREMENTS
        assert prop.status is PropertyStatus.ONBOARDING
        assert prop.events == []

    @pytest.mark.parametrize("left_out", ALL_REQUIREMENTS)
    def test_reports_exactly_the_item_left_out(self, left_out: ActivationRequirement) -> None:
        prop = new_property()
        if left_out is not ActivationRequirement.PROFILE_COMPLETE:
            prop.update_profile(**complete_profile())
        if left_out is not ActivationRequirement.CONTRACT_SIGNED:
            prop.sign_contract(signed_contract())
        if left_out is not ActivationRequirement.SUBLEASE_DECLARATION:
            prop.record_sublease_declaration("ΔΥ-2026-000123")
        if left_out is not ActivationRequirement.AMA:
            prop.assign_ama("00001234567")
        bank_verified = left_out is not ActivationRequirement.BANK_ACCOUNT_VERIFIED

        with pytest.raises(PropertyNotReadyForActivation) as refused:
            prop.activate(owner_bank_account_verified=bank_verified)
        assert list(refused.value.missing) == [left_out]

    def test_activation_succeeds_when_everything_is_in_place(self) -> None:
        prop = ready_property()
        prop.activate(owner_bank_account_verified=True)
        assert prop.status is PropertyStatus.ACTIVE
        assert prop.events[0] == PropertyActivated(
            property_id=prop.id, owner_id=prop.owner_id, code=prop.code.value
        )
        assert [settings.active for settings in settings_announced(prop.events)] == [True]

    def test_items_can_be_completed_in_any_order(self) -> None:
        prop = new_property()
        prop.assign_ama("00001234567")
        prop.sign_contract(signed_contract())
        prop.record_sublease_declaration("ΔΥ-2026-000123")
        prop.update_profile(**complete_profile())
        prop.activate(owner_bank_account_verified=True)
        assert prop.status is PropertyStatus.ACTIVE


class TestProfile:
    def test_a_new_property_has_every_profile_gap(self) -> None:
        assert new_property().profile_gaps() == list(ProfileItem)

    @pytest.mark.parametrize(
        ("change", "gap"),
        [
            ({"address": ""}, ProfileItem.ADDRESS),
            ({"location": None}, ProfileItem.LOCATION),
            ({"check_in_guide": complete_guide(directions_el="")}, ProfileItem.DIRECTIONS_EL),
            ({"check_in_guide": complete_guide(directions_en="")}, ProfileItem.DIRECTIONS_EN),
            ({"check_in_guide": complete_guide(exterior_photo="")}, ProfileItem.EXTERIOR_PHOTO),
            ({"check_in_guide": complete_guide(lockbox_photo="")}, ProfileItem.LOCKBOX_PHOTO),
            ({"check_in_guide": complete_guide(guest_lockbox_code="")}, ProfileItem.LOCKBOX_CODE),
            ({"amenities": Amenities(not_included=("Πισίνα",))}, ProfileItem.AMENITIES),
        ],
    )
    def test_reports_each_gap(self, change: dict[str, Any], gap: ProfileItem) -> None:
        prop = new_property()
        prop.update_profile(**complete_profile(**change))
        assert prop.profile_gaps() == [gap]

    def test_completing_the_profile_is_announced_once(self) -> None:
        prop = new_property()

        def completed() -> list[DomainEvent]:
            return [e for e in prop.events if isinstance(e, PropertyProfileCompleted)]

        prop.update_profile(**complete_profile(address=""))
        assert completed() == []
        prop.update_profile(**complete_profile())
        assert completed() == [PropertyProfileCompleted(property_id=prop.id)]
        prop.update_profile(**complete_profile(name="Άλλο όνομα"))
        assert completed() == [PropertyProfileCompleted(property_id=prop.id)]

    def test_one_feed_per_channel(self) -> None:
        second_airbnb = IcalFeed(
            channel=IcalChannel.AIRBNB, url="https://www.airbnb.com/calendar/ical/2.ics"
        )
        with pytest.raises(InvalidValue):
            new_property().update_profile(
                **complete_profile(ical_feeds=(airbnb_feed(), second_airbnb))
            )

    def test_the_linen_par_level_is_at_least_one(self) -> None:
        with pytest.raises(InvalidValue):
            new_property().update_profile(**complete_profile(linen_par_level=0))

    def test_an_active_property_keeps_a_complete_profile(self) -> None:
        prop = active_property()
        with pytest.raises(ProfileMustStayComplete) as refused:
            prop.update_profile(**complete_profile(address=""))
        assert list(refused.value.gaps) == [ProfileItem.ADDRESS]
        assert prop.address != ""

    def test_an_active_property_can_change_within_a_complete_profile(self) -> None:
        prop = active_property()
        prop.update_profile(**complete_profile(ical_feeds=(airbnb_feed(),)))
        assert prop.ical_feeds == (airbnb_feed(),)


class TestLegalSteps:
    def test_each_step_is_announced(self) -> None:
        prop = new_property()
        prop.sign_contract(signed_contract())
        prop.record_sublease_declaration(" ΔΥ-2026-000123 ")
        prop.assign_ama("00001234567")
        assert prop.events == [
            ContractSigned(property_id=prop.id),
            SubleaseDeclared(property_id=prop.id, number="ΔΥ-2026-000123"),
            AmaAssigned(property_id=prop.id, ama_number="00001234567"),
        ]

    def test_recording_the_same_value_again_changes_nothing(self) -> None:
        prop = ready_property()
        prop.record_sublease_declaration("ΔΥ-2026-000123")
        prop.assign_ama("00001234567")
        assert prop.events == []

    @pytest.mark.parametrize("method", ["record_sublease_declaration", "assign_ama"])
    def test_numbers_cannot_be_blank(self, method: str) -> None:
        with pytest.raises(InvalidValue):
            getattr(new_property(), method)("  ")


class TestStates:
    def test_an_active_property_can_be_deactivated(self) -> None:
        prop = active_property()
        prop.deactivate()
        assert prop.status is PropertyStatus.INACTIVE
        assert prop.events[0] == PropertyDeactivated(property_id=prop.id)
        assert [settings.active for settings in settings_announced(prop.events)] == [False]

    def test_an_inactive_property_comes_back_after_the_checklist_is_checked_again(self) -> None:
        prop = active_property()
        prop.deactivate()
        with pytest.raises(PropertyNotReadyForActivation):
            prop.activate(owner_bank_account_verified=False)
        prop.activate(owner_bank_account_verified=True)
        assert prop.status is PropertyStatus.ACTIVE
        assert PropertyReactivated(property_id=prop.id) in prop.events
        assert settings_announced(prop.events)[-1].active

    @pytest.mark.parametrize("status", ["onboarding", "inactive"])
    def test_only_an_active_property_can_be_deactivated(self, status: str) -> None:
        prop = new_property() if status == "onboarding" else active_property()
        if status == "inactive":
            prop.deactivate()
        with pytest.raises(InvalidStatusTransition):
            prop.deactivate()

    def test_an_active_property_is_not_activated_twice(self) -> None:
        with pytest.raises(InvalidStatusTransition):
            active_property().activate(owner_bank_account_verified=True)

    @pytest.mark.parametrize("status", ["onboarding", "active", "inactive"])
    def test_any_property_can_be_offboarded(self, status: str) -> None:
        prop = new_property() if status == "onboarding" else active_property()
        if status == "inactive":
            prop.deactivate()
            prop.events.clear()
        prop.offboard()
        assert prop.status is PropertyStatus.OFFBOARDED
        assert prop.events[0] == PropertyOffboarded(property_id=prop.id)
        assert all(not settings.active for settings in settings_announced(prop.events))

    @pytest.mark.parametrize(
        "change",
        [
            lambda p: p.offboard(),
            lambda p: p.activate(owner_bank_account_verified=True),
            lambda p: p.deactivate(),
            lambda p: p.update_profile(**complete_profile()),
            lambda p: p.sign_contract(signed_contract()),
            lambda p: p.record_sublease_declaration("ΔΥ-2026-999999"),
            lambda p: p.assign_ama("00009999999"),
        ],
    )
    def test_offboarding_is_final(self, change: Any) -> None:
        prop = ready_property()
        prop.offboard()
        with pytest.raises(InvalidStatusTransition):
            change(prop)
        assert prop.status is PropertyStatus.OFFBOARDED


class TestInactiveProperties:
    def test_an_inactive_property_may_have_gaps_and_reactivation_checks_again(self) -> None:
        prop = active_property()
        prop.deactivate()
        prop.update_profile(**complete_profile(address=""))
        assert prop.profile_gaps() == [ProfileItem.ADDRESS]
        with pytest.raises(PropertyNotReadyForActivation) as refused:
            prop.activate(owner_bank_account_verified=True)
        assert list(refused.value.missing) == [ActivationRequirement.PROFILE_COMPLETE]
        assert prop.status is PropertyStatus.INACTIVE


def test_invalid_values_name_their_field() -> None:
    with pytest.raises(InvalidValue) as blank_ama:
        new_property().assign_ama(" ")
    with pytest.raises(InvalidValue) as par_level:
        new_property().update_profile(**complete_profile(linen_par_level=0))
    assert (blank_ama.value.field, par_level.value.field) == ("ama_number", "linen_par_level")
