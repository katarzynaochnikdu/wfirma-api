"""WO-871 — `create-invoice-from-nip` accepts a PINNED receiver card.

Why: the portal's surcharge proforma goes through this route. The buyer's card
was pinned (`existing_contractor_id`), the receiver travelled only as a data
block and the bridge picked its card itself: by tax id, then by name, else a new
card. Several cards of one receiver are a normal state (`grouped-first-invoice`
always creates a new one when it gets no id), so the lookup could attach another
card than the one the portal proved - the proforma then existed at the provider
while the portal parked it in `requires_review` with no way out (BUG-186, W-1).

The contract:
* `receiver: {"id": "<card id>", "detail": {<8 party fields>}}` (exactly these
  two keys) selects the pinned mode: no lookup, no card creation; the card is
  read by its id and compared by the rule of `_first_invoice_party`; the
  receiver snapshot printed on the document is `detail` verbatim;
* every refusal is named and happens BEFORE the document POST;
* a flat block (with `name`) or no block at all behaves exactly as before;
* `GET /api/capabilities` lets the caller learn, before it starts anything
  durable, that this bridge honours the pin.

Real Flask handlers; the only I/O is a controlled stand-in for wFirma. All data
is invented for this file - no name or tax id is taken from another test.
"""
from __future__ import annotations

import json
import os
import sys
from copy import deepcopy

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importing app.py runs its startup hooks; empty values set BEFORE the import
# keep the tests away from a database and from the token/e-mail monitor.
os.environ["DATABASE_URL"] = ""
os.environ["MAKE_WEBHOOK_SEND_EMAIL_REQUEST"] = ""
os.environ["RENDER_EMAIL_KEY_SEND_REQUEST"] = ""

import app as app_module  # noqa: E402
import document_refusal_log as refusal_log  # noqa: E402

API_KEY = "wo871-synthetic-api-key"
HEADERS = {"X-API-Key": API_KEY}
ROUTE = "/api/workflow/create-invoice-from-nip"
CAPABILITIES = "/api/capabilities"
CAPABILITY = "invoice_from_nip_receiver_pin_v1"

# The receiver as a document prints it: all eight party fields, KSeF role "2".
DETAIL = {
    "role": "2",
    "name": "Zmyslony Oddzial Testowy 871",
    "tax_id_type": "custom",
    "nip": "0000000000-00871",
    "street": "Zmyslona 87",
    "zip": "00-871",
    "city": "Testowo",
    "country": "PL",
}
PINNED = "7002"
TWIN = "7999"


def card(card_id: str, **changes) -> dict:
    """A contractor card as wFirma reads it back: no role, provider extras."""
    value = {key: field for key, field in DETAIL.items() if key != "role"}
    value.update(id=card_id, altname=DETAIL["name"], created="2026-10-01 10:00:00")
    value.update(changes)
    return value


class Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code, self.payload = status_code, payload
        self.text = json.dumps(payload, ensure_ascii=False)
        self.headers = {"Content-Type": "application/json"}
        self.content = b""

    def json(self) -> dict:
        return self.payload

    def __bool__(self) -> bool:
        return self.status_code < 400


