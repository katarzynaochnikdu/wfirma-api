"""WO-502 — strukturalne wyniki tworzenia dokumentow w obu workflow Flask.

Testy uruchamiaja prawdziwe handlery, ale blokuja cala siec poza kontrolowanym
transportem ``invoices/add``. Nie korzystaja z bazy, tokenow ani danych produkcyjnych.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any

import pytest
import requests
from werkzeug.exceptions import BadRequest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import app.py uruchamia istniejace hooki startupowe. Puste wartosci ustawione
# PRZED importem blokuja w testach polaczenie DB oraz monitor tokenu/emaila.
os.environ["DATABASE_URL"] = ""
os.environ["MAKE_WEBHOOK_SEND_EMAIL_REQUEST"] = ""
os.environ["RENDER_EMAIL_KEY_SEND_REQUEST"] = ""

import app as app_module  # noqa: E402


API_KEY = "wo502-test-api-key"
EXACT_KSEF_BATCH_BLOCK = (
    "Nie można wystawić korekty do faktury w trakcie wysyłki wsadowej do KSeF"
)
NEAR_KSEF_BATCH_BLOCK = f"{EXACT_KSEF_BATCH_BLOCK} dla dokumentu testowego"


@dataclass
class FakeResponse:
    status_code: int
    payload: Any = None
    text: str = ""
    headers: dict[str, str] | None = None
    content: bytes = b""

    def __post_init__(self) -> None:
        if not self.text and self.payload is not None:
            self.text = json.dumps(self.payload, ensure_ascii=False)
        if self.headers is None:
            self.headers = {"Content-Type": "application/json"}

    def json(self) -> Any:
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload

    def __bool__(self) -> bool:
        # requests.Response jest falsy dla HTTP >= 400. Atrapa ma odtwarzac ten
        # detal, bo klasyfikator nie moze mylic 5xx z brakiem odpowiedzi.
        return self.status_code < 400


@pytest.fixture
def workflow_harness(monkeypatch):
    """Real Flask handlers with every external integration fail-closed mocked."""
    state: dict[str, Any] = {
        "create_behavior": FakeResponse(200, payload={}),
        "create_calls": [],
    }

    monkeypatch.setattr(app_module, "MAKE_RENDER_API_KEY", API_KEY)
    monkeypatch.setattr(app_module, "load_token", lambda *args, **kwargs: "test-token")
    monkeypatch.setattr(app_module, "is_token_valid", lambda: True)
    monkeypatch.setattr(
        app_module,
        "check_refresh_token_expiry_for_company",
        lambda *args, **kwargs: (None, None),
    )
    monkeypatch.setattr(
        app_module, "send_token_expiry_notification", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        app_module, "wfirma_get_company_id", lambda *args, **kwargs: "130706"
    )
    monkeypatch.setattr(
        app_module,
        "wfirma_find_series_by_name",
        lambda *args, **kwargs: {"id": "71", "name": "Eventy Faktura VAT TEST"},
    )
    monkeypatch.setattr(app_module, "wfirma_list_series", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        app_module,
        "wfirma_get_invoice_pdf",
        lambda *args, **kwargs: FakeResponse(404, text="not found"),
    )

    def fake_post(url: str, **kwargs):
        if "/invoices/add" not in url:
            raise AssertionError(f"WO-502 test blocked unexpected network call: {url}")
        state["create_calls"].append({"url": url, **kwargs})
        behavior = state["create_behavior"]
        if isinstance(behavior, BaseException):
            raise behavior
        return behavior

    monkeypatch.setattr(app_module.requests, "post", fake_post)
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client(), state


def _invoice_request(*, price_mode: str = "netto") -> dict[str, Any]:
    price_key = "unit_price_gross" if price_mode == "brutto" else "unit_price_net"
    body: dict[str, Any] = {
        "company": "md",
        "existing_contractor_id": 7001,
        "nip": "0000000000",
        "purchaser_name": "Firma Testowa",
        "series_name": "Eventy Faktura VAT TEST",
        "mark_as_paid": False,
        "invoice": {
            "issue_date": "2026-08-28",
            "payment_due_days": 7,
            "positions": [
                {
                    "name": "Bilet testowy",
                    "quantity": 1,
                    price_key: 123.00,
                    "vat_rate": 23,
                }
            ],
        },
    }
    if price_mode == "brutto":
        body["price_mode"] = "brutto"
    return body


def _parent_invoice(*, price_mode: str = "netto", with_receiver: bool = False) -> dict[str, Any]:
    invoice: dict[str, Any] = {
        "id": "8001",
        "fullnumber": "FV/EV/TEST/1/8/2026",
        "contractor": {"id": "7001"},
        "invoicecontents": {
            "0": {
                "invoicecontent": {
                    "id": "8101",
                    "name": "Bilet testowy",
                    "count": "1",
                    "price": "123.00",
                    "vat_code": {"id": "222"},
                }
            }
        },
    }
    if price_mode == "brutto":
        invoice["price_type"] = "brutto"
    if with_receiver:
        invoice.update(
            {
                "contractor_receiver": {"id": "7002"},
                "contractor_detail_receiver": {
                    "role": "2",
                    "name": "Odbiorca Testowy",
                    "tax_id_type": "none",
                    "street": "Testowa 1",
                    "zip": "00-000",
                    "city": "Warszawa",
                    "country": "PL",
                },
            }
        )
    return invoice


def _correction_request() -> dict[str, Any]:
    return {
        "company": "md",
        "parent_invoice_id": 8001,
        "correction_reason": "Korekta testowa",
        "full_correction": True,
        "series_name": "Eventy Korekta TEST",
    }


def _success_response(*, document_id: str, fullnumber: str, document_type: str) -> FakeResponse:
    return FakeResponse(
        200,
        payload={
            "status": {"code": "OK"},
            "invoices": {
                "0": {
                    "invoice": {
                        "id": document_id,
                        "fullnumber": fullnumber,
                        "type": document_type,
                        "date": "2026-08-28",
                        "total": "123.00",
                        "paymentstate": "unpaid",
                    }
                }
            },
        },
    )


def _only_create_call(state: dict[str, Any]) -> dict[str, Any]:
    assert len(state["create_calls"]) == 1, "workflow may issue at most one invoices/add"
    call = state["create_calls"][0]
    assert call.get("timeout") == 30, "the sole create transport must have a 30 s timeout"
    return call


def _assert_failed_outcome(data: dict[str, Any], expected: str) -> None:
    assert data["success"] is False
    assert data["outcome"] == expected


def test_document_outcome_envelope_preserves_http_exception_status():
    @app_module.document_outcome_envelope
    def dummy_bad_request_handler():
        raise BadRequest("controlled invalid document request")

    with app_module.app.test_request_context("/_wo502-http-exception"):
        # Act
        response = app_module.app.make_response(dummy_bad_request_handler())

    data = response.get_json()
    assert response.status_code == 400
    assert data["success"] is False
    assert data["outcome"] == "rejected"
    assert isinstance(data["error"], str)
    assert "request" in data["error"].strip().lower()
    assert "internal" not in data["error"].lower()


def test_invoice_missing_api_key_keeps_auth_error_and_is_rejected(workflow_harness):
    client, state = workflow_harness

    # Act
    response = client.post(
        "/api/workflow/create-invoice-from-nip",
        json=_invoice_request(),
    )

    data = response.get_json()
    assert response.status_code == 401
    assert state["create_calls"] == []
    assert data["error"] == "Brak autoryzacji"
    assert data["message"] == "Wymagany header X-API-Key"
    _assert_failed_outcome(data, "rejected")


def test_invoice_invalid_api_key_keeps_auth_error_and_is_rejected(workflow_harness):
    client, state = workflow_harness

    # Act
    response = client.post(
        "/api/workflow/create-invoice-from-nip",
        json=_invoice_request(),
        headers={"X-API-Key": "wrong-wo502-key"},
    )

    data = response.get_json()
    assert response.status_code == 403
    assert state["create_calls"] == []
    assert data["error"] == "Nieprawidłowy klucz API"
    assert data["message"] == "X-API-Key jest niepoprawny"
    _assert_failed_outcome(data, "rejected")


@pytest.mark.parametrize(
    "token,token_is_valid",
    [(None, True), ("expired-test-token", False)],
    ids=["missing-token", "invalid-token"],
)
def test_correction_missing_or_invalid_token_keeps_auth_error_and_is_rejected(
    workflow_harness, monkeypatch, token, token_is_valid
):
    client, state = workflow_harness
    monkeypatch.setattr(app_module, "load_token", lambda *args, **kwargs: token)
    monkeypatch.setattr(app_module, "is_token_valid", lambda: token_is_valid)

    # Act
    response = client.post(
        "/api/workflow/correction",
        json=_correction_request(),
        headers={"X-API-Key": API_KEY},
    )

    data = response.get_json()
    assert response.status_code == 401
    assert state["create_calls"] == []
    assert data["error"] == "Brak autoryzacji"
    assert data["message"] == "Przejdź do /auth aby się zalogować"
    _assert_failed_outcome(data, "rejected")


@pytest.mark.parametrize(
    "route",
    ["/api/workflow/create-invoice-from-nip", "/api/workflow/correction"],
    ids=["invoice-options", "correction-options"],
)
def test_successful_options_response_remains_without_outcome(workflow_harness, route):
    client, state = workflow_harness

    # Act
    response = client.options(route, headers={"X-API-Key": API_KEY})

    data = response.get_json()
    assert response.status_code == 200
    assert state["create_calls"] == []
    assert data == {"status": "ok"}
    assert "outcome" not in data


def test_create_timeout_is_opt_in_only_for_the_two_wo502_workflows(
    workflow_harness, monkeypatch
):
    client, state = workflow_harness
    parent = _parent_invoice()
    monkeypatch.setattr(
        app_module,
        "wfirma_get_invoice",
        lambda *args, **kwargs: (parent, None),
    )
    state["create_behavior"] = _success_response(
        document_id="9301",
        fullnumber="FV/EV/TEST/30/8/2026",
        document_type="normal",
    )

    # Act
    legacy_document, _legacy_response = app_module.wfirma_create_invoice(
        "test-token", {"contractor_id": 7001}, "130706"
    )
    invoice_response = client.post(
        "/api/workflow/create-invoice-from-nip",
        json=_invoice_request(),
        headers={"X-API-Key": API_KEY},
    )
    correction_response = client.post(
        "/api/workflow/correction",
        json=_correction_request(),
        headers={"X-API-Key": API_KEY},
    )

    assert legacy_document["id"] == "9301"
    assert invoice_response.status_code == 200
    assert correction_response.status_code == 200
    assert len(state["create_calls"]) == 3
    legacy_call, invoice_call, correction_call = state["create_calls"]
    assert "timeout" not in legacy_call
    assert invoice_call["timeout"] == 30
    assert correction_call["timeout"] == 30


def test_validation_before_create_is_rejected_and_never_posts(workflow_harness):
    client, state = workflow_harness
    body = _invoice_request()
    body.pop("invoice")

    # Act
    response = client.post(
        "/api/workflow/create-invoice-from-nip",
        json=body,
        headers={"X-API-Key": API_KEY},
    )

    data = response.get_json()
    assert response.status_code == 400
    assert state["create_calls"] == []
    assert data["error"] == "Brak sekcji invoice"
    _assert_failed_outcome(data, "rejected")


@pytest.mark.parametrize(
    "message",
    [
        EXACT_KSEF_BATCH_BLOCK,
        "  NIE MOŻNA WYSTAWIĆ KOREKTY DO FAKTURY   W TRAKCIE WYSYŁKI WSADOWEJ DO KSEF  ",
    ],
    ids=["measured-exact", "normalized-case-and-whitespace"],
)
def test_exact_ksef_batch_block_is_retryable_with_one_correction_create(
    workflow_harness, monkeypatch, message
):
    client, state = workflow_harness
    parent = _parent_invoice()
    monkeypatch.setattr(
        app_module,
        "wfirma_get_invoice",
        lambda *args, **kwargs: (parent, None),
    )
    state["create_behavior"] = FakeResponse(
        200,
        payload={"status": {"code": "ERROR", "message": message}},
    )

    # Act
    response = client.post(
        "/api/workflow/correction",
        json=_correction_request(),
        headers={"X-API-Key": API_KEY},
    )

    data = response.get_json()
    assert response.status_code == 500
    _only_create_call(state)
    assert message.strip() in data["details"]
    _assert_failed_outcome(data, "retryable")


def test_similar_ksef_text_is_rejected_not_retryable(workflow_harness, monkeypatch):
    client, state = workflow_harness
    parent = _parent_invoice()
    monkeypatch.setattr(
        app_module,
        "wfirma_get_invoice",
        lambda *args, **kwargs: (parent, None),
    )
    state["create_behavior"] = FakeResponse(
        200,
        payload={"status": {"code": "ERROR", "message": NEAR_KSEF_BATCH_BLOCK}},
    )

    # Act
    response = client.post(
        "/api/workflow/correction",
        json=_correction_request(),
        headers={"X-API-Key": API_KEY},
    )

    data = response.get_json()
    assert response.status_code == 500
    _only_create_call(state)
    assert NEAR_KSEF_BATCH_BLOCK in data["details"]
    _assert_failed_outcome(data, "rejected")


def test_create_timeout_is_unknown_and_invoice_create_is_not_retried(workflow_harness):
    client, state = workflow_harness
    state["create_behavior"] = requests.Timeout("controlled WO-502 timeout")

    # Act
    response = client.post(
        "/api/workflow/create-invoice-from-nip",
        json=_invoice_request(),
        headers={"X-API-Key": API_KEY},
    )

    data = response.get_json()
    assert response.status_code == 502
    _only_create_call(state)
    assert data["error"] == "Błąd podczas tworzenia faktury"
    _assert_failed_outcome(data, "unknown")


@pytest.mark.parametrize(
    "transport_result",
    [
        requests.ConnectionError("controlled WO-502 connection error"),
        None,
        FakeResponse(503, payload={"status": {"code": "ERROR", "message": "upstream unavailable"}}),
    ],
    ids=["connection-error", "no-response", "http-5xx"],
)
def test_connection_no_response_and_5xx_are_unknown_without_retry(
    workflow_harness, transport_result
):
    client, state = workflow_harness
    state["create_behavior"] = transport_result

    # Act
    response = client.post(
        "/api/workflow/create-invoice-from-nip",
        json=_invoice_request(),
        headers={"X-API-Key": API_KEY},
    )

    data = response.get_json()
    assert response.status_code == 502
    _only_create_call(state)
    assert data["error"] == "Błąd podczas tworzenia faktury"
    _assert_failed_outcome(data, "unknown")


def test_malformed_http_200_is_unknown(workflow_harness):
    client, state = workflow_harness
    state["create_behavior"] = FakeResponse(
        200,
        payload=ValueError("controlled malformed JSON"),
        text="{not-json",
    )

    # Act
    response = client.post(
        "/api/workflow/create-invoice-from-nip",
        json=_invoice_request(),
        headers={"X-API-Key": API_KEY},
    )

    data = response.get_json()
    assert response.status_code == 200
    _only_create_call(state)
    assert data["error"] == "Błąd podczas tworzenia faktury"
    _assert_failed_outcome(data, "unknown")


def test_apparent_success_without_document_id_is_unknown(workflow_harness):
    client, state = workflow_harness
    state["create_behavior"] = FakeResponse(
        200,
        payload={
            "status": {"code": "OK"},
            "invoices": {"0": {"invoice": {"fullnumber": "FV/BEZ/ID"}}},
        },
    )

    # Act
    response = client.post(
        "/api/workflow/create-invoice-from-nip",
        json=_invoice_request(),
        headers={"X-API-Key": API_KEY},
    )

    data = response.get_json()
    assert response.status_code == 200
    _only_create_call(state)
    assert data["error"] == "Błąd podczas tworzenia faktury"
    _assert_failed_outcome(data, "unknown")


def test_invoice_id_then_receiver_readback_failure_is_created_unverified(
    workflow_harness, monkeypatch
):
    client, state = workflow_harness
    body = _invoice_request(price_mode="brutto")
    body["receiver"] = {
        "name": "Odbiorca Testowy",
        "street": "Testowa 1",
        "zip": "00-000",
        "city": "Warszawa",
    }
    monkeypatch.setattr(
        app_module,
        "wfirma_resolve_receiver_contractor",
        lambda *args, **kwargs: ({"id": "7002"}, []),
    )
    monkeypatch.setattr(
        app_module,
        "wfirma_get_invoice",
        lambda *args, **kwargs: (None, "controlled invoice readback failure"),
    )
    state["create_behavior"] = _success_response(
        document_id="9002",
        fullnumber="FV/EV/TEST/2/8/2026",
        document_type="normal",
    )

    # Act
    response = client.post(
        "/api/workflow/create-invoice-from-nip",
        json=body,
        headers={"X-API-Key": API_KEY},
    )

    data = response.get_json()
    assert response.status_code == 502
    _only_create_call(state)
    assert data["receiver_verification_failed"] is True
    assert data["invoice_id"] == "9002"
    _assert_failed_outcome(data, "created_unverified")


def test_correction_id_then_receiver_readback_failure_is_created_unverified(
    workflow_harness, monkeypatch
):
    client, state = workflow_harness
    parent = _parent_invoice(price_mode="brutto", with_receiver=True)

    def fake_get_invoice(_token, invoice_id, _company_id=None):
        if str(invoice_id) == "8001":
            return parent, None
        if str(invoice_id) == "9001":
            return None, "controlled readback failure"
        raise AssertionError(f"Unexpected invoice read: {invoice_id}")

    monkeypatch.setattr(app_module, "wfirma_get_invoice", fake_get_invoice)
    state["create_behavior"] = FakeResponse(
        200,
        payload={
            "status": {"code": "OK"},
            "invoices": {
                "0": {
                    "invoice": {
                        "id": "9001",
                        "fullnumber": "KOR/EV/TEST/1/8/2026",
                        "type": "correction",
                    }
                }
            },
        },
    )

    # Act
    response = client.post(
        "/api/workflow/correction",
        json=_correction_request(),
        headers={"X-API-Key": API_KEY},
    )

    data = response.get_json()
    assert response.status_code == 502
    _only_create_call(state)
    assert data["error"] == "receiver_verification_failed"
    assert data["correction_invoice_id"] == "9001"
    _assert_failed_outcome(data, "created_unverified")


def test_invoice_id_then_mail_failure_is_created_unverified(
    workflow_harness, monkeypatch
):
    client, state = workflow_harness
    body = _invoice_request()
    body.update({"email": "buyer@test.example.pl", "send_email": True})
    monkeypatch.setattr(
        app_module,
        "wfirma_send_invoice_email",
        lambda *args, **kwargs: FakeResponse(503, text="controlled mail failure"),
    )
    state["create_behavior"] = _success_response(
        document_id="9003",
        fullnumber="FV/EV/TEST/3/8/2026",
        document_type="normal",
    )

    # Act
    response = client.post(
        "/api/workflow/create-invoice-from-nip",
        json=body,
        headers={"X-API-Key": API_KEY},
    )

    data = response.get_json()
    assert response.status_code == 503
    _only_create_call(state)
    assert data["error"] == "Nie udało się wysłać faktury mailem"
    assert data["invoice"]["id"] == "9003"
    _assert_failed_outcome(data, "created_unverified")


@pytest.mark.parametrize("price_mode", ["netto", "brutto"])
def test_invoice_success_keeps_legacy_shape_and_price_epoch(
    workflow_harness, price_mode
):
    client, state = workflow_harness
    request_body = _invoice_request(price_mode=price_mode)
    state["create_behavior"] = _success_response(
        document_id="9101",
        fullnumber="FV/EV/TEST/10/8/2026",
        document_type="normal",
    )

    # Act
    response = client.post(
        "/api/workflow/create-invoice-from-nip",
        json=request_body,
        headers={"X-API-Key": API_KEY},
    )

    data = response.get_json()
    create_call = _only_create_call(state)
    sent_invoice = create_call["json"]["invoices"]["invoice"]
    source_position = request_body["invoice"]["positions"][0]
    assert response.status_code == 200
    assert data["success"] is True
    assert "outcome" not in data
    assert sent_invoice.get("price_type") == (
        "brutto" if price_mode == "brutto" else None
    )
    assert ("price_mode" in request_body) is (price_mode == "brutto")
    assert ("unit_price_gross" in source_position) is (price_mode == "brutto")
    assert ("unit_price_net" in source_position) is (price_mode == "netto")
    assert sent_invoice["invoicecontents"]["0"]["invoicecontent"]["price"] == 123.0


@pytest.mark.parametrize("price_mode", ["netto", "brutto"])
def test_correction_success_keeps_legacy_shape_and_parent_price_epoch(
    workflow_harness, monkeypatch, price_mode
):
    client, state = workflow_harness
    parent = _parent_invoice(price_mode=price_mode)
    monkeypatch.setattr(
        app_module,
        "wfirma_get_invoice",
        lambda *args, **kwargs: (parent, None),
    )
    price_key = "unit_price_gross" if price_mode == "brutto" else "unit_price_net"
    request_body = {
        **_correction_request(),
        "full_correction": False,
        "positions": [
            {
                "parent_position_id": 8101,
                "name": "Bilet testowy",
                "quantity": 1,
                price_key: 123.0,
                "vat_rate": 23,
            }
        ],
    }
    state["create_behavior"] = _success_response(
        document_id="9201",
        fullnumber="KOR/EV/TEST/10/8/2026",
        document_type="correction",
    )

    # Act
    response = client.post(
        "/api/workflow/correction",
        json=request_body,
        headers={"X-API-Key": API_KEY},
    )

    data = response.get_json()
    create_call = _only_create_call(state)
    sent_correction = create_call["json"]["invoices"]["invoice"]
    source_position = request_body["positions"][0]
    assert response.status_code == 200
    assert data["success"] is True
    assert "outcome" not in data
    assert sent_correction.get("price_type") == (
        "brutto" if price_mode == "brutto" else None
    )
    assert ("unit_price_gross" in source_position) is (price_mode == "brutto")
    assert ("unit_price_net" in source_position) is (price_mode == "netto")
    assert sent_correction["invoicecontents"]["0"]["invoicecontent"]["price"] == 123.0
