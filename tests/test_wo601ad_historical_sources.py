"""Private history reader, no writes and no fallback to another tenant."""
from copy import deepcopy
import pytest
import app as a
from test_wo599c2b2_structural_workflow import harness, API_KEY
from test_wo601ad_grouped_document_contract import invoice

URL = "/api/workflow/historical-documents/source"
HEADERS = {"X-API-Key":API_KEY}


@pytest.mark.parametrize("kind", ["normal","proforma","correction"])
def test_history_reader_returns_complete_pricing_but_no_arbitrary_metadata(harness, kind, capsys):
    client,state = harness
    state["parent"] = invoice()
    state["parent"].update(type=kind,alreadypaid="0.00",private_note="MUST-NOT-LEAK")
    original = deepcopy(state["parent"])
    # Act
    response = client.post(URL,json=dict(company="md_test",company_id="130706",
        documents=[dict(id="8001",type=kind)]),headers=HEADERS)
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    assert data["company"] == "md_test" and data["company_id"] == "130706"
    assert data["invoices"][0]["type"] == kind
    assert data["invoices"][0]["alreadypaid"] == "0.00"
    assert data["invoices"][0]["invoicecontents"] == original["invoicecontents"]
    assert state["posts"] == [] and len(state["reads"]) == 1
    assert state["parent"] == original and response.headers["Cache-Control"] == "no-store"
    assert "MUST-NOT-LEAK" not in response.get_data(as_text=True)+capsys.readouterr().out


@pytest.mark.parametrize("fault", ["auth","pin","tenant","duplicate","id","type","extra","query","huge","duplicate_key"])
def test_history_reader_refuses_bad_scope_before_network(harness, fault):
    client,state = harness
    body = dict(company="md_test",company_id="130706",documents=[dict(id="8001",type="normal")])
    headers, url, raw = HEADERS,URL,None
    if fault == "auth": headers = {}
    elif fault == "pin": body["company_id"] = "777"
    elif fault == "tenant": body["company"] = "wrong"
    elif fault == "duplicate": body["documents"] *= 2
    elif fault == "id": body["documents"][0]["id"] = "../8001"
    elif fault == "type": body["documents"][0]["type"] = "unknown"
    elif fault == "extra": body["url"] = "https://example.invalid"
    elif fault == "query": url += "?company=md"
    elif fault == "huge": raw = b" "*8193
    else: raw = b'{"company":"md","company":"md_test"}'
    # Act
    response = client.post(url,json=body,headers=headers) if raw is None else client.post(url,data=raw,content_type="application/json",headers=headers)
    assert response.status_code >= 400
    assert state["tokens"] == state["reads"] == state["posts"] == []


@pytest.mark.parametrize("fault", ["unavailable","wrong_type","wrong_id"])
def test_missing_or_changed_provider_document_cannot_be_called_complete(harness, fault):
    client,state = harness
    state["parent"] = invoice()
    if fault == "unavailable": state["read_error"] = "8001"
    elif fault == "wrong_type": state["parent"]["type"] = "proforma"
    else: state["parent"]["id"] = "8002"
    # Act
    response = client.post(URL,json=dict(company="md_test",company_id="130706",
        documents=[dict(id="8001",type="normal")]),headers=HEADERS)
    assert response.status_code == 409 and response.get_json()["success"] is False
    assert state["posts"] == []


@pytest.mark.parametrize("form", ["nested", "scalar", "both", "zero", "missing"])
def test_history_preserves_actual_proforma_link_and_bounded_replacement_metadata(harness, form):
    client, state = harness
    state["parent"] = invoice()
    original = state["parent"]
    original.update(date="2026-08-31", description="Zamówienie: PF TEST/1 - opłacone",
                    alreadypaid=original["total"], private_note="MUST-NOT-LEAK")
    if form in {"nested", "both"}: original["order"] = {"id": "9001", "private": "MUST-NOT-LEAK"}
    if form in {"scalar", "both"}: original["order_id"] = "9001"
    if form == "zero": original["order"] = {"id": "0"}
    before = deepcopy(original)
    # Act
    response = client.post(URL, json=dict(company="md_test", company_id="130706",
        documents=[dict(id="8001", type="normal")]), headers=HEADERS)
    assert response.status_code == 200, response.get_json()
    current = response.get_json()["invoices"][0]
    for key in ("date", "description", "alreadypaid"):
        assert current[key] == original[key]
    if "order" in original: assert current["order"] == {"id": original["order"]["id"]}
    else: assert "order" not in current
    if "order_id" in original: assert current["order_id"] == original["order_id"]
    else: assert "order_id" not in current
    assert original == before and state["posts"] == []
    assert "MUST-NOT-LEAK" not in response.get_data(as_text=True)


@pytest.mark.parametrize("fault", ["conflict", "bad_id", "nested_shape", "bad_date", "huge_description", "description_type"])
def test_history_rejects_unusable_lineage_metadata_without_writes(harness, fault):
    client, state = harness
    state["parent"] = invoice()
    if fault == "conflict": state["parent"].update(order={"id": "9001"}, order_id="9002")
    elif fault == "bad_id": state["parent"]["order_id"] = "../9001"
    elif fault == "nested_shape": state["parent"]["order"] = []
    elif fault == "bad_date": state["parent"]["date"] = "2026-02-31"
    elif fault == "huge_description": state["parent"]["description"] = "x"*4097
    else: state["parent"]["description"] = {}
    # Act
    response = client.post(URL, json=dict(company="md_test", company_id="130706",
        documents=[dict(id="8001", type="normal")]), headers=HEADERS)
    assert response.status_code == 409
    assert response.get_json()["success"] is False and state["posts"] == []
