"""WO-846B - read-only search of the grouped first invoice by its `id_external` marker.

The portal's settlement that is stuck WITHOUT a provider id asks this route whether
wFirma holds its invoice. "found: 0" frees the order there, so it must be a POSITIVE
answer of wFirma: every doubt is 503 `provider_unavailable`, never "0".

The suite calls the real Flask handler (real `_structural_correction_identity` and
company pin) while the token store and the provider transport are controlled. The
only provider request allowed is one `invoices/find`; any other verb, URL, retry or
document create fails loudly.

Manual contract smoke (read-only `invoices/find` on md_test): see the last test.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from dataclasses import dataclass
from typing import Any

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SMOKE = os.environ.get("WFIRMA_SMOKE") == "1"
if not SMOKE:
    # The default run never reaches a database or a mail hook (as WO-507A2-S).
    # The smoke keeps DATABASE_URL: the OAuth tokens live in the service's Postgres.
    os.environ["DATABASE_URL"] = ""
    os.environ["MAKE_WEBHOOK_SEND_EMAIL_REQUEST"] = ""
    os.environ["RENDER_EMAIL_KEY_SEND_REQUEST"] = ""

import app as app_module  # noqa: E402

MAX_BYTES = 2 * 1024 * 1024


@dataclass
class FakeStreamResponse:
    """A streamed provider answer (the WO-507A2-S double, local so the smoke keeps its ENV)."""

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


API_KEY = "wo846b-test-api-key"
PATH = "/api/workflow/grouped-first-invoice/find-by-marker"
HEADERS = {"X-API-Key": API_KEY}
MARKER = "nf1:" + "0123456789abcdef0123456789ab"
FIND_URL = "https://api2.wfirma.pl/invoices/find"
UNAVAILABLE = {"success": False, "outcome": "provider_unavailable"}
INVALID = {"success": False, "error": "invalid_request"}


def _invoice(invoice_id: Any = "9001", *, marker: Any = MARKER, number: Any = "FV/EV/TEST/7/10/2026") -> dict:
    value = {
        "id": invoice_id,
        "type": "normal",
        "fullnumber": number,
        "contractor_detail": {"name": "Synthetic Buyer Sp. z o.o.", "nip": "0000000000"},
        "total": "984.00",
    }
    if marker is not None:
        value["id_external"] = marker
    return value


def _found(*invoices: dict, total: Any = None) -> FakeStreamResponse:
    container: dict[str, Any] = {str(index): {"invoice": invoice} for index, invoice in enumerate(invoices)}
    container["parameters"] = {"limit": "2", "page": "1", "total": str(len(invoices)) if total is None else total}
    return FakeStreamResponse(200, {"invoices": container, "status": {"code": "OK"}})


@pytest.fixture
def harness(monkeypatch):
    state: dict[str, Any] = {"tokens": [], "validity": [], "posts": [], "responses": []}
    monkeypatch.setattr(app_module, "MAKE_RENDER_API_KEY", API_KEY)

    def fake_load_token(*, silent=False, company=None):
        state["tokens"].append((silent, company))
        return f"token-for-{company}"

    def fake_is_valid(company=None):
        state["validity"].append(company)
        return True

    def fake_post(url: str, **kwargs):
        if url != FIND_URL:
            raise AssertionError(f"WO-846B may only call invoices/find, got {url}")
        state["posts"].append({"url": url, **kwargs})
        if not state["responses"]:
            raise AssertionError("unexpected second invoices/find (no retry allowed)")
        behavior = state["responses"].pop(0)
        if isinstance(behavior, BaseException):
            raise behavior
        return behavior

    def forbidden(*_args, **_kwargs):
        raise AssertionError("WO-846B must never write, create or use another transport")

    monkeypatch.setattr(app_module, "load_token", fake_load_token)
    monkeypatch.setattr(app_module, "is_token_valid_for_company", fake_is_valid)
    monkeypatch.setattr(app_module.requests, "post", fake_post)
    for verb in ("get", "put", "patch", "delete"):
        monkeypatch.setattr(app_module.requests, verb, forbidden)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(app_module, "wfirma_create_invoice", forbidden)
    monkeypatch.setattr(app_module, "_mark_document_create_attempt", forbidden)
    monkeypatch.setattr(app_module, "_first_invoice_create_party", forbidden)
    monkeypatch.setattr(app_module, "_strict_wfirma_recovery_get", forbidden)
    monkeypatch.delenv("WFIRMA_MD_COMPANY_ID", raising=False)
    monkeypatch.delenv("WFIRMA_TEST_COMPANY_ID", raising=False)
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client(), state


def _ask(client, *, company="md", marker=MARKER, **kwargs):
    return client.post(PATH, json={"company": company, "id_external": marker}, headers=HEADERS, **kwargs)


def _assert_one_bounded_find(call: dict, *, company_id: str, token: str = "token-for-md") -> None:
    assert call["url"] == FIND_URL
    assert call["params"] == {
        "inputFormat": "json",
        "outputFormat": "json",
        "oauth_version": "2",
        "company_id": company_id,
    }
    assert call["json"] == {"invoices": {"parameters": {
        "conditions": {"condition": {"field": "id_external", "operator": "eq", "value": MARKER}},
        "limit": "2",
    }}}
    assert call["timeout"] == 8
    assert call["allow_redirects"] is False
    assert call["stream"] is True
    assert call["headers"]["Authorization"] == f"Bearer {token}"


# ------------------------------------------------------------------ answers


def test_wo846b_find_by_marker_one_invoice_answers_its_id_and_number(harness, capsys):
    client, state = harness
    answer = _found(_invoice())
    state["responses"].append(answer)

    # Act
    response = _ask(client)

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "found": 1,
        "invoice_id": "9001",
        "fullnumber": "FV/EV/TEST/7/10/2026",
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert state["tokens"] == [(True, "md")] and state["validity"] == ["md"]
    assert len(state["posts"]) == 1
    _assert_one_bounded_find(state["posts"][0], company_id="130706")
    assert answer.closed is True
    log = capsys.readouterr().out
    assert "[WO-846B FIND-BY-MARKER] found=1 company=md marker=" + MARKER + " invoice_id=9001" in log
    assert "Synthetic Buyer" not in log + response.get_data(as_text=True)


def test_wo846b_find_by_marker_numeric_provider_id_is_answered_as_text(harness):
    client, state = harness
    state["responses"].append(_found(_invoice(9001)))

    # Act
    response = _ask(client)

    assert response.status_code == 200
    assert response.get_json()["invoice_id"] == "9001"


def test_wo846b_find_by_marker_zero_invoices_answers_found_zero(harness, capsys):
    client, state = harness
    state["responses"].append(_found())

    # Act
    response = _ask(client)

    assert response.status_code == 200
    assert response.get_json() == {"success": True, "found": 0, "invoice_id": None}
    assert len(state["posts"]) == 1
    _assert_one_bounded_find(state["posts"][0], company_id="130706")
    assert "[WO-846B FIND-BY-MARKER] found=0 company=md marker=" + MARKER in capsys.readouterr().out


@pytest.mark.parametrize("total", ["2", "5", 7])
def test_wo846b_find_by_marker_two_hits_are_ambiguous_and_never_pick_one(harness, total):
    client, state = harness
    state["responses"].append(_found(_invoice("9001"), _invoice("9002"), total=total))

    # Act
    response = _ask(client)

    assert response.status_code == 409
    assert response.get_json() == {"success": False, "outcome": "ambiguous", "found": 2}
    assert "invoice_id" not in response.get_json()
    assert len(state["posts"]) == 1


# ------------------------------------------------------------------ every doubt is "unavailable", never "0"


@pytest.mark.parametrize(
    "behavior",
    [
        requests.Timeout("secret reflected by provider"),
        requests.ConnectionError("secret reflected by provider"),
        FakeStreamResponse(500, {"secret": "must-not-leak"}),
        FakeStreamResponse(404, {"secret": "must-not-leak"}),
        FakeStreamResponse(401, {"secret": "must-not-leak"}),
        FakeStreamResponse(302, {"location": "https://evil.invalid/secret"}),
        FakeStreamResponse(200, raw_body=b"not-json secret"),
        FakeStreamResponse(
            200,
            payload={},
            raw_body=b"x" * (MAX_BYTES + 1),
            headers={"Content-Length": str(MAX_BYTES + 1)},
        ),
    ],
)
def test_wo846b_find_by_marker_provider_failure_is_unavailable_never_zero(harness, behavior, capsys):
    client, state = harness
    state["responses"].append(behavior)

    # Act
    response = _ask(client)

    assert response.status_code == 503
    assert response.get_json() == UNAVAILABLE
    assert len(state["posts"]) == 1 and state["responses"] == []
    captured = capsys.readouterr()
    assert "secret" not in response.get_data(as_text=True) + captured.out + captured.err
    assert "[WO-846B FIND-BY-MARKER] provider_unavailable reason=" in captured.out


def _payload(**change):
    value = {"invoices": {"parameters": {"limit": "2", "page": "1", "total": "0"}}, "status": {"code": "OK"}}
    value.update(change)
    return value


@pytest.mark.parametrize(
    "payload",
    [
        _payload(status={"code": "ERROR"}),
        _payload(status={"code": "NOT FOUND"}),
        _payload(status="OK"),
        {"invoices": {"parameters": {"total": "0"}}},
        _payload(extra={"x": 1}),
        _payload(invoices=[]),
        _payload(invoices={}),
        _payload(invoices={"parameters": {"limit": "2"}}),
        _payload(invoices={"parameters": {"total": "zero"}}),
        _payload(invoices={"parameters": {"total": True}}),
        _payload(invoices={"parameters": "0"}),
        _payload(invoices={"parameters": {"total": "1"}}),
        _payload(invoices={"0": {"invoice": _invoice()}, "parameters": {"total": "0"}}),
        _payload(invoices={"0": {"invoice": _invoice()}, "parameters": {"total": "3"}}),
        _payload(invoices={"0": {"invoice": _invoice(marker=MARKER.upper())}, "parameters": {"total": "1"}}),
        _payload(invoices={"0": {"invoice": _invoice(marker=MARKER + " ")}, "parameters": {"total": "1"}}),
        _payload(invoices={"0": {"invoice": _invoice(marker=None)}, "parameters": {"total": "1"}}),
        _payload(invoices={"0": {"invoice": _invoice("0")}, "parameters": {"total": "1"}}),
        _payload(invoices={"0": {"invoice": _invoice("../9001")}, "parameters": {"total": "1"}}),
        _payload(invoices={"0": {"invoice": _invoice(True)}, "parameters": {"total": "1"}}),
        _payload(invoices={"0": {"invoice": _invoice(number="")}, "parameters": {"total": "1"}}),
        _payload(invoices={"0": {"invoice": _invoice(number=" FV/1")}, "parameters": {"total": "1"}}),
        _payload(invoices={"0": {"invoice": _invoice(), "extra": 1}, "parameters": {"total": "1"}}),
        _payload(invoices={"x": {"invoice": _invoice()}, "parameters": {"total": "1"}}),
        _payload(invoices={"invoice": _invoice(), "parameters": {"total": "1"}}),
        _payload(invoices={"0": {"invoice": _invoice("9001")}, "1": {"invoice": _invoice("9001")},
                           "parameters": {"total": "2"}}),
        _payload(invoices={"0": {"invoice": _invoice("9001")}, "1": {"invoice": _invoice("9002")},
                           "2": {"invoice": _invoice("9003")}, "parameters": {"total": "3"}}),
    ],
)
def test_wo846b_find_by_marker_malformed_answer_is_unavailable_never_zero(harness, payload):
    client, state = harness
    state["responses"].append(FakeStreamResponse(200, payload))

    # Act
    response = _ask(client)

    assert response.status_code == 503
    assert response.get_json() == UNAVAILABLE
    assert len(state["posts"]) == 1


# ------------------------------------------------------------------ request, auth and tenant


@pytest.mark.parametrize(
    "raw,content_type,query",
    [
        (json.dumps({"company": "test", "id_external": MARKER}), "application/json", ""),
        (json.dumps({"company": "MD", "id_external": MARKER}), "application/json", ""),
        (json.dumps({"company": "", "id_external": MARKER}), "application/json", ""),
        (json.dumps({"company": None, "id_external": MARKER}), "application/json", ""),
        (json.dumps({"company": ["md"], "id_external": MARKER}), "application/json", ""),
        (json.dumps({"company": "md", "id_external": ""}), "application/json", ""),
        (json.dumps({"company": "md", "id_external": "n" * 33}), "application/json", ""),
        (json.dumps({"company": "md", "id_external": "nf1:abc def"}), "application/json", ""),
        (json.dumps({"company": "md", "id_external": "nf1:abc\n"}), "application/json", ""),
        (json.dumps({"company": "md", "id_external": "nf1:łab"}), "application/json", ""),
        (json.dumps({"company": "md", "id_external": 12345}), "application/json", ""),
        (json.dumps({"company": "md"}), "application/json", ""),
        (json.dumps({"company": "md", "id_external": MARKER, "company_id": "130706"}), "application/json", ""),
        ('{"company":"md","company":"md","id_external":"' + MARKER + '"}', "application/json", ""),
        ('{"company":"md","id_external":NaN}', "application/json", ""),
        ("[]", "application/json", ""),
        ("not json", "application/json", ""),
        (" " * 1025, "application/json", ""),
        (json.dumps({"company": "md", "id_external": MARKER}), "text/plain", ""),
        (json.dumps({"company": "md", "id_external": MARKER}), "application/json", "?company=md"),
    ],
)
def test_wo846b_find_by_marker_invalid_request_is_400_before_token_or_transport(harness, raw, content_type, query):
    client, state = harness

    # Act
    response = client.post(PATH + query, data=raw, content_type=content_type, headers=HEADERS)

    assert response.status_code == 400
    assert response.get_json() == INVALID
    assert state["tokens"] == [] and state["validity"] == [] and state["posts"] == []


@pytest.mark.parametrize(("headers", "expected_status"), [({}, 401), ({"X-API-Key": "wrong"}, 403)])
def test_wo846b_find_by_marker_auth_failure_has_no_token_or_transport(harness, headers, expected_status):
    client, state = harness

    # Act
    response = client.post(PATH, json={"company": "md", "id_external": MARKER}, headers=headers)

    assert response.status_code == expected_status
    assert state["tokens"] == [] and state["validity"] == [] and state["posts"] == []


@pytest.mark.parametrize("company", ["md", "md_test"])
def test_wo846b_find_by_marker_company_id_is_bound_to_the_requested_tenant(harness, monkeypatch, company):
    client, state = harness
    # md_test is the real Medidesk account with the test series: credentials and ID of md,
    # never the separate `test` company (WO-507A2-S). Its pin must not leak in.
    monkeypatch.setenv("WFIRMA_TEST_COMPANY_ID", "230706")
    state["responses"].append(_found())

    # Act
    response = _ask(client, company=company)

    assert response.status_code == 200
    assert state["tokens"] == [(True, company)] and state["validity"] == [company]
    _assert_one_bounded_find(state["posts"][0], company_id="130706", token=f"token-for-{company}")


@pytest.mark.parametrize("company", ["md", "md_test"])
def test_wo846b_find_by_marker_uses_the_pinned_company_id_of_the_tenant(harness, monkeypatch, company):
    client, state = harness
    monkeypatch.setenv("WFIRMA_MD_COMPANY_ID", "555001")
    state["responses"].append(_found())

    # Act
    response = _ask(client, company=company)

    assert response.status_code == 200
    _assert_one_bounded_find(state["posts"][0], company_id="555001", token=f"token-for-{company}")


@pytest.mark.parametrize("fault", ["no_token", "expired_token", "token_store_raises", "invalid_pin", "blank_token"])
def test_wo846b_find_by_marker_unavailable_identity_is_503_without_transport(harness, monkeypatch, fault):
    client, state = harness
    if fault == "no_token":
        monkeypatch.setattr(app_module, "load_token", lambda **_kwargs: None)
    elif fault == "expired_token":
        monkeypatch.setattr(app_module, "is_token_valid_for_company", lambda _company: False)
    elif fault == "token_store_raises":
        def broken(**_kwargs):
            raise RuntimeError("secret database text")
        monkeypatch.setattr(app_module, "load_token", broken)
    elif fault == "invalid_pin":
        monkeypatch.setenv("WFIRMA_MD_COMPANY_ID", " 130706 ")
    else:
        monkeypatch.setattr(app_module, "load_token", lambda **_kwargs: " ")

    # Act
    response = _ask(client)

    assert response.status_code == 503
    assert response.get_json() == UNAVAILABLE
    assert state["posts"] == []
    assert "secret" not in response.get_data(as_text=True)


def test_wo846b_find_by_marker_is_not_wrapped_by_the_document_create_envelope(harness):
    # The create envelope stamps outcome="rejected" (= nothing created, the portal may
    # free a START) on any failure before a create: here it would replace
    # "provider_unavailable". The route answers its own closed outcome.
    client, state = harness
    state["responses"].append(FakeStreamResponse(500, {}))

    # Act
    response = _ask(client)

    assert response.get_json()["outcome"] == "provider_unavailable"
    view = app_module.app.view_functions["grouped_first_invoice_find_by_marker"]
    # Exactly one decorator (require_api_key): its target is the handler itself.
    assert not hasattr(view.__wrapped__, "__wrapped__")
    assert app_module.FIRST_INVOICE_MARKER_FIND_LIMIT == 2
    assert app_module.FIRST_INVOICE_MARKER_COMPANIES == frozenset({"md", "md_test"})


def test_wo846b_find_by_marker_route_is_post_only(harness):
    client, state = harness

    # Act
    response = client.get(PATH, headers=HEADERS)

    assert response.status_code == 405
    assert state["posts"] == []


# ------------------------------------------------------------------ manual contract smoke (md_test, read-only)


@pytest.mark.manual
@pytest.mark.skipif(not SMOKE, reason="manual contract smoke: WFIRMA_SMOKE=1, md OAuth in Postgres, read-only")
def test_wo846b_manual_smoke_md_test_invoices_find_by_id_external(monkeypatch):
    """Real wFirma, md_test, one read-only `invoices/find` per marker. NOT in the default run.

    Run alone, where the service's Postgres (OAuth tokens) is reachable:
      WFIRMA_SMOKE=1 WFIRMA_SMOKE_MARKER=nf1:... WFIRMA_SMOKE_INVOICE_ID=... \\
        python -m pytest tests/test_wo846b_find_by_marker.py -m manual -q

    Positive control (mandatory): the marker and id of an EXISTING md_test first invoice
    must come back as found=1 with that id. A route that cannot find a known invoice would
    answer "0" for every stuck settlement and free orders that do have an invoice.
    Negative control: a random marker must come back as found=0 (not 503).
    Only `invoices/find` and the OAuth token refresh may leave the process.
    """
    known_marker = os.environ.get("WFIRMA_SMOKE_MARKER", "")
    known_id = os.environ.get("WFIRMA_SMOKE_INVOICE_ID", "")
    assert known_marker and known_id, "set WFIRMA_SMOKE_MARKER and WFIRMA_SMOKE_INVOICE_ID (positive control)"
    real_post = requests.post

    def read_only_post(url, *args, **kwargs):
        assert url == FIND_URL or url.startswith("https://api2.wfirma.pl/oauth2/token"), url
        return real_post(url, *args, **kwargs)

    monkeypatch.setattr(app_module.requests, "post", read_only_post)
    monkeypatch.setattr(app_module, "wfirma_create_invoice", lambda *_a, **_k: pytest.fail("no create"))
    monkeypatch.setattr(app_module, "MAKE_RENDER_API_KEY", API_KEY)
    client = app_module.app.test_client()

    # Act
    known = client.post(PATH, json={"company": "md_test", "id_external": known_marker}, headers=HEADERS)
    unknown = client.post(PATH, json={"company": "md_test", "id_external": "nf1:" + secrets.token_hex(14)},
                          headers=HEADERS)

    assert known.status_code == 200, known.get_json()
    assert known.get_json()["found"] == 1 and known.get_json()["invoice_id"] == known_id
    assert unknown.status_code == 200, unknown.get_json()
    assert unknown.get_json() == {"success": True, "found": 0, "invoice_id": None}
