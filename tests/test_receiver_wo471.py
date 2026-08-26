"""WO-471 — Odbiorca inny niz Nabywca na dokumencie wFirma.

Testy pokrywaja to, co spike z 2026-08-26 wykryl jako grozne:
  * wFirma przyjmuje payload z samym `contractor_receiver_id` i GUBI odbiorce po cichu,
    wiec payload musi niesc OBA klucze albo zaden,
  * identyfikator jednostki wewnetrznej grupy VAT (`5272663852-80408`) nie jest NIP-em
    i przy `tax_id_type=nip` wFirma odrzuca kontrahenta,
  * zamowienie BEZ odbiorcy musi dawac payload bit-w-bit taki jak przed WO-471.

Uruchomienie (z katalogu APIV1):
    python -m pytest tests/test_receiver_wo471.py -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
from app import (  # noqa: E402
    RECEIVER_ROLE,
    _resolve_tax_id_type,
    build_invoice_payload,
    build_receiver_snapshot,
    receiver_stored_id,
    wfirma_resolve_receiver_contractor,
)

CONTRACTOR = {"id": 198741779}
POSITIONS = [{"name": "Bilet Basic", "quantity": 1, "unit_price_net": 398.37, "vat_rate": 23}]
INVOICE_INPUT = {"issue_date": "2026-08-26", "payment_due_days": 7, "positions": POSITIONS}

RECEIVER = {
    "name": "PZU Zdrowie S.A. Oddział Centra Medyczne w Warszawie",
    "nip": "5272663852-80408",
    "street": "Rondo Ignacego Daszyńskiego 4",
    "zip": "00-843",
    "city": "Warszawa",
}


# --------------------------------------------------------------------------- #
# _resolve_tax_id_type
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("1070048403", "nip"),            # Grupa VAT PZU — czysty polski NIP
        ("107-004-84-03", "nip"),         # ten sam numer z myslnikami
        (" 1070048403 ", "nip"),          # ze spacjami na brzegach
        ("5272663852-80408", "custom"),   # NIP grupy VAT + kod jednostki wewnetrznej
        ("CHE176.020.461", "custom"),     # numer zagraniczny (szwajcarski UID)
        ("527266385", "custom"),          # 9 cyfr — nie jest polskim NIP-em
        ("", "none"),
        (None, "none"),
    ],
)
def test_resolve_tax_id_type_classifies_identifier_by_shape(identifier, expected):
    # Act
    result = _resolve_tax_id_type(identifier)

    assert result == expected


# --------------------------------------------------------------------------- #
# build_receiver_snapshot
# --------------------------------------------------------------------------- #

def test_build_receiver_snapshot_sets_role_required_by_wfirma():
    """Pusta rola => wFirma odrzuca CALA fakture ("role: Pole nie moze byc puste.")."""
    # Act
    snapshot = build_receiver_snapshot(RECEIVER)

    assert snapshot["role"] == RECEIVER_ROLE
    assert snapshot["role"], "rola nie moze byc pusta"


def test_build_receiver_snapshot_uses_custom_type_for_vat_group_identifier():
    # Act
    snapshot = build_receiver_snapshot(RECEIVER)

    assert snapshot["tax_id_type"] == "custom"
    assert snapshot["nip"] == "5272663852-80408"


def test_build_receiver_snapshot_normalizes_polish_zip_to_wfirma_format():
    """wFirma przyjmuje polski kod WYLACZNIE jako XX-XXX."""
    # Act
    snapshot = build_receiver_snapshot({**RECEIVER, "zip": "00843"})

    assert snapshot["zip"] == "00-843"


def test_build_receiver_snapshot_omits_identifier_when_absent():
    # Act
    snapshot = build_receiver_snapshot({"name": "Odbiorca bez numeru", "city": "Warszawa"})

    assert "nip" not in snapshot
    assert snapshot["tax_id_type"] == "none"


def test_build_receiver_snapshot_respects_explicit_tax_id_type():
    # Act
    snapshot = build_receiver_snapshot({**RECEIVER, "tax_id_type": "regon"})

    assert snapshot["tax_id_type"] == "regon"


# --------------------------------------------------------------------------- #
# build_invoice_payload
# --------------------------------------------------------------------------- #

def test_build_invoice_payload_without_receiver_has_no_receiver_keys():
    """REGRESJA: 100% dotychczasowych zamowien nie ma Odbiorcy — payload bez zmian."""
    # Act
    payload, err = build_invoice_payload(INVOICE_INPUT, CONTRACTOR, token=None)

    assert err is None
    assert "contractor_receiver_id" not in payload
    assert "contractor_detail_receiver" not in payload


def test_build_invoice_payload_with_receiver_sets_both_keys():
    """Sam `contractor_receiver_id` wFirma przyjmuje i gubi odbiorce po cichu."""
    snapshot = build_receiver_snapshot(RECEIVER)

    # Act
    payload, err = build_invoice_payload(
        INVOICE_INPUT, CONTRACTOR, token=None,
        receiver_contractor_id=198741907, receiver_snapshot=snapshot,
    )

    assert err is None
    assert payload["contractor_receiver_id"] == 198741907
    assert payload["contractor_detail_receiver"]["role"] == RECEIVER_ROLE
    assert payload["contractor_detail_receiver"]["nip"] == "5272663852-80408"


def test_build_invoice_payload_rejects_receiver_id_without_snapshot():
    """Polowiczne dane = pewna cicha utrata odbiorcy. Lepiej nie wystawiac dokumentu."""
    # Act
    payload, err = build_invoice_payload(
        INVOICE_INPUT, CONTRACTOR, token=None, receiver_contractor_id=198741907,
    )

    assert payload is None
    assert "Odbiorca" in err


def test_build_invoice_payload_rejects_snapshot_without_receiver_id():
    # Act
    payload, err = build_invoice_payload(
        INVOICE_INPUT, CONTRACTOR, token=None, receiver_snapshot=build_receiver_snapshot(RECEIVER),
    )

    assert payload is None
    assert "Odbiorca" in err


# --------------------------------------------------------------------------- #
# receiver_stored_id — bezpiecznik przed CICHA UTRATA ODBIORCY
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "stored,expected",
    [
        ({"contractor_receiver": {"id": "198741907"}}, 198741907),  # zapisany poprawnie
        ({"contractor_receiver": {"id": 0}}, 0),                    # wFirma zgubila odbiorce
        ({"contractor_receiver": {}}, 0),
        ({"contractor_receiver": None}, 0),
        ({}, 0),
        (None, 0),                                                  # nie udalo sie odczytac
        ({"contractor_receiver": {"id": "nie-liczba"}}, 0),
    ],
)
def test_receiver_stored_id_treats_anything_but_a_real_id_as_missing(stored, expected):
    # Act
    result = receiver_stored_id(stored)

    assert result == expected


# --------------------------------------------------------------------------- #
# wfirma_resolve_receiver_contractor — kaskada bez duplikatow
# --------------------------------------------------------------------------- #

@pytest.fixture
def wfirma_stubs(monkeypatch):
    """Podstawia trzy wywolania wFirmy i zapisuje, ktore zostaly uzyte."""
    calls = {"by_tax_id": [], "by_name": [], "added": []}
    state = {"by_tax_id": None, "by_name": None, "added": None}

    def fake_by_tax_id(token, identifier, company_id=None):
        calls["by_tax_id"].append(identifier)
        return state["by_tax_id"]

    def fake_by_name(token, name, company_id=None):
        calls["by_name"].append(name)
        return state["by_name"], None

    def fake_add(token, payload, company_id=None):
        calls["added"].append(payload)
        return state["added"], None

    monkeypatch.setattr(app_module, "wfirma_find_contractor_by_tax_id", fake_by_tax_id)
    monkeypatch.setattr(app_module, "wfirma_find_contractor_by_name", fake_by_name)
    monkeypatch.setattr(app_module, "wfirma_add_contractor", fake_add)
    return calls, state


def test_resolve_receiver_reuses_contractor_found_by_identifier(wfirma_stubs):
    """Bez tego kazda kolejna faktura zakladalaby DUPLIKAT odbiorcy.

    Zmierzone na produkcji 2026-08-26: kontrahent ma nip '5272663852-80408', a szukanie
    wersja bez myslnika ('527266385280408') NIE znajduje go.
    """
    calls, state = wfirma_stubs
    state["by_tax_id"] = {"id": "198741907", "name": RECEIVER["name"]}

    # Act
    contractor, errors = wfirma_resolve_receiver_contractor("tok", RECEIVER, "130706")

    assert errors == []
    assert contractor["id"] == "198741907"
    assert calls["by_tax_id"] == ["5272663852-80408"], "identyfikator musi isc DOSLOWNIE"
    assert calls["by_name"] == [], "znaleziony po numerze — nie szukamy dalej"
    assert calls["added"] == [], "znaleziony — nie zakladamy nowego"


def test_resolve_receiver_falls_back_to_name_search(wfirma_stubs):
    calls, state = wfirma_stubs
    state["by_name"] = {"id": "74884330", "name": RECEIVER["name"]}

    # Act
    contractor, errors = wfirma_resolve_receiver_contractor("tok", RECEIVER, "130706")

    assert errors == []
    assert contractor["id"] == "74884330"
    assert calls["added"] == []


def test_resolve_receiver_creates_contractor_without_role_key(wfirma_stubs):
    """`role` nalezy do migawki na dokumencie, nie do rekordu kontrahenta."""
    calls, state = wfirma_stubs
    state["added"] = {"id": "198741907"}

    # Act
    contractor, errors = wfirma_resolve_receiver_contractor("tok", RECEIVER, "130706")

    assert errors == []
    assert contractor["id"] == "198741907"
    sent = calls["added"][0]
    assert "role" not in sent
    assert sent["tax_id_type"] == "custom"
    assert sent["altname"] == sent["name"]


def test_resolve_receiver_returns_wfirma_reason_when_rejected(wfirma_stubs):
    """wFirma odrzuca przez HTTP 200 — powod musi dojsc do wolajacego."""
    calls, state = wfirma_stubs
    state["added"] = {
        "errors": {"0": {"error": {"field": "nip", "message": "Nieprawidłowy NIP."}}}
    }

    # Act
    contractor, errors = wfirma_resolve_receiver_contractor("tok", RECEIVER, "130706")

    assert contractor is None
    assert errors == ["nip: Nieprawidłowy NIP."]


def test_resolve_receiver_requires_name(wfirma_stubs):
    calls, state = wfirma_stubs

    # Act
    contractor, errors = wfirma_resolve_receiver_contractor("tok", {"nip": "1070048403"}, "130706")

    assert contractor is None
    assert errors == ["name: Odbiorca wymaga nazwy"]
    assert calls["added"] == [], "bez nazwy nie zakladamy kontrahenta"
