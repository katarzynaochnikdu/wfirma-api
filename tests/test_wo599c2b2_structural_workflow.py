"""Real Flask workflow; synthetic invoices and no external services."""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DATABASE_URL"] = ""
os.environ["MAKE_WEBHOOK_SEND_EMAIL_REQUEST"] = ""
os.environ["RENDER_EMAIL_KEY_SEND_REQUEST"] = ""
import app as app_module
import participant_change_correction as contract

API_KEY = "wo599-local-synthetic-key"
BASE = "/api/workflow/participant-change-correction"


def invoice(mode="netto"):
    return {
        "id": "8001", "type": "normal", "price_type": mode, "currency": "PLN",
        "corrections": "0", "contractor": {"id": "7001"},
        "contractor_detail": {"name": "Firma testowa", "country": "PL"},
        "total_composed": "123.00", "netto": "100.00", "tax": "23.00",
        "invoicecontents": {"0": {"invoicecontent": {
            "id": "8101", "name": "Konferencja testowa", "unit": "szt.",
            "count": "1", "price": "100.00" if mode == "netto" else "123.00",
            "netto": "100.00", "brutto": "123.00", "vat_code": {"id": "222"},
        }}},
    }


@pytest.fixture
def harness(monkeypatch):
    state = {"parent": invoice(), "reads": [], "posts": [], "tokens": [],
             "series": {"id": "71", "name": "Korekty TEST"}, "created": None,
             "create_response": None, "read_error": None}
    monkeypatch.setattr(app_module, "MAKE_RENDER_API_KEY", API_KEY)
    monkeypatch.setattr(app_module, "_pinned_recovery_company_id", lambda company: "130706")
    def load(**kwargs):
        state["tokens"].append(kwargs)
        return "synthetic-token"
    monkeypatch.setattr(app_module, "load_token", load)
    monkeypatch.setattr(app_module, "is_token_valid_for_company", lambda company: True)

    def read(token, **kwargs):
        state["reads"].append(kwargs)
        if state["read_error"] == kwargs["entity_id"]:
            return None, "unavailable"
        if kwargs["plural"] == "series":
            return copy.deepcopy(state["series"]), None
        return copy.deepcopy(state["parent"] if kwargs["entity_id"] == "8001" else state["created"]), None

    def post(url, **kwargs):
        state["posts"].append({"url": url, **kwargs})
        result = state["create_response"]
        if isinstance(result, BaseException):
            raise result
        if result is not None:
            return result
        return response(200, {"invoices": {"0": {"invoice": {"id": "9001"}}}})

    def deny(*args, **kwargs):
        raise AssertionError("Unexpected network access")

    monkeypatch.setattr(app_module, "_strict_wfirma_recovery_get", read)
    monkeypatch.setattr(requests.sessions.Session, "request", deny)
    monkeypatch.setattr(app_module.requests, "post", post)
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client(), state


def test_parent_endpoint_returns_exact_private_snapshot(harness):
    client, state = harness
    response = client.get(BASE + "/parent/8001?company=md_test", headers={"X-API-Key": API_KEY})
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["parent"]["totals"] == {"net_grosze": 10000, "vat_grosze": 2300, "gross_grosze": 12300}
    assert body["parent"]["positions"][0]["position_id"] == "8101"
    assert len(body["parent_sha256"]) == 64
    assert len(state["reads"]) == 1
    assert state["reads"][0]["company_id"] == "130706"


def test_parent_endpoint_requires_api_key_before_reading(harness):
    client, state = harness
    response = client.get(BASE + "/parent/8001?company=md_test")
    assert response.status_code == 401
    assert state["reads"] == []


def response(status, body):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode("utf-8")
    result.headers["Content-Type"] = "application/json"
    return result


def request_body(state):
    parent = contract.project_parent(state["parent"], "130706")
    mode = parent["price_model"]
    return {
        "contract_version": 1, "company": "md_test", "change_id": "synthetic-change-1",
        "parent": parent, "parent_sha256": contract.fingerprint(parent),
        "issue_date": "2026-09-11", "series_id": "71", "series_name": "Korekty TEST",
        "correction_reason": "Dodanie bankietu", "price_model": mode, "currency": "PLN",
        "positions": [
            {"kind": "existing", "line_key": "conference", "parent_position_id": "8101",
             "quantity": 1, "unit_price_grosze": 10000 if mode == "netto" else 12300, "vat_rate_code": "23"},
            {"kind": "new", "line_key": "banquet", "name": "Bankiet testowy", "unit": "szt.",
             "quantity": 1, "unit_price_grosze": 5000 if mode == "netto" else 6150, "vat_rate_code": "23"},
        ],
        "after_totals": {"net_grosze": 15000, "vat_grosze": 3450, "gross_grosze": 18450},
    }


