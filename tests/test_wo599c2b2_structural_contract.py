"""Pure structural invoice proof; expected amounts are literal integer cents."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import participant_change_correction as c


def source(mode="netto"):
    return {
        "id": "8001", "type": "normal", "price_type": mode, "currency": "PLN", "corrections": "0",
        "contractor": {"id": "7001"}, "contractor_detail": {"name": "Syntetyczna firma", "country": "PL"},
        "total_composed": "123.00", "invoicecontents": {"0": {"invoicecontent": {
            "id": "8101", "name": "Konferencja", "unit": "szt.", "count": "1",
            "price": "100.00" if mode == "netto" else "123.00", "netto": "100.00", "brutto": "123.00",
            "vat_code": {"id": "222"},
        }}},
    }


def request_for(parent, mode="netto"):
    proof = c.project_parent(parent, "130706")
    return {
        "contract_version": 1, "company": "md_test", "change_id": "synthetic-1",
        "parent": proof, "parent_sha256": c.fingerprint(proof), "issue_date": "2026-09-11",
        "series_id": "71", "series_name": "KOR TEST", "correction_reason": "Zmniejszenie liczby biletow",
        "price_model": mode, "currency": "PLN", "positions": [{
            "kind": "existing", "line_key": "conference", "parent_position_id": "8101",
            "quantity": 0, "unit_price_grosze": 10000 if mode == "netto" else 12300, "vat_rate_code": "23",
        }], "after_totals": {"net_grosze": 0, "vat_grosze": 0, "gross_grosze": 0},
    }


@pytest.mark.parametrize("mode,rate,qty,price,expected", [
    ("netto", "23", 9, 39837, (358533, 82463, 440996)),
    ("brutto", "23", 9, 49000, (358537, 82463, 441000)),
    ("netto", "23", 3, 47290, (141870, 32630, 174500)),
    ("brutto", "23", 1, 174500, (141870, 32630, 174500)),
    ("netto", "8", 3, 123, (369, 30, 399)),
    ("brutto", "8", 3, 123, (342, 27, 369)),
    ("netto", "5", 1, 10, (10, 1, 11)),
    ("brutto", "5", 1, 11, (10, 1, 11)),
    *[(mode, rate, 3, 123, (369, 0, 369)) for mode in ("netto", "brutto") for rate in ("0", "zw", "np")],
    *[(mode, "23", 0, 123, (0, 0, 0)) for mode in ("netto", "brutto")],
    *[(mode, "23", 3, 0, (0, 0, 0)) for mode in ("netto", "brutto")],
])
def test_line_rounding_matches_literal_cents(mode, rate, qty, price, expected):
    result = c.line_totals(mode, rate, qty, price)
    assert tuple(result[k] for k in ("net_grosze", "vat_grosze", "gross_grosze")) == expected


@pytest.mark.parametrize("mode", ["netto", "brutto"])
def test_cancellation_keeps_existing_row_and_receiver_without_mutating_inputs(mode):
    parent = source(mode)
    parent["contractor_receiver"] = {"id": "7999"}
    parent["contractor_detail_receiver"] = {"name": "Odbiorca testowy", "role": 2, "city": "Testowo", "ignored": "never copy"}
    body = request_for(parent, mode)
    before = copy.deepcopy((body, parent))
    prepared = c.prepare_correction(body, parent, "130706", {"id": "71", "name": "KOR TEST"})
    assert (body, parent) == before
    assert prepared["totals"] == {"net_grosze": 0, "vat_grosze": 0, "gross_grosze": 0}
    assert prepared["document"]["invoicecontents"]["0"]["invoicecontent"] == {
        "parent_id": 8101, "count": 0, "price": "100.00" if mode == "netto" else "123.00"}
    assert prepared["document"]["contractor_receiver_id"] == 7999
    assert prepared["document"]["contractor_detail_receiver"] == {"name": "Odbiorca testowy", "role": "2", "city": "Testowo"}


@pytest.mark.parametrize("field,value", [("quantity", True), ("quantity", 1.0), ("quantity", -1), ("quantity", 5001),
    ("unit_price_grosze", True), ("unit_price_grosze", 1.1), ("unit_price_grosze", "10000"),
    ("unit_price_grosze", c.MAX_MONEY+1), ("vat_rate_code", 23), ("vat_rate_code", "0.23"),
    ("vat_rate_code", []), ("parent_position_id", 8101), ("parent_position_id", "08101"),
    ("kind", "existing "), ("line_key", "a\nb"), ("line_key", "a\u001bb")])
def test_invalid_line_never_builds_document(field, value):
    parent = source()
    body = request_for(parent)
    body["positions"][0][field] = value
    with pytest.raises(c.StructuralContractError):
        c.prepare_correction(body, parent, "130706", {"id": "71", "name": "KOR TEST"})


@pytest.mark.parametrize("field,value", [("contract_version", True), ("company", "other"), ("issue_date", "2026-02-30"),
    ("issue_date", "20260911"), ("currency", "EUR"), ("series_id", 71), ("series_id", "071"),
    ("price_model", "unknown"), ("price_model", None), ("correction_reason", "x\r\ny"),
    ("parent_sha256", "0"*64), ("positions", []), ("positions", [{}]*501)])
def test_closed_request_rejects_invalid_fields(field, value):
    body = request_for(source())
    body[field] = value
    with pytest.raises(c.StructuralContractError):
        c.decode_request(json.dumps(body).encode("utf-8"))


def test_parent_absent_epoch_is_legacy_net_but_explicit_unknown_never_is():
    parent = source()
    del parent["price_type"]
    assert c.project_parent(parent, "130706")["price_model"] == "netto"
    for value in (None, "", "NETTO", "other", 0):
        parent["price_type"] = value
        with pytest.raises(c.StructuralContractError):
            c.project_parent(parent, "130706")


@pytest.mark.parametrize("mutation", ["corrected", "total", "line_net", "line_gross", "discount", "duplicate_id", "unknown_entry", "missing_count", "missing_vat", "receiver_missing", "buyer_id_conflict"])
def test_parent_projection_rejects_incomplete_or_inconsistent_evidence(mutation):
    parent = source()
    line = parent["invoicecontents"]["0"]["invoicecontent"]
    if mutation == "corrected": parent["corrections"] = "1"
    elif mutation == "total": parent["total_composed"] = "122.99"
    elif mutation == "line_net": line["netto"] = "99.99"
    elif mutation == "line_gross": line["brutto"] = "122.99"
    elif mutation == "discount": line["discount"] = "1.00"
    elif mutation == "duplicate_id": parent["invoicecontents"]["1"] = copy.deepcopy(parent["invoicecontents"]["0"])
    elif mutation == "unknown_entry": parent["invoicecontents"]["extra"] = {}
    elif mutation == "missing_count": del line["count"]
    elif mutation == "missing_vat": line["vat_code"] = {"id": "99999"}
    elif mutation == "receiver_missing": parent["contractor_receiver"] = {"id": "7999"}
    else: parent["contractor_id"] = "7002"
    with pytest.raises(c.StructuralContractError):
        c.project_parent(parent, "130706")


def test_readback_matches_identity_not_provider_order_and_can_be_next_parent():
    parent = source()
    body = request_for(parent)
    prepared = c.prepare_correction(body, parent, "130706", {"id": "71", "name": "KOR TEST"})
    after = source()
    after.update(id="9001", type="correction", parent={"id": "8001"}, series_id="71",
                 id_external=prepared["document"]["id_external"], total_composed="0.00")
    row = after["invoicecontents"].pop("0")
    row["invoicecontent"].update(id="9101", parent_id="8101", count="0", netto="0.00", brutto="0.00")
    after["invoicecontents"]["7"] = row
    result = c.verify_created(prepared, after, "9001", "130706")
    assert result["position_mapping"] == [{"line_key": "conference", "position_id": "9101"}]
    assert result["parent"]["positions"][0]["source_parent_id"] == "8101"
    assert result["parent_sha256"] == c.fingerprint(c.project_parent(after, "130706"))


def test_duplicate_signature_is_refused_instead_of_guessing_position_mapping():
    parent = source()
    body = request_for(parent)
    body["positions"] = [
        {**body["positions"][0], "quantity": 1},
        {"kind": "new", "line_key": "second", "name": "Konferencja", "unit": "szt.",
         "quantity": 1, "unit_price_grosze": 10000, "vat_rate_code": "23"},
    ]
    body["after_totals"] = {"net_grosze": 20000, "vat_grosze": 4600, "gross_grosze": 24600}
    with pytest.raises(c.StructuralContractError, match="ambiguous_result_positions"):
        c.prepare_correction(body, parent, "130706", {"id": "71", "name": "KOR TEST"})


@pytest.mark.parametrize("metadata", [{"total": "2"}, {"page": "1"}, {"total": True}, {}, None])
def test_unproved_position_coverage_is_refused(metadata):
    parent = source()
    parent["invoicecontents"]["parameters"] = metadata
    with pytest.raises(c.StructuralContractError):
        c.project_parent(parent, "130706")


def test_exact_position_count_metadata_is_accepted():
    parent = source()
    parent["invoicecontents"]["parameters"] = {"total": "1"}
    assert len(c.project_parent(parent, "130706")["positions"]) == 1
