"""Handlers of the properties context, driven through the real bus with fakes (Cosmic Python ch. 5).

Each test sends commands the way the admin (and later the owner portal) does and checks the
stored aggregates, the commits and the events that reached other handlers.
"""

from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from kospm.bootstrap import ContextWiring, bootstrap
from kospm.properties.domain.checklist import ActivationRequirement
from kospm.properties.domain.codes import PropertyCodeSeries
from kospm.properties.domain.commands import (
    ActivateProperty,
    AssignAma,
    ChangeBankAccount,
    ConfirmBankAccount,
    CreateProperty,
    DeactivateProperty,
    OffboardProperty,
    OfferContract,
    RecordSubleaseDeclaration,
    RecordTestTransfer,
    RegisterOwner,
    SignContract,
    StartBankAccountVerification,
    UpdateOwnerDetails,
    UpdatePropertyProfile,
)
from kospm.properties.domain.defaults import BankVerificationPolicy, PropertyDefaults
from kospm.properties.domain.errors import (
    BankAccountAlreadyVerified,
    ChangeThroughTheIke,
    InvalidValue,
    NoContractToSign,
    OwnerAlreadyRegistered,
    OwnerNotFound,
    PropertyCodeTaken,
    PropertyNotFound,
    PropertyNotReadyForActivation,
    TransferNotSentYet,
    WrongVerificationCode,
)
from kospm.properties.domain.events import OwnerEmailChanged
from kospm.properties.domain.owner import BankAccountStatus
from kospm.properties.domain.property import PropertyStatus
from kospm.properties.domain.value_objects import (
    AccountHolderName,
    Email,
    Iban,
    IcalChannel,
    PropertyCode,
)
from kospm.properties.service_layer.handlers import COMMAND_HANDLERS, EVENT_HANDLERS
from kospm.shared.clock import FixedClock
from kospm.shared.domain import Money, new_id
from kospm.shared.messagebus import MessageBus
from tests.unit.properties.builders import (
    HOLDER,
    OTHER_VALID_AFM,
    OTHER_VALID_IBAN,
    VALID_AFM,
    VALID_IBAN,
)
from tests.unit.properties.fakes import (
    FakeBankAccountVerifier,
    FakePropertiesUnitOfWork,
    RequestedTransfer,
)

NOW = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)


class Harness:
    """A bus wired with the properties handlers, a fake Unit of Work and fixed dependencies."""

    def __init__(self) -> None:
        self.uow = FakePropertiesUnitOfWork()
        self.verifier = FakeBankAccountVerifier()
        self.email_changes: list[OwnerEmailChanged] = []
        self.bus: MessageBus = bootstrap(
            clock=FixedClock(NOW),
            contexts=[
                ContextWiring(
                    name="properties",
                    uow=self.uow,
                    command_handlers=COMMAND_HANDLERS,
                    event_handlers={
                        **EVENT_HANDLERS,
                        OwnerEmailChanged: [self.email_changes.append],
                    },
                    dependencies={
                        "property_defaults": PropertyDefaults(),
                        "property_codes": PropertyCodeSeries(),
                        "bank_verification": BankVerificationPolicy(max_attempts=3),
                        "bank_account_verifier": self.verifier,
                    },
                )
            ],
        )

    def register_owner(self, *, afm: str = VALID_AFM, email: str = "maria@example.com") -> UUID:
        owner_id = new_id()
        self.bus.handle(
            RegisterOwner(
                owner_id=owner_id,
                name="Μαρία Παπαδοπούλου",
                email=email,
                phone="+30 6900000000",
                afm=afm,
                iban=VALID_IBAN,
                holder_name="PAPADOPOULOU MARIA",
                acting_owner_id=None,
            )
        )
        return owner_id

    def create_property(self, owner_id: UUID, code: str = "KOS-A1") -> UUID:
        property_id = new_id()
        self.bus.handle(
            CreateProperty(
                property_id=property_id,
                owner_id=owner_id,
                code=code,
                name="Σπίτι",
                acting_owner_id=None,
            )
        )
        return property_id

    def complete_profile(self, property_id: UUID, **overrides: Any) -> None:
        values: dict[str, Any] = {
            "property_id": property_id,
            "name": "Σπίτι Αιγαίου",
            "address": "Βασιλέως Παύλου 12, Κως",
            "lat": Decimal("36.893300"),
            "lng": Decimal("27.288900"),
            "directions_el": "Δεύτερο στενό δεξιά.",
            "directions_en": "Second street on the right.",
            "map_url": "",
            "exterior_photo": "properties/photos/exterior.jpg",
            "lockbox_photo": "properties/photos/lockbox.jpg",
            "guest_lockbox_code": "4711",
            "cleaner_lockbox_code": "",
            "amenities_included": ("Wi-Fi",),
            "amenities_not_included": (),
            "ical_feeds": (),
            "default_check_in_time": time(15),
            "default_check_out_time": time(11),
            "linen_par_level": 3,
            "preferred_cleaner_id": None,
            "acting_owner_id": None,
        }
        values.update(overrides)
        self.bus.handle(UpdatePropertyProfile(**values))

    def do_legal_steps(self, property_id: UUID) -> None:
        self.bus.handle(
            SignContract(
                property_id=property_id, document="contracts/signed.pdf", acting_owner_id=None
            )
        )
        self.bus.handle(
            RecordSubleaseDeclaration(
                property_id=property_id, number="ΔΥ-123", acting_owner_id=None
            )
        )
        self.bus.handle(AssignAma(property_id=property_id, ama_number="00001234567"))

    def send_test_transfer(self, owner_id: UUID, result: str = "match") -> None:
        self.bus.handle(StartBankAccountVerification(owner_id=owner_id, acting_owner_id=None))
        self.bus.handle(RecordTestTransfer(owner_id=owner_id, result=result))

    def verify_bank_account(self, owner_id: UUID) -> None:
        self.send_test_transfer(owner_id)
        code = self.owner(owner_id).bank_account.verification_code
        self.bus.handle(ConfirmBankAccount(owner_id=owner_id, code=code, acting_owner_id=None))

    def owner(self, owner_id: UUID) -> Any:
        return next(o for o in self.uow.owners.all() if o.id == owner_id)

    def property(self, property_id: UUID) -> Any:
        return next(p for p in self.uow.properties.all() if p.id == property_id)


