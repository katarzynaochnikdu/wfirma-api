"""
Kompleksowy test CREATE/UPDATE/DELETE dla wszystkich modułów Backstage API.
BEZPIECZNY TEST - tworzy testowe dane i od razu je usuwa.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Tuple, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Referencyjnie"))
from zoho_oauth import exchange_refresh_for_tokens  # noqa: E402


CLIENT_ID = "1000.YLC6VBUIYXAM1AS8ITS4PECA9CZIVO"
CLIENT_SECRET = "9282a59044892e38064c5e90b2fda60a4b057e0bb3"
REFRESH_TOKEN = "1000.69ff540e329f057b925855080abdcd4b.bf995fc5b6f67fb919034db1e25279e4"
REGION = "eu"

PORTAL_ID = "20101549222"
EVENT_ID = "24311000000429149"
API_BASE = "https://www.zohoapis.eu/backstage/v3"


def get_access_token() -> str:
    payload = exchange_refresh_for_tokens(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        refresh_token=REFRESH_TOKEN,
        region=REGION,
    )
    return payload["access_token"]


def api_request(
    method: str,
    url: str,
    access_token: str,
    payload: Optional[dict] = None
) -> Tuple[bool, int, str, Optional[dict]]:
    """
    Wykonuje request API.
    Zwraca (success, status_code, message, response_data)
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
                    resp_data = json.loads(content) if content else {}
                    return True, status, "OK", resp_data
                except Exception:
                    return True, status, "OK (no JSON)", None
            else:
                return False, status, f"HTTP {status}", None
                
    except urllib.error.HTTPError as e:
        try:
            error_content = e.read().decode("utf-8", errors="ignore")
            error_data = json.loads(error_content)
            msg = error_data.get("message", f"HTTP {e.code}")
        except Exception:
            msg = f"HTTP {e.code}"
        return False, e.code, msg, None
        
    except Exception as e:
        return False, 0, str(e), None


def test_speaker_crud(access_token: str) -> dict:
    """Test CREATE/UPDATE/DELETE dla Speaker"""
    print("\n" + "=" * 70)
    print("TEST: SPEAKER (CREATE/UPDATE/DELETE)")
    print("=" * 70)
    
    results = {"create": False, "update": False, "delete": False}
    speaker_id = None
    
    # === CREATE Speaker ===
    url_create = f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/speakers"
    payload_create = {
        "email": "api.test.speaker@example.com",
        "first_name": "APITest",
        "last_name": "Speaker",
    }
    
    print("[CREATE] Probuje utworzyc speakera... ", end="", flush=True)
    success, status, msg, data = api_request("POST", url_create, access_token, payload_create)
    
    if success and data:
        speaker_id = data.get("id")
        print(f"[OK] Speaker created: ID={speaker_id}")
        results["create"] = True
    else:
        print(f"[FAIL] {msg}")
        return results
    
    time.sleep(0.5)
    
    # === UPDATE Speaker ===
    if speaker_id:
        url_update = f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/speakers/{speaker_id}"
        payload_update = {
            "designation": "Updated Test Speaker"
        }
        
        print("[UPDATE] Probuje zaktualizowac speakera... ", end="", flush=True)
        success, status, msg, data = api_request("PUT", url_update, access_token, payload_update)
        
        if success:
            print(f"[OK] HTTP {status}")
            results["update"] = True
        else:
            print(f"[FAIL] {msg}")
            # Spróbuj PATCH
            print("[UPDATE] Probuje PATCH... ", end="", flush=True)
            success, status, msg, data = api_request("PATCH", url_update, access_token, payload_update)
            if success:
                print(f"[OK] HTTP {status}")
                results["update"] = True
            else:
                print(f"[FAIL] {msg}")
        
        time.sleep(0.5)
    
    # === DELETE Speaker ===
    if speaker_id:
        url_delete = f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/speakers/{speaker_id}"
        
        print("[DELETE] Probuje usunac speakera... ", end="", flush=True)
        success, status, msg, data = api_request("DELETE", url_delete, access_token)
        
        if success:
            print(f"[OK] HTTP {status}")
            results["delete"] = True
        else:
            print(f"[FAIL] {msg}")
    
    return results


def test_sponsor_crud(access_token: str) -> dict:
    """Test CREATE/UPDATE/DELETE dla Sponsor"""
    print("\n" + "=" * 70)
    print("TEST: SPONSOR (CREATE/UPDATE/DELETE)")
    print("=" * 70)
    
    results = {"create": False, "update": False, "delete": False}
    sponsor_id = None
    
    # === CREATE Sponsor ===
    url_create = f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/sponsors"
    # Minimalny payload - tylko wymagane pola
    payload_create = {
        "sponsorship_type": "24311000000445140",  # STRATEGICZNY
        "company_name": "API Test Sponsor",
    }
    
    print("[CREATE] Probuje utworzyc sponsora... ", end="", flush=True)
    success, status, msg, data = api_request("POST", url_create, access_token, payload_create)
    
    if success and data:
        sponsor_id = data.get("id")
        print(f"[OK] Sponsor created: ID={sponsor_id}")
        results["create"] = True
    else:
        print(f"[FAIL] {msg}")
        return results
    
    time.sleep(0.5)
    
    # === UPDATE Sponsor ===
    if sponsor_id:
        url_update = f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/sponsors/{sponsor_id}"
        payload_update = {"sponsor_type": "Platinum"}
        
        print("[UPDATE] Probuje zaktualizowac sponsora (PUT)... ", end="", flush=True)
        success, status, msg, data = api_request("PUT", url_update, access_token, payload_update)
        
        if success:
            print(f"[OK] HTTP {status}")
            results["update"] = True
        else:
            print(f"[FAIL] {msg}")
    
    # === DELETE Sponsor ===
    if sponsor_id:
        url_delete = f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/sponsors/{sponsor_id}"
        
        print("[DELETE] Probuje usunac sponsora... ", end="", flush=True)
        success, status, msg, data = api_request("DELETE", url_delete, access_token)
        
        if success:
            print(f"[OK] HTTP {status}")
            results["delete"] = True
        else:
            print(f"[FAIL] {msg}")
    
    return results