@pytest.fixture
def bridge(monkeypatch):
    """Real handlers over a stand-in provider that holds TWO cards of one receiver."""
    state = {
        "cards": {PINNED: card(PINNED), TWIN: card(TWIN)},
        "read_error": None,     # card id whose GET fails
        "reads": [],            # contractor GETs by id
        "lookups": [],          # every lookup / create helper the old cascade uses
        "tokens": [],
        "posts": [],            # invoices/add bodies
        "lookup_hit": None,     # what the tax-id lookup of the old cascade returns
        "provider_drops_receiver": False,
        "stored_receiver_id": 0,
    }

    def load_token(*args, **kwargs):
        state["tokens"].append(kwargs)
        return "synthetic-token"

    def strict_get(token, *, plural, singular, entity_id, company_id):
        assert (plural, singular) == ("contractors", "contractor"), "only a contractor card is read"
        state["reads"].append(entity_id)
        if state["read_error"] == entity_id or entity_id not in state["cards"]:
            return None, "not_found"
        return deepcopy(state["cards"][entity_id]), None

    def by_tax_id(token, identifier, company_id=None):
        state["lookups"].append(("by_tax_id", identifier))
        return deepcopy(state["lookup_hit"])

    def by_name(token, name, company_id=None):
        state["lookups"].append(("by_name", name))
        return None, None

    def add_contractor(token, payload, company_id=None):
        state["lookups"].append(("add", payload.get("name")))
        return {"id": "7555"}, None

    def create_party(token, company_id, detail):
        state["lookups"].append(("create_party", detail.get("name")))
        return "7556"

    def post(url, **kwargs):
        assert "/invoices/add" in url, f"WO-871 test blocked an unexpected provider write: {url}"
        document = kwargs["json"]["invoices"]["invoice"]
        state["posts"].append(document)
        if not state["provider_drops_receiver"]:
            state["stored_receiver_id"] = document.get("contractor_receiver_id", 0)
        return Response(200, {"status": {"code": "OK"}, "invoices": {"0": {"invoice": {
            "id": "9001", "fullnumber": "PF/TEST/871", "type": "proforma", "date": "2026-10-02",
            "total": "123.00", "paymentstate": "unpaid"}}}})

    def get_invoice(token, invoice_id, company_id=None):
        return {"id": invoice_id, "contractor_receiver": {"id": str(state["stored_receiver_id"])}}, None

    monkeypatch.setattr(app_module, "MAKE_RENDER_API_KEY", API_KEY)
    monkeypatch.setattr(app_module, "load_token", load_token)
    monkeypatch.setattr(app_module, "check_refresh_token_expiry_for_company", lambda *a, **k: (None, None))
    monkeypatch.setattr(app_module, "send_token_expiry_notification", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "wfirma_get_company_id", lambda *a, **k: "130706")
    monkeypatch.setattr(app_module, "wfirma_find_series_by_name",
                        lambda *a, **k: {"id": "71", "name": "Zmyslona Pro forma TEST"})
    monkeypatch.setattr(app_module, "wfirma_list_series", lambda *a, **k: [])
    monkeypatch.setattr(app_module, "wfirma_get_invoice_pdf",
                        lambda *a, **k: Response(404, {"error": "not found"}))
    monkeypatch.setattr(app_module, "_strict_wfirma_recovery_get", strict_get)
    monkeypatch.setattr(app_module, "wfirma_find_contractor_by_tax_id", by_tax_id)
    monkeypatch.setattr(app_module, "wfirma_find_contractor_by_name", by_name)
    monkeypatch.setattr(app_module, "wfirma_add_contractor", add_contractor)
    monkeypatch.setattr(app_module, "_first_invoice_create_party", create_party)
    monkeypatch.setattr(app_module, "wfirma_get_invoice", get_invoice)
    monkeypatch.setattr(app_module.requests, "post", post)
    monkeypatch.setattr(app_module.requests, "get",
                        lambda url, **kwargs: pytest.fail(f"unexpected provider read: {url}"))
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client(), state


def request_body(receiver=None) -> dict:
    """A surcharge proforma as the portal sends it: buyer card pinned, one gross line."""
    body = {
        "company": "md_test",
        "existing_contractor_id": "7001",
        "nip": "0000000000",
        "purchaser_name": "Zmyslony Nabywca Testowy 871",
        "document_type": "proforma",
        "series_name": "Zmyslona Pro forma TEST",
        "payment_status": "unpaid",
        "price_mode": "brutto",
        "send_email": False,
        "email": "",
        "invoice": {
            "issue_date": "2026-10-02",
            "payment_due_date": "2026-10-09",
            "positions": [{"name": "Doplata testowa", "unit": "szt.", "quantity": 1,
                           "unit_price_gross": "123.00", "vat_rate": "23"}],
        },
    }
    if receiver is not None:
        body["receiver"] = receiver
    return body


def pin(card_id=PINNED, **detail_changes) -> dict:
    return {"id": card_id, "detail": dict(DETAIL, **detail_changes)}


def bridge_lines(capsys) -> tuple[str, list[str]]:
    captured = capsys.readouterr()
    text = captured.out + captured.err
    return text, [row for row in text.splitlines() if row.startswith(refusal_log.PREFIX)]


def refusal_line(reason: str) -> str:
    return f"[document-bridge] refused stage=invoice_receiver_pin reason={reason} exc=grouped_document_error"


