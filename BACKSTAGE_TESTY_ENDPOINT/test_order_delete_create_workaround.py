"""
Test "UPDATE przez DELETE+CREATE" - sprawdza czy można zmienić status zamówienia
przez usunięcie starego i stworzenie nowego.

UWAGA: To NIE jest prawdziwy UPDATE (ID się zmieni), ale może być workaroundem.
"""

from __future__ import annotations

import json
import os
import sys
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
# Użyjemy testowego zamówienia (cancelled) z JSONa
TEST_ORDER_ID = "24311000000839027"
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
            return False, e.code, f"{msg} | {error_content[:150]}", None
        except Exception:
            msg = f"HTTP {e.code}"
        return False, e.code, msg, None
        
    except Exception as e:
        return False, 0, str(e), None


def main() -> int:
    print("=" * 70)
    print('TEST: "UPDATE" przez DELETE + CREATE (workaround)')
    print("=" * 70)
    print(f"Order ID do testu: {TEST_ORDER_ID}")
    print()
    
    access_token = get_access_token()
    print(f"[OK] Access token: {access_token[:30]}...")
    print()
    
    # === KROK 1: Pobierz szczegóły istniejącego zamówienia ===
    print("[1/4] Pobieram szczegoly zamowienia...")
    url_get = f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/orders/{TEST_ORDER_ID}"
    success, status, msg, order_data = api_request("GET", url_get, access_token)
    
    if not success or not order_data:
        print(f"[ERROR] Nie mozna pobrac zamowienia: {msg}")
        return 1
    
    print(f"[OK] Status: {order_data.get('status')} ({order_data.get('status_string')})")
    print(f"[OK] Payment: {order_data.get('payment_status')} ({order_data.get('payment_status_string')})")
    print(f"[OK] Order by: {order_data.get('order_by')}")
    print()
    
    # === KROK 2: Test DELETE order ===
    print("[2/4] Testuje DELETE order...")
    url_delete = f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/orders/{TEST_ORDER_ID}"
    
    # NIE USUWAMY PRODUKCYJNEGO ZAMÓWIENIA - tylko testujemy endpoint
    print("[SKIP] Pomijam DELETE (produkcyjne zamowienie)")
    print("[INFO] Endpoint DELETE: DELETE", url_delete)
    print()
    
    # === KROK 3: Test CREATE nowego order ===
    print("[3/4] Testuje CREATE order...")
    
    # Pobierz ticket classes z zamówienia (różne formaty)
    order_tickets = order_data.get("order_tickets") or order_data.get("orderTickets") or []
    if not order_tickets:
        # Jeśli nie ma tickets w order, pobierz dostępne ticket classes
        print("[INFO] Zamowienie nie ma order_tickets, pobieram ticket_classes...")
        url_tickets = f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/ticket_classes"
        t_success, t_status, t_msg, t_data = api_request("GET", url_tickets, access_token)
        if t_success and t_data and t_data.get("ticket_classes"):
            ticket_class_id = t_data["ticket_classes"][0]["id"]
            print(f"[OK] Uzyto pierwszej dostepnej klasy: {ticket_class_id}")
        else:
            print(f"[ERROR] Nie mozna pobrac ticket classes: {t_msg}")
            return 1
    else:
        first_ticket = order_tickets[0]
        ticket_class_id = first_ticket.get("ticket_class") or first_ticket.get("ticketClass")
    
    # Minimalny payload do CREATE
    payload_create = {
        "order_by": "api.workaround.test@example.com",
        "buyer_details": {
            "first_name": "API",
            "last_name": "Workaround",
            "email": "api.workaround.test@example.com",
            "mobile_no": "+48888555444"
        },
        "payment_status": 2,  # Paid (próbujemy od razu jako paid)
        "tickets": [
            {
                "ticket_class": str(ticket_class_id),
                "quantity": 1
            }
        ]
    }
    
    url_create = f"{API_BASE}/portals/{PORTAL_ID}/events/{EVENT_ID}/orders"
    success, status, msg, new_order = api_request("POST", url_create, access_token, payload_create)
    
    if success and new_order:
        new_order_id = new_order.get("id")
        new_payment_status = new_order.get("payment_status")
        print(f"[OK] Nowe zamowienie utworzone: ID={new_order_id}")
        print(f"[OK] Payment status: {new_payment_status} ({new_order.get('payment_status_string')})")
        
        # === KROK 4: Spróbuj usunąć nowo utworzone zamówienie (cleanup) ===
        print()
        print("[4/4] Cleanup: usuwam testowe zamowienie...")
        url_delete_new = f"{url_create}/{new_order_id}"
        del_success, del_status, del_msg, _ = api_request("DELETE", url_delete_new, access_token)
        
        if del_success:
            print(f"[OK] Testowe zamowienie usuniete")
        else:
            print(f"[WARN] Nie udalo sie usunac: {del_msg}")
            print(f"[INFO] Moze DELETE order nie dziala w API v3")
        
        print()
        print("=" * 70)
        print("WNIOSKI")
        print("=" * 70)
        print()
        if del_success:
            print("[OK] WORKAROUND DZIALA!")
            print("Mozna 'zaktualizowac' zamowienie przez DELETE + CREATE")
            print("UWAGA: ID sie zmieni, to nie jest prawdziwy UPDATE")
        else:
            print("[PARTIAL] CREATE dziala, ale DELETE nie")
            print("Nie mozna 'zaktualizowac' przez ten workaround")
            print(f"UWAGA: Zostalo testowe zamowienie ID={new_order_id}")
        
    else:
        print(f"[FAIL] CREATE nie dziala: {msg}")
        print()
        print("=" * 70)
        print("WNIOSKI")
        print("=" * 70)
        print()
        print("[FAIL] WORKAROUND NIE DZIALA")
        print("CREATE order nie dziala w API v3")
        print("Nie da sie 'zaktualizowac' zamowienia przez DELETE+CREATE")
    
    return 0 if (success and new_order) else 1


if __name__ == "__main__":
    raise SystemExit(main())