def created_invoice(state, body):
    result = copy.deepcopy(state["parent"])
    result.update(id="9001", type="correction", parent={"id": "8001"},
                  series={"id": "71"}, fullnumber="KOR/TEST/1/2026", total_composed="184.50",
                  id_external=("mt1:" + contract.fingerprint({"change_id": body["change_id"], "parent": body["parent_sha256"]}))[:contract.MARKER_LIMIT])
    first = result["invoicecontents"]["0"]["invoicecontent"]
    first.update(id="9101", parent={"id": "8101"})
    result["invoicecontents"]["1"] = {"invoicecontent": {
        "id": "9102", "name": "Bankiet testowy", "unit": "szt.", "count": "1",
        "price": "50.00" if body["price_model"] == "netto" else "61.50",
        "netto": "50.00", "brutto": "61.50", "vat_code": {"id": "222"},
    }}
    return result


@pytest.mark.parametrize("mode", ["netto", "brutto"])
def test_correction_adds_new_position_with_exact_money_and_new_ids(harness, mode, capsys):
    client, state = harness
    state["parent"] = invoice(mode)
    body = request_body(state)
    state["created"] = created_invoice(state, body)

    result = client.post(BASE, json=body, headers={"X-API-Key": API_KEY})

    assert result.status_code == 200, result.get_json()
    data = result.get_json()
    assert data["success"] is True
    assert data["proof"]["parent"]["totals"] == body["after_totals"]
    assert data["proof"]["position_mapping"] == [
        {"line_key": "banquet", "position_id": "9102"}, {"line_key": "conference", "position_id": "9101"}]
    assert len(state["posts"]) == 1
    sent = state["posts"][0]
    assert "company_id=130706" in sent["url"]
    assert sent["timeout"] == 30 and sent["allow_redirects"] is False
    doc = sent["json"]["invoices"]["invoice"]
    assert doc["price_type"] == mode and doc["auto_send"] == 0
    assert doc["invoicecontents"]["0"]["invoicecontent"] == {
        "parent_id": 8101, "count": 1, "price": "100.00" if mode == "netto" else "123.00"}
    assert doc["invoicecontents"]["1"]["invoicecontent"] == {
        "name": "Bankiet testowy", "unit": "szt.", "vat": "23", "count": 1,
        "price": "50.00" if mode == "netto" else "61.50"}
    assert [item["entity_id"] for item in state["reads"]] == ["8001", "71", "9001"]
    assert state["tokens"] == [{"silent": True, "company": "md_test"}]
    log = capsys.readouterr().out
    assert "Firma testowa" not in log and "Bankiet" not in log and "9001" not in log


@pytest.mark.parametrize("fault", ["parent_drift", "price_drift", "total_drift", "series", "unknown_line", "missing_line", "receiver"])
def test_invalid_proof_never_reaches_create(harness, fault):
    client, state = harness
    body = request_body(state)
    if fault == "parent_drift":
        state["parent"]["contractor_detail"]["name"] = "Zmieniony nabywca"
    elif fault == "price_drift":
        body["positions"][0]["unit_price_grosze"] += 1
    elif fault == "total_drift":
        body["after_totals"]["gross_grosze"] += 1
    elif fault == "series":
        state["series"]["name"] = "Inna seria"
    elif fault == "unknown_line":
        body["positions"][0]["parent_position_id"] = "9999"
    elif fault == "missing_line":
        body["positions"].pop(0)
    else:
        state["parent"]["contractor_receiver"] = {"id": "7999"}
    result = client.post(BASE, json=body, headers={"X-API-Key": API_KEY})
    assert result.status_code == 409
    assert result.get_json()["outcome"] == "rejected"
    assert state["posts"] == []


@pytest.mark.parametrize("behavior,outcome", [
    (requests.Timeout("secret synthetic payload"), "unknown"),
    (response(500, {"error": "secret synthetic payload"}), "unknown"),
    (response(302, {}), "unknown"),
    (response(200, {}), "unknown"),
    (response(400, {"error": "secret synthetic payload"}), "rejected"),
    (response(200, {"status": {"code": "ERROR"}}), "rejected"),
])
def test_uncertain_create_is_not_retried(harness, behavior, outcome, capsys):
    client, state = harness
    state["create_response"] = behavior
    result = client.post(BASE, json=request_body(state), headers={"X-API-Key": API_KEY})
    assert result.status_code == 502
    assert result.get_json()["outcome"] == outcome
    assert len(state["posts"]) == 1 and len(state["reads"]) == 2
    assert "secret synthetic payload" not in result.get_data(as_text=True)
    captured = capsys.readouterr()
    assert "secret synthetic payload" not in captured.out + captured.err


