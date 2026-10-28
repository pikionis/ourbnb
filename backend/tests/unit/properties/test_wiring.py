"""Bootstrap turns the properties settings into configuration objects (CLAUDE.md: policies)."""

import re
from collections.abc import Callable
from datetime import time
from decimal import Decimal

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from kospm.bootstrap import (
    default_contexts,
    listing_extractor,
    listing_text_policy,
    listing_throttle,
    properties_dependencies,
)
from kospm.properties.adapters.bank_verification import ManualBankAccountVerifier
from kospm.properties.adapters.listing_extractor import (
    ClaudeListingExtractor,
    UnavailableListingExtractor,
)
from kospm.properties.domain.commands import ActivateProperty, RegisterOwner
from kospm.properties.domain.defaults import BankVerificationPolicy, PropertyDefaults
from kospm.properties.domain.listing import ListingTextPolicy
from kospm.shared.clock import SystemClock
from kospm.shared.domain import Money


def test_the_settings_become_the_defaults_and_the_policy() -> None:
    dependencies = properties_dependencies()
    assert dependencies["property_defaults"] == PropertyDefaults(
        check_in_time=time(15),
        check_out_time=time(11),
        linen_par_level=3,
        commission_rate=Decimal("0.15"),
        owner_cleaning_charge=Money("40.00"),
    )
    assert dependencies["bank_verification"] == BankVerificationPolicy(max_attempts=3)


@override_settings(
    PROPERTY_DEFAULT_CHECK_IN_TIME="16:00",
    CONTRACT_DEFAULT_COMMISSION_RATE="0.18",
    BANK_VERIFICATION_MAX_ATTEMPTS=5,
)
def test_the_business_can_change_them_without_code() -> None:
    dependencies = properties_dependencies()
    defaults = dependencies["property_defaults"]
    assert isinstance(defaults, PropertyDefaults)
    assert (defaults.check_in_time, defaults.commission_rate) == (time(16), Decimal("0.18"))
    assert dependencies["bank_verification"] == BankVerificationPolicy(max_attempts=5)


@pytest.mark.parametrize(
    "setting",
    [
        {"PROPERTY_DEFAULT_CHECK_IN_TIME": "noon"},
        {"CONTRACT_DEFAULT_COMMISSION_RATE": "15%"},
        {"CONTRACT_DEFAULT_OWNER_CLEANING_CHARGE": "forty"},
        {"BANK_VERIFICATION_MAX_ATTEMPTS": 0},
    ],
)
def test_invalid_settings_fail_at_startup(setting: dict[str, object]) -> None:
    with override_settings(**setting), pytest.raises(ImproperlyConfigured):
        properties_dependencies()


def test_the_admin_sends_the_test_transfer_by_hand_for_now() -> None:
    assert isinstance(properties_dependencies()["bank_account_verifier"], ManualBankAccountVerifier)


def test_verification_codes_have_six_digits() -> None:
    verifier = ManualBankAccountVerifier()
    codes = {verifier.new_code() for _ in range(50)}
    assert all(re.fullmatch(r"[0-9]{6}", code) for code in codes)
    assert len(codes) > 1


def test_the_production_bus_handles_the_properties_commands() -> None:
    contexts = {context.name: context for context in default_contexts(SystemClock())}
    assert {RegisterOwner, ActivateProperty} <= set(contexts["properties"].command_handlers)


KEY = "sk-ant-test-not-a-key"


def test_without_an_api_key_the_owner_fills_in_the_profile_by_hand() -> None:
    assert isinstance(listing_extractor(), UnavailableListingExtractor)


@override_settings(ANTHROPIC_API_KEY=KEY)
def test_with_an_api_key_claude_reads_the_listing() -> None:
    assert isinstance(listing_extractor(), ClaudeListingExtractor)


@override_settings(LISTING_TEXT_MAX_CHARS=5000)
def test_the_listing_text_limit_is_configuration() -> None:
    assert listing_text_policy() == ListingTextPolicy(max_characters=5000)


@pytest.mark.parametrize(
    ("build", "setting"),
    [
        (listing_extractor, {"ANTHROPIC_API_KEY": KEY, "LISTING_EXTRACTOR_EFFORT": "fast"}),
        (listing_extractor, {"ANTHROPIC_API_KEY": KEY, "LISTING_EXTRACTOR_TIMEOUT_SECONDS": 0}),
        (listing_text_policy, {"LISTING_TEXT_MAX_CHARS": 0}),
        (listing_throttle, {"LISTING_READINGS_PER_HOUR": "many"}),
    ],
)
def test_invalid_listing_settings_fail_at_startup(
    build: Callable[[], object], setting: dict[str, object]
) -> None:
    with override_settings(**setting), pytest.raises(ImproperlyConfigured):
        build()
