"""
Dogłębny test endpointa Agenda/Sessions w Zoho Backstage.
Próbuje wszystkie możliwe warianty URLi i parametrów.
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
EVENT_DATE = "2026-02-05"  # Z event details (start_time)
API_BASE = "https://www.zohoapis.eu/backstage/v3"


def get_access_token() -> str:
    payload = exchange_refresh_for_tokens(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        refresh_token=REFRESH_TOKEN,
        region=REGION,
    )
    return payload["access_token"]


def test_url(url: str, access_token: str) -> Tuple[bool, int, str]:
    """
    Zwraca (success, status_code, message)
    """
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", f"Zoho-oauthtoken {access_token}")
        req.add_header("Content-Type", "application/json")
        
        with urllib.request.urlopen(req, timeout=15) as response:
            status = response.status
            content = response.read().decode("utf-8", errors="ignore")
            
            if status == 200:
                try:
                    data = json.loads(content)
                    sample = json.dumps(data, indent=2)[:300]
                    return True, status, sample
                except Exception:
                    return True, status, content[:300]
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
    print("DOGLEBNY TEST AGENDA/SESSIONS - ZOHO BACKSTAGE")
    print("=" * 70)
    print(f"Portal ID: {PORTAL_ID}")
    print(f"Event ID: {EVENT_ID}")
    print(f"Event Date: {EVENT_DATE}")
    print()
    
    access_token = get_access_token()
    print(f"[OK] Access token: {access_token[:30]}...")
    print()
    
    # Lista wszystkich wariantów do przetestowania
    variants = []
    
    # === Wariant 1: /sessions (bez parametrów) ===
    variants.append(("sessions (no params)", f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/sessions"))
    
    # === Wariant 2: /session singular ===
    variants.append(("session singular (no params)", f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/session"))
    
    # === Wariant 3: /agenda ===
    variants.append(("agenda (no params)", f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/agenda"))
    
    # === Wariant 4: /sessions z parametrem ?day= ===
    variants.append(("sessions?day=YYYY-MM-DD", f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/sessions?day={EVENT_DATE}"))
    
    # === Wariant 5: /sessions z parametrem ?date= ===
    variants.append(("sessions?date=YYYY-MM-DD", f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/sessions?date={EVENT_DATE}"))
    
    # === Wariant 6: /sessions z parametrem ?agenda_day= ===
    variants.append(("sessions?agenda_day=YYYY-MM-DD", f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/sessions?agenda_day={EVENT_DATE}"))
    
    # === Wariant 7: /agenda z parametrem ?day= ===
    variants.append(("agenda?day=YYYY-MM-DD", f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/agenda?day={EVENT_DATE}"))
    
    # === Wariant 8: /agenda_days ===
    variants.append(("agenda_days", f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/agenda_days"))
    
    # === Wariant 9: /agendaDays camelCase ===
    variants.append(("agendaDays camelCase", f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/agendaDays"))
    
    # === Wariant 10: /sessions/{date} jako path param ===
    variants.append(("sessions/{date} path param", f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/sessions/{EVENT_DATE}"))
    
    # === Wariant 11: /agenda/{date} jako path param ===
    variants.append(("agenda/{date} path param", f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/agenda/{EVENT_DATE}"))
    
    # === Wariant 12: różne formaty daty ===
    date_formats = [
        EVENT_DATE,  # 2026-02-05
        EVENT_DATE.replace("-", ""),  # 20260205
        "1",  # agenda day 1
        "day1",  # day1
    ]
    
    for fmt in date_formats:
        variants.append((f"sessions?day={fmt}", f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/sessions?day={fmt}"))
    
    print(f"Testuje {len(variants)} wariantow...\n")
    
    working = []
    failing = []
    
    for i, (name, url) in enumerate(variants, 1):
        print(f"[{i:2}/{len(variants)}] {name}... ", end="", flush=True)
        success, status, msg = test_url(url, access_token)
        
        if success:
            print(f"[OK] HTTP {status}")
            working.append((name, url, status, msg))
        else:
            print(f"[FAIL] {msg}")
            failing.append((name, url, status, msg))
    
    print("\n" + "=" * 70)
    print("WYNIKI")
    print("=" * 70)
    
    if working:
        print(f"\n[OK] Dzialajace ({len(working)}):")
        for name, url, status, sample in working:
            print(f"\n  [{name}]")
            print(f"  URL: {url}")
            print(f"  Status: {status}")
            print(f"  Sample: {sample[:150]}")
    
    if failing:
        print(f"\n[FAIL] Niedzialajace ({len(failing)}):")
        for name, url, status, msg in failing:
            print(f"  - {name}: {msg}")
    
    # Zapisz szczegółowy raport
    report = []
    report.append("# Agenda/Sessions - Dogłębny Test")
    report.append("")
    report.append(f"Portal: {PORTAL_ID}")
    report.append(f"Event: {EVENT_ID}")
    report.append(f"Event Date: {EVENT_DATE}")
    report.append("")
    
    if working:
        report.append("## ✅ Działające warianty")
        report.append("")
        for name, url, status, sample in working:
            report.append(f"### {name}")
            report.append(f"- URL: `{url}`")
            report.append(f"- Status: {status}")
            report.append(f"```json\n{sample}\n```")
            report.append("")
    
    if failing:
        report.append("## ❌ Niedziałające warianty")
        report.append("")
        for name, url, status, msg in failing:
            report.append(f"- **{name}**: {msg}")
            report.append(f"  - URL: `{url}`")
        report.append("")
    
    with open("BACKSTAGE_AGENDA_DEEP_TEST.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    
    print("\n[OK] Raport: BACKSTAGE_AGENDA_DEEP_TEST.md")
    
    return 0 if working else 1


if __name__ == "__main__":
    raise SystemExit(main())
