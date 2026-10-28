"""The Owner aggregate and the bank-account verification of DOMAIN §5 (ADR 0018)."""

import pytest

from kospm.properties.domain.defaults import BankVerificationPolicy
from kospm.properties.domain.errors import (
    BankAccountAlreadyVerified,
    BankVerificationNotStarted,
    ChangeThroughTheIke,
    InvalidValue,
    TransferNotSentYet,
)
from kospm.properties.domain.events import (
    BankAccountVerified,
    OwnerEmailChanged,
    OwnerRegistered,
)
from kospm.properties.domain.owner import (
    BankAccountStatus,
    Owner,
    PayeeCheck,
    PayeeCheckResult,
)
from kospm.properties.domain.value_objects import AccountHolderName, Afm, Email, Iban
from kospm.shared.domain import new_id
from tests.unit.properties.builders import (
    HOLDER,
    OTHER_VALID_IBAN,
    VALID_AFM,
    VALID_IBAN,
    owner,
)

POLICY = BankVerificationPolicy(max_attempts=3)
MATCH = PayeeCheck(PayeeCheckResult.MATCH)


def status_of(subject: Owner) -> BankAccountStatus:
    """Read the status afresh (mypy keeps narrowing an attribute across method calls)."""
    return subject.bank_account.status


def pending_owner(code: str = "123456") -> Owner:
    """The IKE has to send the test transfer with `code`."""
    registered = owner()
    registered.start_bank_verification(code)
    return registered


def sent_owner(code: str = "123456", check: PayeeCheck = MATCH) -> Owner:
    """The test transfer with `code` was sent: the owner has to enter the code."""
    subject = pending_owner(code)
    subject.record_test_transfer(check)
    return subject


def verified_owner() -> Owner:
    subject = sent_owner("123456")
    subject.confirm_bank_account("123456", POLICY)
    subject.events.clear()
    return subject


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
            holder_name=AccountHolderName("PAPADOPOULOU MARIA"),
        )
        assert registered.events == [OwnerRegistered(owner_id=owner_id)]
        assert registered.bank_account.status is BankAccountStatus.UNVERIFIED
        assert registered.bank_account.holder_name == AccountHolderName("PAPADOPOULOU MARIA")
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
                holder_name=HOLDER,
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

    def test_a_new_email_is_announced_so_an_unused_invitation_follows_it(self) -> None:
        subject = owner(email="maria@example.com")
        new = Email("m.p@example.com")
        subject.update_details(name="Μαρία", email=new, phone="+30 6900000000")
        subject.update_details(name="Μαρία Π.", email=new, phone="+30 6900000000")
        assert subject.events == [OwnerEmailChanged(owner_id=subject.id, email="m.p@example.com")]

    def test_website_consent_is_requested_once(self) -> None:
        subject = owner()
        assert subject.request_website_consent() is True
        assert subject.request_website_consent() is False
        assert subject.website_consent_requested is True
        assert subject.show_on_website is False


