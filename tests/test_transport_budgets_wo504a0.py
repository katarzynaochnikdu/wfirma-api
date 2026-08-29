"""WO-504A0 — hard transport budgets for invoice readback and OAuth refresh.

Every HTTP call in this module is mocked.  The tests deliberately count calls so a
future retry cannot silently turn an ambiguous document/token result into a duplicate
write or a long-held OAuth advisory lock.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# app.py has existing startup hooks.  Empty values set before import keep this suite
# detached from Postgres and the token/email monitor.
os.environ["DATABASE_URL"] = ""
os.environ["MAKE_WEBHOOK_SEND_EMAIL_REQUEST"] = ""
os.environ["RENDER_EMAIL_KEY_SEND_REQUEST"] = ""

import app as app_module  # noqa: E402
import pg_storage  # noqa: E402


API_KEY = "wo504a0-test-api-key"
ACCESS_TOKEN = "wo504a0-super-secret-access-token"


@dataclass
class FakeResponse:
    status_code: int
    payload: Any = None
    text: str = ""

    def __post_init__(self) -> None:
        if not self.text and self.payload is not None and not isinstance(
            self.payload, BaseException
        ):
            self.text = json.dumps(self.payload, ensure_ascii=False)

    def json(self) -> Any:
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload

    def __bool__(self) -> bool:
        return self.status_code < 400


def _authenticated_client(monkeypatch):
    monkeypatch.setattr(app_module, "MAKE_RENDER_API_KEY", API_KEY)
    monkeypatch.setattr(app_module, "load_token", lambda *args, **kwargs: "test-token")
    monkeypatch.setattr(app_module, "is_token_valid", lambda: True)
    monkeypatch.setattr(
        app_module, "wfirma_get_company_id", lambda *args, **kwargs: "130706"
    )
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


def _invoice_request_with_receiver() -> dict[str, Any]:
    return {
        "company": "md",
        "existing_contractor_id": 7001,
        "nip": "0000000000",
        "purchaser_name": "Firma Testowa",
        "series_name": "Eventy Faktura VAT TEST",
        "mark_as_paid": False,
        "receiver": {
            "name": "Odbiorca Testowy",
            "street": "Testowa 1",
            "zip": "00-000",
            "city": "Warszawa",
        },
        "invoice": {
            "issue_date": "2026-08-29",
            "payment_due_days": 7,
            "positions": [
                {
                    "name": "Bilet testowy",
                    "quantity": 1,
                    "unit_price_net": 100.00,
                    "vat_rate": 23,
                }
            ],
        },
    }


def _created_invoice_response(document_id: str = "9501") -> FakeResponse:
    return FakeResponse(
        200,
        payload={
            "status": {"code": "OK"},
            "invoices": {
                "0": {
                    "invoice": {
                        "id": document_id,
                        "fullnumber": "FV/EV/TEST/50/8/2026",
                        "type": "normal",
                        "date": "2026-08-29",
                        "total": "100.00",
                        "paymentstate": "unpaid",
                    }
                }
            },
        },
    )


def _install_oauth_transport(monkeypatch, behavior: Any):
    posts: list[dict[str, Any]] = []
    lock_events: list[str] = []
    saves: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    monkeypatch.setenv("WFIRMA_MD_CLIENT_ID", "wo504a0-client-id")
    monkeypatch.setenv("WFIRMA_MD_CLIENT_SECRET", "wo504a0-client-secret")

    token_row = {
        "access_token": "expired-access-token",
        "access_token_expires_at": 0,
        "refresh_token": "wo504a0-refresh-token",
    }
    monkeypatch.setattr(pg_storage, "get_wfirma_token", lambda _company: token_row)

    @contextmanager
    def fake_advisory_lock_ctx(_lock_id):
        lock_events.append("enter")
        try:
            yield
        finally:
            lock_events.append("exit")

    monkeypatch.setattr(pg_storage, "advisory_lock_ctx", fake_advisory_lock_ctx)

    def fake_post(url: str, **kwargs):
        posts.append({"url": url, **kwargs})
        if isinstance(behavior, BaseException):
            raise behavior
        return behavior

    monkeypatch.setattr(app_module.requests, "post", fake_post)
    monkeypatch.setattr(
        app_module,
        "save_token",
        lambda *args, **kwargs: saves.append((args, kwargs)),
    )
    return posts, lock_events, saves


def test_transport_budget_constants_are_fixed_to_the_approved_values():
    assert app_module.WFIRMA_INVOICE_READ_TIMEOUT_SECONDS == 8
    assert app_module.WFIRMA_OAUTH_REFRESH_TIMEOUT_SECONDS == 15


def test_invoice_readback_success_uses_exactly_one_eight_second_get(monkeypatch):
    calls: list[dict[str, Any]] = []
    expected = {"id": "8101", "total_composed": "123.00"}

    def fake_get(url: str, **kwargs):
        calls.append({"url": url, **kwargs})
        return FakeResponse(200, payload={"invoices": {"0": {"invoice": expected}}})

    monkeypatch.setattr(app_module.requests, "get", fake_get)

    # Act
    invoice, error = app_module.wfirma_get_invoice("test-token", "8101", "130706")

    assert (invoice, error) == (expected, None)
    assert len(calls) == 1
    assert calls[0]["timeout"] == 8
    assert "/invoices/get/8101?" in calls[0]["url"]
    assert calls[0]["url"].endswith("&company_id=130706")


@pytest.mark.parametrize("status", [404, 500])
def test_invoice_readback_http_error_preserves_existing_tuple(monkeypatch, status):
    calls: list[dict[str, Any]] = []

    def fake_get(url: str, **kwargs):
        calls.append({"url": url, **kwargs})
        return FakeResponse(status, text="controlled wFirma error")

    monkeypatch.setattr(app_module.requests, "get", fake_get)

    # Act
    invoice, error = app_module.wfirma_get_invoice("test-token", "8102")

    assert invoice is None
    assert error == f"Błąd API: {status} - controlled wFirma error"
    assert len(calls) == 1
    assert calls[0]["timeout"] == 8


def test_invoice_readback_timeout_returns_existing_tuple_without_retry(monkeypatch):
    calls: list[dict[str, Any]] = []

    def fake_get(url: str, **kwargs):
        calls.append({"url": url, **kwargs})
        raise requests.Timeout("controlled invoice readback timeout")

    monkeypatch.setattr(app_module.requests, "get", fake_get)

    # Act
    invoice, error = app_module.wfirma_get_invoice("test-token", "8103")

    assert invoice is None
    assert error == "controlled invoice readback timeout"
    assert len(calls) == 1
    assert calls[0]["timeout"] == 8


def test_invoice_get_endpoint_keeps_404_error_details_after_timeout(monkeypatch):
    client = _authenticated_client(monkeypatch)
    calls: list[dict[str, Any]] = []

    def fake_get(url: str, **kwargs):
        calls.append({"url": url, **kwargs})
        raise requests.Timeout("controlled endpoint readback timeout")

    monkeypatch.setattr(app_module.requests, "get", fake_get)

    # Act
    response = client.get("/api/invoice/8104", headers={"X-API-Key": API_KEY})

    assert response.status_code == 404
    assert response.get_json() == {
        "error": "Nie znaleziono faktury o ID 8104",
        "details": "controlled endpoint readback timeout",
    }
    assert len(calls) == 1
    assert calls[0]["timeout"] == 8


def test_parent_readback_timeout_stops_correction_before_create(monkeypatch):
    client = _authenticated_client(monkeypatch)
    get_calls: list[dict[str, Any]] = []
    post_calls: list[dict[str, Any]] = []

    def fake_get(url: str, **kwargs):
        get_calls.append({"url": url, **kwargs})
        raise requests.Timeout("controlled parent readback timeout")

    def forbidden_post(url: str, **kwargs):
        post_calls.append({"url": url, **kwargs})
        raise AssertionError("correction create must not run without a readable parent")

    monkeypatch.setattr(app_module.requests, "get", fake_get)
    monkeypatch.setattr(app_module.requests, "post", forbidden_post)

    # Act
    response = client.post(
        "/api/workflow/correction",
        json={
            "company": "md",
            "parent_invoice_id": 8105,
            "correction_reason": "Korekta testowa",
            "full_correction": True,
            "series_name": "Eventy Korekta TEST",
        },
        headers={"X-API-Key": API_KEY},
    )

    data = response.get_json()
    assert response.status_code == 404
    assert data["error"] == "Nie udało się pobrać faktury oryginalnej"
    assert data["details"] == "controlled parent readback timeout"
    assert data["success"] is False
    assert data["outcome"] == "rejected"
    assert len(get_calls) == 1
    assert get_calls[0]["timeout"] == 8
    assert post_calls == []


def test_readback_timeout_after_canonical_id_is_created_unverified_without_retry(
    monkeypatch,
):
    client = _authenticated_client(monkeypatch)
    create_calls: list[dict[str, Any]] = []
    read_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        app_module,
        "check_refresh_token_expiry_for_company",
        lambda *args, **kwargs: (None, None),
    )
    monkeypatch.setattr(
        app_module, "send_token_expiry_notification", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        app_module,
        "wfirma_find_series_by_name",
        lambda *args, **kwargs: {"id": "71", "name": "Eventy Faktura VAT TEST"},
    )
    monkeypatch.setattr(app_module, "wfirma_list_series", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        app_module,
        "wfirma_resolve_receiver_contractor",
        lambda *args, **kwargs: ({"id": "7002"}, []),
    )
    monkeypatch.setattr(
        app_module,
        "wfirma_get_invoice_pdf",
        lambda *args, **kwargs: FakeResponse(404, text="not found"),
    )

    def fake_post(url: str, **kwargs):
        if "/invoices/add" not in url:
            raise AssertionError(f"unexpected network call: {url}")
        create_calls.append({"url": url, **kwargs})
        return _created_invoice_response("9501")

    def fake_get(url: str, **kwargs):
        read_calls.append({"url": url, **kwargs})
        raise requests.Timeout("controlled receiver readback timeout")

    monkeypatch.setattr(app_module.requests, "post", fake_post)
    monkeypatch.setattr(app_module.requests, "get", fake_get)

    # Act
    response = client.post(
        "/api/workflow/create-invoice-from-nip",
        json=_invoice_request_with_receiver(),
        headers={"X-API-Key": API_KEY},
    )

    data = response.get_json()
    assert response.status_code == 502
    assert data["success"] is False
    assert data["outcome"] == "created_unverified"
    assert data["receiver_verification_failed"] is True
    assert data["invoice_id"] == "9501"
    assert len(create_calls) == 1
    assert create_calls[0]["timeout"] == 30
    assert len(read_calls) == 1
    assert read_calls[0]["timeout"] == 8


def test_oauth_refresh_success_posts_secret_in_body_once_and_saves_rotated_token(
    monkeypatch, capsys
):
    response = FakeResponse(
        200,
        payload={
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        },
    )
    posts, lock_events, saves = _install_oauth_transport(monkeypatch, response)

    # Act
    token = app_module.refresh_access_token(company="md", skip_fresh_check=True)

    assert token == "new-access-token"
    assert lock_events == ["enter", "exit"]
    assert len(posts) == 1
    assert posts[0]["url"] == "https://api2.wfirma.pl/oauth2/token"
    assert posts[0]["timeout"] == 15
    assert "params" not in posts[0]
    assert "json" not in posts[0]
    assert posts[0]["data"] == {
        "grant_type": "refresh_token",
        "client_id": "wo504a0-client-id",
        "client_secret": "wo504a0-client-secret",
        "refresh_token": "wo504a0-refresh-token",
    }
    assert saves == [
        (
            ("new-access-token", 3600),
            {
                "refresh_token": "new-refresh-token",
                "company": "md",
                "send_refresh_email": False,
                "refresh_token_source": "refresh_rotation",
            },
        )
    ]
    captured = capsys.readouterr()
    assert "wo504a0-client-secret" not in captured.out + captured.err
    assert "wo504a0-refresh-token" not in captured.out + captured.err


def test_require_api_key_uses_constant_time_bytes_compare_and_keeps_statuses(
    monkeypatch,
):
    compare_calls: list[tuple[bytes, bytes]] = []

    def fake_compare_digest(provided: bytes, expected: bytes) -> bool:
        compare_calls.append((provided, expected))
        return provided == expected

    monkeypatch.setattr(app_module, "MAKE_RENDER_API_KEY", API_KEY)
    monkeypatch.setattr(app_module.hmac, "compare_digest", fake_compare_digest)
    app_module.app.config.update(TESTING=True)
    client = app_module.app.test_client()

    @app_module.require_api_key
    def protected_probe():
        return app_module.jsonify({"ok": True})

    with app_module.app.test_request_context(headers={"X-API-Key": API_KEY}):
        success = protected_probe()
    with app_module.app.test_request_context(headers={"X-API-Key": "wrong-key"}):
        forbidden, forbidden_status = protected_probe()
    with app_module.app.test_request_context():
        missing, missing_status = protected_probe()

    assert success.get_json() == {"ok": True}
    assert forbidden_status == 403
    assert forbidden.get_json() == {
        "error": "Nieprawidłowy klucz API",
        "message": "X-API-Key jest niepoprawny",
    }
    assert missing_status == 401
    assert missing.get_json() == {
        "error": "Brak autoryzacji",
        "message": "Wymagany header X-API-Key",
    }
    assert compare_calls == [
        (API_KEY.encode("utf-8"), API_KEY.encode("utf-8")),
        (b"wrong-key", API_KEY.encode("utf-8")),
    ]


@pytest.mark.parametrize("invalid_config", [None, b"bytes-key", object()])
def test_require_api_key_non_string_configuration_fails_closed(
    monkeypatch, invalid_config
):
    monkeypatch.setattr(app_module, "MAKE_RENDER_API_KEY", invalid_config)
    app_module.app.config.update(TESTING=True)

    @app_module.require_api_key
    def protected_probe():
        return app_module.jsonify({"ok": True})

    with app_module.app.test_request_context(headers={"X-API-Key": API_KEY}):
        response, status = protected_probe()

    assert status == 503
    assert response.get_json() == {
        "error": "Server misconfigured",
        "message": "Brak MAKE_RENDER_API_KEY w konfiguracji serwera",
    }


@pytest.mark.parametrize(
    ("headers", "expected_status", "expected_body"),
    [
        pytest.param(
            {},
            401,
            {
                "error": "Brak autoryzacji",
                "message": "Wymagany header X-API-Key",
            },
            id="missing-key",
        ),
        pytest.param(
            {"X-API-Key": "wrong-key"},
            403,
            {
                "error": "Nieprawidłowy klucz API",
                "message": "X-API-Key jest niepoprawny",
            },
            id="wrong-key",
        ),
    ],
)
def test_manual_refresh_post_rejects_unauthorized_before_db_lock_http_or_save(
    monkeypatch, headers, expected_status, expected_body
):
    side_effects: list[str] = []

    monkeypatch.setattr(app_module, "MAKE_RENDER_API_KEY", API_KEY)
    monkeypatch.setattr(
        pg_storage,
        "get_wfirma_token",
        lambda *_args, **_kwargs: side_effects.append("db-read"),
    )

    @contextmanager
    def forbidden_lock(_lock_id):
        side_effects.append("lock")
        yield

    monkeypatch.setattr(pg_storage, "advisory_lock_ctx", forbidden_lock)
    monkeypatch.setattr(
        app_module.requests,
        "post",
        lambda *_args, **_kwargs: side_effects.append("oauth-post"),
    )
    monkeypatch.setattr(
        app_module,
        "save_token",
        lambda *_args, **_kwargs: side_effects.append("save"),
    )
    app_module.app.config.update(TESTING=True)
    client = app_module.app.test_client()

    # Act
    response = client.post("/api/token/refresh?company=md&force=true", headers=headers)

    assert response.status_code == expected_status
    assert response.get_json() == expected_body
    assert side_effects == []


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-API-Key": "wrong-key"}, {"X-API-Key": API_KEY}],
    ids=["missing-key", "wrong-key", "valid-key"],
)
def test_manual_refresh_get_is_method_not_allowed_without_any_side_effect(
    monkeypatch, headers
):
    side_effects: list[str] = []
    monkeypatch.setattr(app_module, "MAKE_RENDER_API_KEY", API_KEY)
    monkeypatch.setattr(
        pg_storage,
        "get_wfirma_token",
        lambda *_args, **_kwargs: side_effects.append("db-read"),
    )

    @contextmanager
    def forbidden_lock(_lock_id):
        side_effects.append("lock")
        yield

    monkeypatch.setattr(pg_storage, "advisory_lock_ctx", forbidden_lock)
    monkeypatch.setattr(
        app_module.requests,
        "post",
        lambda *_args, **_kwargs: side_effects.append("oauth-post"),
    )
    monkeypatch.setattr(
        app_module,
        "save_token",
        lambda *_args, **_kwargs: side_effects.append("save"),
    )
    app_module.app.config.update(TESTING=True)
    client = app_module.app.test_client()

    # Act
    response = client.get(
        "/api/token/refresh?company=md&force=true",
        headers=headers,
    )

    assert response.status_code == 405
    assert side_effects == []


def test_manual_refresh_success_never_returns_or_logs_access_token_fragment(
    monkeypatch, capsys
):
    posts, lock_events, saves = _install_oauth_transport(
        monkeypatch,
        FakeResponse(
            200,
            payload={"access_token": ACCESS_TOKEN, "expires_in": 3600},
        ),
    )
    monkeypatch.setattr(app_module, "MAKE_RENDER_API_KEY", API_KEY)
    app_module.app.config.update(TESTING=True)
    client = app_module.app.test_client()

    # Act
    response = client.post(
        "/api/token/refresh?company=md&force=true",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "message": "Token odświeżony pomyślnie dla firmy MD",
        "company": "md",
    }
    assert len(posts) == 1
    assert posts[0]["timeout"] == 15
    assert lock_events == ["enter", "exit"]
    assert len(saves) == 1
    captured = capsys.readouterr()
    evidence = captured.out + captured.err + response.get_data(as_text=True)
    assert ACCESS_TOKEN not in evidence
    assert ACCESS_TOKEN[:20] not in evidence


def test_save_token_logs_only_non_reversible_access_fingerprint(monkeypatch, capsys):
    monkeypatch.setenv("WFIRMA_MD_ACCESS_TOKEN", "previous-access-token")
    monkeypatch.setenv("WFIRMA_MD_TOKEN_EXPIRES", "0")
    monkeypatch.setenv("WFIRMA_MD_REFRESH_TOKEN", "previous-refresh-token")
    monkeypatch.setattr(
        pg_storage,
        "save_wfirma_token",
        lambda **_kwargs: {"ok": True, "updated_at": "controlled"},
    )

    # Act
    app_module.save_token(
        ACCESS_TOKEN,
        3600,
        refresh_token="replacement-refresh-token",
        company="md",
        send_refresh_email=False,
        refresh_token_source="controlled-test",
    )

    captured = capsys.readouterr()
    evidence = captured.out + captured.err
    assert ACCESS_TOKEN not in evidence
    assert ACCESS_TOKEN[:20] not in evidence
    assert app_module._token_fingerprint(ACCESS_TOKEN) in evidence


@pytest.mark.parametrize(
    "payload",
    [pytest.param({}, id="missing-access-token"), pytest.param(ValueError("bad json"), id="invalid-json")],
)
def test_oauth_http_200_without_valid_access_token_never_saves(monkeypatch, payload):
    posts, lock_events, saves = _install_oauth_transport(
        monkeypatch, FakeResponse(200, payload=payload)
    )

    # Act
    token = app_module.refresh_access_token(company="md", skip_fresh_check=True)

    assert token is None
    assert len(posts) == 1
    assert posts[0]["timeout"] == 15
    assert saves == []
    assert lock_events == ["enter", "exit"]


def test_oauth_non_200_reflected_secrets_never_reach_logs(monkeypatch, capsys):
    reflected_body = (
        "invalid_request "
        "client_secret=wo504a0-client-secret "
        "refresh_token=wo504a0-refresh-token "
        f"access_token={ACCESS_TOKEN}"
    )
    posts, lock_events, saves = _install_oauth_transport(
        monkeypatch,
        FakeResponse(400, text=reflected_body),
    )

    # Act
    token = app_module.refresh_access_token(company="md", skip_fresh_check=True)

    assert token is None
    assert len(posts) == 1
    assert posts[0]["timeout"] == 15
    assert saves == []
    assert lock_events == ["enter", "exit"]
    captured = capsys.readouterr()
    evidence = captured.out + captured.err
    assert "wo504a0-client-secret" not in evidence
    assert "wo504a0-refresh-token" not in evidence
    assert ACCESS_TOKEN not in evidence
    assert ACCESS_TOKEN[:20] not in evidence


def test_oauth_transport_exception_message_and_traceback_never_log_secrets(
    monkeypatch, capsys
):
    reflected_exception = requests.RequestException(
        "transport failed "
        "client_secret=wo504a0-client-secret "
        "refresh_token=wo504a0-refresh-token "
        f"access_token={ACCESS_TOKEN}"
    )
    posts, lock_events, saves = _install_oauth_transport(
        monkeypatch,
        reflected_exception,
    )

    # Act
    token = app_module.refresh_access_token(company="md", skip_fresh_check=True)

    assert token is None
    assert len(posts) == 1
    assert posts[0]["timeout"] == 15
    assert saves == []
    assert lock_events == ["enter", "exit"]
    captured = capsys.readouterr()
    evidence = captured.out + captured.err
    assert "wo504a0-client-secret" not in evidence
    assert "wo504a0-refresh-token" not in evidence
    assert ACCESS_TOKEN not in evidence
    assert ACCESS_TOKEN[:20] not in evidence
    assert "Traceback" not in evidence


def test_oauth_http_200_missing_access_never_logs_reflected_secret_key_names(
    monkeypatch, capsys
):
    reflected_keys = {
        "client_secret=wo504a0-client-secret": "controlled",
        "refresh_token=wo504a0-refresh-token": "controlled",
        f"provider_key={ACCESS_TOKEN}": "controlled",
    }
    posts, lock_events, saves = _install_oauth_transport(
        monkeypatch,
        FakeResponse(200, payload=reflected_keys),
    )

    # Act
    token = app_module.refresh_access_token(company="md", skip_fresh_check=True)

    assert token is None
    assert len(posts) == 1
    assert posts[0]["timeout"] == 15
    assert saves == []
    assert lock_events == ["enter", "exit"]
    captured = capsys.readouterr()
    evidence = captured.out + captured.err
    assert "wo504a0-client-secret" not in evidence
    assert "wo504a0-refresh-token" not in evidence
    assert ACCESS_TOKEN not in evidence
    assert ACCESS_TOKEN[:20] not in evidence


def test_manual_oauth_timeout_keeps_500_keyset_does_not_save_and_releases_lock(
    monkeypatch, capsys
):
    posts, lock_events, saves = _install_oauth_transport(
        monkeypatch, requests.Timeout("controlled OAuth timeout")
    )
    app_module.app.config.update(TESTING=True)
    client = app_module.app.test_client()
    monkeypatch.setattr(app_module, "MAKE_RENDER_API_KEY", API_KEY)

    # Act
    response = client.post(
        "/api/token/refresh?company=md&force=true",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 500
    data = response.get_json()
    assert set(data) == {"error", "message", "hint", "company"}
    assert data == {
        "error": "Nie udało się odświeżyć tokenu",
        "message": "Sprawdź logi na Render dla szczegółów błędu",
        "hint": "Możliwe że refresh_token wygasł. Przejdź do /auth?company=md",
        "company": "md",
    }
    assert len(posts) == 1
    assert posts[0]["timeout"] == 15
    assert saves == []
    assert lock_events == ["enter", "exit"]
    captured = capsys.readouterr()
    assert "wo504a0-client-secret" not in captured.out + captured.err
    assert "wo504a0-refresh-token" not in captured.out + captured.err


def test_automatic_oauth_timeout_keeps_401_gate_without_invoice_read(monkeypatch):
    posts, lock_events, saves = _install_oauth_transport(
        monkeypatch, requests.Timeout("controlled automatic OAuth timeout")
    )
    monkeypatch.setattr(app_module, "MAKE_RENDER_API_KEY", API_KEY)
    get_calls: list[dict[str, Any]] = []

    def forbidden_get(url: str, **kwargs):
        get_calls.append({"url": url, **kwargs})
        raise AssertionError("invoice read must remain behind the token gate")

    monkeypatch.setattr(app_module.requests, "get", forbidden_get)
    app_module.app.config.update(TESTING=True)
    client = app_module.app.test_client()

    # Act
    response = client.get("/api/invoice/8106", headers={"X-API-Key": API_KEY})

    assert response.status_code == 401
    assert response.get_json() == {
        "error": "Brak autoryzacji",
        "message": "Przejdź do /auth aby się zalogować",
    }
    assert len(posts) == 1
    assert posts[0]["timeout"] == 15
    assert saves == []
    assert lock_events == ["enter", "exit"]
    assert get_calls == []
