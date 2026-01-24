"""
Test UPDATE zamówienia w Zoho Backstage.
Próbuje różne metody HTTP i parametry (bezpieczny test - bez zmiany danych).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Referencyjnie"))
from zoho_oauth import exchange_refresh_for_tokens  # noqa: E402


CLIENT_ID = "1000.YLC6VBUIYXAM1AS8ITS4PECA9CZIVO"
CLIENT_SECRET = "9282a59044892e38064c5e90b2fda60a4b057e0bb3"
REFRESH_TOKEN = "1000.69ff540e329f057b925855080abdcd4b.bf995fc5b6f67fb919034db1e25279e4"
REGION = "eu"

PORTAL_ID = "20101549222"
EVENT_ID = "24311000000429149"
ORDER_ID = "24311000000839027"
API_BASE = "https://www.zohoapis.eu/backstage/v3"


def get_access_token() -> str:
    payload = exchange_refresh_for_tokens(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        refresh_token=REFRESH_TOKEN,
        region=REGION,
    )
    return payload["access_token"]


def test_update(method: str, url: str, access_token: str, payload: dict = None) -> Tuple[bool, int, str]:
    """
    Testuje UPDATE na endpoincie.
    Zwraca (success, status_code, message)
    """
    try:
        data = None
        if payload:
            data = json.dumps(payload).encode("utf-8")
        
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Zoho-oauthtoken {access_token}")
        req.add_header("Content-Type", "application/json")
        
        with urllib.request.urlopen(req, timeout=15) as response:
            status = response.status
            content = response.read().decode("utf-8", errors="ignore")
            
            if status in (200, 201, 204):
                try:
                    resp_data = json.loads(content)
                    sample = json.dumps(resp_data, indent=2)[:300]
                    return True, status, sample
                except Exception:
                    return True, status, content[:300] if content else "OK (no content)"
            else:
                return False, status, f"HTTP {status}"
                
    except urllib.error.HTTPError as e:
        try:
            error_content = e.read().decode("utf-8", errors="ignore")
            error_data = json.loads(error_content)
            msg = error_data.get("message", f"HTTP {e.code}")
        except Exception:
            msg = f"HTTP {e.code}"
        return False, e.code, msg
        
    except Exception as e:
        return False, 0, str(e)


def main() -> int:
    print("=" * 70)
    print("TEST UPDATE ZAMOWIENIA - ZOHO BACKSTAGE")
    print("=" * 70)
    print(f"Portal ID: {PORTAL_ID}")
    print(f"Event ID: {EVENT_ID}")
    print(f"Order ID: {ORDER_ID}")
    print()
    
    access_token = get_access_token()
    print(f"[OK] Access token: {access_token[:30]}...")
    print()
    
    # Najpierw pobierz aktualne dane zamówienia
    print("[*] Pobieram aktualne dane zamowienia...")
    url_get = f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/orders/{ORDER_ID}"
    req = urllib.request.Request(url_get)
    req.add_header("Authorization", f"Zoho-oauthtoken {access_token}")
    
    try:
        with urllib.request.urlopen(req) as response:
            order_data = json.loads(response.read())
            current_status = order_data.get("status")
            current_status_str = order_data.get("status_string")
            current_comment = order_data.get("order_comment", "")
            print(f"[OK] Status: {current_status} ({current_status_str})")
            print(f"[OK] Komentarz: '{current_comment}'")
    except Exception as e:
        print(f"[ERROR] Nie mozna pobrac zamowienia: {e}")
        return 1
    
    print()
    print("[*] Testuje rozne metody UPDATE...")
    print()
    
    # URL do UPDATE
    url_update = f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/orders/{ORDER_ID}"
    
    tests = []
    
    # === Test 1: PUT z minimalnym payloadem (tylko ID) ===
    tests.append(("PUT - minimal payload (id only)", "PUT", {"id": ORDER_ID}))
    
    # === Test 2: PUT z obecnym statusem (bez zmiany) ===
    tests.append(("PUT - same status (no change)", "PUT", {"status": current_status}))
    
    # === Test 3: PATCH z obecnym statusem ===
    tests.append(("PATCH - same status", "PATCH", {"status": current_status}))
    
    # === Test 4: PUT z dodaniem komentarza testowego ===
    test_comment = (current_comment or "") + " [API TEST]"
    tests.append(("PUT - add comment", "PUT", {"order_comment": test_comment}))
    
    # === Test 5: PATCH z dodaniem komentarza ===
    tests.append(("PATCH - add comment", "PATCH", {"order_comment": test_comment}))
    
    # === Test 6: PUT z pustym payloadem ===
    tests.append(("PUT - empty payload", "PUT", {}))
    
    # === Test 7: POST (zwykle nie używane do UPDATE) ===
    tests.append(("POST - test", "POST", {"order_comment": test_comment}))
    
    working = []
    failing = []
    
    for i, (name, method, payload) in enumerate(tests, 1):
        print(f"[{i}/{len(tests)}] {name}... ", end="", flush=True)
        success, status, msg = test_update(method, url_update, access_token, payload)
        
        if success:
            print(f"[OK] HTTP {status}")
            working.append((name, method, payload, status, msg))
        else:
            print(f"[FAIL] {msg}")
            failing.append((name, method, payload, status, msg))
    
    print()
    print("=" * 70)
    print("WYNIKI")
    print("=" * 70)
    
    if working:
        print(f"\n[OK] Dzialajace UPDATE ({len(working)}):")
        for name, method, payload, status, sample in working:
            print(f"\n  [{name}]")
            print(f"  Metoda: {method}")
            print(f"  Payload: {json.dumps(payload)}")
            print(f"  Status: {status}")
            print(f"  Response: {sample[:150]}")
    
    if failing:
        print(f"\n[FAIL] Niedzialajace ({len(failing)}):")
        for name, method, payload, status, msg in failing:
            print(f"  - {name} ({method}): {msg}")
    
    # Raport
    report = []
    report.append("# Order UPDATE - Test")
    report.append("")
    report.append(f"Portal: {PORTAL_ID}")
    report.append(f"Event: {EVENT_ID}")
    report.append(f"Order: {ORDER_ID}")
    report.append(f"Current Status: {current_status} ({current_status_str})")
    report.append("")
    
    if working:
        report.append("## ✅ Działające metody UPDATE")
        report.append("")
        for name, method, payload, status, sample in working:
            report.append(f"### {name}")
            report.append(f"- Metoda: `{method}`")
            report.append(f"- Payload: `{json.dumps(payload)}`")
            report.append(f"- Status: {status}")
            report.append(f"```json\n{sample}\n```")
            report.append("")
    
    if failing:
        report.append("## ❌ Niedziałające metody")
        report.append("")
        for name, method, payload, status, msg in failing:
            report.append(f"- **{name}** ({method}): {msg}")
        report.append("")
    
    with open("BACKSTAGE_ORDER_UPDATE_TEST.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    
    print("\n[OK] Raport: BACKSTAGE_ORDER_UPDATE_TEST.md")
    
    # Sprawdź czy status się zmienił
    print("\n[*] Sprawdzam czy status sie zmienil...")
    req_check = urllib.request.Request(url_get)
    req_check.add_header("Authorization", f"Zoho-oauthtoken {access_token}")
    
    try:
        with urllib.request.urlopen(req_check) as response:
            new_data = json.loads(response.read())
            new_status = new_data.get("status")
            new_comment = new_data.get("order_comment", "")
            print(f"[OK] Nowy status: {new_status} ({new_data.get('status_string')})")
            print(f"[OK] Nowy komentarz: '{new_comment}'")
            
            if new_status != current_status:
                print(f"[WARN] Status sie zmienil! {current_status} -> {new_status}")
            elif new_comment != current_comment:
                print(f"[INFO] Komentarz sie zmienil")
            else:
                print("[OK] Zadnych zmian (bezpieczny test)")
    except Exception as e:
        print(f"[ERROR] Nie mozna sprawdzic: {e}")
    
    return 0 if working else 1


if __name__ == "__main__":
    raise SystemExit(main())
