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


def test_new_equal_position_remains_separate_from_existing_position():
    parent = source()
    body = request_for(parent)
    body["positions"] = [
        {**body["positions"][0], "quantity": 1},
        {"kind": "new", "line_key": "second", "name": "Konferencja", "unit": "szt.",
         "quantity": 1, "unit_price_grosze": 10000, "vat_rate_code": "23"},
    ]
    body["after_totals"] = {"net_grosze": 20000, "vat_grosze": 4600, "gross_grosze": 24600}
    result = c.prepare_correction(body, parent, "130706", {"id": "71", "name": "KOR TEST"})
    assert result["document"]["invoicecontents"]["0"]["invoicecontent"]["parent_id"] == 8101
    assert "parent_id" not in result["document"]["invoicecontents"]["1"]["invoicecontent"]
    assert result["totals"] == body["after_totals"]


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


def test_equal_rows_keep_separate_rounding_and_report_only_proven_identity():
    parent = source()
    parent["invoicecontents"]["1"] = copy.deepcopy(parent["invoicecontents"]["0"])
    parent["invoicecontents"]["1"]["invoicecontent"]["id"] = "8102"
    parent["total_composed"] = "246.00"
    body = request_for(parent)
    body["positions"] = [
        {**body["positions"][0], "quantity": 1},
        {**body["positions"][0], "quantity": 1, "line_key": "second", "parent_position_id": "8102"},
    ]
    body["after_totals"] = {"net_grosze": 20000, "vat_grosze": 4600, "gross_grosze": 24600}
    prepared = c.prepare_correction(body, parent, "130706", {"id": "71", "name": "KOR TEST"})
    assert len(prepared["document"]["invoicecontents"]) == 2
    after = copy.deepcopy(parent)
    after.update(id="9001", type="correction", parent={"id": "8001"}, series_id="71",
                 id_external=prepared["document"]["id_external"])
    after["invoicecontents"]["0"]["invoicecontent"]["id"] = "9102"
    after["invoicecontents"]["1"]["invoicecontent"]["id"] = "9101"
    result = c.verify_created(prepared, after, "9001", "130706")
    assert result["position_mapping"] == []
    assert result["equivalent_position_groups"] == [
        {"line_keys": ["conference", "second"], "position_ids": ["9101", "9102"]}]
    after["invoicecontents"]["0"]["invoicecontent"]["parent_id"] = "8101"
    after["invoicecontents"]["1"]["invoicecontent"]["parent_id"] = "8102"
    result = c.verify_created(prepared, after, "9001", "130706")
    assert result["equivalent_position_groups"] == []
    assert result["position_mapping"] == [
        {"line_key": "conference", "position_id": "9102"}, {"line_key": "second", "position_id": "9101"}]


@pytest.mark.parametrize("bad", ["different_quantity", "duplicate_parent", "foreign_parent"])
def test_equal_position_group_cannot_hide_changed_quantity_or_false_parent(bad):
    parent = source()
    body = request_for(parent)
    body["positions"][0]["quantity"] = 1
    body["positions"].append({"kind": "new", "line_key": "new", "name": "Konferencja", "unit": "szt.",
                              "quantity": 1, "unit_price_grosze": 10000, "vat_rate_code": "23"})
    body["after_totals"] = {"net_grosze": 20000, "vat_grosze": 4600, "gross_grosze": 24600}
    prepared = c.prepare_correction(body, parent, "130706", {"id": "71", "name": "KOR TEST"})
    after = source()
    after.update(id="9001", type="correction", parent_id="8001", series_id="71",
                 id_external=prepared["document"]["id_external"], total_composed="246.00")
    row = after["invoicecontents"]["0"]["invoicecontent"]
    row.update(id="9101", parent_id="8101")
    second = copy.deepcopy(row)
    second["id"] = "9102"
    after["invoicecontents"]["1"] = {"invoicecontent": second}
    if bad == "different_quantity":
        row.update(count="0", netto="0.00", brutto="0.00")
        second.update(count="2", netto="200.00", brutto="246.00")
        del second["parent_id"]
    elif bad == "foreign_parent":
        second["parent_id"] = "9999"
    with pytest.raises(c.StructuralContractError, match="created_positions_mismatch"):
        c.verify_created(prepared, after, "9001", "130706")