def test_attendee_update_delete(access_token: str) -> dict:
    """Test UPDATE/DELETE dla Attendee (nie testujemy CREATE - attendees powstają przez orders)"""
    print("\n" + "=" * 70)
    print("TEST: ATTENDEE (UPDATE/DELETE - bez CREATE)")
    print("=" * 70)
    
    results = {"create": None, "update": False, "delete": False}
    
    # Pobierz pierwszego attendee
    url_get = f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/attendees"
    success, status, msg, data = api_request("GET", url_get, access_token)
    
    if not success or not data or not data.get("attendees"):
        print("[SKIP] Brak attendees do testowania")
        return results
    
    attendee = data["attendees"][0]
    attendee_id = attendee["id"]
    print(f"[INFO] Testuje na attendee ID: {attendee_id}")
    
    # === UPDATE Attendee ===
    url_update = f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/attendees/{attendee_id}"
    current_status = attendee.get("status", 1)
    
    print("[UPDATE] Probuje zaktualizowac attendee (PUT status=1)... ", end="", flush=True)
    success, status, msg, resp = api_request("PUT", url_update, access_token, {"status": current_status})
    
    if success:
        print(f"[OK] HTTP {status}")
        results["update"] = True
    else:
        print(f"[FAIL] {msg}")
        # Spróbuj PATCH
        print("[UPDATE] Probuje PATCH... ", end="", flush=True)
        success, status, msg, resp = api_request("PATCH", url_update, access_token, {"status": current_status})
        if success:
            print(f"[OK] HTTP {status}")
            results["update"] = True
        else:
            print(f"[FAIL] {msg}")
    
    # NIE TESTUJEMY DELETE attendee - żeby nie usunąć rzeczywistych uczestników
    print("[DELETE] [SKIP] Nie testujemy DELETE attendee (produkcyjne dane)")
    
    return results


def main() -> int:
    print("=" * 70)
    print("KOMPLEKSOWY TEST CRUD - ZOHO BACKSTAGE API v3")
    print("=" * 70)
    print(f"Portal ID: {PORTAL_ID}")
    print(f"Event ID: {EVENT_ID}")
    print()
    print("UWAGA: Ten test tworzy testowe dane i natychmiast je usuwa.")
    print()
    
    access_token = get_access_token()
    print(f"[OK] Access token: {access_token[:30]}...")
    
    # Testy
    all_results = {}
    
    all_results["speaker"] = test_speaker_crud(access_token)
    time.sleep(1)
    
    all_results["sponsor"] = test_sponsor_crud(access_token)
    time.sleep(1)
    
    all_results["attendee"] = test_attendee_update_delete(access_token)
    
    # Podsumowanie
    print("\n" + "=" * 70)
    print("PODSUMOWANIE WSZYSTKICH TESTOW")
    print("=" * 70)
    
    print("\n| Modul | CREATE | UPDATE | DELETE |")
    print("|-------|--------|--------|--------|")
    for module, results in all_results.items():
        c = "[OK]" if results["create"] else "[FAIL]"
        u = "[OK]" if results["update"] else "[FAIL]"
        d = "[OK]" if results["delete"] else "[FAIL]"
        print(f"| {module.capitalize()} | {c} | {u} | {d} |")
    
    # Zapisz raport
    report = []
    report.append("# Backstage API v3 - Test CRUD Operations")
    report.append("")
    report.append("## Wyniki")
    report.append("")
    report.append("| Moduł | CREATE | UPDATE | DELETE |")
    report.append("|-------|--------|--------|--------|")
    for module, results in all_results.items():
        c = "✅" if results["create"] else "❌"
        u = "✅" if results["update"] else "❌"
        d = "✅" if results["delete"] else "❌"
        report.append(f"| {module.capitalize()} | {c} | {u} | {d} |")
    report.append("")
    
    with open("BACKSTAGE_CRUD_TEST_RESULTS.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    
    print("\n[OK] Raport: BACKSTAGE_CRUD_TEST_RESULTS.md")
    
    # Sprawdź czy wszystko działa
    all_working = all(
        r["create"] and r["delete"]
        for r in all_results.values()
    )
    
    return 0 if all_working else 1


if __name__ == "__main__":
    raise SystemExit(main())
