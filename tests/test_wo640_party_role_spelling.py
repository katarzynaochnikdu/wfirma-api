"""A party is not "changed" just because the provider spelled "no role" twice (WO-640).

Measured on production 2026-09-18: a proforma carried `role=""` while its own
contractor card carried `role="0"`. Everything else about the buyer - name, tax
id, street, zip, city, country and the contractor id - was identical, yet the
two read back as different parties and no invoice could be settled.

Twin of the portal's `tests/unit/test_wo640_party_role_spelling.py`; both copies
of this contract must keep answering the same way.
"""
import pytest
import grouped_document_contract as c

PARTY = dict(name="Synthetic company", tax_id_type="nip", nip="1132906449",
             street="Testowa 1", zip="00-001", city="Warszawa", country="PL")


@pytest.mark.parametrize("spelling", ["", "0", 0])
def test_wo640_every_spelling_of_no_role_reads_back_the_same(spelling):
    # Act
    assert c.party_detail(dict(PARTY, role=spelling))["role"] == ""


def test_wo640_a_party_without_the_field_at_all_reads_back_the_same():
    # Act
    assert c.party_detail(PARTY)["role"] == ""


@pytest.mark.parametrize("role,expected", [(1, "1"), ("1", "1"), (2, "2"), ("buyer", "buyer")])
def test_wo640_a_role_that_says_something_is_kept(role, expected):
    """Only the empty meaning is folded; anything the provider actually says stays."""
    # Act
    assert c.party_detail(dict(PARTY, role=role))["role"] == expected


def test_wo640_two_spellings_of_the_same_buyer_compare_equal():
    # Act
    written = c.party_detail(dict(PARTY, role=""))
    read_back = c.party_detail(dict(PARTY, role="0"))
    assert written == read_back


def test_wo640_a_buyer_who_really_changed_still_differs():
    # Act
    written = c.party_detail(dict(PARTY, role=""))
    read_back = c.party_detail(dict(PARTY, role="0", street="Inna 9"))
    assert written != read_back