@pytest.fixture
def harness() -> Harness:
    return Harness()


class TestOwners:
    def test_registers_an_owner(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        owner = harness.owner(owner_id)
        assert owner.email == Email("maria@example.com")
        assert owner.bank_account.status is BankAccountStatus.UNVERIFIED
        assert harness.uow.committed == 1

    def test_afm_and_email_identify_one_owner(self, harness: Harness) -> None:
        harness.register_owner()
        with pytest.raises(OwnerAlreadyRegistered) as same_afm:
            harness.register_owner(email="other@example.com")
        with pytest.raises(OwnerAlreadyRegistered) as same_email:
            harness.register_owner(afm=OTHER_VALID_AFM, email="MARIA@example.com")
        assert (same_afm.value.field, same_email.value.field) == ("afm", "email")
        assert len(harness.uow.owners.all()) == 1

    def test_an_invalid_afm_registers_nothing(self, harness: Harness) -> None:
        with pytest.raises(InvalidValue):
            harness.register_owner(afm="123456789")
        assert harness.uow.owners.all() == []

    def test_details_change_but_the_email_stays_unique(self, harness: Harness) -> None:
        maria = harness.register_owner()
        harness.register_owner(afm=OTHER_VALID_AFM, email="nikos@example.com")
        harness.bus.handle(
            UpdateOwnerDetails(
                owner_id=maria,
                name="Μαρία Π.",
                email="m@example.com",
                phone="1",
                acting_owner_id=None,
            )
        )
        assert harness.owner(maria).name == "Μαρία Π."
        with pytest.raises(OwnerAlreadyRegistered):
            harness.bus.handle(
                UpdateOwnerDetails(
                    owner_id=maria,
                    name="Μαρία",
                    email="nikos@example.com",
                    phone="1",
                    acting_owner_id=None,
                )
            )

    def test_a_new_iban_must_be_verified_again(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        harness.verify_bank_account(owner_id)
        harness.bus.handle(
            ChangeBankAccount(
                owner_id=owner_id,
                iban=OTHER_VALID_IBAN,
                holder_name="MARIA P",
                acting_owner_id=None,
            )
        )
        account = harness.owner(owner_id).bank_account
        assert (account.iban, account.status) == (
            Iban(OTHER_VALID_IBAN),
            BankAccountStatus.UNVERIFIED,
        )

    def test_unknown_owner(self, harness: Harness) -> None:
        with pytest.raises(OwnerNotFound):
            harness.bus.handle(
                StartBankAccountVerification(owner_id=new_id(), acting_owner_id=None)
            )

    def test_a_new_email_is_announced_to_the_other_contexts(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        harness.bus.handle(
            UpdateOwnerDetails(
                owner_id=owner_id,
                name="Μαρία",
                email="M.P@example.com",
                phone="1",
                acting_owner_id=None,
            )
        )
        assert harness.email_changes == [
            OwnerEmailChanged(owner_id=owner_id, email="m.p@example.com")
        ]


class TestBankAccountVerification:
    def test_the_verifier_sends_the_transfer_with_its_code(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        harness.bus.handle(StartBankAccountVerification(owner_id=owner_id, acting_owner_id=None))
        account = harness.owner(owner_id).bank_account
        assert (account.status, account.verification_code) == (
            BankAccountStatus.PENDING,
            "123456",
        )
        assert harness.verifier.transfers == [
            RequestedTransfer(owner_id, Iban(VALID_IBAN), HOLDER, "123456")
        ]

    def test_no_transfer_for_a_verified_account(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        harness.verify_bank_account(owner_id)
        with pytest.raises(BankAccountAlreadyVerified):
            harness.bus.handle(
                StartBankAccountVerification(owner_id=owner_id, acting_owner_id=None)
            )
        assert len(harness.verifier.transfers) == 1

    def test_the_code_stays_out_of_the_command_repr(self) -> None:
        assert "987654" not in repr(
            ConfirmBankAccount(owner_id=new_id(), code="987654", acting_owner_id=None)
        )

    def test_the_admin_records_the_transfer_with_the_banks_payee_check(
        self, harness: Harness
    ) -> None:
        owner_id = harness.register_owner()
        harness.bus.handle(StartBankAccountVerification(owner_id=owner_id, acting_owner_id=None))
        harness.bus.handle(
            RecordTestTransfer(owner_id=owner_id, result="close_match", bank_name="PAPADOPOULOU M")
        )
        account = harness.owner(owner_id).bank_account
        assert account.status is BankAccountStatus.TRANSFER_SENT
        assert account.holder_name == AccountHolderName("PAPADOPOULOU M")

    @pytest.mark.parametrize(
        ("result", "bank_name"), [("close_match", ""), ("maybe", ""), ("match", "X")]
    )
    def test_a_check_must_be_one_of_the_banks_answers(
        self, harness: Harness, result: str, bank_name: str
    ) -> None:
        owner_id = harness.register_owner()
        harness.bus.handle(StartBankAccountVerification(owner_id=owner_id, acting_owner_id=None))
        with pytest.raises(InvalidValue):
            harness.bus.handle(
                RecordTestTransfer(owner_id=owner_id, result=result, bank_name=bank_name)
            )

    def test_recording_the_transfer_checks_the_admins_page_is_current(
        self, harness: Harness
    ) -> None:
        owner_id = harness.register_owner()
        harness.bus.handle(StartBankAccountVerification(owner_id=owner_id, acting_owner_id=None))
        harness.bus.handle(
            RecordTestTransfer(owner_id=owner_id, result="match", expected_version=2)
        )
        assert harness.uow.owners.expected_versions[-1] == 2

    def test_no_code_before_the_transfer_is_sent(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        harness.bus.handle(StartBankAccountVerification(owner_id=owner_id, acting_owner_id=None))
        with pytest.raises(TransferNotSentYet):
            harness.bus.handle(
                ConfirmBankAccount(owner_id=owner_id, code="123456", acting_owner_id=None)
            )

    def test_a_wrong_code_is_reported_after_the_attempt_is_saved(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        harness.send_test_transfer(owner_id)
        commits_before = harness.uow.committed
        with pytest.raises(WrongVerificationCode) as wrong:
            harness.bus.handle(
                ConfirmBankAccount(owner_id=owner_id, code="000000", acting_owner_id=None)
            )
        assert wrong.value.attempts_left == 2
        assert harness.uow.committed == commits_before + 1
        assert harness.owner(owner_id).bank_account.failed_attempts == 1

    def test_the_right_code_verifies_the_account(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        harness.verify_bank_account(owner_id)
        assert harness.owner(owner_id).bank_account_verified is True


class TestOwnerPortalRules:
    """Commands from the owner portal name the acting owner (ADR 0017, DOMAIN §5)."""

    def test_an_owner_acts_only_on_their_own_data(self, harness: Harness) -> None:
        maria = harness.register_owner()
        nikos = harness.register_owner(afm=OTHER_VALID_AFM, email="nikos@example.com")
        with pytest.raises(OwnerNotFound):
            harness.bus.handle(StartBankAccountVerification(owner_id=maria, acting_owner_id=nikos))
        with pytest.raises(OwnerNotFound):
            harness.bus.handle(
                ChangeBankAccount(
                    owner_id=maria,
                    iban=OTHER_VALID_IBAN,
                    holder_name="NIKOS",
                    acting_owner_id=nikos,
                )
            )
        with pytest.raises(OwnerNotFound):
            harness.bus.handle(
                ConfirmBankAccount(owner_id=maria, code="123456", acting_owner_id=nikos)
            )
        with pytest.raises(OwnerNotFound):
            harness.bus.handle(
                UpdateOwnerDetails(
                    owner_id=maria,
                    name="Νίκος",
                    email="maria@example.com",
                    phone="1",
                    acting_owner_id=nikos,
                )
            )
        assert harness.owner(maria).bank_account.iban == Iban(VALID_IBAN)
        assert harness.owner(maria).name == "Μαρία Παπαδοπούλου"

    def test_an_owner_registers_only_themself(self, harness: Harness) -> None:
        owner_id = new_id()
        with pytest.raises(OwnerNotFound):
            harness.bus.handle(
                RegisterOwner(
                    owner_id=owner_id,
                    name="Μαρία Παπαδοπούλου",
                    email="maria@example.com",
                    phone="+30 6900000000",
                    afm=VALID_AFM,
                    iban=VALID_IBAN,
                    holder_name="PAPADOPOULOU MARIA",
                    acting_owner_id=new_id(),
                )
            )
        assert harness.uow.owners.all() == []

    def test_an_owner_starts_the_verification_once(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        start = StartBankAccountVerification(owner_id=owner_id, acting_owner_id=owner_id)
        harness.bus.handle(start)
        with pytest.raises(ChangeThroughTheIke):
            harness.bus.handle(start)  # the transfer on its way is kept
        assert len(harness.verifier.transfers) == 1

    def test_an_owner_changes_their_bank_account_only_until_it_is_verified(
        self, harness: Harness
    ) -> None:
        owner_id = harness.register_owner()

        def change_to(iban: str) -> ChangeBankAccount:
            return ChangeBankAccount(
                owner_id=owner_id, iban=iban, holder_name="MARIA P", acting_owner_id=owner_id
            )

        harness.bus.handle(change_to(OTHER_VALID_IBAN))
        harness.verify_bank_account(owner_id)
        with pytest.raises(ChangeThroughTheIke):
            harness.bus.handle(change_to(VALID_IBAN))
        assert harness.owner(owner_id).bank_account_verified is True

    def test_an_owner_does_not_change_their_login_email(self, harness: Harness) -> None:
        owner_id = harness.register_owner()

        def details_with(email: str) -> UpdateOwnerDetails:
            return UpdateOwnerDetails(
                owner_id=owner_id, name="Μαρία Π.", email=email, phone="1", acting_owner_id=owner_id
            )

        harness.bus.handle(details_with("maria@example.com"))
        with pytest.raises(ChangeThroughTheIke):
            harness.bus.handle(details_with("other@example.com"))
        assert harness.owner(owner_id).name == "Μαρία Π."

    def test_an_owner_enters_their_own_code(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        harness.send_test_transfer(owner_id)
        code = harness.owner(owner_id).bank_account.verification_code
        harness.bus.handle(
            ConfirmBankAccount(owner_id=owner_id, code=code, acting_owner_id=owner_id)
        )
        assert harness.owner(owner_id).bank_account_verified is True


class TestProperties:
    def test_one_owner_with_many_properties(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        for code in ("KOS-A1", "KOS-A2", "KOS-B1"):
            harness.create_property(owner_id, code)
        owned = harness.uow.properties.list_by_owner(owner_id)
        assert sorted(str(p.code) for p in owned) == ["KOS-A1", "KOS-A2", "KOS-B1"]
        assert {p.status for p in owned} == {PropertyStatus.ONBOARDING}

    def test_a_property_belongs_to_a_registered_owner(self, harness: Harness) -> None:
        with pytest.raises(OwnerNotFound):
            harness.create_property(new_id())

    def test_the_code_identifies_one_property(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        harness.create_property(owner_id, "KOS-A1")
        with pytest.raises(PropertyCodeTaken):
            harness.create_property(owner_id, "kos-a1")

    def test_a_profile_update_keeps_the_lockbox_codes_unless_new_ones_are_given(
        self, harness: Harness
    ) -> None:
        property_id = harness.create_property(harness.register_owner())
        harness.complete_profile(property_id, guest_lockbox_code="4711")
        harness.complete_profile(property_id, guest_lockbox_code=None, name="Νέο όνομα")
        assert harness.property(property_id).check_in_guide.guest_lockbox_code == "4711"
        harness.complete_profile(property_id, guest_lockbox_code="8080")
        assert harness.property(property_id).check_in_guide.guest_lockbox_code == "8080"

    def test_the_profile_takes_the_calendar_feeds(self, harness: Harness) -> None:
        property_id = harness.create_property(harness.register_owner())
        harness.complete_profile(
            property_id, ical_feeds=(("airbnb", "https://www.airbnb.com/calendar/ical/1.ics"),)
        )
        (feed,) = harness.property(property_id).ical_feeds
        assert feed.channel is IcalChannel.AIRBNB

    def test_coordinates_come_in_pairs(self, harness: Harness) -> None:
        property_id = harness.create_property(harness.register_owner())
        with pytest.raises(InvalidValue):
            harness.complete_profile(property_id, lng=None)

    def test_a_contract_without_terms_gets_the_configured_defaults(self, harness: Harness) -> None:
        property_id = harness.create_property(harness.register_owner())
        harness.bus.handle(
            SignContract(property_id=property_id, document="contracts/a.pdf", acting_owner_id=None)
        )
        contract = harness.property(property_id).contract
        assert (contract.commission_rate, contract.owner_cleaning_charge, contract.signed_at) == (
            Decimal("0.15"),
            Money("40.00"),
            NOW,
        )

    def test_a_contract_with_its_own_terms(self, harness: Harness) -> None:
        property_id = harness.create_property(harness.register_owner())
        harness.bus.handle(
            SignContract(
                property_id=property_id,
                document="contracts/a.pdf",
                commission_rate=Decimal("0.18"),
                owner_cleaning_charge=Decimal("35.00"),
                acting_owner_id=None,
            )
        )
        contract = harness.property(property_id).contract
        assert (contract.commission_rate, contract.owner_cleaning_charge) == (
            Decimal("0.18"),
            Money("35.00"),
        )

    def test_unknown_property(self, harness: Harness) -> None:
        with pytest.raises(PropertyNotFound):
            harness.bus.handle(ActivateProperty(property_id=new_id()))


class TestOwnerPortalProperties:
    """Property commands sent from the owner portal name the acting owner (ADR 0017)."""

    def add_property(self, harness: Harness, owner_id: UUID, acting: UUID | None = None) -> UUID:
        property_id = new_id()
        harness.bus.handle(
            CreateProperty(
                property_id=property_id,
                owner_id=owner_id,
                name="Villa Elena",
                acting_owner_id=acting or owner_id,
            )
        )
        return property_id

    def test_an_owner_adds_a_property_and_it_gets_the_next_code(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        harness.create_property(owner_id, "KOS-005")
        added = harness.property(self.add_property(harness, owner_id))
        assert added.code == PropertyCode("KOS-006")
        assert added.status is PropertyStatus.ONBOARDING

    def test_an_owner_adds_properties_only_for_themself(self, harness: Harness) -> None:
        maria = harness.register_owner()
        nikos = harness.register_owner(afm=OTHER_VALID_AFM, email="nikos@example.com")
        with pytest.raises(OwnerNotFound):
            self.add_property(harness, maria, acting=nikos)

    def test_an_owner_completes_only_their_own_profile(self, harness: Harness) -> None:
        maria = harness.register_owner()
        nikos = harness.register_owner(afm=OTHER_VALID_AFM, email="nikos@example.com")
        property_id = self.add_property(harness, maria)
        harness.complete_profile(property_id, acting_owner_id=maria)
        assert harness.property(property_id).profile_gaps() == []
        with pytest.raises(PropertyNotFound):
            harness.complete_profile(property_id, acting_owner_id=nikos, name="Δικό μου")

    @pytest.mark.parametrize(
        "change",
        [
            {"ical_feeds": (("airbnb", "https://www.airbnb.com/calendar/ical/1.ics"),)},
            {"linen_par_level": 5},
            {"default_check_in_time": time(14)},
            {"preferred_cleaner_id": new_id()},
        ],
    )
    def test_an_owner_never_changes_what_the_ike_sets(
        self, harness: Harness, change: dict[str, Any]
    ) -> None:
        owner_id = harness.register_owner()
        property_id = self.add_property(harness, owner_id)
        with pytest.raises(ChangeThroughTheIke):
            harness.complete_profile(property_id, acting_owner_id=owner_id, **change)

    def test_an_owner_signs_the_contract_the_ike_offered_with_its_terms(
        self, harness: Harness
    ) -> None:
        owner_id = harness.register_owner()
        property_id = self.add_property(harness, owner_id)
        harness.bus.handle(
            OfferContract(
                property_id=property_id,
                document="contracts/drafts/a.pdf",
                commission_rate=Decimal("0.18"),
            )
        )
        harness.bus.handle(
            SignContract(
                property_id=property_id,
                document="contracts/a-signed.pdf",
                acting_owner_id=owner_id,
            )
        )
        contract = harness.property(property_id).contract
        assert (contract.commission_rate, contract.owner_cleaning_charge, contract.signed_at) == (
            Decimal("0.18"),
            Money("40.00"),
            NOW,
        )

    def test_an_owner_signs_only_their_own_property_while_it_is_set_up(
        self, harness: Harness
    ) -> None:
        owner_id = harness.register_owner()
        nikos = harness.register_owner(afm=OTHER_VALID_AFM, email="nikos@example.com")
        property_id = self.add_property(harness, owner_id)
        harness.bus.handle(OfferContract(property_id=property_id, document="contracts/d.pdf"))

        def signed_by(acting_owner_id: UUID) -> SignContract:
            return SignContract(
                property_id=property_id, document="contracts/s.pdf", acting_owner_id=acting_owner_id
            )

        with pytest.raises(PropertyNotFound):
            harness.bus.handle(signed_by(nikos))
        harness.bus.handle(OffboardProperty(property_id=property_id))
        with pytest.raises(ChangeThroughTheIke):
            harness.bus.handle(signed_by(owner_id))
        assert harness.property(property_id).contract is None

    def test_an_owner_never_replaces_a_recorded_contract(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        property_id = self.add_property(harness, owner_id)
        harness.bus.handle(OfferContract(property_id=property_id, document="contracts/d.pdf"))
        harness.bus.handle(  # the IKE records a contract signed on paper, with its own terms
            SignContract(
                property_id=property_id,
                document="contracts/paper.pdf",
                commission_rate=Decimal("0.12"),
                acting_owner_id=None,
            )
        )
        with pytest.raises(ChangeThroughTheIke):
            harness.bus.handle(
                SignContract(
                    property_id=property_id, document="contracts/s.pdf", acting_owner_id=owner_id
                )
            )
        assert harness.property(property_id).contract.commission_rate == Decimal("0.12")

    def test_a_code_taken_in_the_meantime_is_skipped(
        self, harness: Harness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        owner_id = harness.register_owner()
        harness.create_property(owner_id, code="KOS-001")  # added by someone else meanwhile
        real = harness.uow.properties.codes_with_prefix
        reads: list[str] = []

        def stale_first(prefix: str) -> list[PropertyCode]:
            reads.append(prefix)
            return [] if len(reads) == 1 else real(prefix)

        monkeypatch.setattr(harness.uow.properties, "codes_with_prefix", stale_first)

        property_id = self.add_property(harness, owner_id)

        assert harness.property(property_id).code == PropertyCode("KOS-002")

    def test_no_signed_contract_before_the_ike_offers_one(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        property_id = self.add_property(harness, owner_id)
        with pytest.raises(NoContractToSign):
            harness.bus.handle(
                SignContract(
                    property_id=property_id, document="contracts/a.pdf", acting_owner_id=owner_id
                )
            )

    def test_an_owner_records_the_sublease_number_until_the_property_works(
        self, harness: Harness
    ) -> None:
        owner_id = harness.register_owner()
        property_id = harness.create_property(owner_id)
        record = RecordSubleaseDeclaration(
            property_id=property_id, number="ΔΥ-1", acting_owner_id=owner_id
        )
        harness.bus.handle(record)
        harness.complete_profile(property_id)
        harness.do_legal_steps(property_id)
        harness.verify_bank_account(owner_id)
        harness.bus.handle(ActivateProperty(property_id=property_id))
        with pytest.raises(ChangeThroughTheIke):
            harness.bus.handle(record)


class TestActivation:
    def test_activation_fails_listing_each_missing_item(self, harness: Harness) -> None:
        property_id = harness.create_property(harness.register_owner())
        with pytest.raises(PropertyNotReadyForActivation) as refused:
            harness.bus.handle(ActivateProperty(property_id=property_id))
        assert len(refused.value.missing) == len(ActivationRequirement)

    def test_the_owners_bank_account_is_part_of_the_checklist(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        property_id = harness.create_property(owner_id)
        harness.complete_profile(property_id)
        harness.do_legal_steps(property_id)
        with pytest.raises(PropertyNotReadyForActivation) as refused:
            harness.bus.handle(ActivateProperty(property_id=property_id))
        assert list(refused.value.missing) == [ActivationRequirement.BANK_ACCOUNT_VERIFIED]

    def test_activation_succeeds_and_asks_the_owner_for_website_consent(
        self, harness: Harness
    ) -> None:
        owner_id = harness.register_owner()
        property_id = harness.create_property(owner_id)
        harness.complete_profile(property_id)
        harness.do_legal_steps(property_id)
        harness.verify_bank_account(owner_id)

        harness.bus.handle(ActivateProperty(property_id=property_id))

        assert harness.property(property_id).status is PropertyStatus.ACTIVE
        assert harness.owner(owner_id).website_consent_requested is True

    def test_one_verified_account_serves_all_the_owners_properties(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        harness.verify_bank_account(owner_id)
        for code in ("KOS-A1", "KOS-A2"):
            property_id = harness.create_property(owner_id, code)
            harness.complete_profile(property_id)
            harness.do_legal_steps(property_id)
            harness.bus.handle(ActivateProperty(property_id=property_id))
        assert {p.status for p in harness.uow.properties.all()} == {PropertyStatus.ACTIVE}

    def test_deactivate_reactivate_and_offboard(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        property_id = harness.create_property(owner_id)
        harness.complete_profile(property_id)
        harness.do_legal_steps(property_id)
        harness.verify_bank_account(owner_id)
        harness.bus.handle(ActivateProperty(property_id=property_id))

        harness.bus.handle(DeactivateProperty(property_id=property_id))
        assert harness.property(property_id).status is PropertyStatus.INACTIVE
        harness.bus.handle(ActivateProperty(property_id=property_id))
        assert harness.property(property_id).status is PropertyStatus.ACTIVE
        harness.bus.handle(OffboardProperty(property_id=property_id))
        assert harness.property(property_id).status is PropertyStatus.OFFBOARDED

    def test_codes_are_normalised(self, harness: Harness) -> None:
        property_id = harness.create_property(harness.register_owner(), " kos-b2 ")
        assert harness.property(property_id).code == PropertyCode("KOS-B2")


class TestFormVersions:
    """Every command a form sends passes the form's version to the repository (ADR 0016)."""

    def test_owner_commands(self, harness: Harness) -> None:
        owner_id = harness.register_owner()
        harness.bus.handle(
            UpdateOwnerDetails(
                owner_id=owner_id,
                name="Μαρία",
                email="m@example.com",
                phone="1",
                expected_version=7,
                acting_owner_id=None,
            )
        )
        harness.bus.handle(
            ChangeBankAccount(
                owner_id=owner_id,
                iban=OTHER_VALID_IBAN,
                holder_name="M",
                expected_version=8,
                acting_owner_id=None,
            )
        )
        assert harness.uow.owners.expected_versions[-2:] == [7, 8]

    def test_property_commands(self, harness: Harness) -> None:
        property_id = harness.create_property(harness.register_owner())
        harness.complete_profile(property_id, expected_version=1)
        harness.bus.handle(
            SignContract(
                property_id=property_id,
                document="c/s.pdf",
                expected_version=2,
                acting_owner_id=None,
            )
        )
        harness.bus.handle(
            RecordSubleaseDeclaration(
                property_id=property_id, number="ΔΥ-1", expected_version=3, acting_owner_id=None
            )
        )
        harness.bus.handle(AssignAma(property_id=property_id, ama_number="1", expected_version=4))
        assert harness.uow.properties.expected_versions[-4:] == [1, 2, 3, 4]