# ---------------------------------------------------------------------------
# 1) The pin is honoured: the document is linked to the card the caller named
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pinned,other", [(PINNED, TWIN), (TWIN, PINNED)], ids=["first_card", "second_card"])
def test_wo871_pinned_receiver_with_two_cards_links_the_document_to_the_pinned_card(bridge, capsys, pinned, other):
    # Arrange - two cards of the same receiver; the old lookup would return the OTHER one.
    client, state = bridge
    state["lookup_hit"] = card(other)

    # Act
    response = client.post(ROUTE, json=request_body(pin(pinned)), headers=HEADERS)

    # Assert - one document, attached to the pinned card and to nothing else.
    data = response.get_json()
    assert response.status_code == 200, data
    assert data["success"] is True and data["invoice_id"] == "9001"
    assert data["receiver_contractor_id"] == int(pinned) and data["receiver_pinned"] is True
    assert len(state["posts"]) == 1
    document = state["posts"][0]
    assert document["contractor_receiver_id"] == int(pinned)
    # The snapshot printed on the document is the caller's detail, verbatim.
    assert document["contractor_detail_receiver"] == DETAIL
    # The card was read by its id; the lookup cascade never ran and no card was created.
    assert state["reads"] == [pinned] and state["lookups"] == []
    assert bridge_lines(capsys)[1] == []


def test_wo871_pinned_receiver_snapshot_is_not_normalised_and_drops_only_empty_fields(bridge):
    """`build_receiver_snapshot` would rewrite the zip code, upper-case the
    country and re-derive `tax_id_type`. A pinned snapshot is what the caller
    proved on the source document, so it is printed as it is."""
    # Arrange - a foreign receiver without a tax id; the card carries the same data.
    client, state = bridge
    changes = dict(tax_id_type="none", nip="", zip="10115", country="DE")
    state["cards"][PINNED] = card(PINNED, **changes)

    # Act
    response = client.post(ROUTE, json=request_body(pin(**changes)), headers=HEADERS)

    # Assert
    assert response.status_code == 200, response.get_json()
    snapshot = state["posts"][0]["contractor_detail_receiver"]
    assert snapshot == {key: value for key, value in dict(DETAIL, **changes).items() if value != ""}
    assert "nip" not in snapshot and snapshot["zip"] == "10115" and snapshot["tax_id_type"] == "none"


@pytest.mark.parametrize("card_role", ["0", "", None, "3"], ids=["zero", "empty", "absent", "other_code"])
def test_wo871_pinned_card_is_compared_without_its_own_role(bridge, card_role):
    """The KSeF role belongs to the document. A card created by the bridge
    carries none, and whatever it carries is overwritten by the document's."""
    # Arrange
    client, state = bridge
    if card_role is not None:
        state["cards"][PINNED]["role"] = card_role

    # Act
    response = client.post(ROUTE, json=request_body(pin()), headers=HEADERS)

    # Assert
    assert response.status_code == 200, response.get_json()
    assert state["posts"][0]["contractor_detail_receiver"]["role"] == "2"


def test_wo871_pinned_receiver_lost_by_the_provider_is_still_reported_as_created_unverified(bridge):
    """The readback assertion of WO-471 keeps guarding the pinned mode too."""
    # Arrange - wFirma accepts the document and silently drops the receiver.
    client, state = bridge
    state["provider_drops_receiver"] = True

    # Act
    response = client.post(ROUTE, json=request_body(pin()), headers=HEADERS)

    # Assert
    data = response.get_json()
    assert response.status_code == 502 and data["outcome"] == "created_unverified"
    assert data["receiver_verification_failed"] is True and data["invoice_id"] == "9001"
    assert (data["expected_receiver_id"], data["stored_receiver_id"]) == (int(PINNED), 0)
    assert len(state["posts"]) == 1


# ---------------------------------------------------------------------------
# 2) Every refusal is named and happens before the document POST
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field,value", [
    ("street", "Inna 9"), ("zip", "99-999"), ("city", "Innowo"), ("country", "DE"),
    ("name", "Zmyslony Inny Oddzial"), ("nip", "0000000000-00872"), ("tax_id_type", "nip"),
], ids=["street", "zip", "city", "country", "name", "nip", "tax_id_type"])
def test_wo871_pinned_card_with_different_data_is_refused_before_the_document_post(bridge, capsys, field, value):
    # Arrange - the pinned card was edited after the caller proved it.
    client, state = bridge
    state["cards"][PINNED][field] = value

    # Act
    response = client.post(ROUTE, json=request_body(pin()), headers=HEADERS)

    # Assert - a named 409, nothing sent to the provider, nothing created.
    data = response.get_json()
    assert response.status_code == 409, data
    assert data == {"success": False, "error": "receiver_pin_mismatch", "outcome": "rejected"}
    assert state["posts"] == [], "the POST counter stays at zero"
    assert state["reads"] == [PINNED] and state["lookups"] == []
    text, lines = bridge_lines(capsys)
    assert lines == [refusal_line("party_changed")]
    assert str(value) not in lines[0] and str(value) not in response.get_data(as_text=True)


