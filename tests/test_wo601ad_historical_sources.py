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