def test_equal_net_positions_are_not_merged_when_vat_rounding_would_change():
    parent = source()
    body = request_for(parent)
    body["positions"] += [{"kind": "new", "line_key": key, "name": "Dodatek", "unit": "szt.",
                           "quantity": 1, "unit_price_grosze": 3, "vat_rate_code": "23"} for key in ("a", "b")]
    # WO-891: rows stay separate (4 + 4 gross), the document total is the rate group: 6 + 1 = 7.
    body["after_totals"] = {"net_grosze": 6, "vat_grosze": 1, "gross_grosze": 7}
    prepared = c.prepare_correction(body, parent, "130706", {"id": "71", "name": "KOR TEST"})
    assert len(prepared["document"]["invoicecontents"]) == 3
    assert prepared["totals"] == body["after_totals"]
    assert c.line_totals("netto", "23", 2, 3)["gross_grosze"] == 7


# --- WO-891: wFirma NETTO document totals are per VAT-rate group, not per row ---

SERIES = {"id": "71", "name": "KOR TEST"}
TWO_AT_23 = [("8101", "1", "170.16", "222", "170.16", "209.30"),
             ("8102", "1", "170.16", "222", "170.16", "209.30")]


def parent_with(lines, total, mode="netto"):
    """lines: (id, count, price, vat_code_id, netto, brutto) exactly as the provider sends them."""
    parent = source(mode)
    parent["total_composed"] = total
    parent["invoicecontents"] = {str(i): {"invoicecontent": {
        "id": pid, "name": "Konferencja", "unit": "szt.", "count": count, "price": price,
        "netto": netto, "brutto": brutto, "vat_code": {"id": vat}}}
        for i, (pid, count, price, vat, netto, brutto) in enumerate(lines)}
    return parent


def remove_second_of_two(parent):
    body = request_for(parent)
    body["positions"] = [
        {**body["positions"][0], "quantity": 1, "unit_price_grosze": 17016},
        {**body["positions"][0], "quantity": 0, "unit_price_grosze": 17016,
         "line_key": "second", "parent_position_id": "8102"},
    ]
    body["after_totals"] = {"net_grosze": 17016, "vat_grosze": 3914, "gross_grosze": 20930}
    return body


def test_netto_parent_with_grouped_vat_rounding_is_accepted_with_group_totals():
    # Arrange
    parent = parent_with(TWO_AT_23, "418.59")
    # Act
    proof = c.project_parent(parent, "130706")
    # Assert
    assert proof["totals"] == {"net_grosze": 34032, "vat_grosze": 7827, "gross_grosze": 41859}
    assert [row["gross_grosze"] for row in proof["positions"]] == [20930, 20930]


def test_netto_parent_with_per_row_gross_sum_as_total_is_refused():
    # Arrange
    parent = parent_with(TWO_AT_23, "418.60")
    # Act / Assert
    with pytest.raises(c.StructuralContractError, match="document_total_mismatch"):
        c.project_parent(parent, "130706")


def test_netto_parent_with_mixed_rates_sums_each_rate_group_separately():
    # Arrange
    parent = parent_with(TWO_AT_23 + [("8103", "1", "100.04", "223", "100.04", "108.04")], "526.63")
    # Act
    proof = c.project_parent(parent, "130706")
    # Assert
    assert proof["totals"] == {"net_grosze": 44036, "vat_grosze": 8627, "gross_grosze": 52663}


