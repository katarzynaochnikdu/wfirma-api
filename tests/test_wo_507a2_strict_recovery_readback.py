"""WO-507A2-S — strict, tenant-bound recovery readback for wFirma documents.

The suite calls the real Flask handler while every provider transport and token lookup
is controlled.  Any accidental search, write verb, retry or tenant fallback fails loudly.
"""

from __future__ import annotations

import json
import inspect
import os
import sys
from dataclasses import dataclass
from typing import Any

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_URL"] = ""
os.environ["MAKE_WEBHOOK_SEND_EMAIL_REQUEST"] = ""
os.environ["RENDER_EMAIL_KEY_SEND_REQUEST"] = ""

import app as app_module  # noqa: E402


API_KEY = "wo507a2s-test-api-key"
MAX_BYTES = 2 * 1024 * 1024


@dataclass
class FakeStreamResponse:
    status_code: int
    payload: Any = None
    raw_body: bytes | None = None
    headers: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.raw_body is None:
            self.raw_body = json.dumps(self.payload, ensure_ascii=False).encode("utf-8")
        if self.headers is None:
            self.headers = {"Content-Length": str(len(self.raw_body))}
        self.closed = False

    def iter_content(self, chunk_size: int):
        assert chunk_size == 64 * 1024
        body = self.raw_body or b""
        for offset in range(0, len(body), chunk_size):
            yield body[offset : offset + chunk_size]

    def close(self) -> None:
        self.closed = True


def _entity_response(plural: str, singular: str, entity: dict[str, Any]):
    return FakeStreamResponse(200, {plural: {"0": {singular: entity}}})


def _invoice(
    invoice_id: str = "8101",
    *,
    contractor_id: str = "7101",
    receiver_id: str | None = "7201",
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": invoice_id,
        "fullnumber": "FV/EV/TEST/50/9/2026",
        "contractor": {"id": contractor_id},
        "price_type": "brutto",
        "date": "2026-09-03",
        "disposaldate": "2026-09-03",
        "currency": "PLN",
        "description": "Controlled recovery proof",
        "total_composed": "123.00",
        "invoicecontents": {},
    }
    if receiver_id is not None:
        value["contractor_receiver"] = {"id": receiver_id}
        value["contractor_detail_receiver"] = {
            "role": "2",
            "name": "Receiver Test",
            "nip": "0000000000-00000",
            "street": "Testowa 2",
            "zip": "00-002",
            "city": "Warszawa",
        }
    else:
        value["contractor_receiver"] = {"id": "0"}
    return value


def _contractor(contractor_id: str, *, name: str) -> dict[str, Any]:
    return {
        "id": contractor_id,
        "name": name,
        "nip": "0000000000",
        "street": "Testowa 1",
        "zip": "00-001",
        "city": "Warszawa",
    }


@pytest.fixture
def harness(monkeypatch):
    state: dict[str, Any] = {
        "token_companies": [],
        "validity_companies": [],
        "gets": [],
        "responses": [],
    }
    monkeypatch.setattr(app_module, "MAKE_RENDER_API_KEY", API_KEY)

    def fake_load_token(*, silent=False, company=None):
        state["token_companies"].append((silent, company))
        return f"token-for-{company}"

    def fake_is_valid(company=None):
        state["validity_companies"].append(company)
        return True

    def fake_get(url: str, **kwargs):
        state["gets"].append({"url": url, **kwargs})
        if not state["responses"]:
            raise AssertionError(f"unexpected recovery GET: {url}")
        behavior = state["responses"].pop(0)
        if isinstance(behavior, BaseException):
            raise behavior
        return behavior

    def forbidden_transport(*_args, **_kwargs):
        raise AssertionError("WO-507A2-S must never use a provider write/search transport")

    monkeypatch.setattr(app_module, "load_token", fake_load_token)
    monkeypatch.setattr(app_module, "is_token_valid_for_company", fake_is_valid)
    monkeypatch.setattr(app_module.requests, "get", fake_get)
    monkeypatch.setattr(app_module.requests, "post", forbidden_transport)
    monkeypatch.setattr(app_module.requests, "put", forbidden_transport)
    monkeypatch.setattr(app_module.requests, "patch", forbidden_transport)
    monkeypatch.setattr(app_module.requests, "delete", forbidden_transport)
    monkeypatch.delenv("WFIRMA_MD_COMPANY_ID", raising=False)
    monkeypatch.delenv("WFIRMA_TEST_COMPANY_ID", raising=False)
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client(), state


