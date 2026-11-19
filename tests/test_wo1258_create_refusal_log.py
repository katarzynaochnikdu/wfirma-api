"""WO-1258 / BUG-369 — the strict create path logs WHY wFirma refused a document.

The strict workflows call ``wfirma_create_invoice(..., redact_logs=True)``, which never
prints the request or the response body. When wFirma answered HTTP 200 without a
document (INPUT ERROR) the reason was lost. One redacted line now carries the wFirma
status code, the error fields and the error messages (digits and e-mails masked).
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["DATABASE_URL"] = ""
os.environ["MAKE_WEBHOOK_SEND_EMAIL_REQUEST"] = ""
os.environ["RENDER_EMAIL_KEY_SEND_REQUEST"] = ""

import app as app_module  # noqa: E402

MARKER = "[document-bridge] wfirma_create_refused"
REQUEST_ECHO = "Opis z zamowienia testowego"


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload
        self.text = json.dumps(payload, ensure_ascii=False)
        self.headers = {"Content-Type": "application/json"}

    def json(self):
        return self.payload

    def __bool__(self):
        return self.status_code < 400


def _create(monkeypatch, response):
    monkeypatch.setattr(app_module.requests, "post", lambda *args, **kwargs: response)
    return app_module.wfirma_create_invoice(
        "test-token", {"description": REQUEST_ECHO}, "123", request_timeout=30, redact_logs=True
    )


def _refusal_lines(capsys):
    return [line for line in capsys.readouterr().out.splitlines() if line.startswith(MARKER)]


def _input_error_payload():
    return {
        "invoices": {
            "0": {
                "invoice": {
                    "description": REQUEST_ECHO,
                    "errors": {
                        "0": {
                            "error": {
                                "field": "contractor_id",
                                "message": "Kontrahent 5260250995 (kontakt@test.example.pl) jest niepoprawny",
                            }
                        }
                    },
                }
            }
        },
        "status": {"code": "INPUT ERROR"},
    }


def test_create_input_error_logs_status_field_and_masked_message(monkeypatch, capsys):
    # Arrange
    response = FakeResponse(200, _input_error_payload())

    # Act
    invoice, returned = _create(monkeypatch, response)

    # Assert
    assert invoice is None and returned is response
    lines = _refusal_lines(capsys)
    assert len(lines) == 1
    line = lines[0]
    assert "http=200" in line and "wfirma_status=INPUT ERROR" in line
    assert "contractor_id" in line and "jest niepoprawny" in line
    assert "5260250995" not in line and "kontakt@test.example.pl" not in line
    assert "<num>" in line and "<email>" in line
    assert REQUEST_ECHO not in line


def test_create_status_error_logs_one_refusal_line(monkeypatch, capsys):
    # Arrange
    response = FakeResponse(200, {"status": {"code": "ERROR", "message": "Brak uprawnien"}})

    # Act
    invoice, _ = _create(monkeypatch, response)

    # Assert
    assert invoice is None
    lines = _refusal_lines(capsys)
    assert len(lines) == 1 and "wfirma_status=ERROR" in lines[0] and "Brak uprawnien" in lines[0]


def test_create_http_500_logs_one_refusal_line(monkeypatch, capsys):
    # Arrange
    response = FakeResponse(500, {"status": {"code": "FATAL"}})

    # Act
    invoice, _ = _create(monkeypatch, response)

    # Assert
    assert invoice is None
    lines = _refusal_lines(capsys)
    assert len(lines) == 1 and "http=500" in lines[0] and "wfirma_status=FATAL" in lines[0]


def test_create_success_logs_no_refusal_line(monkeypatch, capsys):
    # Arrange
    payload = {"invoices": {"0": {"invoice": {"id": "777", "fullnumber": "FV/EV/TEST/1/11/2026"}}},
               "status": {"code": "OK"}}

    # Act
    invoice, _ = _create(monkeypatch, FakeResponse(200, payload))

    # Assert
    assert invoice is not None and invoice["id"] == "777"
    assert _refusal_lines(capsys) == []


def test_create_refusal_log_caps_message_count_and_length(monkeypatch, capsys):
    # Arrange
    errors = {str(i): {"error": {"field": f"pole_{i}", "message": "x" * 500}} for i in range(10)}
    payload = {"invoices": {"0": {"invoice": {"errors": errors}}}, "status": {"code": "INPUT ERROR"}}

    # Act
    _create(monkeypatch, FakeResponse(200, payload))

    # Assert
    line = _refusal_lines(capsys)[0]
    assert line.count("pole_") == 6
    assert "x" * 241 not in line and "x" * 240 in line


def test_create_refusal_log_failure_never_changes_result(monkeypatch, capsys):
    # Arrange
    response = FakeResponse(200, _input_error_payload())
    monkeypatch.setattr(app_module, "_extract_document_error_messages",
                        lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))

    # Act
    invoice, returned = _create(monkeypatch, response)

    # Assert
    assert invoice is None and returned is response


def test_legacy_unredacted_path_keeps_its_own_logging_without_refusal_line(monkeypatch, capsys):
    # Arrange
    monkeypatch.setattr(app_module.requests, "post",
                        lambda *args, **kwargs: FakeResponse(200, _input_error_payload()))

    # Act
    invoice, _ = app_module.wfirma_create_invoice("test-token", {"description": "x"}, "123")

    # Assert
    assert invoice is None
    assert _refusal_lines(capsys) == []