def test_correction_removing_one_of_two_grouped_rows_is_validated_and_read_back():
    # Arrange
    parent = parent_with(TWO_AT_23, "418.59")
    body = remove_second_of_two(parent)
    prepared = c.prepare_correction(body, parent, "130706", SERIES)
    after = parent_with([("9101", "1", "170.16", "222", "170.16", "209.30"),
                         ("9102", "0", "170.16", "222", "0.00", "0.00")], "209.30")
    after.update(id="9001", type="correction", parent={"id": "8001"}, series_id="71",
                 id_external=prepared["document"]["id_external"])
    after["invoicecontents"]["0"]["invoicecontent"]["parent_id"] = "8101"
    after["invoicecontents"]["1"]["invoicecontent"]["parent_id"] = "8102"
    # Act
    result = c.verify_created(prepared, after, "9001", "130706")
    # Assert
    assert prepared["totals"] == body["after_totals"]
    assert body["parent"]["totals"]["gross_grosze"] - prepared["totals"]["gross_grosze"] == 20929
    assert result["parent"]["totals"] == body["after_totals"]


def test_request_with_per_row_after_totals_is_refused_when_group_total_differs():
    # Arrange
    parent = parent_with(TWO_AT_23, "418.59")
    body = remove_second_of_two(parent)
    body["positions"][1]["quantity"] = 1
    body["after_totals"] = {"net_grosze": 34032, "vat_grosze": 7828, "gross_grosze": 41860}
    # Act / Assert
    with pytest.raises(c.StructuralContractError, match="after_snapshot_mismatch"):
        c.prepare_correction(body, parent, "130706", SERIES)


@pytest.mark.parametrize("rows,expected", [
    ([("23", 17016), ("23", 17016)], (34032, 7827, 41859)),
    ([("23", 17016), ("23", 17016), ("8", 10004)], (44036, 8627, 52663)),
    ([("0", 10000), ("zw", 5000), ("np", 1)], (15001, 0, 15001)),
    ([("zw", 10000), ("23", 17016), ("23", 17016)], (44032, 7827, 51859)),
    ([("23", 3), ("23", 3), ("23", 0)], (6, 1, 7)),
    ([("23", 0)], (0, 0, 0)),
])
def test_netto_document_totals_round_vat_once_per_rate_code(rows, expected):
    # Arrange
    projected = [{"vat_rate_code": code, "net_grosze": net} for code, net in rows]
    # Act
    result = c.document_totals("netto", projected)
    # Assert
    assert tuple(result[k] for k in ("net_grosze", "vat_grosze", "gross_grosze")) == expected


def test_netto_parent_with_zero_and_exempt_rows_keeps_totals():
    # Arrange
    parent = parent_with([("8101", "1", "100.00", "225", "100.00", "100.00"),
                          ("8102", "1", "50.00", "226", "50.00", "50.00")], "150.00")
    # Act
    proof = c.project_parent(parent, "130706")
    # Assert
    assert proof["totals"] == {"net_grosze": 15000, "vat_grosze": 0, "gross_grosze": 15000}
    assert sorted(row["vat_rate_code"] for row in proof["positions"]) == ["0", "zw"]


@pytest.mark.parametrize("total,accepted", [("418.60", True), ("418.59", False)])
def test_brutto_parent_still_uses_the_per_row_sum(total, accepted):
    # Arrange
    parent = parent_with([("8101", "1", "209.30", "222", "170.16", "209.30"),
                          ("8102", "1", "209.30", "222", "170.16", "209.30")], total, mode="brutto")
    # Act / Assert
    if accepted:
        assert c.project_parent(parent, "130706")["totals"] == {
            "net_grosze": 34032, "vat_grosze": 7828, "gross_grosze": 41860}
    else:
        with pytest.raises(c.StructuralContractError, match="document_total_mismatch"):
            c.project_parent(parent, "130706")


