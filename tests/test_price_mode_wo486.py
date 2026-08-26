"""WO-486 — tryb ceny 'brutto' w builderze dokumentow (plan_dokumenty_od_brutto, Etap 1).

Naprawiany blad: BUG-061. Dokument liczony od netto wychodzi na inna kwote niz
zamowienie, bo wFirma liczy VAT od SUMY netto stawki, a czesci kwot brutto (np.
4 410,00) nie da sie zlozyc z zadnego dwumiejscowego netto.

Testy pilnuja trzech rzeczy naraz:
  * tryb 'brutto' wysyla `price_type` i cene brutto,
  * BRAK trybu daje payload bit w bit jak przed zmiana (endpoint chroni jeden
    wspolny klucz API — nie wiadomo, kto jeszcze go wola),
  * polmigrowany konsument (zle pole ceny do trybu) dostaje 400, a nie cichy
    dokument fiskalny o 23% obok prawdy.

Uruchomienie (z katalogu APIV1):
    python -m pytest tests/test_price_mode_wo486.py -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (  # noqa: E402
    PRICE_FIELD_BY_MODE,
    VAT_CODE_MAP,
    build_invoice_payload,
    normalize_vat_key,
    resolve_price_mode,
)

CONTRACTOR = {"id": 198741779}
VAT_CODE_23 = VAT_CODE_MAP["23"]
VAT_CODE_8 = VAT_CODE_MAP["8"]


def _invoice(positions, **extra):
    payload = {"issue_date": "2026-08-26", "payment_due_days": 7, "positions": positions}
    payload.update(extra)
    return payload


def _prices(payload):
    """Ceny pozycji w kolejnosci indeksow, tak jak poleca do wFirmy."""
    contents = payload["invoicecontents"]
    return [contents[str(i)]["invoicecontent"]["price"] for i in range(len(contents))]


# --------------------------------------------------------------------------- #
# normalize_vat_key — koniec cichego domyslnika 23% (znalezisko A12)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("23", "23"),
        (23, "23"),
        (23.0, "23"),
        ("23.0", "23"),      # A12: backend wysyla wlasnie taki string
        ("23,0", "23"),
        ("23%", "23"),
        ("8", "8"),
        (8.0, "8"),
        (0.23, "23"),        # stawka podana ulamkiem — spotykane w integracjach no-code
        (0.08, "8"),
        ("0.05", "5"),
        ("zw", "zw"),
        ("ZW", "zw"),
        ("np", "np"),
        ("0", "0"),
    ],
)
def test_normalize_vat_key_accepts_every_shape_of_a_known_rate(raw, expected):
    # Act
    assert normalize_vat_key(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "abc", 7, 22.5, "17", True, {"id": 222}])
def test_normalize_vat_key_returns_none_for_an_unknown_rate(raw):
    # Act
    assert normalize_vat_key(raw) is None


# --------------------------------------------------------------------------- #
# resolve_price_mode
# --------------------------------------------------------------------------- #

def test_resolve_price_mode_defaults_to_netto_when_nothing_is_given():
    # Act
    mode, err = resolve_price_mode(None, None)
    # Assert
    assert (mode, err) == ("netto", None)


def test_resolve_price_mode_takes_the_first_non_empty_candidate():
    # Act
    mode, err = resolve_price_mode(None, "  BRUTTO  ")
    # Assert
    assert (mode, err) == ("brutto", None)


def test_resolve_price_mode_rejects_an_unknown_mode():
    # Act
    mode, err = resolve_price_mode("gross")
    # Assert
    assert mode is None
    assert "gross" in err


def test_price_field_by_mode_is_the_single_source_of_the_field_name():
    # Assert — testy nizej opieraja sie na tej mapie, wiec pilnujemy jej wprost
    assert PRICE_FIELD_BY_MODE == {"netto": "unit_price_net", "brutto": "unit_price_gross"}


# --------------------------------------------------------------------------- #
# Tryb netto — payload bit w bit jak przed WO-486
# --------------------------------------------------------------------------- #

def test_netto_mode_payload_carries_no_price_type_at_all():
    # Arrange
    positions = [{"name": "Bilet Basic", "quantity": 1, "unit_price_net": 398.37, "vat_rate": 23}]
    # Act
    payload, err = build_invoice_payload(_invoice(positions), CONTRACTOR)
    # Assert
    assert err is None
    assert "price_type" not in payload
    assert _prices(payload) == [398.37]


def test_explicit_netto_mode_still_carries_no_price_type():
    # Arrange
    positions = [{"name": "Bilet Basic", "quantity": 1, "unit_price_net": 398.37, "vat_rate": 23}]
    # Act
    payload, err = build_invoice_payload(_invoice(positions), CONTRACTOR, price_mode="netto")
    # Assert
    assert err is None
    assert "price_type" not in payload


def test_netto_mode_alreadypaid_initial_still_multiplies_by_the_vat_rate():
    # Arrange
    positions = [{"name": "Bilet", "quantity": 2, "unit_price_net": 100.00, "vat_rate": 23}]
    # Act
    payload, err = build_invoice_payload(_invoice(positions), CONTRACTOR, mark_as_paid=True)
    # Assert
    assert err is None
    assert float(payload["alreadypaid_initial"]) == pytest.approx(246.00)


def test_netto_mode_tolerates_more_than_two_decimals_without_changing_the_payload():
    # WHY: przed WO-486 cena szla do wFirmy surowym floatem. W trybie netto zostaje
    # ostrzezenie w logu, zeby nie zepsuc konsumentow, ktorych nie znamy.
    # Arrange
    positions = [{"name": "Bilet", "quantity": 1, "unit_price_net": 398.3739, "vat_rate": 23}]
    # Act
    payload, err = build_invoice_payload(_invoice(positions), CONTRACTOR)
    # Assert
    assert err is None
    assert _prices(payload) == [398.3739]


# --------------------------------------------------------------------------- #
# Tryb brutto
# --------------------------------------------------------------------------- #

def test_brutto_mode_sends_price_type_and_the_gross_price():
    # Arrange
    positions = [{"name": "Bilet Basic", "quantity": 1, "unit_price_gross": 490.00, "vat_rate": 23}]
    # Act
    payload, err = build_invoice_payload(_invoice(positions), CONTRACTOR, price_mode="brutto")
    # Assert
    assert err is None
    assert payload["price_type"] == "brutto"
    assert _prices(payload) == [490.00]
    assert payload["invoicecontents"]["0"]["invoicecontent"]["vat_code"] == {"id": VAT_CODE_23}


def test_brutto_mode_reads_the_price_mode_from_the_invoice_section_too():
    # Arrange
    positions = [{"name": "Bilet", "quantity": 1, "unit_price_gross": 490.00, "vat_rate": 23}]
    # Act
    payload, err = build_invoice_payload(_invoice(positions, price_mode="brutto"), CONTRACTOR)
    # Assert
    assert err is None
    assert payload["price_type"] == "brutto"


def test_brutto_mode_alreadypaid_initial_is_the_plain_sum_of_gross_prices():
    # WHY: w trybie netto ta sama linijka mnozy przez (1+VAT). Gdyby zostala, kwota
    # oplacona zostalaby pomnozona przez 1,23 DRUGI raz.
    # Arrange
    positions = [{"name": "Bilet", "quantity": 2, "unit_price_gross": 123.00, "vat_rate": 23}]
    # Act
    payload, err = build_invoice_payload(_invoice(positions), CONTRACTOR, mark_as_paid=True, price_mode="brutto")
    # Assert
    assert err is None
    assert float(payload["alreadypaid_initial"]) == pytest.approx(246.00)


def test_bug_061_nine_tickets_at_490_gross_sum_to_exactly_4410():
    """Test regresyjny BUG-061 — dokladnie przypadek z proformy, od ktorej sie zaczelo.

    Model od netto: 490 / 1,23 = 398,3739 -> 398,37; wFirma liczy VAT od SUMY netto
    stawki (9 x 398,37 = 3 585,33 -> VAT 824,63), wiec dokument opiewal na 4 409,96.
    """
    # Arrange
    positions = [
        {"name": f"Basic AMOZ XI #{i}", "quantity": 1, "unit_price_gross": 490.00, "vat_rate": 23}
        for i in range(9)
    ]
    # Act
    payload, err = build_invoice_payload(_invoice(positions), CONTRACTOR, mark_as_paid=True, price_mode="brutto")
    # Assert
    assert err is None
    assert _prices(payload) == [490.00] * 9
    assert float(payload["alreadypaid_initial"]) == pytest.approx(4410.00)


def test_brutto_mode_with_mixed_vat_rates_sums_to_the_plain_total():
    """Odwzorowuje FV/EV/TEST/2/8/2026 — jedyny wariant, w ktorym modele sie rozjezdzaly."""
    # Arrange
    positions = [
        {"name": "Pozycja 23%", "quantity": 1, "unit_price_gross": 490.00, "vat_rate": 23},
        {"name": "Pozycja 8%", "quantity": 1, "unit_price_gross": 100.00, "vat_rate": "8"},
    ]
    # Act
    payload, err = build_invoice_payload(_invoice(positions), CONTRACTOR, mark_as_paid=True, price_mode="brutto")
    # Assert
    assert err is None
    assert float(payload["alreadypaid_initial"]) == pytest.approx(590.00)
    contents = payload["invoicecontents"]
    assert contents["0"]["invoicecontent"]["vat_code"] == {"id": VAT_CODE_23}
    assert contents["1"]["invoicecontent"]["vat_code"] == {"id": VAT_CODE_8}


# --------------------------------------------------------------------------- #
# Walidacja krzyzowa tryb <-> pole ceny
# --------------------------------------------------------------------------- #

def test_brutto_mode_rejects_a_position_without_a_gross_price():
    # Arrange
    positions = [{"name": "Bilet", "quantity": 1, "unit_price_net": 398.37, "vat_rate": 23}]
    # Act
    payload, err = build_invoice_payload(_invoice(positions), CONTRACTOR, price_mode="brutto")
    # Assert
    assert payload is None
    assert "unit_price_gross" in err


def test_netto_mode_rejects_a_position_carrying_a_gross_price():
    # Arrange
    positions = [
        {"name": "Bilet", "quantity": 1, "unit_price_net": 398.37, "unit_price_gross": 490.00, "vat_rate": 23}
    ]
    # Act
    payload, err = build_invoice_payload(_invoice(positions), CONTRACTOR)
    # Assert
    assert payload is None
    assert "unit_price_gross" in err


def test_brutto_mode_rejects_a_position_carrying_a_net_price_as_well():
    # Arrange
    positions = [
        {"name": "Bilet", "quantity": 1, "unit_price_gross": 490.00, "unit_price_net": 398.37, "vat_rate": 23}
    ]
    # Act
    payload, err = build_invoice_payload(_invoice(positions), CONTRACTOR, price_mode="brutto")
    # Assert
    assert payload is None
    assert "unit_price_net" in err


def test_an_unknown_price_mode_is_refused_before_anything_is_built():
    # Arrange
    positions = [{"name": "Bilet", "quantity": 1, "unit_price_net": 398.37, "vat_rate": 23}]
    # Act
    payload, err = build_invoice_payload(_invoice(positions), CONTRACTOR, price_mode="gross")
    # Assert
    assert payload is None
    assert "price_mode" in err


# --------------------------------------------------------------------------- #
# Stawka VAT i kwantyzacja
# --------------------------------------------------------------------------- #

def test_an_unknown_vat_rate_is_refused_in_gross_mode():
    # Arrange
    positions = [{"name": "Bilet", "quantity": 1, "unit_price_gross": 490.00, "vat_rate": "17"}]
    # Act
    payload, err = build_invoice_payload(_invoice(positions), CONTRACTOR, price_mode="brutto")
    # Assert
    assert payload is None
    assert "17" in err


def test_an_unknown_vat_rate_in_net_mode_keeps_the_pre_change_default():
    """W trybie netto zostaje domyslnik 23% — tego endpointu moga uzywac konsumenci,
    ktorych nie znamy, a nowe 400 byloby dla nich regresja. Roznica wobec stanu sprzed
    WO-486: teraz widac to w logu, a normalizator rozpoznaje kazdy realny zapis stawki."""
    # Arrange
    positions = [{"name": "Bilet", "quantity": 1, "unit_price_net": 100.00, "vat_rate": "17"}]
    # Act
    payload, err = build_invoice_payload(_invoice(positions), CONTRACTOR)
    # Assert
    assert err is None
    assert payload["invoicecontents"]["0"]["invoicecontent"]["vat_code"] == {"id": VAT_CODE_23}


def test_a_vat_rate_written_as_23_0_string_still_maps_to_23_percent():
    # A12: taki wlasnie string wysyla dzis backend — do WO-486 trafial w default mapy
    # Arrange
    positions = [{"name": "Bilet", "quantity": 1, "unit_price_gross": 490.00, "vat_rate": "23.0"}]
    # Act
    payload, err = build_invoice_payload(_invoice(positions), CONTRACTOR, price_mode="brutto")
    # Assert
    assert err is None
    assert payload["invoicecontents"]["0"]["invoicecontent"]["vat_code"] == {"id": VAT_CODE_23}


def test_brutto_mode_refuses_a_price_with_three_decimals():
    # WHY: w trybie brutto cena JEST kwota do zaplaty — trzecie miejsce po przecinku
    # to cichy rozjazd z zamowieniem.
    # Arrange
    positions = [{"name": "Bilet", "quantity": 1, "unit_price_gross": 490.005, "vat_rate": 23}]
    # Act
    payload, err = build_invoice_payload(_invoice(positions), CONTRACTOR, price_mode="brutto")
    # Assert
    assert payload is None
    assert "2 miejsca" in err
