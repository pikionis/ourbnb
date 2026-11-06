"""A request for an estimate from the public site's form (ADR 0021)."""

import pytest

from kospm.properties.domain.errors import InvalidValue
from kospm.properties.domain.lead import LeadFormOptions, ListedOnline, OwnerLead

OPTIONS = LeadFormOptions(areas=("Ψαλίδι", "Τιγκάκι"), bedrooms=("1", "2", "5+"))


def lead(**changes: str) -> OwnerLead:
    form = {
        "name": "Μαρία Π.",
        "phone": "694 000 0000",
        "area": "Ψαλίδι",
        "bedrooms": "2",
        "online": "one",
    }
    return OwnerLead.from_form(**{**form, **changes}, options=OPTIONS)


def test_a_complete_form_becomes_a_lead() -> None:
    assert lead() == OwnerLead(
        name="Μαρία Π.",
        phone="694 000 0000",
        area="Ψαλίδι",
        bedrooms="2",
        listed_online=ListedOnline.ONE,
    )


@pytest.mark.parametrize("name", ["", "   ", "\r\n\t"])
def test_a_lead_needs_a_name(name: str) -> None:
    with pytest.raises(InvalidValue) as refused:
        lead(name=name)
    assert refused.value.field == "name"


@pytest.mark.parametrize("phone", ["", "12345", "call me maybe", "6" * 31, "694-abc-0000"])
def test_a_lead_needs_a_phone_number_we_can_call(phone: str) -> None:
    with pytest.raises(InvalidValue) as refused:
        lead(phone=phone)
    assert refused.value.field == "phone"


@pytest.mark.parametrize("phone", ["6940000000", "+30 694 000 0000", "(694) 000-0000"])
def test_a_phone_number_may_be_written_in_the_usual_ways(phone: str) -> None:
    assert lead(phone=phone).phone == phone


def test_line_breaks_and_control_characters_become_spaces() -> None:
    made = lead(name="Μαρία\r\nBcc: someone@example.com\x00", phone="694\n000 0000")
    assert made.name == "Μαρία Bcc: someone@example.com"
    assert made.phone == "694 000 0000"


def test_a_long_name_is_cut_at_the_forms_limit() -> None:
    assert len(lead(name="α" * 500).name) == 100


def test_what_the_form_does_not_offer_counts_as_not_stated() -> None:
    made = lead(area="Αθήνα", bedrooms="99", online="maybe")
    assert made.area is None
    assert made.bedrooms is None
    assert made.listed_online is None


def test_an_empty_list_of_options_is_a_configuration_mistake() -> None:
    with pytest.raises(ValueError, match="areas"):
        LeadFormOptions(areas=(), bedrooms=("1",))
    with pytest.raises(ValueError, match="bedrooms"):
        LeadFormOptions(areas=("Ψαλίδι",), bedrooms=())