@pytest.mark.parametrize("mutation", ["unknown_entry", "missing_vat", "row_net"])
def test_grouped_parent_with_an_unparsed_row_is_still_refused(mutation):
    # Arrange
    parent = parent_with(TWO_AT_23, "418.59")
    line = parent["invoicecontents"]["1"]["invoicecontent"]
    if mutation == "unknown_entry": parent["invoicecontents"]["extra"] = {}
    elif mutation == "missing_vat": line["vat_code"] = {"id": "99999"}
    else: line["netto"] = "170.15"
    # Act / Assert
    with pytest.raises(c.StructuralContractError):
        c.project_parent(parent, "130706")


@pytest.mark.parametrize("mode,rows", [
    ("netto", [{"vat_rate_code": "22", "net_grosze": 1}]),
    ("netto", [{"vat_rate_code": "23", "net_grosze": -1}]),
    ("netto", [{"vat_rate_code": "23", "net_grosze": True}]),
    ("other", []),
])
def test_document_totals_refuse_unknown_rate_or_amount(mode, rows):
    # Act / Assert
    with pytest.raises(c.StructuralContractError):
        c.document_totals(mode, rows)


def created_correction():
    """A prepared zeroing correction and the way wFirma reads it back (marker as sent)."""
    parent = source()
    body = request_for(parent)
    prepared = c.prepare_correction(body, parent, "130706", {"id": "71", "name": "KOR TEST"})
    after = source()
    after.update(id="9001", type="correction", parent={"id": "8001"}, series_id="71",
                 id_external=prepared["document"]["id_external"], total_composed="0.00")
    row = after["invoicecontents"].pop("0")
    row["invoicecontent"].update(id="9101", parent_id="8101", count="0", netto="0.00", brutto="0.00")
    after["invoicecontents"]["7"] = row
    return prepared, after


def test_wo984_correction_read_back_without_marker_is_recognised():
    # wFirma zwraca korekte z pustym `id_external` (zmierzone 2026-10-09 i 2026-10-12).
    prepared, after = created_correction()
    after["id_external"] = ""
    # Act
    result = c.verify_created(prepared, after, "9001", "130706")
    assert result["parent"]["external_key"] == ""
    assert result["position_mapping"] == [{"line_key": "conference", "position_id": "9101"}]


def test_wo984_correction_read_back_with_missing_marker_field_is_recognised():
    prepared, after = created_correction()
    del after["id_external"]
    # Act
    result = c.verify_created(prepared, after, "9001", "130706")
    assert result["parent"]["document_id"] == "9001"


def test_wo984_correction_read_back_with_the_exact_marker_is_still_recognised():
    prepared, after = created_correction()
    assert after["id_external"] == prepared["document"]["id_external"] != ""
    # Act
    result = c.verify_created(prepared, after, "9001", "130706")
    assert result["parent"]["external_key"] == prepared["document"]["id_external"]


def test_wo984_correction_with_a_foreign_marker_is_still_refused():
    prepared, after = created_correction()
    after["id_external"] = "mt1:" + "0" * 28
    # Act / Assert
    with pytest.raises(c.StructuralContractError, match="created_document_mismatch"):
        c.verify_created(prepared, after, "9001", "130706")


@pytest.mark.parametrize("fault", ["identity", "parent", "type", "series", "totals", "party", "positions"])
def test_wo984_empty_marker_does_not_relax_any_other_correction_check(fault):
    prepared, after = created_correction()
    after["id_external"] = ""
    document_id = "9001"
    if fault == "identity": document_id = "9002"
    elif fault == "parent": after["parent"] = {"id": "7999"}
    elif fault == "type": after["type"] = "normal"; del after["parent"]
    elif fault == "series": after["series_id"] = "72"
    elif fault == "totals": after["total_composed"] = "1.00"
    elif fault == "party": after["contractor"] = {"id": "7002"}
    else: after["invoicecontents"]["7"]["invoicecontent"]["count"] = "1"
    # Act / Assert
    with pytest.raises(c.StructuralContractError):
        c.verify_created(prepared, after, document_id, "130706")