def test_wo871_pinned_receiver_without_an_id_is_refused_and_no_card_is_created(bridge, capsys):
    """`grouped-first-invoice` creates one exact card for `id: null`. This route
    must not: a card created here is one more duplicate nobody proved."""
    # Arrange
    client, state = bridge

    # Act
    response = client.post(ROUTE, json=request_body(pin(None)), headers=HEADERS)

    # Assert - refused before the token is even loaded: no provider call at all.
    data = response.get_json()
    assert response.status_code == 400, data
    assert data == {"success": False, "error": "receiver_pin_id_missing", "outcome": "rejected"}
    assert state["tokens"] == [] and state["reads"] == [] and state["lookups"] == []
    assert state["posts"] == []
    assert bridge_lines(capsys)[1] == [refusal_line("receiver_pin_id_missing")]


@pytest.mark.parametrize("receiver,reason", [
    (pin(role=""), "receiver_role_invalid"),
    (pin(role="12"), "receiver_role_invalid"),
    (pin(role="0"), "invalid_grouped_contract"),
    (pin(7002), "invalid_grouped_contract"),
    (pin("0"), "invalid_grouped_contract"),
    (pin("07002"), "invalid_grouped_contract"),
    ({"id": PINNED, "detail": {k: v for k, v in DETAIL.items() if k != "country"}}, "invalid_grouped_contract"),
    ({"id": PINNED, "detail": dict(DETAIL, altname="x")}, "invalid_grouped_contract"),
    ({"id": PINNED, "detail": dict(DETAIL, street=" Zmyslona 87")}, "party_invalid"),
    ({"id": PINNED, "detail": dict(DETAIL, name="")}, "party_invalid"),
    ({"id": PINNED, "detail": "not an object"}, "invalid_grouped_contract"),
], ids=["empty_role", "role_above", "role_zero", "int_id", "zero_id", "padded_id", "missing_field",
        "extra_field", "untrimmed_field", "no_name", "detail_not_object"])
def test_wo871_malformed_pin_is_refused_before_any_provider_call(bridge, capsys, receiver, reason):
    # Arrange
    client, state = bridge

    # Act
    response = client.post(ROUTE, json=request_body(receiver), headers=HEADERS)

    # Assert
    data = response.get_json()
    assert response.status_code == 409, data
    assert data == {"success": False, "error": "receiver_pin_invalid", "outcome": "rejected"}
    assert state["tokens"] == [] and state["reads"] == [] and state["lookups"] == [] and state["posts"] == []
    assert bridge_lines(capsys)[1] == [refusal_line(reason)]


@pytest.mark.parametrize("fault", ["read_fails", "card_missing"])
def test_wo871_unreadable_pinned_card_is_refused_before_the_document_post(bridge, capsys, fault):
    # Arrange
    client, state = bridge
    if fault == "read_fails":
        state["read_error"] = PINNED
    else:
        del state["cards"][PINNED]

    # Act
    response = client.post(ROUTE, json=request_body(pin()), headers=HEADERS)

    # Assert - 502: the caller cannot tell a missing card from a provider outage.
    data = response.get_json()
    assert response.status_code == 502, data
    assert data == {"success": False, "error": "receiver_pin_unreadable", "outcome": "rejected"}
    assert state["posts"] == [] and state["lookups"] == []
    assert bridge_lines(capsys)[1] == [refusal_line("party_read_unavailable")]


def test_wo871_card_read_returning_another_id_is_refused_before_the_document_post(bridge, capsys):
    # Arrange - the provider answers the GET with a card of another id.
    client, state = bridge
    state["cards"][PINNED] = card(TWIN)

    # Act
    response = client.post(ROUTE, json=request_body(pin()), headers=HEADERS)

    # Assert
    assert response.status_code == 502 and response.get_json()["error"] == "receiver_pin_unreadable"
    assert state["posts"] == []
    assert bridge_lines(capsys)[1] == [refusal_line("party_read_unavailable")]


