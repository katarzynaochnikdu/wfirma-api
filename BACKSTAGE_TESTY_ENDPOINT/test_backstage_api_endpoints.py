"""
Kompletny test wszystkich endpointów Zoho Backstage API v3.

Sprawdza które endpointy faktycznie działają z tokenem wygenerowanym dla scope'ów Backstage.
Tworzy raport MD z listą działających i niedziałających endpointów.

Dane testowe (z JSONa zamówienia):
- Portal ID: 20101549222
- Event ID: 24311000000429149
- Order ID: 24311000000839027
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional

# Dodaj katalog referencyjny do ścieżki importu
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Referencyjnie"))

from zoho_oauth import exchange_refresh_for_tokens  # noqa: E402


# === DANE TESTOWE ===
CLIENT_ID = "1000.YLC6VBUIYXAM1AS8ITS4PECA9CZIVO"
CLIENT_SECRET = "9282a59044892e38064c5e90b2fda60a4b057e0bb3"
REFRESH_TOKEN = None  # Podaj refresh token wygenerowany przez test_backstage_oauth.py
REGION = "eu"

# IDs z JSONa zamówienia
PORTAL_ID = "20101549222"
EVENT_ID = "24311000000429149"
ORDER_ID = "24311000000839027"
TICKET_CLASS_ID = "24311000000547201"

# Base URL dla regionu EU
API_BASE = "https://www.zohoapis.eu/backstage/v3"


class EndpointTest:
    """Pojedynczy test endpointa"""
    def __init__(
        self,
        name: str,
        method: str,
        url: str,
        description: str,
        required_scopes: List[str],
    ):
        self.name = name
        self.method = method
        self.url = url
        self.description = description
        self.required_scopes = required_scopes
        self.status_code: Optional[int] = None
        self.success: bool = False
        self.error_message: Optional[str] = None
        self.response_sample: Optional[str] = None


def get_access_token() -> str:
    """Wygeneruj access token z refresh tokena"""
    if not REFRESH_TOKEN:
        raise ValueError(
            "Brak REFRESH_TOKEN. Wygeneruj go przez test_backstage_oauth.py i wklej tutaj."
        )
    
    payload = exchange_refresh_for_tokens(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        refresh_token=REFRESH_TOKEN,
        region=REGION,
    )
    
    if "error" in payload:
        raise RuntimeError(f"Błąd wymiany refresh tokena: {payload}")
    
    access_token = payload.get("access_token")
    if not access_token:
        raise RuntimeError("Brak access_token w odpowiedzi")
    
    return access_token


def test_endpoint(endpoint: EndpointTest, access_token: str) -> None:
    """Testuj pojedynczy endpoint"""
    try:
        req = urllib.request.Request(endpoint.url, method=endpoint.method)
        req.add_header("Authorization", f"Zoho-oauthtoken {access_token}")
        req.add_header("Content-Type", "application/json")
        
        with urllib.request.urlopen(req, timeout=15) as response:
            endpoint.status_code = response.status
            content = response.read().decode("utf-8", errors="ignore")
            
            if endpoint.status_code == 200:
                endpoint.success = True
                # Zapisz próbkę odpowiedzi (max 200 znaków)
                try:
                    data = json.loads(content)
                    endpoint.response_sample = json.dumps(data, indent=2)[:200]
                except Exception:
                    endpoint.response_sample = content[:200]
            else:
                endpoint.success = False
                endpoint.error_message = f"HTTP {endpoint.status_code}"
                
    except urllib.error.HTTPError as e:
        endpoint.status_code = e.code
        endpoint.success = False
        try:
            error_content = e.read().decode("utf-8", errors="ignore")
            try:
                error_data = json.loads(error_content)
                endpoint.error_message = error_data.get("message", f"HTTP {e.code}")
            except Exception:
                endpoint.error_message = f"HTTP {e.code}"
        except Exception:
            endpoint.error_message = f"HTTP {e.code}"
            
    except urllib.error.URLError as e:
        endpoint.success = False
        endpoint.error_message = f"URL Error: {e.reason}"
    except Exception as e:
        endpoint.success = False
        endpoint.error_message = f"Error: {e}"


def build_test_suite() -> List[EndpointTest]:
    """Zbuduj pełną listę endpointów do przetestowania"""
    tests = []
    
    # === PORTALS ===
    tests.append(EndpointTest(
        name="Get All Portals",
        method="GET",
        url=f"{API_BASE}/portals",
        description="Lista wszystkich portali",
        required_scopes=["zohobackstage.portal.READ"],
    ))
    
    tests.append(EndpointTest(
        name="Get Specific Portal",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}",
        description="Szczegóły konkretnego portalu",
        required_scopes=["zohobackstage.portal.READ"],
    ))
    
    # === EVENTS ===
    tests.append(EndpointTest(
        name="Get All Events",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events",
        description="Lista wszystkich wydarzeń w portalu",
        required_scopes=["zohobackstage.event.READ"],
    ))
    
    tests.append(EndpointTest(
        name="Get Specific Event",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}",
        description="Szczegóły konkretnego wydarzenia",
        required_scopes=["zohobackstage.event.READ"],
    ))
    
    # === MEMBERS (portal + event) ===
    tests.append(EndpointTest(
        name="Get All Portal Members",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/members",
        description="Lista wszystkich członków portalu",
        required_scopes=["zohobackstage.portal.READ"],
    ))
    
    tests.append(EndpointTest(
        name="Get All Event Members",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/members",
        description="Lista wszystkich członków wydarzenia",
        required_scopes=["zohobackstage.event.READ"],
    ))
    
    # === SESSIONS (AGENDA) - różne warianty URLi ===
    tests.append(EndpointTest(
        name="Get All Sessions (variant 1: /sessions)",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/sessions",
        description="Lista wszystkich sesji/agendy",
        required_scopes=["zohobackstage.agenda.READ"],
    ))
    
    tests.append(EndpointTest(
        name="Get All Sessions (variant 2: /agenda)",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/agenda",
        description="Lista wszystkich sesji/agendy (wariant 2)",
        required_scopes=["zohobackstage.agenda.READ"],
    ))
    
    tests.append(EndpointTest(
        name="Get All Sessions (variant 3: /session singular)",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/session",
        description="Lista wszystkich sesji (wariant singular)",
        required_scopes=["zohobackstage.agenda.READ"],
    ))
    
    # === SPEAKERS ===
    tests.append(EndpointTest(
        name="Get All Speakers (plural /speakers)",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/speakers",
        description="Lista wszystkich prelegentów (plural)",
        required_scopes=["zohobackstage.speaker.READ"],
    ))
    
    tests.append(EndpointTest(
        name="Get All Speakers (singular /speaker)",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/speaker",
        description="Lista wszystkich prelegentów (singular - dokumentacja)",
        required_scopes=["zohobackstage.speaker.READ"],
    ))
    
    # === SPONSORS ===
    tests.append(EndpointTest(
        name="Get All Sponsors (plural /sponsors)",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/sponsors",
        description="Lista wszystkich sponsorów (plural)",
        required_scopes=["zohobackstage.sponsor.READ"],
    ))
    
    tests.append(EndpointTest(
        name="Get All Sponsors (singular /sponsor)",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/sponsor",
        description="Lista wszystkich sponsorów (singular)",
        required_scopes=["zohobackstage.sponsor.READ"],
    ))
    
    # === TICKETS (TICKET CLASSES) - różne warianty ===
    tests.append(EndpointTest(
        name="Get All Ticket Classes (variant 1: /ticket_classes underscore)",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/ticket_classes",
        description="Lista wszystkich klas biletów (underscore - DOKUMENTACJA)",
        required_scopes=["zohobackstage.eventticket.READ"],
    ))
    
    tests.append(EndpointTest(
        name="Get Specific Ticket Class (underscore)",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/ticket_classes/{TICKET_CLASS_ID}",
        description="Szczegóły konkretnej klasy biletu (underscore)",
        required_scopes=["zohobackstage.eventticket.READ"],
    ))
    
    tests.append(EndpointTest(
        name="Get All Ticket Classes (variant 2: /ticketClasses camelCase)",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/ticketClasses",
        description="Lista wszystkich klas biletów (camelCase)",
        required_scopes=["zohobackstage.eventticket.READ"],
    ))
    
    tests.append(EndpointTest(
        name="Get All Ticket Classes (variant 3: /tickets)",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/tickets",
        description="Lista wszystkich biletów",
        required_scopes=["zohobackstage.eventticket.READ"],
    ))
    
    # === ORDERS ===
    tests.append(EndpointTest(
        name="Get All Orders",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/orders",
        description="Lista wszystkich zamówień",
        required_scopes=["zohobackstage.order.READ"],
    ))
    
    tests.append(EndpointTest(
        name="Get Specific Order",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/orders/{ORDER_ID}",
        description="Szczegóły konkretnego zamówienia",
        required_scopes=["zohobackstage.order.READ"],
    ))
    
    # === ATTENDEES ===
    tests.append(EndpointTest(
        name="Get All Attendees",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/attendees",
        description="Lista wszystkich uczestników",
        required_scopes=["zohobackstage.attendee.READ"],
    ))
    
    # === EXHIBITORS - różne warianty ===
    tests.append(EndpointTest(
        name="Get All Exhibitors (variant 1: /exhibitors)",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/exhibitors",
        description="Lista wszystkich wystawców (plural)",
        required_scopes=["zohobackstage.exhibitor.READ"],
    ))
    
    tests.append(EndpointTest(
        name="Get All Exhibitors (variant 2: /exhibitor singular)",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/exhibitor",
        description="Lista wszystkich wystawców (singular)",
        required_scopes=["zohobackstage.exhibitor.READ"],
    ))
    
    # === WEBHOOKS - różne warianty ===
    tests.append(EndpointTest(
        name="Get All Webhooks (variant 1: /webhooks plural)",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/webhooks",
        description="Lista wszystkich webhooków (plural)",
        required_scopes=["zohobackstage.webhook.READ"],
    ))
    
    tests.append(EndpointTest(
        name="Get All Webhooks (variant 2: /webhook singular)",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/webhook",
        description="Lista wszystkich webhooków (singular)",
        required_scopes=["zohobackstage.webhook.READ"],
    ))
    
    tests.append(EndpointTest(
        name="Get All Webhooks (variant 3: portal level)",
        method="GET",
        url=f"{API_BASE}/portals/{PORTAL_ID}/webhooks",
        description="Lista webhooków na poziomie portalu",
        required_scopes=["zohobackstage.webhook.READ"],
    ))
    
    return tests


def write_markdown_report(
    tests: List[EndpointTest],
    output_path: str,
) -> None:
    """Zapisz raport testów do pliku MD"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    lines = []
    lines.append("# Zoho Backstage API - Test Endpointów")
    lines.append("")
    lines.append(f"- **Data**: `{now}`")
    lines.append(f"- **Portal ID**: `{PORTAL_ID}`")
    lines.append(f"- **Event ID**: `{EVENT_ID}`")
    lines.append(f"- **Order ID**: `{ORDER_ID}`")
    lines.append(f"- **Region**: `{REGION}`")
    lines.append(f"- **API Base**: `{API_BASE}`")
    lines.append("")
    
    working = [t for t in tests if t.success]
    failing = [t for t in tests if not t.success]
    
    lines.append(f"## 📊 Podsumowanie")
    lines.append("")
    lines.append(f"- ✅ **Działające**: {len(working)}/{len(tests)}")
    lines.append(f"- ❌ **Niedziałające**: {len(failing)}/{len(tests)}")
    lines.append("")
    
    if working:
        lines.append("## ✅ Działające endpointy")
        lines.append("")
        lines.append("| Endpoint | Metoda | Scope | Status |")
        lines.append("|----------|--------|-------|--------|")
        for t in working:
            scope_str = ", ".join(t.required_scopes)
            lines.append(f"| {t.name} | `{t.method}` | `{scope_str}` | {t.status_code} |")
        lines.append("")
    
    if failing:
        lines.append("## ❌ Niedziałające endpointy")
        lines.append("")
        lines.append("| Endpoint | Metoda | Scope | Status | Błąd |")
        lines.append("|----------|--------|-------|--------|------|")
        for t in failing:
            scope_str = ", ".join(t.required_scopes)
            error = t.error_message or "N/A"
            status = t.status_code or "N/A"
            lines.append(f"| {t.name} | `{t.method}` | `{scope_str}` | {status} | {error} |")
        lines.append("")
    
    lines.append("## 📋 Szczegóły testów")
    lines.append("")
    for t in tests:
        icon = "✅" if t.success else "❌"
        lines.append(f"### {icon} {t.name}")
        lines.append("")
        lines.append(f"- **Opis**: {t.description}")
        lines.append(f"- **Metoda**: `{t.method}`")
        lines.append(f"- **URL**: `{t.url}`")
        lines.append(f"- **Wymagane scope'y**: `{', '.join(t.required_scopes)}`")
        lines.append(f"- **Status HTTP**: `{t.status_code or 'N/A'}`")
        
        if t.success:
            lines.append(f"- **Wynik**: ✅ Działa")
            if t.response_sample:
                lines.append("")
                lines.append("**Próbka odpowiedzi:**")
                lines.append("```json")
                lines.append(t.response_sample)
                lines.append("```")
        else:
            lines.append(f"- **Wynik**: ❌ Nie działa")
            lines.append(f"- **Błąd**: {t.error_message or 'N/A'}")
        
        lines.append("")
    
    lines.append("## 🔑 Wnioski")
    lines.append("")
    if failing:
        lines.append("### Scope'y które prawdopodobnie nie działają:")
        lines.append("")
        failing_scopes = set()
        for t in failing:
            failing_scopes.update(t.required_scopes)
        for scope in sorted(failing_scopes):
            lines.append(f"- `{scope}`")
        lines.append("")
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> int:
    print("=" * 70)
    print("TEST ENDPOINTÓW ZOHO BACKSTAGE API")
    print("=" * 70)
    print(f"Portal ID: {PORTAL_ID}")
    print(f"Event ID: {EVENT_ID}")
    print(f"Order ID: {ORDER_ID}")
    print(f"Region: {REGION}")
    print()
    
    # Sprawdź czy jest refresh token
    global REFRESH_TOKEN
    REFRESH_TOKEN = os.getenv("ZOHO_BACKSTAGE_REFRESH_TOKEN")
    if not REFRESH_TOKEN:
        print("❌ Brak REFRESH_TOKEN!")
        print("Ustaw zmienną środowiskową lub edytuj skrypt:")
        print("  $env:ZOHO_BACKSTAGE_REFRESH_TOKEN=\"twoj_token\"")
        print("lub wygeneruj token przez: test_backstage_oauth.py")
        return 1
    
    print("[*] Generuje access token...")
    try:
        access_token = get_access_token()
        print(f"[OK] Access token: {access_token[:30]}...")
    except Exception as e:
        print(f"[ERROR] Blad generowania access tokena: {e}")
        return 1
    
    print()
    print("[*] Przygotowuje testy endpointow...")
    tests = build_test_suite()
    print(f"Liczba testow: {len(tests)}")
    print()
    
    # Uruchom testy
    for i, test in enumerate(tests, 1):
        print(f"[{i:2}/{len(tests)}] {test.name}... ", end="", flush=True)
        test_endpoint(test, access_token)
        if test.success:
            print(f"[OK] HTTP {test.status_code}")
        else:
            print(f"[FAIL] {test.error_message}")
        time.sleep(0.5)  # Nie spamuj API
    
    print()
    print("=" * 70)
    print("PODSUMOWANIE")
    print("=" * 70)
    
    working = [t for t in tests if t.success]
    failing = [t for t in tests if not t.success]
    
    print(f"\n[OK] Dzialajace: {len(working)}/{len(tests)}")
    for t in working:
        print(f"  - {t.name}")
    
    if failing:
        print(f"\n[FAIL] Niedzialajace: {len(failing)}/{len(tests)}")
        for t in failing:
            print(f"  - {t.name}: {t.error_message}")
    
    # Zapisz raport
    report_path = "BACKSTAGE_API_ENDPOINTS_TEST_RESULTS.md"
    try:
        write_markdown_report(tests, report_path)
        print(f"\n[OK] Raport zapisany: {report_path}")
    except Exception as e:
        print(f"\n[ERROR] Blad zapisu raportu: {e}")
    
    return 0 if not failing else 1


if __name__ == "__main__":
    raise SystemExit(main())
