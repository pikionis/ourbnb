"""Rules of DOMAIN §5 for properties that owners handle in the portal: automatic codes, the
contract to sign, and what an owner may change."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kospm.properties.domain.codes import PropertyCodeSeries
from kospm.properties.domain.errors import (
    ChangeThroughTheIke,
    InvalidStatusTransition,
    InvalidValue,
    NoContractToSign,
    PropertyNotFound,
)
from kospm.properties.domain.events import ContractOffered, ContractSigned
from kospm.properties.domain.value_objects import ContractDraft, PropertyCode
from kospm.shared.domain import Money, new_id
from tests.unit.properties.builders import new_property, ready_property

SIGNED_AT = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)


def codes(*values: str) -> list[PropertyCode]:
    return [PropertyCode(value) for value in values]


def draft(**overrides: object) -> ContractDraft:
    values: dict[str, object] = {
        "document": "contracts/drafts/kos-001.pdf",
        "commission_rate": Decimal("0.18"),
        "owner_cleaning_charge": Money("35.00"),
    }
    values.update(overrides)
    return ContractDraft(**values)  # type: ignore[arg-type]


class TestAutomaticCodes:
    def test_the_first_code_of_the_series(self) -> None:
        assert PropertyCodeSeries().next_code([]) == PropertyCode("KOS-001")

    def test_one_more_than_the_highest_number_in_use_so_no_code_is_reused(self) -> None:
        series = PropertyCodeSeries()
        assert series.next_code(codes("KOS-001", "KOS-007", "KOS-003")) == PropertyCode("KOS-008")

    def test_codes_of_another_shape_are_ignored(self) -> None:
        series = PropertyCodeSeries()
        assert series.next_code(codes("KOS-A1", "VIL-009", "KOS-1-2")) == PropertyCode("KOS-001")

    def test_the_number_grows_past_its_width(self) -> None:
        assert PropertyCodeSeries().next_code(codes("KOS-999")) == PropertyCode("KOS-1000")

    def test_prefix_and_width_are_configuration(self) -> None:
        series = PropertyCodeSeries(prefix="kef", digits=2)
        assert series.next_code(codes("KEF-09")) == PropertyCode("KEF-10")

    @pytest.mark.parametrize("prefix", ["", "K-S", "ΚΩΣ", "TOOLONGPREFIXX"])
    def test_a_prefix_must_make_valid_codes(self, prefix: str) -> None:
        with pytest.raises(ValueError, match="prefix"):
            PropertyCodeSeries(prefix=prefix)


class TestContractToSign:
    def test_a_draft_has_the_terms_of_a_contract(self) -> None:
        with pytest.raises(InvalidValue):
            draft(commission_rate=Decimal("1.2"))
        with pytest.raises(InvalidValue):
            draft(owner_cleaning_charge=Money("-1.00"))
        with pytest.raises(InvalidValue) as not_pdf:
            draft(document="contracts/drafts/kos-001.docx")
        assert not_pdf.value.field == "contract_draft"

    def test_offering_a_draft_is_announced(self) -> None:
        prop = new_property()
        prop.offer_contract(draft())
        assert prop.contract_draft == draft()
        assert prop.events == [ContractOffered(property_id=prop.id)]

    def test_the_owner_signs_the_draft_with_its_terms(self) -> None:
        prop = new_property()
        prop.offer_contract(draft())
        prop.events.clear()
        prop.sign_offered_contract("contracts/kos-001-signed.pdf", signed_at=SIGNED_AT)
        assert prop.contract is not None
        assert (prop.contract.commission_rate, prop.contract.owner_cleaning_charge) == (
            Decimal("0.18"),
            Money("35.00"),
        )
        assert (prop.contract.document, prop.contract.signed_at) == (
            "contracts/kos-001-signed.pdf",
            SIGNED_AT,
        )
        assert prop.events == [ContractSigned(property_id=prop.id)]

    def test_nothing_to_sign_before_a_draft_exists(self) -> None:
        with pytest.raises(NoContractToSign):
            new_property().sign_offered_contract("contracts/x.pdf", signed_at=SIGNED_AT)

    def test_a_new_draft_does_not_undo_a_signed_contract(self) -> None:
        prop = ready_property()
        signed = prop.contract
        prop.offer_contract(draft())
        assert prop.contract == signed

    def test_an_offboarded_property_gets_no_contract(self) -> None:
        prop = new_property()
        prop.offboard()
        with pytest.raises(InvalidStatusTransition):
            prop.offer_contract(draft())


class TestWhatTheOwnerMayChange:
    def test_their_own_property_while_it_is_being_set_up(self) -> None:
        owner_id = new_id()
        new_property(owner_id=owner_id).check_owner_may_change(owner_id)

    def test_never_another_owners_property(self) -> None:
        with pytest.raises(PropertyNotFound):
            new_property(owner_id=new_id()).check_owner_may_change(new_id())

    @pytest.mark.parametrize("leave", ["activate", "offboard"])
    def test_after_the_set_up_changes_go_through_the_ike(self, leave: str) -> None:
        owner_id = new_id()
        prop = ready_property(owner_id=owner_id)
        if leave == "activate":
            prop.activate(owner_bank_account_verified=True)
        else:
            prop.offboard()
        with pytest.raises(ChangeThroughTheIke) as refused:
            prop.check_owner_may_change(owner_id)
        assert refused.value.item == "property"