@pytest.mark.parametrize("fault", ["unavailable", "buyer", "number", "parent", "line_price", "epoch", "mapping"])
def test_created_id_survives_every_readback_failure(harness, fault):
    client, state = harness
    body = request_body(state)
    readback = created_invoice(state, body)
    state["created"] = readback
    if fault == "unavailable":
        state["read_error"] = "9001"
    elif fault == "buyer":
        readback["contractor_detail"]["name"] = "Inny nabywca"
    elif fault == "number":
        readback["fullnumber"] = None
    elif fault == "parent":
        readback["parent"]["id"] = "8002"
    elif fault == "line_price":
        readback["invoicecontents"]["1"]["invoicecontent"]["price"] = "49.99"
    elif fault == "epoch":
        readback["price_type"] = "brutto"
    else:
        readback["invoicecontents"]["1"]["invoicecontent"]["parent_id"] = "8101"
    result = client.post(BASE, json=body, headers={"X-API-Key": API_KEY})
    assert result.status_code in (409, 502)
    assert result.get_json()["outcome"] == "created_unverified"
    assert result.get_json()["document_id"] == "9001"
    assert len(state["posts"]) == 1


@pytest.mark.parametrize("raw", [b"{}", b'{"company":"md","company":"test"}', b'{"number":NaN}', b"[1]", b"["*1200+b"]"*1200, b" "*(contract.MAX_BODY_BYTES+1)],
                         ids=["empty", "duplicate", "nan", "array", "depth", "oversized"])
def test_bad_bodies_do_not_read_provider_or_create(harness, raw):
    client, state = harness
    result = client.post(BASE, data=raw, content_type="application/json", headers={"X-API-Key": API_KEY})
    assert result.status_code == 409
    assert state["reads"] == state["posts"] == []


def test_post_authentication_precedes_body_and_provider(harness):
    client, state = harness
    result = client.post(BASE, json=request_body(state))
    assert result.status_code == 401 and result.get_json()["outcome"] == "rejected"
    assert state["reads"] == state["posts"] == state["tokens"] == []


@pytest.mark.parametrize("query", ["", "company=md&company=test", "company=unknown", "company=md&x=1"])
def test_parent_query_is_closed_before_provider(harness, query):
    client, state = harness
    result = client.get(BASE + "/parent/8001?" + query, headers={"X-API-Key": API_KEY})
    assert result.status_code == 400 and state["reads"] == []


@pytest.mark.parametrize("endpoint", ["get", "post"])
def test_no_oauth_never_falls_back_to_default_company(harness, monkeypatch, endpoint):
    client, state = harness
    monkeypatch.setattr(app_module, "is_token_valid_for_company", lambda company: False)
    result = (client.get(BASE + "/parent/8001?company=md_test", headers={"X-API-Key": API_KEY}) if endpoint == "get"
              else client.post(BASE, json=request_body(state), headers={"X-API-Key": API_KEY}))
    assert result.status_code == 503
    assert state["reads"] == state["posts"] == []


@pytest.mark.parametrize("value", ["secret\nsynthetic", "9001/secret", True, "09001"])
def test_malformed_provider_id_is_never_echoed_or_followed(harness, value, capsys):
    client, state = harness
    state["create_response"] = response(200, {"invoices": {"0": {"invoice": {"id": value}}}})
    result = client.post(BASE, json=request_body(state), headers={"X-API-Key": API_KEY})
    data = result.get_json()
    assert data["success"] is False and data["outcome"] == "created_unverified"
    assert "document_id" not in data and "secret" not in result.get_data(as_text=True)
    assert len(state["reads"]) == 2 and len(state["posts"]) == 1
    captured = capsys.readouterr()
    assert "secret" not in captured.out + captured.err


def test_multiple_returned_documents_are_unverified_not_success(harness):
    client, state = harness
    body = request_body(state)
    state["created"] = created_invoice(state, body)
    state["create_response"] = response(200, {"invoices": {
        "0": {"invoice": {"id": "9001"}}, "1": {"invoice": {"id": "9002"}}}})
    result = client.post(BASE, json=body, headers={"X-API-Key": API_KEY})
    assert result.get_json()["outcome"] == "created_unverified"
    assert result.get_json()["document_id"] == "9001"
    assert len(state["reads"]) == 2 and len(state["posts"]) == 1


def test_receiver_and_new_position_order_survive_successful_readback(harness):
    client, state = harness
    state["parent"]["contractor_receiver"] = {"id": "7999"}
    state["parent"]["contractor_detail_receiver"] = {"name": "Odbiorca testowy", "role": 2}
    body = request_body(state)
    state["created"] = created_invoice(state, body)
    first = state["created"]["invoicecontents"].pop("0")
    state["created"]["invoicecontents"]["7"] = first
    result = client.post(BASE, json=body, headers={"X-API-Key": API_KEY})
    assert result.status_code == 200
    doc = state["posts"][0]["json"]["invoices"]["invoice"]
    assert doc["contractor_receiver_id"] == 7999
    assert doc["contractor_detail_receiver"] == {"name": "Odbiorca testowy", "role": "2"}
