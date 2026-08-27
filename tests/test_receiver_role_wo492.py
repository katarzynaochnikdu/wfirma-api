"""WO-492 — rola odbiorcy to KOD LICZBOWY KSeF, a korekta nie dziedziczy odbiorcy.

CO SIE STALO
------------
WO-471 wysylalo w `contractor_detail_receiver.role` slowo `"receiver"`. Dzialalo — ale
TYLKO na proformie, bo proforma nie jedzie do KSeF. Przy fakturze VAT wFirma buduje XML
dla KSeF i odrzuca CALY dokument:

    Pole Rola posiada niepoprawna wartosc, poprawne wartosci dla pola: 1..11

Czyli funkcja wygladala na dzialajaca (proformy wychodzily z Odbiorca), a faktura VAT dla
tego samego klienta NIE POWSTAWALA W OGOLE. Zmierzone 2026-08-27 na serii testowej:
rola `"receiver"` -> odrzucone; rola `"2"` -> FV/EV/TEST/4/8/2026 (KSeF ref
`7010659520-20260827-0EA9F5400001-AF`) oraz PROF/EV/TEST/8/8/2026.

Drugie ustalenie tego samego dnia: korekta do faktury z Odbiorca wyszla jako
FK/EV/TEST/4/8/2026 z `contractor_receiver.id = 0` — wFirma **nie dziedziczy** odbiorcy
na dokumencie korygujacym.

Uruchomienie (z katalogu APIV1):
    python -m pytest tests/test_receiver_role_wo491.py -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (  # noqa: E402
    RECEIVER_ROLE,
    RECEIVER_ROLE_ALLOWED,
    build_receiver_snapshot,
    receiver_block_from_invoice,
    resolve_receiver_role,
)

RECEIVER = {
    "name": "PZU Zdrowie S.A. Oddział Centra Medyczne w Warszawie",
    "nip": "5272663852-80408",
    "street": "Rondo Ignacego Daszyńskiego 4",
    "zip": "00-843",
    "city": "Warszawa",
}

#: Odczyt faktury macierzystej z wFirmy — ksztalt zmierzony, nie wymyslony.
PARENT_WITH_RECEIVER = {
    "fullnumber": "FV/EV/TEST/4/8/2026",
    "contractor_receiver": {"id": 198741907},
    "contractor_detail_receiver": {
        "id": "847168531",
        "role": "2",
        "name": "PZU Zdrowie S.A. Oddział Centra Medyczne w Warszawie",
        "tax_id_type": "custom",
        "nip": "5272663852-80408",
        "street": "Rondo Ignacego Daszyńskiego 4",
        "zip": "00-843",
        "city": "Warszawa",
        "country": "PL",
        "created": "2026-08-27 01:59:26",
        "modified": "2026-08-27 01:59:26",
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# Rola musi byc kodem KSeF
# ──────────────────────────────────────────────────────────────────────────────

def test_default_receiver_role_is_a_ksef_numeric_code():
    """Straznik przed powrotem do slowa — to jest CALA wada WO-492."""
    # Act
    role = RECEIVER_ROLE

    # Slowo w tym polu wywala fakture VAT na walidacji XML w KSeF
    assert role in RECEIVER_ROLE_ALLOWED
    assert role.isdigit()
    assert 1 <= int(role) <= 11


def test_allowed_roles_are_exactly_the_ksef_dictionary():
    # Act
    allowed = sorted(int(v) for v in RECEIVER_ROLE_ALLOWED)

    assert allowed == list(range(1, 12))


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_missing_role_falls_back_to_default(raw):
    # Act
    role, error = resolve_receiver_role(raw)

    assert error is None
    assert role == RECEIVER_ROLE


@pytest.mark.parametrize("raw", ["10", 10, " 2 "])
def test_role_from_request_is_accepted_when_in_dictionary(raw):
    """Dobor kodu bywa decyzja ksiegowa (np. 10 dla czlonka grupy VAT) — bez wdrozenia."""
    # Act
    role, error = resolve_receiver_role(raw)

    assert error is None
    assert role == str(raw).strip()


@pytest.mark.parametrize("raw", ["receiver", "0", "12", "odbiorca", "-1"])
def test_role_outside_dictionary_is_refused_before_any_document_is_created(raw):
    """Odrzucamy u siebie, z czytelnym powodem — zamiast bledu XML przy dokumencie."""
    # Act
    role, error = resolve_receiver_role(raw)

    assert role is None
    assert error is not None
    assert "KSeF" in error


def test_snapshot_carries_the_requested_role():
    # Act
    snapshot = build_receiver_snapshot(RECEIVER, "10")

    assert snapshot["role"] == "10"


def test_snapshot_without_explicit_role_uses_the_ksef_default():
    # Act
    snapshot = build_receiver_snapshot(RECEIVER)

    assert snapshot["role"] == RECEIVER_ROLE


# ──────────────────────────────────────────────────────────────────────────────
# Korekta przepisuje odbiorce z faktury macierzystej
# ──────────────────────────────────────────────────────────────────────────────

def test_correction_copies_receiver_from_parent_invoice():
    # Act
    block = receiver_block_from_invoice(PARENT_WITH_RECEIVER)

    # OBA klucze albo zaden — sam identyfikator wFirma przyjmuje i gubi po cichu
    assert block["contractor_receiver_id"] == 198741907
    assert block["contractor_detail_receiver"]["name"].startswith("PZU Zdrowie")
    assert block["contractor_detail_receiver"]["nip"] == "5272663852-80408"
    assert block["contractor_detail_receiver"]["role"] == "2"


def test_correction_snapshot_drops_wfirma_bookkeeping_fields():
    """`id`, `created`, `modified` to pola wFirmy — odsylanie ich zwrotnie prosi sie o klopot."""
    # Act
    snapshot = receiver_block_from_invoice(PARENT_WITH_RECEIVER)["contractor_detail_receiver"]

    assert set(snapshot) <= {"role", "name", "tax_id_type", "nip", "street", "zip", "city", "country"}


@pytest.mark.parametrize(
    "parent",
    [
        None,
        {},
        {"contractor_receiver": {"id": 0}},                       # wFirma zgubila odbiorce
        {"contractor_receiver": {"id": 5}},                       # jest id, brak migawki
        {"contractor_receiver": {"id": 5}, "contractor_detail_receiver": {}},
        {"contractor_receiver": {"id": 5}, "contractor_detail_receiver": {"name": "  "}},
    ],
)
def test_parent_without_usable_receiver_gives_empty_block(parent):
    """Brak odbiorcy na macierzystej = payload korekty bit w bit jak przed WO-492."""
    # Act
    block = receiver_block_from_invoice(parent)

    assert block == {}
