#!/usr/bin/env python3
"""
Test: wystaw testową fakturę VAT, potem korektę na 0 z mark_refund_settled.
Używa serii TEST. Wymaga: DATABASE_URL, token wFirma dla company=test.
Uruchom z katalogu APIV1, gdzie jest .env z DATABASE_URL.
"""
import os
import sys

# Załaduj .env z katalogu projektu
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass

# Dla lokalnego uruchomienia: użyj EXTERNAL_DATABASE_URL (połączenie z zewnątrz Render)
if os.environ.get("EXTERNAL_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["EXTERNAL_DATABASE_URL"]

# Dodaj katalog główny projektu do ścieżki
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    from app import (
        load_token,
        wfirma_get_company_id,
        wfirma_find_series_by_name,
        wfirma_create_invoice,
        wfirma_create_correction,
        build_invoice_payload,
        WFIRMA_SERIES_CORRECTION_TEST,
    )
    WFIRMA_SERIES_NAME_TEST = os.environ.get("WFIRMA_SERIES_NAME_TEST", "Eventy Faktura VAT TEST")

    for company in ("test", "md"):
        token = load_token(silent=True, company=company)
        if token:
            print(f"[TEST] Używam tokenu dla company={company}")
            break
    else:
        print("[TEST] Brak tokenu wFirma. Zaloguj się: /auth?company=md lub /auth?company=test")
        return 1

    company_id = wfirma_get_company_id(token, company)
    if not company_id:
        print("[TEST] Nie udało się pobrać company_id")
        return 1

    # 1) Znajdź serię "Eventy Faktura VAT TEST"
    series = wfirma_find_series_by_name(token, WFIRMA_SERIES_NAME_TEST, company_id)
    if not series or not series.get("id"):
        print(f"[TEST] Nie znaleziono serii: {WFIRMA_SERIES_NAME_TEST}")
        return 1
    series_id = int(series["id"])
    print(f"[TEST] Seria FV: {WFIRMA_SERIES_NAME_TEST} -> ID {series_id}")

    # 2) Kontrahent testowy - znajdź po NIP lub weź pierwszego
    from app import wfirma_find_contractor_by_nip, _extract_contractor_id, get_wfirma_headers
    import requests as _req
    contractor = None
    for nip_try in ("7010659520", "5272816170", "5260250996"):
        contractor, _ = wfirma_find_contractor_by_nip(token, nip_try, company_id)
        if contractor:
            break
    if not contractor:
        # Fallback: pobierz pierwszego kontrahenta (limit 1)
        api_url = f"https://api2.wfirma.pl/contractors/find?inputFormat=json&outputFormat=json&oauth_version=2&company_id={company_id}"
        r = _req.post(api_url, headers=get_wfirma_headers(token), json={"contractors": {"parameters": {"limit": 1, "page": 1}}})
        if r.status_code == 200:
            data = r.json()
            for k, v in (data.get("contractors") or {}).items():
                if k.isdigit() and isinstance(v, dict) and v.get("contractor"):
                    contractor = v["contractor"]
                    break
    if not contractor:
        print("[TEST] Nie znaleziono kontrahenta. Dodaj kontrahenta w wFirma.")
        return 1

    contractor_id = _extract_contractor_id(contractor)
    if not contractor_id:
        print("[TEST] Nie można wyciągnąć ID kontrahenta")
        return 1
    print(f"[TEST] Kontrahent: {contractor.get('name', '?')} (ID {contractor_id})")

    # 3) Faktura testowa
    invoice_input = {
        "positions": [
            {"name": "Test usługa - korekta flow", "quantity": 1, "unit_price_net": 100.0, "vat_rate": "23"}
        ]
    }
    payload, err = build_invoice_payload(
        invoice_input, contractor, token,
        series_id=series_id, mark_as_paid=True, document_type="normal"
    )
    if err or not payload:
        print(f"[TEST] Błąd build_invoice_payload: {err}")
        return 1

    payload["description"] = "!!! TEST - korekta payment flow !!!"

    invoice, resp = wfirma_create_invoice(token, payload, company_id)
    if not invoice or not invoice.get("id"):
        print(f"[TEST] Nie udało się utworzyć faktury: {resp.text[:500] if resp else 'brak'}")
        return 1

    fv_id = invoice.get("id")
    fv_number = invoice.get("fullnumber", "")
    print(f"[TEST] Faktura VAT utworzona: {fv_number} (ID {fv_id})")

    # 4) Korekta na 0 + mark_refund_settled
    correction, resp_c = wfirma_create_correction(
        token=token,
        source_invoice_id=str(fv_id),
        correction_description="Test korekty - odhaczanie płatności",
        company_id=company_id,
        series_name_override=WFIRMA_SERIES_CORRECTION_TEST,
        mark_refund_settled=True,
        send_email=False,
    )

    if not correction or not correction.get("id"):
        print(f"[TEST] Nie udało się utworzyć korekty: {resp_c.text[:500] if resp_c else 'brak'}")
        return 1

    fk_number = correction.get("fullnumber", "")
    print(f"[TEST] Korekta utworzona: {fk_number} (mark_refund_settled=True)")
    print("[TEST] Gotowe. Sprawdź w wFirma czy korekta ma płatność jako rozliczoną.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