class TestChangingTheBankAccount:
    def test_a_new_iban_must_be_verified_again(self) -> None:
        subject = verified_owner()
        subject.change_bank_account(Iban(OTHER_VALID_IBAN), HOLDER)
        assert subject.bank_account.iban == Iban(OTHER_VALID_IBAN)
        assert subject.bank_account.status is BankAccountStatus.UNVERIFIED

    def test_a_new_holder_name_must_be_verified_again(self) -> None:
        subject = verified_owner()
        subject.change_bank_account(Iban(VALID_IBAN), AccountHolderName("MARIA P."))
        assert subject.bank_account.status is BankAccountStatus.UNVERIFIED

    def test_the_same_account_keeps_the_verification(self) -> None:
        subject = verified_owner()
        subject.change_bank_account(Iban(VALID_IBAN.lower()), AccountHolderName(f" {HOLDER} "))
        assert subject.bank_account_verified is True

    def test_a_new_iban_cancels_a_transfer_on_its_way(self) -> None:
        subject = sent_owner("123456")
        subject.change_bank_account(Iban(OTHER_VALID_IBAN), HOLDER)
        assert subject.bank_account.status is BankAccountStatus.UNVERIFIED
        assert subject.bank_account.verification_code == ""
        with pytest.raises(BankVerificationNotStarted):
            subject.confirm_bank_account("123456", POLICY)

    def test_the_owner_changes_it_only_until_it_is_verified(self) -> None:
        subject = sent_owner()
        subject.change_own_bank_account(Iban(OTHER_VALID_IBAN), HOLDER)
        assert subject.bank_account.iban == Iban(OTHER_VALID_IBAN)

        verified = verified_owner()
        with pytest.raises(ChangeThroughTheIke) as refused:
            verified.change_own_bank_account(Iban(OTHER_VALID_IBAN), HOLDER)
        assert refused.value.item == "bank_account"
        assert verified.bank_account_verified is True

    def test_the_owner_may_resend_the_same_verified_account(self) -> None:
        subject = verified_owner()
        subject.change_own_bank_account(Iban(VALID_IBAN), HOLDER)
        assert subject.bank_account_verified is True


class TestTestTransfer:
    """The IKE sends €0.01 with the code and records its bank's payee check (ADR 0018)."""

    def test_starting_waits_for_the_ike_to_send_the_transfer_with_the_code(self) -> None:
        subject = pending_owner("123456")
        assert subject.bank_account.status is BankAccountStatus.PENDING
        assert subject.bank_account.verification_code == "123456"
        assert "123456" not in repr(subject.bank_account)

    @pytest.mark.parametrize("code", ["", "12345", "1234567", "12345a"])
    def test_the_code_has_six_digits(self, code: str) -> None:
        with pytest.raises(InvalidValue):
            owner().start_bank_verification(code)

    @pytest.mark.parametrize("result", [PayeeCheckResult.MATCH, PayeeCheckResult.NOT_POSSIBLE])
    def test_a_match_or_no_check_means_the_transfer_was_sent(
        self, result: PayeeCheckResult
    ) -> None:
        subject = sent_owner("123456", PayeeCheck(result))
        assert subject.bank_account.status is BankAccountStatus.TRANSFER_SENT
        assert subject.bank_account.payee_check == PayeeCheck(result)
        assert subject.bank_account.holder_name == HOLDER

    def test_a_close_match_takes_the_banks_spelling_of_the_name(self) -> None:
        bank_name = AccountHolderName("PAPADOPOULOU MARIA K")
        subject = sent_owner("123456", PayeeCheck(PayeeCheckResult.CLOSE_MATCH, bank_name))
        assert subject.bank_account.status is BankAccountStatus.TRANSFER_SENT
        assert subject.bank_account.holder_name == bank_name

    def test_no_match_sends_nothing_and_says_why(self) -> None:
        subject = sent_owner("123456", PayeeCheck(PayeeCheckResult.NO_MATCH))
        assert subject.bank_account.status is BankAccountStatus.UNVERIFIED
        assert subject.bank_account.payee_check == PayeeCheck(PayeeCheckResult.NO_MATCH)
        assert subject.bank_account.verification_code == ""
        with pytest.raises(BankVerificationNotStarted):
            subject.confirm_bank_account("123456", POLICY)

    def test_a_transfer_is_recorded_only_while_one_is_waiting_to_be_sent(self) -> None:
        with pytest.raises(BankVerificationNotStarted):
            owner().record_test_transfer(MATCH)
        with pytest.raises(BankVerificationNotStarted):
            sent_owner().record_test_transfer(MATCH)

    def test_the_owner_starts_it_for_an_unverified_account(self) -> None:
        subject = owner()
        subject.start_own_bank_verification("123456")
        assert status_of(subject) is BankAccountStatus.PENDING

    def test_a_verification_under_way_is_restarted_by_the_ike_only(self) -> None:
        # Restarting cancels the transfer already sent: the owner asks the IKE (DOMAIN §5).
        for subject in (pending_owner(), sent_owner()):
            with pytest.raises(ChangeThroughTheIke) as refused:
                subject.start_own_bank_verification("654321")
            assert refused.value.item == "bank_verification"
            assert subject.bank_account.verification_code == "123456"
        restarted = sent_owner()
        restarted.start_bank_verification("654321")
        assert status_of(restarted) is BankAccountStatus.PENDING

    def test_starting_again_forgets_the_previous_check(self) -> None:
        subject = sent_owner("123456", PayeeCheck(PayeeCheckResult.NO_MATCH))
        subject.start_bank_verification("654321")
        assert subject.bank_account.payee_check is None

    @pytest.mark.parametrize(
        ("result", "bank_name"),
        [
            (PayeeCheckResult.CLOSE_MATCH, None),
            (PayeeCheckResult.MATCH, AccountHolderName("X")),
            (PayeeCheckResult.NO_MATCH, AccountHolderName("X")),
        ],
    )
    def test_only_a_close_match_comes_with_the_banks_name(
        self, result: PayeeCheckResult, bank_name: AccountHolderName | None
    ) -> None:
        with pytest.raises(InvalidValue) as refused:
            PayeeCheck(result, bank_name)
        assert refused.value.field == "payee_check"


