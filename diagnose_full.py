import requests
import json
import webbrowser
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs, quote

# Twoje dane (aplikacja lokalna z panelu wFirma)
CLIENT_ID = "017bd7d64f9c90ea409d84a69ffb9ab0"
CLIENT_SECRET = "26b10097dcd5911ac1302f549f8f952d"
REDIRECT_URI = "http://localhost:8000"  # Zgodne z panelem wFirma

# Zmienna na kod autoryzacyjny
auth_code = None

class AuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed_path = urlparse(self.path)
        
        # Obsługa zarówno / jak i /callback
        if parsed_path.path in ['/', '/callback']:
            query_components = parse_qs(parsed_path.query)
            if 'code' in query_components:
                auth_code = query_components['code'][0]
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b"<h1>Autoryzacja OK! Wracaj do terminala.</h1><script>window.close()</script>")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Brak kodu!")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return  # wycisz logi serwera

def get_token():
    # 1. Uruchom serwer lokalny na chwilę
    server = HTTPServer(('localhost', 8000), AuthHandler)
    
    # 2. Otwórz przeglądarkę
    scope = "companies-read company_addresses-read company_packs-read company_accounts-read company_accounts-write contractors-read contractors-write invoice_descriptions-read invoice_deliveries-read invoice_deliveries-write invoices-read invoices-write notes-read notes-write payments-read payments-write tags-read tags-write"
    auth_url = f"https://wfirma.pl/oauth2/auth?response_type=code&client_id={CLIENT_ID}&redirect_uri={quote(REDIRECT_URI, safe='')}&scope={quote(scope)}"
    
    print(f"Otwieram: {auth_url}")
    webbrowser.open(auth_url)
    
    print("Czekam na zalogowanie w przeglądarce...")
    while not auth_code:
        server.handle_request()
    
    print(f"Mam kod: {auth_code[:10]}...")
    
    # 3. Wymień kod na token
    token_url = "https://api2.wfirma.pl/oauth2/token"
    data = {
        'grant_type': 'authorization_code',
        'code': auth_code,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI
    }
    
    resp = requests.post(token_url, data=data)
    if resp.status_code != 200:
        print(f"Błąd tokena: {resp.text}")
        return None
    
    tokens = resp.json()
    access_token = tokens['access_token']
    refresh_token = tokens.get('refresh_token')
    
    # Zapisz tokeny do pliku
    token_data = {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'expires_at': time.time() + int(tokens.get('expires_in', 3600))
    }
    try:
        with open('wfirma_token_local.json', 'w') as f:
            json.dump(token_data, f)
        print("✓ Token zapisany do wfirma_token_local.json")
    except Exception as e:
        print(f"Nie udało się zapisać tokenu: {e}")
        
    return access_token

