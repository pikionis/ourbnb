"""The Owner aggregate and the bank-account verification of DOMAIN §5."""

import pytest

from kospm.properties.domain.defaults import BankVerificationPolicy
from kospm.properties.domain.errors import (
    BankAccountAlreadyVerified,
    BankVerificationNotStarted,
    InvalidValue,
)
from kospm.properties.domain.events import BankAccountVerified, OwnerRegistered
from kospm.properties.domain.owner import BankAccountStatus, Owner
from kospm.properties.domain.value_objects import Afm, Email, Iban
from kospm.shared.domain import new_id
from tests.unit.properties.builders import OTHER_VALID_IBAN, VALID_AFM, VALID_IBAN, owner

POLICY = BankVerificationPolicy(max_attempts=3)


def status_of(subject: Owner) -> BankAccountStatus:
    """Read the status afresh (mypy keeps narrowing an attribute across method calls)."""
    return subject.bank_account.status


def pending_owner(code: str = "123456") -> Owner:
    registered = owner()
    registered.start_bank_verification(code)
    return registered


class TestRegistration:
    def test_registers_with_an_unverified_bank_account(self) -> None:
        owner_id = new_id()
        registered = Owner.register(
            owner_id=owner_id,
            name="Μαρία Παπαδοπούλου",
            email=Email("maria@example.com"),
            phone="+30 6900000000",
            afm=Afm(VALID_AFM),
            iban=Iban(VALID_IBAN),
        )
        assert registered.events == [OwnerRegistered(owner_id=owner_id)]
        assert registered.bank_account.status is BankAccountStatus.UNVERIFIED
        assert registered.bank_account_verified is False
        assert registered.show_on_website is False
        assert registered.website_consent_requested is False

    @pytest.mark.parametrize(("name", "phone"), [("", "+30 690"), ("Μαρία", " ")])
    def test_needs_a_name_and_a_phone(self, name: str, phone: str) -> None:
        with pytest.raises(InvalidValue):
            Owner.register(
                owner_id=new_id(),
                name=name,
                email=Email("maria@example.com"),
                phone=phone,
                afm=Afm(VALID_AFM),
                iban=Iban(VALID_IBAN),
            )


class TestDetails:
    def test_contact_details_can_change(self) -> None:
        subject = owner()
        subject.update_details(
            name="Μαρία Π.", email=Email("m.p@example.com"), phone="+30 6911111111"
        )
        assert (subject.name, subject.email, subject.phone) == (
            "Μαρία Π.",
            Email("m.p@example.com"),
            "+30 6911111111",
        )

    def test_a_new_iban_must_be_verified_again(self) -> None:
        subject = pending_owner("123456")
        subject.confirm_bank_account("123456", POLICY)
        subject.change_iban(Iban(OTHER_VALID_IBAN))
        assert subject.bank_account.iban == Iban(OTHER_VALID_IBAN)
        assert subject.bank_account.status is BankAccountStatus.UNVERIFIED

    def test_the_same_iban_keeps_the_verification(self) -> None:
        subject = pending_owner("123456")
        subject.confirm_bank_account("123456", POLICY)
        subject.change_iban(Iban(VALID_IBAN.lower()))
        assert subject.bank_account_verified is True

    def test_website_consent_is_requested_once(self) -> None:
        subject = owner()
        assert subject.request_website_consent() is True
        assert subject.request_website_consent() is False
        assert subject.website_consent_requested is True
        assert subject.show_on_website is False


class TestBankAccountVerification:
    def test_starting_sends_the_account_to_pending_with_the_code(self) -> None:
        subject = pending_owner("123456")
        assert subject.bank_account.status is BankAccountStatus.PENDING
        assert subject.bank_account.verification_code == "123456"
        assert "123456" not in repr(subject.bank_account)

    @pytest.mark.parametrize("code", ["", "12345", "1234567", "12345a"])
    def test_the_code_has_six_digits(self, code: str) -> None:
        with pytest.raises(InvalidValue):
            owner().start_bank_verification(code)

    def test_the_right_code_verifies_the_account(self) -> None:
        subject = pending_owner("123456")
        outcome = subject.confirm_bank_account("123456", POLICY)
        assert outcome.verified is True
        assert subject.bank_account.status is BankAccountStatus.VERIFIED
        assert subject.bank_account.verification_code == ""
        assert subject.events == [BankAccountVerified(owner_id=subject.id)]

    def test_wrong_codes_count_down_and_the_last_one_starts_over(self) -> None:
        subject = pending_owner("123456")
        first = subject.confirm_bank_account("000000", POLICY)
        second = subject.confirm_bank_account("000000", POLICY)
        assert (first.verified, first.attempts_left) == (False, 2)
        assert (second.verified, second.attempts_left) == (False, 1)
        assert status_of(subject) is BankAccountStatus.PENDING

        last = subject.confirm_bank_account("000000", POLICY)
        assert (last.verified, last.attempts_left) == (False, 0)
        assert status_of(subject) is BankAccountStatus.UNVERIFIED
        assert subject.bank_account.verification_code == ""
        assert subject.events == []

    def test_after_running_out_of_attempts_the_old_code_no_longer_works(self) -> None:
        subject = pending_owner("123456")
        for _ in range(3):
            subject.confirm_bank_account("000000", POLICY)
        with pytest.raises(BankVerificationNotStarted):
            subject.confirm_bank_account("123456", POLICY)

    def test_a_new_transfer_restarts_the_count(self) -> None:
        subject = pending_owner("123456")
        subject.confirm_bank_account("000000", POLICY)
        subject.start_bank_verification("654321")
        assert subject.confirm_bank_account("000000", POLICY).attempts_left == 2

    def test_confirming_needs_a_transfer_first(self) -> None:
        with pytest.raises(BankVerificationNotStarted):
            owner().confirm_bank_account("123456", POLICY)

    def test_a_verified_account_is_not_verified_again(self) -> None:
        subject = pending_owner("123456")
        subject.confirm_bank_account("123456", POLICY)
        with pytest.raises(BankAccountAlreadyVerified):
            subject.start_bank_verification("654321")

    def test_the_policy_needs_at_least_one_attempt(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            BankVerificationPolicy(max_attempts=0)


def test_a_new_iban_cancels_a_pending_transfer() -> None:
    subject = pending_owner("123456")
    subject.change_iban(Iban(OTHER_VALID_IBAN))
    assert subject.bank_account.status is BankAccountStatus.UNVERIFIED
    assert subject.bank_account.verification_code == ""
    with pytest.raises(BankVerificationNotStarted):
        subject.confirm_bank_account("123456", POLICY)


def test_a_code_with_letters_is_simply_wrong() -> None:
    subject = pending_owner("123456")
    assert subject.confirm_bank_account("12345α", POLICY).verified is False