class TestCode:
    def test_the_code_is_accepted_only_after_the_transfer_was_sent(self) -> None:
        with pytest.raises(TransferNotSentYet):
            pending_owner("123456").confirm_bank_account("123456", POLICY)

    def test_the_right_code_verifies_the_account(self) -> None:
        subject = sent_owner("123456")
        outcome = subject.confirm_bank_account("123456", POLICY)
        assert outcome.verified is True
        assert subject.bank_account.status is BankAccountStatus.VERIFIED
        assert subject.bank_account.verification_code == ""
        assert subject.bank_account.payee_check == MATCH
        assert subject.events == [BankAccountVerified(owner_id=subject.id)]

    def test_wrong_codes_count_down_and_the_last_one_starts_over(self) -> None:
        subject = sent_owner("123456")
        first = subject.confirm_bank_account("000000", POLICY)
        second = subject.confirm_bank_account("000000", POLICY)
        assert (first.verified, first.attempts_left) == (False, 2)
        assert (second.verified, second.attempts_left) == (False, 1)
        assert status_of(subject) is BankAccountStatus.TRANSFER_SENT

        last = subject.confirm_bank_account("000000", POLICY)
        assert (last.verified, last.attempts_left) == (False, 0)
        assert status_of(subject) is BankAccountStatus.UNVERIFIED
        assert subject.bank_account.verification_code == ""
        assert subject.events == []

    def test_after_running_out_of_attempts_the_old_code_no_longer_works(self) -> None:
        subject = sent_owner("123456")
        for _ in range(3):
            subject.confirm_bank_account("000000", POLICY)
        with pytest.raises(BankVerificationNotStarted):
            subject.confirm_bank_account("123456", POLICY)

    def test_a_new_transfer_restarts_the_count(self) -> None:
        subject = sent_owner("123456")
        subject.confirm_bank_account("000000", POLICY)
        subject.start_bank_verification("654321")
        subject.record_test_transfer(MATCH)
        assert subject.confirm_bank_account("000000", POLICY).attempts_left == 2

    def test_confirming_needs_a_transfer_first(self) -> None:
        with pytest.raises(BankVerificationNotStarted):
            owner().confirm_bank_account("123456", POLICY)

    def test_a_verified_account_is_not_verified_again(self) -> None:
        with pytest.raises(BankAccountAlreadyVerified):
            verified_owner().start_bank_verification("654321")

    def test_a_code_for_a_verified_account_says_it_is_verified(self) -> None:
        with pytest.raises(BankAccountAlreadyVerified):
            verified_owner().confirm_bank_account("123456", POLICY)

    def test_a_code_with_letters_is_simply_wrong(self) -> None:
        assert sent_owner("123456").confirm_bank_account("12345α", POLICY).verified is False

    def test_the_policy_needs_at_least_one_attempt(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            BankVerificationPolicy(max_attempts=0)
