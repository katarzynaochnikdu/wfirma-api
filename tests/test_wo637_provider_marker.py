"""Every provider request marker fits in what wFirma stores (WO-637).

wFirma keeps `id_external` truncated to 32 characters. Measured on production
2026-09-18 through the WO-636 breakdown: `marker_seen=32 marker_sent=68`, on a
real settlement. A longer marker therefore can never read back equal to what
was written, which made every identity check fail and left the bridge unable to
recognise a document it had created itself.
"""
import hashlib
import pytest
import grouped_document_contract as c
import first_invoice_contract as n
import participant_change_correction as m
from test_wo601ad_first_invoice_contract import body, prepare
from test_wo601ad_grouped_document_contract import invoice as grouped_source, prepare as grouped_prepare

LIMIT = 32


def test_wo637_the_first_invoice_marker_fits_in_what_the_provider_stores():
    # Act
    prepared = prepare()
    external = prepared["document"]["id_external"]
    assert len(external) <= LIMIT and external.startswith("nf1:")


def test_wo637_a_document_created_before_the_fix_still_verifies():
    """The one property that decides whether real invoices need a correction.

    A document issued with the old 68 character marker carries whatever the
    provider kept of it. Because the new marker is that same string cut at the
    provider's own limit, the stored value and the expected value are equal, so
    an invoice created before this fix reconciles instead of needing a
    correction and a duplicate.
    """
    value = body()
    digest = hashlib.sha256(c.canonical(
        {"change_id": value["change_id"], "intent_sha256": value["intent_sha256"]})).hexdigest()
    before_the_fix = "nf1:" + digest
    # Act
    prepared = prepare(value)
    assert len(before_the_fix) == 68
    assert prepared["document"]["id_external"] == before_the_fix[:LIMIT]


def test_wo637_the_correction_marker_fits_in_what_the_provider_stores():
    # Act
    prepared = grouped_prepare(grouped_source())
    external = prepared["document"]["id_external"]
    assert len(external) <= LIMIT and external.startswith("nd2:")


def test_wo637_the_participant_change_marker_fits_in_what_the_provider_stores():
    assert m.MARKER_LIMIT == LIMIT
    digest = hashlib.sha256(m.canonical({"change_id": "x", "parent": "y"})).hexdigest()
    # Act
    external = ("mt1:" + digest)[:m.MARKER_LIMIT]
    assert len(external) == LIMIT and external.startswith("mt1:")


@pytest.mark.parametrize("prefix", ["nf1", "nf1:x", "", "much_longer_prefix", 17, None])
def test_wo637_a_marker_prefix_of_the_wrong_shape_is_refused(prefix):
    with pytest.raises(c.GroupedDocumentError):
        # Act
        c.marker(prefix, {"change_id": "x"})


def test_wo637_the_marker_is_stable_for_the_same_request():
    value = {"change_id": "synthetic-1", "intent_sha256": "a" * 64}
    # Act
    assert c.marker("nf1:", value) == c.marker("nf1:", value)


def test_wo637_the_marker_still_separates_two_different_requests():
    # Act
    one = c.marker("nf1:", {"change_id": "synthetic-1", "intent_sha256": "a" * 64})
    two = c.marker("nf1:", {"change_id": "synthetic-2", "intent_sha256": "a" * 64})
    assert one != two and len(one) == len(two) == LIMIT