def test_invoice(token):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    contractor_id = 170471377  # Twój kontrahent
    
    # KROK 1: Test autoryzacji - sprawdź czy token działa
    print("\n--- TEST AUTORYZACJI (contractors/find) ---")
    test_url = "https://api2.wfirma.pl/contractors/find?inputFormat=json&outputFormat=json&oauth_version=2"
    test_body = {"contractors": {"parameters": {"limit": "1"}}}
    test_resp = requests.post(test_url, headers=headers, json=test_body)
    print(f"Status: {test_resp.status_code}")
    print(f"Body: {test_resp.text[:200]}")
    
    if test_resp.status_code == 401:
        print("❌ Token nieważny! Próbuję odświeżyć...")
        
        # Odśwież token
        try:
            import os
            with open('wfirma_token_local.json', 'r') as f:
                data = json.load(f)
            refresh_token = data.get('refresh_token')
            
            if not refresh_token:
                print("Brak refresh_token - potrzebne nowe logowanie!")
                return
            
            token_url = "https://api2.wfirma.pl/oauth2/token"
            payload = {
                'grant_type': 'refresh_token',
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET,
                'code': refresh_token
            }
            
            resp = requests.post(token_url, data=payload)
            if resp.status_code == 200:
                new_tokens = resp.json()
                token = new_tokens['access_token']
                new_refresh = new_tokens.get('refresh_token', refresh_token)
                
                # Zapisz
                token_data = {
                    'access_token': token,
                    'refresh_token': new_refresh,
                    'expires_at': time.time() + int(new_tokens.get('expires_in', 3600))
                }
                with open('wfirma_token_local.json', 'w') as f:
                    json.dump(token_data, f)
                
                headers["Authorization"] = f"Bearer {token}"
                print("✓ Token odświeżony! Testuję ponownie...")
                
                # Ponów test
                test_resp = requests.post(test_url, headers=headers, json=test_body)
                print(f"Status po refresh: {test_resp.status_code}")
                print(f"Body: {test_resp.text[:200]}")
            else:
                print(f"Błąd refresh: {resp.text}")
                return
        except Exception as e:
            print(f"Błąd: {e}")
            return
    
    print("\n✓ Autoryzacja OK, przechodzę do testów faktur")
    url = "https://api2.wfirma.pl/invoices/add?inputFormat=json&outputFormat=json&oauth_version=2"
    
    # TEST 1: Bez type
    print("\n--- TEST 1: Bez pola type ---")
    body1 = {
        "invoice": {
            "contractor_id": contractor_id,
            "paymenttype": "transfer",
            "date": "2025-12-06"
        }
    }
    print(json.dumps(body1, indent=2))
    r1 = requests.post(url, headers=headers, json=body1)
    print(f"Status: {r1.status_code}")
    print(f"Body: {r1.text}")
    if "OK" in r1.text: print("✅ DZIAŁA!")

    # TEST 2: Bez paymenttype
    print("\n--- TEST 2: Bez paymenttype ---")
    body2 = {
        "invoice": {
            "contractor_id": contractor_id,
            "date": "2025-12-06",
            "type": "normal"
        }
    }
    print(json.dumps(body2, indent=2))
    r2 = requests.post(url, headers=headers, json=body2)
    print(f"Status: {r2.status_code}")
    print(f"Body: {r2.text}")
    if "OK" in r2.text: print("✅ DZIAŁA!")
    
    # TEST 3: Zagnieżdżony contractor (z XML)
    print("\n--- TEST 3: Zagnieżdżony contractor ---")
    body3 = {
        "invoice": {
            "contractor": {
                "name": "Katarzyna Ochnik Digital Unity",
                "zip": "00-712",
                "city": "Warszawa"
            },
            "paymenttype": "transfer",
            "date": "2025-12-06",
            "type": "normal"
        }
    }
    print(json.dumps(body3, indent=2))
    r3 = requests.post(url, headers=headers, json=body3)
    print(f"Status: {r3.status_code}")
    print(f"Body: {r3.text}")
    if "OK" in r3.text: print("✅ DZIAŁA!")
    
    # TEST 4: Z pozycją (prostą strukturą)
    print("\n--- TEST 4: Z pozycją (prosty format) ---")
    body4 = {
        "invoice": {
            "contractor": {
                "name": "Katarzyna Ochnik Digital Unity",
                "zip": "00-712",
                "city": "Warszawa"
            },
            "type": "normal",
            "type_of_sale": "WSTO_EE",
            "invoicecontents": {
                "invoicecontent": [
                    {
                        "name": "Test API",
                        "count": 1,
                        "unit_count": 1,
                        "price": 100,
                        "unit": "szt."
                    }
                ]
            }
        }
    }
    print(json.dumps(body4, indent=2))
    r4 = requests.post(url, headers=headers, json=body4)
    print(f"Status: {r4.status_code}")
    print(f"Body: {r4.text}")
    if "OK" in r4.text: print("✅ DZIAŁA!")
    
    # TEST 5: Bez oauth_version=2 w URL
    print("\n--- TEST 5: Bez oauth_version=2 ---")
    url_no_oauth = "https://api2.wfirma.pl/invoices/add?inputFormat=json&outputFormat=json"
    body5 = {
        "invoice": {
            "contractor_id": contractor_id,
            "date": "2025-12-06",
            "paymenttype": "transfer"
        }
    }
    print(json.dumps(body5, indent=2))
    r5 = requests.post(url_no_oauth, headers=headers, json=body5)
    print(f"Status: {r5.status_code}")
    print(f"Body: {r5.text}")
    if "OK" in r5.text: print("✅ DZIAŁA!")
    
    # TEST 6: Z pozycjami w prostym formacie (nie zagnieżdżone invoicecontents)
    print("\n--- TEST 6: invoicecontent jako lista bezpośrednia ---")
    body6 = {
        "invoice": {
            "contractor_id": contractor_id,
            "date": "2025-12-06",
            "paymenttype": "transfer",
            "type": "normal",
            "invoicecontent": [
                {
                    "name": "Test",
                    "count": 1,
                    "price": 100,
                    "unit": "szt.",
                    "vat": "23"
                }
            ]
        }
    }
    print(json.dumps(body6, indent=2))
    r6 = requests.post(url, headers=headers, json=body6)
    print(f"Status: {r6.status_code}")
    print(f"Body: {r6.text}")
    if "OK" in r6.text: print("✅ DZIAŁA!")

if __name__ == "__main__":
    print("--- DIAGNOSTYKA wFirma ---")
    
    # Spróbuj wczytać token z pliku (jeśli istnieje)
    token = None
    try:
        import os
        if os.path.exists('wfirma_token_local.json'):
            print("Wczytuję token z pliku...")
            with open('wfirma_token_local.json', 'r') as f:
                data = json.load(f)
                if time.time() < data.get('expires_at', 0):
                    token = data['access_token']
                    print("✓ Token z pliku jest ważny")
                else:
                    print("Token wygasł, pobieram nowy...")
    except Exception as e:
        print(f"Nie udało się wczytać tokenu z pliku: {e}")
    
    # Jeśli nie ma tokenu, pobierz nowy
    if not token:
        token = get_token()
    
    if token:
        print("\nToken gotowy! Rozpoczynam testy...")
        test_invoice(token)
    else:
        print("Nie udało się pobrać tokenu")
