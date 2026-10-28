"""Django repositories of the properties context against PostgreSQL (Appendix D, ADR 0016)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from django.db import connection

from kospm.properties import models
from kospm.properties.adapters.unit_of_work import DjangoPropertiesUnitOfWork
from kospm.properties.domain.errors import (
    OwnerAlreadyRegistered,
    OwnerNotFound,
    PropertyCodeTaken,
    PropertyNotFound,
)
from kospm.properties.domain.owner import BankAccountStatus, Owner, PayeeCheck, PayeeCheckResult
from kospm.properties.domain.property import Property, PropertyStatus
from kospm.properties.domain.value_objects import AccountHolderName, Afm, Email, PropertyCode
from kospm.shared.clock import FixedClock
from kospm.shared.domain import Money
from kospm.shared.outbox.adapters import DjangoOutbox
from kospm.shared.unit_of_work import ConcurrencyError
from tests.unit.properties.builders import (
    OTHER_VALID_AFM,
    VALID_AFM,
    airbnb_feed,
    complete_profile,
    owner,
    ready_property,
    signed_contract,
)

pytestmark = pytest.mark.django_db


def new_uow() -> DjangoPropertiesUnitOfWork:
    return DjangoPropertiesUnitOfWork(
        outbox=DjangoOutbox(FixedClock(datetime(2026, 10, 23, tzinfo=UTC)))
    )


def stored_owner() -> Owner:
    subject = owner()
    uow = new_uow()
    with uow:
        uow.owners.add(subject)
        uow.commit()
    return subject


def stored_property(owner_id: UUID, code: str = "KOS-A1") -> Property:
    prop = ready_property(owner_id=owner_id, code=code)
    prop.update_profile(**complete_profile(ical_feeds=(airbnb_feed(),)))
    uow = new_uow()
    with uow:
        uow.properties.add(prop)
        uow.commit()
    return prop


def version_of(model: type[models.Owner] | type[models.Property], pk: UUID) -> int:
    return model.objects.values_list("version", flat=True).get(pk=pk)


class TestOwnerRepository:
    def test_round_trip(self) -> None:
        saved = stored_owner()
        uow = new_uow()
        with uow:
            loaded = uow.owners.get(saved.id)
        assert (loaded.name, loaded.email, loaded.phone, loaded.afm) == (
            saved.name,
            saved.email,
            saved.phone,
            saved.afm,
        )
        assert loaded.bank_account == saved.bank_account
        assert loaded.bank_account.status is BankAccountStatus.UNVERIFIED

    def test_finds_by_afm_and_email(self) -> None:
        saved = stored_owner()
        uow = new_uow()
        with uow:
            assert uow.owners.find_by_afm(Afm(VALID_AFM)) is uow.owners.get(saved.id)
            assert uow.owners.find_by_email(Email("MARIA@example.com")) is not None
            assert uow.owners.find_by_email(Email("nobody@example.com")) is None

    def test_a_pending_verification_survives_a_reload(self) -> None:
        saved = stored_owner()
        uow = new_uow()
        with uow:
            uow.owners.get(saved.id).start_bank_verification("123456")
            uow.commit()
        with uow:
            account = uow.owners.get(saved.id).bank_account
        assert (account.status, account.verification_code) == (BankAccountStatus.PENDING, "123456")

    def test_a_sent_transfer_keeps_the_banks_spelling_and_check(self) -> None:
        saved = stored_owner()
        check = PayeeCheck(PayeeCheckResult.CLOSE_MATCH, AccountHolderName("PAPADOPOULOU M"))
        uow = new_uow()
        with uow:
            subject = uow.owners.get(saved.id)
            subject.start_bank_verification("123456")
            subject.record_test_transfer(check)
            uow.commit()
        with uow:
            account = uow.owners.get(saved.id).bank_account
        assert (account.status, account.holder_name, account.payee_check) == (
            BankAccountStatus.TRANSFER_SENT,
            AccountHolderName("PAPADOPOULOU M"),
            check,
        )
        assert account.verification_code == "123456"

    def test_unknown_owner(self) -> None:
        uow = new_uow()
        with uow, pytest.raises(OwnerNotFound):
            uow.owners.get(UUID(int=1))


class TestPropertyRepository:
    def test_round_trip_of_the_whole_aggregate(self) -> None:
        saved = stored_property(stored_owner().id)
        uow = new_uow()
        with uow:
            loaded = uow.properties.get(saved.id)
        assert loaded.code == PropertyCode("KOS-A1")
        assert loaded.status is PropertyStatus.ONBOARDING
        assert loaded.location == saved.location
        assert loaded.check_in_guide == saved.check_in_guide
        assert loaded.amenities == saved.amenities
        assert loaded.ical_feeds == (airbnb_feed(),)
        assert loaded.contract == signed_contract()
        assert loaded.contract is not None
        assert loaded.contract.owner_cleaning_charge == Money("40.00")
        assert (loaded.sublease_declaration_number, loaded.ama_number) == (
            saved.sublease_declaration_number,
            saved.ama_number,
        )
        assert loaded.missing_for_activation(owner_bank_account_verified=True) == []

    def test_lockbox_codes_are_encrypted_at_rest(self) -> None:
        saved = stored_property(stored_owner().id)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT guest_lockbox_code FROM properties_property WHERE id = %s", [saved.id]
            )
            (raw,) = cursor.fetchone()
        assert raw
        assert "4711" not in raw

    def test_finds_by_code_and_lists_by_owner(self) -> None:
        owner_id = stored_owner().id
        first = stored_property(owner_id, "KOS-A1")
        second = stored_property(owner_id, "KOS-A2")
        uow = new_uow()
        with uow:
            assert uow.properties.find_by_code(PropertyCode("kos-a2")) is uow.properties.get(
                second.id
            )
            assert uow.properties.find_by_code(PropertyCode("KOS-Z9")) is None
            owned = uow.properties.list_by_owner(owner_id)
        assert {p.id for p in owned} == {first.id, second.id}

    def test_unknown_property(self) -> None:
        uow = new_uow()
        with uow, pytest.raises(PropertyNotFound):
            uow.properties.get(UUID(int=1))


class TestOptimisticConcurrency:
    def test_a_change_bumps_the_version(self) -> None:
        saved = stored_property(stored_owner().id)
        uow = new_uow()
        with uow:
            uow.properties.get(saved.id).assign_ama("00009999999")
            uow.commit()
        assert version_of(models.Property, saved.id) == 1

    def test_a_unit_that_only_reads_writes_nothing(self) -> None:
        saved_owner = stored_owner()
        saved = stored_property(saved_owner.id)
        uow = new_uow()
        with uow:
            prop = uow.properties.get(saved.id)
            uow.owners.get(prop.owner_id)
            uow.commit()
        assert version_of(models.Property, saved.id) == 0
        assert version_of(models.Owner, saved_owner.id) == 0

    def test_a_concurrent_change_is_refused_and_rolled_back(self) -> None:
        saved = stored_property(stored_owner().id)
        uow = new_uow()
        with uow:
            uow.properties.get(saved.id).assign_ama("00009999999")
            # Another unit changes the same property in the meantime. (Here it runs inside this
            # unit's savepoint, so the rollback undoes it too; what matters is the refusal.)
            models.Property.objects.filter(pk=saved.id).update(linen_par_level=4, version=1)
            with pytest.raises(ConcurrencyError):
                uow.commit()
        assert models.Property.objects.get(pk=saved.id).ama_number == saved.ama_number

    def test_a_property_added_and_changed_in_one_unit_is_written_once_per_change(self) -> None:
        owner_id = stored_owner().id
        prop = ready_property(owner_id=owner_id)
        uow = new_uow()
        with uow:
            uow.properties.add(prop)
            prop.activate(owner_bank_account_verified=True)
            uow.commit()
        row = models.Property.objects.get(pk=prop.id)
        assert (row.status, row.version) == (PropertyStatus.ACTIVE.value, 1)

    def test_a_stale_form_is_refused_before_anything_changes(self) -> None:
        saved = stored_property(stored_owner().id)
        models.Property.objects.filter(pk=saved.id).update(version=3)  # saved by someone else
        uow = new_uow()
        with uow, pytest.raises(ConcurrencyError):
            uow.properties.get(saved.id, expected_version=2)
        with uow:
            assert uow.properties.get(saved.id, expected_version=3).id == saved.id

    def test_a_stale_owner_form_is_refused_too(self) -> None:
        saved = stored_owner()
        uow = new_uow()
        with uow, pytest.raises(ConcurrencyError):
            uow.owners.get(saved.id, expected_version=1)

    def test_a_reader_is_not_refused_when_someone_else_writes(self) -> None:
        saved = stored_property(stored_owner().id)
        uow = new_uow()
        with uow:
            uow.properties.get(saved.id)
            models.Property.objects.filter(pk=saved.id).update(linen_par_level=4, version=1)
            uow.commit()  # read only: nothing to write back, so nothing to refuse
        row = models.Property.objects.get(pk=saved.id)
        assert (row.linen_par_level, row.version) == (4, 1)

    def test_one_aggregate_loaded_twice_is_written_once(self) -> None:
        saved = stored_property(stored_owner().id)
        uow = new_uow()
        with uow:
            first = uow.properties.get(saved.id)
            again = uow.properties.find_by_code(saved.code)
            assert again is first  # identity map
            first.assign_ama("00009999999")
            uow.commit()
        assert version_of(models.Property, saved.id) == 1

    def test_a_refused_unit_announces_nothing(self) -> None:
        saved = stored_property(stored_owner().id)
        uow = new_uow()
        with uow:
            uow.properties.get(saved.id).assign_ama("00009999999")  # raises AmaAssigned
            models.Property.objects.filter(pk=saved.id).update(version=1)
            with pytest.raises(ConcurrencyError):
                uow.commit()
        assert list(uow.collect_new_events()) == []

    def test_what_a_form_was_shown_is_confirmed_at_commit_even_if_unchanged(self) -> None:
        saved = stored_property(stored_owner().id)
        uow = new_uow()
        with uow:
            uow.properties.get(saved.id, expected_version=0)  # a save's first command: no change
            # Someone else saves between the check and the commit.
            models.Property.objects.filter(pk=saved.id).update(ama_number="0002222", version=1)
            with pytest.raises(ConcurrencyError):
                uow.commit()

    def test_the_confirmation_does_not_bump_the_version(self) -> None:
        saved = stored_property(stored_owner().id)
        uow = new_uow()
        with uow:
            uow.properties.get(saved.id, expected_version=0)
            uow.commit()
        assert version_of(models.Property, saved.id) == 0


class TestUniqueConstraints:
    """A race lost between a handler's check and its insert reads as the business rule."""

    def test_the_same_afm(self) -> None:
        stored_owner()
        uow = new_uow()
        with uow, pytest.raises(OwnerAlreadyRegistered) as refused:
            uow.owners.add(owner(email="other@example.com"))
        assert refused.value.field == "afm"

    def test_the_same_email_even_one_containing_afm(self) -> None:
        uow = new_uow()
        with uow:
            uow.owners.add(owner(email="kafm@example.com"))
            uow.commit()
        with uow, pytest.raises(OwnerAlreadyRegistered) as refused:
            uow.owners.add(owner(email="kafm@example.com", afm=OTHER_VALID_AFM))
        assert refused.value.field == "email"  # read from the constraint, not the message

    def test_the_same_property_code(self) -> None:
        owner_id = stored_owner().id
        stored_property(owner_id, "KOS-A1")
        uow = new_uow()
        with uow, pytest.raises(PropertyCodeTaken):
            uow.properties.add(ready_property(owner_id=owner_id, code="KOS-A1"))

    def test_the_same_email_on_an_update(self) -> None:
        stored_owner()
        nikos = owner(email="nikos@example.com", afm=OTHER_VALID_AFM)
        uow = new_uow()
        with uow:
            uow.owners.add(nikos)
            uow.commit()
        with uow:
            uow.owners.get(nikos.id).update_details(
                name="Νίκος", email=Email("maria@example.com"), phone="+30 6900000001"
            )
            with pytest.raises(OwnerAlreadyRegistered) as refused:
                uow.commit()
        assert refused.value.field == "email"

    def test_the_unit_stays_usable_after_the_refusal(self) -> None:
        stored_owner()
        uow = new_uow()
        with uow:
            with pytest.raises(OwnerAlreadyRegistered):
                uow.owners.add(owner(email="other@example.com"))
            other = owner(email="nikos@example.com", afm=OTHER_VALID_AFM)
            uow.owners.add(other)
            uow.commit()
        assert models.Owner.objects.filter(pk=other.id).exists()


def test_model_choices_match_the_domain() -> None:
    assert set(models.PropertyStatusChoices.values) == {status.value for status in PropertyStatus}
    assert set(models.BankAccountStatusChoices.values) == {
        status.value for status in BankAccountStatus
    }
    assert set(models.PayeeCheckChoices.values) == {result.value for result in PayeeCheckResult}


def test_contract_terms_keep_their_precision() -> None:
    saved = stored_property(stored_owner().id)
    row = models.Property.objects.get(pk=saved.id)
    assert row.contract_commission_rate == Decimal("0.1500")
    assert row.contract_owner_cleaning_charge == Decimal("40.00")