def _assert_get_budget(call: dict[str, Any], *, path: str, company_id: str) -> None:
    assert call["url"] == f"https://api2.wfirma.pl/{path}"
    assert call["params"] == {
        "inputFormat": "json",
        "outputFormat": "json",
        "oauth_version": "2",
        "company_id": company_id,
    }
    assert call["timeout"] == 8
    assert call["allow_redirects"] is False
    assert call["stream"] is True
    assert call["headers"]["Authorization"].startswith("Bearer token-for-")


def test_recovery_readback_returns_exact_tenant_bound_invoice_and_parties(
    harness, monkeypatch
):
    client, state = harness
    monkeypatch.setenv("WFIRMA_TEST_COMPANY_ID", "230706")
    responses = [
        _entity_response("invoices", "invoice", _invoice()),
        _entity_response("contractors", "contractor", _contractor("7101", name="Buyer Test")),
        _entity_response("contractors", "contractor", _contractor("7201", name="Receiver Test")),
    ]
    state["responses"].extend(responses)

    # Act
    response = client.get(
        "/api/recovery/invoice/8101?company=test",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "proof": {
            "version": 1,
            "company": "test",
            "company_id": "230706",
            "invoice": _invoice(),
            "contractor": _contractor("7101", name="Buyer Test"),
            "receiver": _contractor("7201", name="Receiver Test"),
        },
    }
    assert state["token_companies"] == [(True, "test")]
    assert state["validity_companies"] == ["test"]
    assert len(state["gets"]) == 3
    _assert_get_budget(state["gets"][0], path="invoices/get/8101", company_id="230706")
    _assert_get_budget(state["gets"][1], path="contractors/get/7101", company_id="230706")
    _assert_get_budget(state["gets"][2], path="contractors/get/7201", company_id="230706")
    assert all(item.closed for item in responses)


