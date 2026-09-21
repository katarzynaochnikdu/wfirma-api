"""BUG-155: a v2 first invoice is linked to its proforma in wFirma ("order").

Synthetic data only. The same test lives in the wFirma bridge repository; only
the import lines differ. v1 must stay byte for byte as it was.
"""
import hashlib
from pathlib import Path
import pytest
import first_invoice_contract as n
from test_wo601ad_first_invoice_contract import body, prepare, readback

#: sha256 of the LF-normalized contract file. The bridge pins the SAME value for
#: its copy (first_invoice_contract.py): change both copies and both pins at once.
CONTRACT_SHA256 = "67ffbfd595919604cf8766defc7d7dbf1385d3fe5d3771a53c4d8c15af7dc5bb"
CONTRACT_FILE = Path(n.__file__)
#: v1 goldens computed with the contract BEFORE BUG-155 (backend origin/master 98ead96).
V1_DOCUMENT_SHA256 = "aa7c805a37ea1045bef7b7a170afaa4b38309e567548455735f66337af9bd980"
V1_PROOF_SHA256 = "c08e6df6cea5e649d71afc1131c78cd7a000d3b4b6d4850e3dc0ed401e70159c"
PROFORMA_ID = "9001"


def linked_body(proforma_id=PROFORMA_ID):
    value = body()
    value.update(contract_version=n.LINKED_VERSION, proforma_id=proforma_id)
    return value


def test_bug_155_contract_copy_matches_the_pinned_shared_hash():
    raw = CONTRACT_FILE.read_bytes().replace(b"\r\n", b"\n")
    # Act
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == CONTRACT_SHA256


def test_bug_155_v1_request_prepares_and_verifies_exactly_as_before():
    prepared = prepare()
    # Act
    proof = n.verify_created(prepared, readback(prepared), "8001", "130706")
    assert "order" not in prepared["document"]
    assert n.c.fingerprint(prepared["document"]) == V1_DOCUMENT_SHA256
    assert n.c.fingerprint(proof) == V1_PROOF_SHA256


def test_bug_155_v1_invoice_is_not_judged_by_a_link_it_never_asked_for():
    prepared = prepare()
    invoice = readback(prepared)
    invoice["order"] = {"id": "4242"}
    # Act
    proof = n.verify_created(prepared, invoice, "8001", "130706")
    assert n.c.fingerprint(proof) == V1_PROOF_SHA256


def test_bug_155_v2_request_sends_the_proforma_as_the_order_link():
    value = linked_body()
    # Act
    prepared = prepare(value)
    assert prepared["document"]["order"] == {"id": 9001}
    assert {k: v for k, v in prepared["document"].items() if k != "order"} == prepare()["document"]
    assert n.verify_created(prepared, readback(prepared), "8001", "130706")["paid_grosze"] == 97999


@pytest.mark.parametrize("returned", [None, {"id": "0"}, {"id": "9002"}, {"id": ""}])
def test_bug_155_v2_readback_without_the_same_link_is_refused(returned):
    prepared = prepare(linked_body())
    invoice = readback(prepared)
    if returned is None:
        del invoice["order"]
    else:
        invoice["order"] = returned
    with pytest.raises(n.c.GroupedDocumentError) as refused:
        # Act
        n.verify_created(prepared, invoice, "8001", "130706")
    assert refused.value.args == ("created_proforma_link_mismatch",)


@pytest.mark.parametrize("proforma_id", ["0", "09001", 9001, "", None, True])
def test_bug_155_v2_request_with_a_non_canonical_proforma_id_is_refused(proforma_id):
    with pytest.raises(n.c.GroupedDocumentError):
        # Act
        prepare(linked_body(proforma_id))


def test_bug_155_link_key_is_refused_outside_v2_and_required_in_v2():
    with_link_v1 = body()
    with_link_v1["proforma_id"] = PROFORMA_ID
    without_link_v2 = body()
    without_link_v2["contract_version"] = n.LINKED_VERSION
    for value in (with_link_v1, without_link_v2, dict(linked_body(), contract_version=3)):
        with pytest.raises(n.c.GroupedDocumentError):
            # Act
            prepare(value)