def test_wo871_unexpected_failure_of_the_pin_check_is_refused_without_its_text(bridge, capsys, monkeypatch):
    # Arrange - our own code fails inside the check with text that must not leave.
    client, state = bridge
    secret = "Zmyslony Oddzial buyer@test.example.pl"

    def broken(*args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(app_module, "_first_invoice_party", broken)

    # Act
    response = client.post(ROUTE, json=request_body(pin()), headers=HEADERS)

    # Assert
    data = response.get_json()
    assert response.status_code == 502, data
    assert data == {"success": False, "error": "receiver_pin_unverified", "outcome": "rejected"}
    assert state["posts"] == []
    text, lines = bridge_lines(capsys)
    assert lines == ["[document-bridge] refused stage=invoice_receiver_pin reason=unnamed exc=runtime_error"]
    assert secret not in response.get_data(as_text=True)


def test_wo871_pinned_receiver_is_checked_before_a_buyer_card_could_be_created(bridge, monkeypatch):
    """Without `existing_contractor_id` the route may create the buyer's card.
    A refused pin must not leave even that behind."""
    # Arrange - no buyer card id, and the pinned receiver card has changed.
    client, state = bridge
    body = request_body(pin())
    del body["existing_contractor_id"]
    state["cards"][PINNED]["city"] = "Innowo"
    buyer_lookups = []
    monkeypatch.setattr(app_module, "wfirma_find_contractor_by_nip",
                        lambda *a, **k: buyer_lookups.append("by_nip") or (None, None))

    # Act
    response = client.post(ROUTE, json=body, headers=HEADERS)

    # Assert
    assert response.status_code == 409 and response.get_json()["error"] == "receiver_pin_mismatch"
    assert buyer_lookups == [] and state["lookups"] == [] and state["posts"] == []


def test_wo871_pinned_receiver_request_without_an_api_key_touches_nothing(bridge):
    # Arrange
    client, state = bridge

    # Act
    response = client.post(ROUTE, json=request_body(pin()))

    # Assert
    assert response.status_code == 401 and response.get_json()["outcome"] == "rejected"
    assert state["tokens"] == [] and state["reads"] == [] and state["posts"] == []


def test_wo871_the_refusal_stage_is_a_declared_word_of_the_bridge_log():
    # Act / Assert - otherwise the line would read `stage=unnamed`.
    assert app_module.RECEIVER_PIN_STAGE == "invoice_receiver_pin"
    assert app_module.RECEIVER_PIN_STAGE in refusal_log._STAGES
    assert app_module.RECEIVER_PIN_KEYS == frozenset({"id", "detail"})


# ---------------------------------------------------------------------------
# 3) Everybody else: a flat block or no block behaves exactly as before
# ---------------------------------------------------------------------------

FLAT = {key: value for key, value in DETAIL.items() if key not in ("role", "tax_id_type")}


def test_wo871_flat_receiver_block_keeps_the_old_lookup_cascade(bridge, capsys):
    """Characterisation of the path every other caller uses: the card comes
    from the bridge's own lookup - here the tax-id search returns the twin."""
    # Arrange
    client, state = bridge
    state["lookup_hit"] = card(TWIN)

    # Act
    response = client.post(ROUTE, json=request_body(dict(FLAT)), headers=HEADERS)

    # Assert - the document is attached to whatever the lookup found.
    data = response.get_json()
    assert response.status_code == 200, data
    assert data["receiver_contractor_id"] == int(TWIN) and "receiver_pinned" not in data
    assert state["lookups"] == [("by_tax_id", DETAIL["nip"])]
    assert state["reads"] == [], "no card is read by id on the old path"
    document = state["posts"][0]
    assert document["contractor_receiver_id"] == int(TWIN)
    # Snapshot built by build_receiver_snapshot: default role, derived id type.
    assert document["contractor_detail_receiver"] == dict(FLAT, role="2", tax_id_type="custom")
    assert bridge_lines(capsys)[1] == []


def test_wo871_flat_receiver_block_still_creates_a_card_when_the_lookup_finds_none(bridge):
    # Arrange - neither the tax id nor the name is known to the provider.
    client, state = bridge

    # Act
    response = client.post(ROUTE, json=request_body(dict(FLAT)), headers=HEADERS)

    # Assert
    assert response.status_code == 200, response.get_json()
    assert [step for step, _ in state["lookups"]] == ["by_tax_id", "by_name", "add"]
    assert state["posts"][0]["contractor_receiver_id"] == 7555 and state["reads"] == []


def test_wo871_flat_block_that_also_carries_id_and_detail_is_not_the_pinned_mode(bridge):
    """Only EXACTLY `{id, detail}` selects the pin. Anything wider is the old
    flat block: its `id`/`detail` keys are ignored, as every unknown key is."""
    # Arrange
    client, state = bridge
    state["lookup_hit"] = card(TWIN)

    # Act
    response = client.post(ROUTE, json=request_body(dict(FLAT, id=PINNED, detail=dict(DETAIL))), headers=HEADERS)

    # Assert
    data = response.get_json()
    assert response.status_code == 200 and "receiver_pinned" not in data
    assert data["receiver_contractor_id"] == int(TWIN) and state["reads"] == []


def test_wo871_request_without_a_receiver_is_issued_exactly_as_before(bridge, capsys):
    # Arrange
    client, state = bridge

    # Act
    response = client.post(ROUTE, json=request_body(), headers=HEADERS)

    # Assert
    data = response.get_json()
    assert response.status_code == 200, data
    assert data["receiver_contractor_id"] is None and "receiver_pinned" not in data
    assert "contractor_receiver_id" not in state["posts"][0]
    assert "contractor_detail_receiver" not in state["posts"][0]
    assert state["reads"] == [] and state["lookups"] == []


@pytest.mark.parametrize("receiver", [
    {key: value for key, value in FLAT.items() if key != "name"},
    dict(FLAT, name="   "),
    {"id": PINNED, "detail": dict(DETAIL), "role": "2"},
    {"id": PINNED},
    {"detail": dict(DETAIL)},
], ids=["no_name", "blank_name", "pin_with_a_third_key", "id_only", "detail_only"])
def test_wo871_receiver_block_without_a_name_is_refused_with_400_before_the_document_post(bridge, receiver):
    """The portal's second safety layer stands on this validation: a bridge
    that does not know the pinned shape sees `{id, detail}` as a flat block
    WITHOUT `name` and answers this 400 - it never falls back to a lookup.
    Frozen here so that nobody relaxes it without seeing why it matters."""
    # Arrange
    client, state = bridge

    # Act
    response = client.post(ROUTE, json=request_body(receiver), headers=HEADERS)

    # Assert
    data = response.get_json()
    assert response.status_code == 400, data
    assert data["error"] == 'Odbiorca wymaga pola "name"' and data["outcome"] == "rejected"
    assert state["posts"] == [] and state["lookups"] == [] and state["reads"] == []


# ---------------------------------------------------------------------------
# 4) GET /api/capabilities
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("headers,status", [({}, 401), ({"X-API-Key": "wrong-wo871-key"}, 403)],
                         ids=["no_key", "wrong_key"])
def test_wo871_capabilities_route_requires_the_api_key(bridge, headers, status):
    # Arrange
    client, state = bridge

    # Act
    response = client.get(CAPABILITIES, headers=headers)

    # Assert
    assert response.status_code == status
    assert CAPABILITY not in response.get_data(as_text=True)


def test_wo871_capabilities_route_lists_the_receiver_pin_and_nothing_else(bridge):
    # Arrange
    client, state = bridge

    # Act
    response = client.get(CAPABILITIES, headers=HEADERS)

    # Assert - a list of names: no version, no commit, no configuration, no provider call.
    assert response.status_code == 200 and response.mimetype == "application/json"
    assert response.get_json() == {"success": True, "capabilities": [CAPABILITY]}
    assert response.headers["Cache-Control"] == "no-store"
    assert list(app_module.BRIDGE_CAPABILITIES) == [CAPABILITY]
    assert state["tokens"] == [] and state["reads"] == [] and state["posts"] == []


def test_wo871_capabilities_route_is_read_only(bridge):
    # Arrange
    client, state = bridge

    # Act
    response = client.post(CAPABILITIES, json={}, headers=HEADERS)

    # Assert
    assert response.status_code == 405