@pytest.mark.parametrize("company", ["md", "md_test"])
def test_recovery_readback_md_variants_share_pinned_credentials_but_preserve_request(
    harness, company
):
    client, state = harness
    state["responses"].extend(
        [
            _entity_response("invoices", "invoice", _invoice(receiver_id=None)),
            _entity_response("contractors", "contractor", _contractor("7101", name="Buyer Test")),
        ]
    )

    # Act
    response = client.get(
        f"/api/recovery/invoice/8101?company={company}",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    assert response.get_json()["proof"]["company"] == company
    assert response.get_json()["proof"]["company_id"] == "130706"
    assert response.get_json()["proof"]["receiver"] is None
    assert state["token_companies"] == [(True, company)]
    assert state["validity_companies"] == [company]
    assert len(state["gets"]) == 2


@pytest.mark.parametrize(
    "target",
    [
        "/api/recovery/invoice/8101",
        "/api/recovery/invoice/8101?company=",
        "/api/recovery/invoice/8101?company=unknown",
        "/api/recovery/invoice/8101?company=md&company=test",
        "/api/recovery/invoice/8101?company=md&extra=1",
        "/api/recovery/invoice/0?company=md",
        "/api/recovery/invoice/08101?company=md",
        "/api/recovery/invoice/none?company=md",
    ],
)
def test_recovery_readback_invalid_request_stops_before_token_or_transport(harness, target):
    client, state = harness

    # Act
    response = client.get(target, headers={"X-API-Key": API_KEY})

    assert response.status_code == 400
    assert response.get_json() == {"success": False, "error": "invalid_request"}
    assert state["token_companies"] == []
    assert state["validity_companies"] == []
    assert state["gets"] == []


@pytest.mark.parametrize(
    ("headers", "expected_status"),
    [({}, 401), ({"X-API-Key": "wrong"}, 403)],
)
def test_recovery_readback_auth_failure_has_no_token_or_transport(
    harness, headers, expected_status
):
    client, state = harness

    # Act
    response = client.get("/api/recovery/invoice/8101?company=md", headers=headers)

    assert response.status_code == expected_status
    assert state["token_companies"] == []
    assert state["validity_companies"] == []
    assert state["gets"] == []


def test_recovery_readback_missing_test_company_pin_never_falls_back_or_searches(harness):
    client, state = harness

    # Act
    response = client.get(
        "/api/recovery/invoice/8101?company=test",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 503
    assert response.get_json() == {
        "success": False,
        "error": "recovery_configuration_unavailable",
    }
    assert state["token_companies"] == []
    assert state["validity_companies"] == []
    assert state["gets"] == []


def test_recovery_readback_unavailable_oauth_stops_before_provider_get(harness, monkeypatch):
    client, state = harness
    monkeypatch.setattr(app_module, "load_token", lambda **_kwargs: None)

    # Act
    response = client.get(
        "/api/recovery/invoice/8101?company=md",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 401
    assert response.get_json() == {"success": False, "error": "oauth_unavailable"}
    assert state["gets"] == []


@pytest.mark.parametrize(
    ("behavior", "expected_status", "expected_error"),
    [
        (requests.Timeout("secret reflected by provider"), 502, "recovery_read_unavailable"),
        (FakeStreamResponse(302, {"location": "https://evil.invalid/secret"}), 502, "recovery_read_unavailable"),
        (FakeStreamResponse(404, {"secret": "must-not-leak"}), 404, "document_not_found"),
        (FakeStreamResponse(500, {"secret": "must-not-leak"}), 502, "recovery_read_unavailable"),
        (FakeStreamResponse(200, raw_body=b"not-json"), 502, "recovery_read_unavailable"),
        (
            FakeStreamResponse(
                200,
                payload={},
                raw_body=b"x" * (MAX_BYTES + 1),
                headers={"Content-Length": str(MAX_BYTES + 1)},
            ),
            502,
            "recovery_read_unavailable",
        ),
    ],
)
def test_recovery_readback_invoice_failure_is_closed_without_retry_or_leak(
    harness, behavior, expected_status, expected_error, capsys
):
    client, state = harness
    state["responses"].append(behavior)

    # Act
    response = client.get(
        "/api/recovery/invoice/8101?company=md",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == expected_status
    assert response.get_json() == {"success": False, "error": expected_error}
    captured = capsys.readouterr()
    evidence = response.get_data(as_text=True) + captured.out + captured.err
    assert "secret" not in evidence
    assert len(state["gets"]) == 1
    assert state["responses"] == []


@pytest.mark.parametrize(
    "invoice_payload",
    [
        {"invoices": {}},
        {
            "invoices": {
                "0": {"invoice": _invoice()},
                "1": {"invoice": _invoice("8102")},
            }
        },
        {"invoices": {"0": {"invoice": _invoice("8102")}}},
        {"invoices": {"0": {"invoice": {**_invoice(), "contractor": {"id": "0"}}}}},
        {"invoices": {"0": {"invoice": {**_invoice(), "contractor_receiver": {"id": "bad"}}}}},
    ],
)
def test_recovery_readback_malformed_invoice_or_relation_stops_before_party_get(
    harness, invoice_payload
):
    client, state = harness
    state["responses"].append(FakeStreamResponse(200, invoice_payload))

    # Act
    response = client.get(
        "/api/recovery/invoice/8101?company=md",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 502
    assert response.get_json() == {
        "success": False,
        "error": "recovery_read_unavailable",
    }
    assert len(state["gets"]) == 1


def test_recovery_readback_party_id_mismatch_discards_partial_proof(harness):
    client, state = harness
    state["responses"].extend(
        [
            _entity_response("invoices", "invoice", _invoice()),
            _entity_response("contractors", "contractor", _contractor("9999", name="Wrong Buyer")),
        ]
    )

    # Act
    response = client.get(
        "/api/recovery/invoice/8101?company=md",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 502
    assert response.get_json() == {
        "success": False,
        "error": "recovery_read_unavailable",
    }
    assert "proof" not in response.get_json()
    assert len(state["gets"]) == 2


def test_recovery_readback_invalid_company_pin_stops_before_oauth_and_transport(
    harness, monkeypatch
):
    client, state = harness
    monkeypatch.setenv("WFIRMA_TEST_COMPANY_ID", " 230706 ")

    # Act
    response = client.get(
        "/api/recovery/invoice/8101?company=test",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 503
    assert response.get_json() == {
        "success": False,
        "error": "recovery_configuration_unavailable",
    }
    assert state["token_companies"] == []
    assert state["gets"] == []


def test_recovery_readback_expired_oauth_stops_before_provider_get(harness, monkeypatch):
    client, state = harness
    monkeypatch.setattr(app_module, "is_token_valid_for_company", lambda _company: False)

    # Act
    response = client.get(
        "/api/recovery/invoice/8101?company=md",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 401
    assert response.get_json() == {"success": False, "error": "oauth_unavailable"}
    assert state["gets"] == []


def test_recovery_readback_receiver_id_mismatch_discards_all_proof(harness):
    client, state = harness
    state["responses"].extend(
        [
            _entity_response("invoices", "invoice", _invoice()),
            _entity_response("contractors", "contractor", _contractor("7101", name="Buyer Test")),
            _entity_response("contractors", "contractor", _contractor("9999", name="Wrong Receiver")),
        ]
    )

    # Act
    response = client.get(
        "/api/recovery/invoice/8101?company=md",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 502
    assert response.get_json() == {
        "success": False,
        "error": "recovery_read_unavailable",
    }
    assert len(state["gets"]) == 3


@pytest.mark.parametrize("party", ["contractor", "receiver"])
def test_recovery_readback_missing_party_is_not_misreported_as_missing_document(
    harness, party
):
    client, state = harness
    state["responses"].append(
        _entity_response("invoices", "invoice", _invoice())
    )
    if party == "contractor":
        state["responses"].append(FakeStreamResponse(404, {"status": "missing"}))
    else:
        state["responses"].extend(
            [
                _entity_response("contractors", "contractor", _contractor("7101", name="Buyer Test")),
                FakeStreamResponse(404, {"status": "missing"}),
            ]
        )

    # Act
    response = client.get(
        "/api/recovery/invoice/8101?company=md",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 502
    assert response.get_json() == {
        "success": False,
        "error": "recovery_read_unavailable",
    }


def test_recovery_readback_contract_has_fixed_limits_and_no_write_verb():
    assert app_module.WFIRMA_RECOVERY_READ_TIMEOUT_SECONDS == 8
    assert app_module.WFIRMA_RECOVERY_RESPONSE_MAX_BYTES == MAX_BYTES

    helper_source = "\n".join(
        inspect.getsource(function)
        for function in (
            app_module._strict_wfirma_recovery_get,
            app_module.wfirma_get_recovery_invoice_proof,
            app_module.api_get_recovery_invoice,
        )
    )

    # Act / Assert
    assert helper_source.count("requests.get(") == 1
    assert "requests.post(" not in helper_source
    assert "requests.put(" not in helper_source
    assert "requests.patch(" not in helper_source
    assert "requests.delete(" not in helper_source
    assert "wfirma_get_company_id" not in helper_source
