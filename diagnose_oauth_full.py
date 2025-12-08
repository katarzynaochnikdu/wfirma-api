"""
Pełna diagnostyka OAuth 2.0 wFirma API
======================================
Ten skrypt testuje wszystkie kluczowe operacje:
1. Autoryzacja (pobieranie tokenu)
2. Odczyt firm (companies) - TWOJA firma
3. Dodanie kontrahenta (contractors) - KLIENT
4. Wystawienie faktury (invoices)

Użycie:
  python diagnose_oauth_full.py

Wymagania:
  - Poprawny CLIENT_ID i CLIENT_SECRET
  - Pełny scope z panelu OAuth 2.0
  - Skonfigurowana firma w panelu wFirma
"""

import requests
import json
import webbrowser
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs, quote
from datetime import datetime

# ============================================================================
# KONFIGURACJA - Dane z panelu OAuth 2.0 wFirma
# ============================================================================
CLIENT_ID = "017bd7d64f9c90ea409d84a69ffb9ab0"
CLIENT_SECRET = "26b10097dcd5911ac1302f549f8f952d"
REDIRECT_URI = "http://localhost:8000"

# Pełny scope z obrazka
FULL_SCOPE = (
    "companies-read company_addresses-read company_packs-read "
    "company_accounts-read company_accounts-write "
    "contractors-read contractors-write "
    "invoice_descriptions-read invoice_deliveries-read invoice_deliveries-write "
    "invoices-read invoices-write "
    "notes-read notes-write "
    "payments-read payments-write "
    "tags-read tags-write"
)

# NIPy kontrahentów do testów
TEST_CONTRACTORS_NIP = [
    "6682018672",   # Hs1 Sp. z o. o.
    "9710668048",   # Katarzyna Ochnik Digital Unity
]

# ============================================================================
# OBSŁUGA AUTORYZACJI
# ============================================================================
auth_code = None

class AuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed_path = urlparse(self.path)
        
        if parsed_path.path in ['/', '/callback']:
            query_components = parse_qs(parsed_path.query)
            if 'code' in query_components:
                auth_code = query_components['code'][0]
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                html = """
                <html>
                <head><meta charset="utf-8"><title>Autoryzacja OK</title></head>
                <body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1 style="color: green;">✅ Autoryzacja pomyślna!</h1>
                    <p>Możesz zamknąć to okno i wrócić do terminala.</p>
                    <script>setTimeout(() => window.close(), 2000);</script>
                </body>
                </html>
                """
                self.wfile.write(html.encode('utf-8'))
            else:
                self.send_response(400)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(b"<h1>Blad: Brak kodu autoryzacyjnego!</h1>")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return  # Wycisz logi serwera

def print_section(title):
    """Wyświetl nagłówek sekcji"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_test(test_num, test_name):
    """Wyświetl nagłówek testu"""
    print(f"\n--- TEST {test_num}: {test_name} ---")

def get_token():
    """Pobierz token OAuth 2.0 przez flow Authorization Code"""
    print_section("KROK 1: AUTORYZACJA OAuth 2.0")
    
    # Uruchom lokalny serwer
    server = HTTPServer(('localhost', 8000), AuthHandler)
    
    # Otwórz przeglądarkę z URL autoryzacji
    auth_url = (
        f"https://wfirma.pl/oauth2/auth"
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={quote(REDIRECT_URI, safe='')}"
        f"&scope={quote(FULL_SCOPE)}"
    )
    
    print(f"\n📱 Otwieram przeglądarkę do autoryzacji...")
    print(f"URL: {auth_url[:100]}...")
    webbrowser.open(auth_url)
    
    print("\n⏳ Czekam na zalogowanie w przeglądarce...")
    print("   (Zaloguj się do wFirma i autoryzuj aplikację)")
    
    # Czekaj na kod autoryzacyjny
    while not auth_code:
        server.handle_request()
    
    print(f"\n✅ Otrzymano kod autoryzacyjny: {auth_code[:20]}...")
    
    # Wymień kod na token
    print("\n🔄 Wymieniam kod na access token...")
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
        print(f"\n❌ BŁĄD podczas wymiany kodu na token!")
        print(f"Status: {resp.status_code}")
        print(f"Odpowiedź: {resp.text}")
        return None
    
    tokens = resp.json()
    access_token = tokens['access_token']
    refresh_token = tokens.get('refresh_token')
    expires_in = tokens.get('expires_in', 3600)
    
    print(f"\n✅ Token otrzymany!")
    print(f"   Access token: {access_token[:30]}...")
    print(f"   Ważny przez: {expires_in} sekund ({expires_in//60} minut)")
    
    # Zapisz token do pliku
    token_data = {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'expires_at': time.time() + expires_in
    }
    
    try:
        with open('wfirma_token_local.json', 'w') as f:
            json.dump(token_data, f, indent=2)
        print(f"   📁 Token zapisany do: wfirma_token_local.json")
    except Exception as e:
        print(f"   ⚠️  Nie udało się zapisać tokenu: {e}")
    
    return access_token

def test_authorization(token):
    """TEST 1: Sprawdź czy token działa"""
    print_test(1, "AUTORYZACJA - Czy token działa?")
    
    url = "https://api2.wfirma.pl/contractors/find?inputFormat=json&outputFormat=json&oauth_version=2"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    body = {"contractors": {"parameters": {"limit": "1"}}}
    
    print(f"\n📤 Wysyłam zapytanie: GET {url}")
    print(f"Body: {json.dumps(body, indent=2)}")
    
    try:
        resp = requests.post(url, headers=headers, json=body)
        print(f"\n📥 Odpowiedź:")
        print(f"   Status: {resp.status_code}")
        print(f"   Body (pierwsze 300 znaków): {resp.text[:300]}")
        
        if resp.status_code == 200:
            print("\n✅ TOKEN DZIAŁA! Autoryzacja OK.")
            return True
        elif resp.status_code == 401:
            print("\n❌ BŁĄD 401: Token nieważny lub wygasły!")
            return False
        else:
            print(f"\n⚠️  Nieoczekiwany status: {resp.status_code}")
            return False
    except Exception as e:
        print(f"\n❌ Wyjątek: {e}")
        return False

def test_companies(token):
    """TEST 2: Odczyt TWOJEJ firmy (companies)"""
    print_test(2, "COMPANIES (TWOJA FIRMA) - Odczyt danych")
    
    print("\n💡 UWAGA: Companies to TWOJE firmy (jako sprzedawca).")
    print("   Musisz je skonfigurować RĘCZNIE w panelu wFirma!")
    print("   API pozwala tylko na ODCZYT (companies-read).")
    
    url = "https://api2.wfirma.pl/companies/find?inputFormat=json&outputFormat=json&oauth_version=2"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    body = {"companies": {"parameters": {"limit": "10"}}}
    
    print(f"\n📤 Wysyłam zapytanie: GET {url}")
    
    try:
        resp = requests.post(url, headers=headers, json=body)
        print(f"\n📥 Odpowiedź:")
        print(f"   Status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            companies = data.get('companies', {})
            
            if companies and isinstance(companies, dict):
                # companies to dict z kluczami "0", "1", etc.
                print(f"\n✅ Znaleziono {len(companies)} firm(y):")
                
                first_company_id = None
                for idx, (key, comp_wrapper) in enumerate(companies.items(), 1):
                    comp = comp_wrapper.get('company', {})
                    print(f"\n   Firma {idx}:")
                    print(f"      ID: {comp.get('id')}")
                    print(f"      Nazwa: {comp.get('name')}")
                    print(f"      NIP: {comp.get('nip')}")
                    print(f"      Miasto: {comp.get('city')}")
                    
                    if idx == 1:
                        first_company_id = comp.get('id')
                
                return True, first_company_id
            else:
                print("\n⚠️  Brak firm w systemie!")
                print("   Musisz skonfigurować swoją firmę w panelu wFirma:")
                print("   Panel wFirma → Ustawienia → Moja firma")
                return False, None
        else:
            print(f"   Body: {resp.text[:500]}")
            print(f"\n❌ BŁĄD {resp.status_code}")
            return False, None
            
    except Exception as e:
        print(f"\n❌ Wyjątek: {e}")
        return False, None

def test_find_contractor_by_nip(token, nip_list):
    """TEST 3: Wyszukiwanie kontrahentów po NIP"""
    print_test(3, "CONTRACTORS - Wyszukiwanie istniejących po NIP")
    
    print("\n💡 UWAGA: Testuję 2 formaty API wyszukiwania kontrahentów.")
    print("   Format A: condition z field/operator/value")
    print("   Format B: uproszczony z 'nip' bezpośrednio")
    
    found_contractors = []
    
    for idx, nip in enumerate(nip_list, 1):
        print(f"\n--- Kontrahent {idx}: NIP {nip} ---")
        
        # Format A: z app.py (field/operator/value)
        print("\n🔍 Test Format A (condition z field/operator/value):")
        
        url = "https://api2.wfirma.pl/contractors/find?inputFormat=json&outputFormat=json&oauth_version=2"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        body_format_a = {
            "contractors": {
                "parameters": {
                    "conditions": {
                        "condition": {
                            "field": "nip",
                            "operator": "eq",
                            "value": nip
                        }
                    }
                }
            }
        }
        
        print(f"Body: {json.dumps(body_format_a, indent=2)}")
        
        try:
            resp = requests.post(url, headers=headers, json=body_format_a)
            print(f"Status: {resp.status_code}")
            print(f"Body (pierwsze 300 znaków): {resp.text[:300]}")
            
            if resp.status_code == 200:
                data = resp.json()
                contractors = data.get('contractors', {})
                
                # Próba wyciągnięcia danych kontrahenta
                contractor = None
                if isinstance(contractors, dict):
                    # Szukaj kluczy numerycznych lub 'contractor'
                    for key in contractors:
                        if key.isdigit():
                            contractor = contractors[key].get('contractor')
                            break
                        elif key == 'contractor':
                            contractor = contractors[key]
                            break
                elif isinstance(contractors, list) and len(contractors) > 0:
                    contractor = contractors[0].get('contractor', {})
                
                if contractor:
                    print(f"✅ Format A DZIAŁA!")
                    print(f"   ID: {contractor.get('id')}")
                    print(f"   Nazwa: {contractor.get('name')}")
                    print(f"   NIP: {contractor.get('nip')}")
                    found_contractors.append(contractor)
                    continue  # Znaleziono, pomijamy Format B
                else:
                    print(f"⚠️  Format A zwrócił 200, ale brak danych kontrahenta")
            else:
                print(f"❌ Format A - błąd {resp.status_code}")
        except Exception as e:
            print(f"❌ Format A - wyjątek: {e}")
        
        # Format B: prostsza struktura
        print("\n🔍 Test Format B (uproszczony):")
        
        body_format_b = {
            "contractors": {
                "parameters": {
                    "conditions": {
                        "nip": nip
                    }
                }
            }
        }
        
        print(f"Body: {json.dumps(body_format_b, indent=2)}")
        
        try:
            resp = requests.post(url, headers=headers, json=body_format_b)
            print(f"Status: {resp.status_code}")
            print(f"Body (pierwsze 300 znaków): {resp.text[:300]}")
            
            if resp.status_code == 200:
                data = resp.json()
                contractors = data.get('contractors', {})
                
                contractor = None
                if isinstance(contractors, dict):
                    for key in contractors:
                        if key.isdigit():
                            contractor = contractors[key].get('contractor')
                            break
                        elif key == 'contractor':
                            contractor = contractors[key]
                            break
                elif isinstance(contractors, list) and len(contractors) > 0:
                    contractor = contractors[0].get('contractor', {})
                
                if contractor:
                    print(f"✅ Format B DZIAŁA!")
                    print(f"   ID: {contractor.get('id')}")
                    print(f"   Nazwa: {contractor.get('name')}")
                    print(f"   NIP: {contractor.get('nip')}")
                    found_contractors.append(contractor)
                else:
                    print(f"⚠️  Format B zwrócił 200, ale brak danych kontrahenta")
            else:
                print(f"❌ Format B - błąd {resp.status_code}")
        except Exception as e:
            print(f"❌ Format B - wyjątek: {e}")
    
    if found_contractors:
        print(f"\n✅ PODSUMOWANIE: Znaleziono {len(found_contractors)} kontrahent(ów)")
        return True, found_contractors
    else:
        print(f"\n❌ PODSUMOWANIE: Nie znaleziono żadnego kontrahenta")
        print("   Sprawdź czy NIPy są poprawne w systemie wFirma")
        return False, []

def test_add_contractor(token):
    """TEST 4: Dodanie kontrahenta (KLIENTA)"""
    print_test(4, "CONTRACTORS (KLIENT) - Dodanie nowego")
    
    print("\n💡 UWAGA: Contractors to TWOI KLIENCI (komu wystawiasz faktury).")
    print("   Możesz ich dodawać przez API (contractors-write).")
    
    url = "https://api2.wfirma.pl/contractors/add?inputFormat=json&outputFormat=json&oauth_version=2"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    # Wygeneruj unikalną nazwę z timestampem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # KLUCZOWE: Musi być wrapper "contractors"!
    contractor_data = {
        "contractors": {
            "contractor": {
                "name": f"Test Kontrahent {timestamp}",
                "altname": f"Test Kontrahent {timestamp}",
                "nip": "1234567890",
                "tax_id_type": "custom",  # custom = dowolny identyfikator
                "street": "ul. Testowa 1",
                "zip": "00-001",
                "city": "Warszawa",
                "country": "PL"
            }
        }
    }
    
    print(f"\n📤 Wysyłam zapytanie: POST {url}")
    print(f"Body: {json.dumps(contractor_data, indent=2, ensure_ascii=False)}")
    
    try:
        resp = requests.post(url, headers=headers, json=contractor_data)
        print(f"\n📥 Odpowiedź:")
        print(f"   Status: {resp.status_code}")
        print(f"   Body: {resp.text[:500]}")
        
        if resp.status_code == 200:
            data = resp.json()
            status_code = data.get('status', {}).get('code')
            
            if status_code == 'OK':
                # Wyciągnij ID kontrahenta (struktura jak w find - contractors.0.contractor.id)
                contractor_id = None
                if 'contractors' in data:
                    contractors = data['contractors']
                    if isinstance(contractors, dict):
                        for key in contractors:
                            if key.isdigit() or key == 'contractor':
                                contractor_id = contractors[key].get('contractor', {}).get('id')
                                if not contractor_id:
                                    contractor_id = contractors[key].get('id')
                                break
                
                if contractor_id:
                    print(f"\n✅ Kontrahent dodany pomyślnie!")
                    print(f"   ID: {contractor_id}")
                    return True, contractor_id
                else:
                    print("\n⚠️  Dodano, ale nie znaleziono ID w odpowiedzi")
                    print(f"   Pełna odpowiedź: {json.dumps(data, indent=2)[:500]}")
                    return True, None
            else:
                print(f"\n❌ Status: {status_code}")
                print(f"   Message: {data.get('status', {}).get('message')}")
                return False, None
        elif resp.status_code == 400:
            print(f"\n❌ BŁĄD 400: Nieprawidłowe dane!")
            print(f"   Sprawdź strukturę danych kontrahenta.")
            return False, None
        else:
            print(f"\n❌ BŁĄD {resp.status_code}")
            return False, None
            
    except Exception as e:
        print(f"\n❌ Wyjątek: {e}")
        return False, None

def test_download_invoice(token, invoice_id, company_id=None):
    """TEST 6: Pobieranie PDF faktury"""
    print_test(6, "DOWNLOAD - Pobranie PDF faktury")
    
    print(f"\n💡 Pobieram PDF faktury ID: {invoice_id}")
    
    url = f"https://api2.wfirma.pl/invoices/download/{invoice_id}?inputFormat=json&outputFormat=json&oauth_version=2&company_id={company_id}" if company_id else f"https://api2.wfirma.pl/invoices/download/{invoice_id}?inputFormat=json&outputFormat=json&oauth_version=2"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/pdf"
    }
    
    # Parametry - pobierz oryginalny
    body = {
        "invoices": {
            "parameters": {
                "parameter": [
                    {"name": "page", "value": "invoice"},
                    {"name": "address", "value": "0"},
                    {"name": "leaflet", "value": "0"},
                    {"name": "duplicate", "value": "0"}
                ]
            }
        }
    }
    
    print(f"\n📤 Wysyłam zapytanie: POST {url}")
    
    try:
        resp = requests.post(url, headers=headers, json=body)
        print(f"\n📥 Odpowiedź:")
        print(f"   Status: {resp.status_code}")
        print(f"   Content-Type: {resp.headers.get('Content-Type')}")
        print(f"   Size: {len(resp.content)} bytes")
        
        if resp.status_code == 200 and 'pdf' in resp.headers.get('Content-Type', '').lower():
            filename = f"faktura_{invoice_id}.pdf"
            with open(filename, 'wb') as f:
                f.write(resp.content)
            print(f"\n✅ PDF zapisany do: {filename}")
            return True, filename
        else:
            print(f"\n❌ Nie udało się pobrać PDF")
            print(f"   Body: {resp.text[:300]}")
            return False, None
    except Exception as e:
        print(f"\n❌ Wyjątek: {e}")
        return False, None

def test_send_invoice(token, invoice_id, email, company_id=None):
    """TEST 7: Wysyłanie faktury na email"""
    print_test(7, "SEND - Wysłanie faktury na email")
    
    print(f"\n💡 Wysyłam fakturę ID: {invoice_id}")
    print(f"   📧 Na adres: {email}")
    
    url = f"https://api2.wfirma.pl/invoices/send/{invoice_id}?inputFormat=json&outputFormat=json&oauth_version=2&company_id={company_id}" if company_id else f"https://api2.wfirma.pl/invoices/send/{invoice_id}?inputFormat=json&outputFormat=json&oauth_version=2"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    # Struktura zgodna z dokumentacją - każdy parameter osobno
    body = {
        "invoices": {
            "parameters": [
                {"parameter": {"name": "email", "value": email}},
                {"parameter": {"name": "subject", "value": "Otrzymałeś fakturę"}},
                {"parameter": {"name": "page", "value": "invoice"}},
                {"parameter": {"name": "leaflet", "value": "0"}},
                {"parameter": {"name": "duplicate", "value": "0"}},
                {"parameter": {"name": "body", "value": "Przesyłam fakturę"}}
            ]
        }
    }
    
    print(f"\n📤 Wysyłam zapytanie: POST {url}")
    print(f"Body: {json.dumps(body, indent=2)}")
    
    try:
        resp = requests.post(url, headers=headers, json=body)
        print(f"\n📥 Odpowiedź:")
        print(f"   Status: {resp.status_code}")
        print(f"   Body: {resp.text[:500]}")
        
        if resp.status_code == 200:
            data = resp.json()
            status_code = data.get('status', {}).get('code')
            
            if status_code == 'OK':
                print(f"\n✅ Email wysłany pomyślnie na: {email}")
                return True
            else:
                print(f"\n⚠️ Status: {status_code}")
                print(f"   Message: {data.get('status', {}).get('message')}")
                return False
        else:
            print(f"\n❌ BŁĄD {resp.status_code}")
            return False
    except Exception as e:
        print(f"\n❌ Wyjątek: {e}")
        return False

def test_create_invoice(token, contractors_list, company_id=None):
    """TEST 5: Wystawienie faktury"""
    print_test(5, "INVOICES (FAKTURA) - Wystawienie nowej")
    
    if not contractors_list or len(contractors_list) == 0:
        print("\n⚠️  Brak kontrahentów - pomijam test faktury.")
        print("   (Najpierw musi się udać Test 3)")
        return False
    
    # Użyj pierwszego kontrahenta z listy
    contractor = contractors_list[0]
    contractor_id = contractor.get('id')
    contractor_name = contractor.get('name', 'Nieznany')
    
    # Konwertuj ID na int (API może wymagać int nie string)
    if isinstance(contractor_id, str):
        contractor_id = int(contractor_id)
    
    if company_id and isinstance(company_id, str):
        company_id = int(company_id)
    
    print(f"\n💡 Wystawiam fakturę dla kontrahenta:")
    print(f"   Contractor ID: {contractor_id}")
    print(f"   Nazwa: {contractor_name}")
    if company_id:
        print(f"   Company ID (Twoja firma): {company_id}")
    
    # URL z company_id (jak w Postmanie)
    url_json = f"https://api2.wfirma.pl/invoices/add?inputFormat=json&outputFormat=json&oauth_version=2&company_id={company_id}" if company_id else "https://api2.wfirma.pl/invoices/add?inputFormat=json&outputFormat=json&oauth_version=2"
    
    # URL dla XML (jak w Postmanie)
    url_xml = f"https://api2.wfirma.pl/invoices/add?inputFormat=xml&outputFormat=xml&company_id={company_id}" if company_id else "https://api2.wfirma.pl/invoices/add?inputFormat=xml&outputFormat=xml"
    
    headers_json = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    headers_xml = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/xml",
        "Accept": "application/xml"
    }
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    # TEST RÓŻNYCH FORMATÓW FAKTURY
    # KLUCZOWE: Musi być wrapper "invoices"!
    
    # Format 1: Najprostszy - tylko contractor_id
    invoice_data_simple = {
        "invoices": {
            "invoice": {
                "contractor_id": contractor_id,
                "type": "normal"
            }
        }
    }
    
    # Format 2: Z pozycjami
    invoice_data_with_items = {
        "invoices": {
            "invoice": {
                "contractor_id": contractor_id,
                "date": today,
                "type": "normal",
                "invoicecontents": {
                    "invoicecontent": [
                        {
                            "name": "Test - Diagnostyka API",
                            "count": 1,
                            "unit": "szt.",
                            "price": 100.00,
                            "vat": "23"
                        }
                    ]
                }
            }
        }
    }
    
    # Testuj formaty JSON (z poprawnym wrapperem "invoices"!)
    test_formats_json = [
        ("JSON: Najprostszy (contractor_id + type)", invoice_data_simple),
        ("JSON: Z pozycjami", invoice_data_with_items)
    ]
    
    success = False
    
    for test_name, invoice_data in test_formats_json:
        print(f"\n🧪 Test: {test_name}")
        
        print(f"Body: {json.dumps(invoice_data, indent=2, ensure_ascii=False)}")
        
        try:
            resp = requests.post(url_json, headers=headers_json, json=invoice_data)
            print(f"Status: {resp.status_code}")
            print(f"Body: {resp.text[:500]}")
            
            if resp.status_code == 200:
                data = resp.json()
                status_code = data.get('status', {}).get('code')
                
                if status_code == 'OK':
                    print(f"✅ {test_name} - DZIAŁA!")
                    
                    # Wyciągnij numer faktury i ID
                    invoice_num = None
                    created_invoice_id = None
                    if 'invoices' in data:
                        invoices = data['invoices']
                        if isinstance(invoices, dict):
                            for key in invoices:
                                if key.isdigit():
                                    inv = invoices[key].get('invoice', {})
                                    invoice_num = inv.get('fullnumber')
                                    created_invoice_id = inv.get('id')
                                    break
                        elif isinstance(invoices, list) and len(invoices) > 0:
                            inv = invoices[0].get('invoice', {})
                            invoice_num = inv.get('fullnumber')
                            created_invoice_id = inv.get('id')
                    
                    if invoice_num:
                        print(f"   📄 Numer faktury: {invoice_num}")
                    if created_invoice_id:
                        print(f"   🆔 ID faktury: {created_invoice_id}")
                    
                    success = True
                    return True, created_invoice_id  # Zwróć ID faktury!
                else:
                    print(f"❌ {test_name} - Status: {status_code}")
                    if data.get('status', {}).get('message'):
                        print(f"   Message: {data.get('status', {}).get('message')}")
            else:
                print(f"❌ {test_name} - HTTP {resp.status_code}")
                
        except Exception as e:
            print(f"❌ {test_name} - Wyjątek: {e}")
    
    if success:
        print("\n✅ Udało się wystawić fakturę!")
        return True, created_invoice_id if 'created_invoice_id' in locals() else None
    else:
        print("\n❌ Żaden format faktury nie zadziałał")
        return False, None

def main():
    print("\n" + "=" * 80)
    print("  🔍 PEŁNA DIAGNOSTYKA wFirma OAuth 2.0 API")
    print("=" * 80)
    print(f"\nData: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Client ID: {CLIENT_ID}")
    print(f"Scope: {FULL_SCOPE[:80]}...")
    
    # Spróbuj wczytać token z pliku
    token = None
    try:
        import os
        if os.path.exists('wfirma_token_local.json'):
            print("\n📁 Znaleziono zapisany token...")
            with open('wfirma_token_local.json', 'r') as f:
                data = json.load(f)
                if time.time() < data.get('expires_at', 0):
                    token = data['access_token']
                    print("✅ Token z pliku jest ważny - używam go")
                else:
                    print("⏰ Token wygasł - pobieram nowy")
    except Exception as e:
        print(f"⚠️  Nie udało się wczytać tokenu: {e}")
    
    # Jeśli nie ma tokenu, pobierz nowy
    if not token:
        token = get_token()
    
    if not token:
        print("\n❌ Nie udało się pobrać tokenu - kończę!")
        return
    
    # Wykonaj testy
    print_section("KROK 2: TESTY API")
    
    results = {
        'authorization': False,
        'companies': False,
        'find_contractors': False,
        'add_contractor': False,
        'invoices': False,
        'download': False,
        'send_email': False
    }
    
    company_id = None
    found_contractors = []
    new_contractor_id = None
    invoice_id = None
    
    # Test 1: Autoryzacja
    results['authorization'] = test_authorization(token)
    
    if not results['authorization']:
        print("\n❌ Token nie działa - pozostałe testy nie mają sensu!")
        print_summary(results)
        return
    
    # Test 2: Companies
    results['companies'], company_id = test_companies(token)
    
    # Test 3: Wyszukiwanie kontrahentów po NIP
    results['find_contractors'], found_contractors = test_find_contractor_by_nip(token, TEST_CONTRACTORS_NIP)
    
    # Test 4: Dodanie nowego kontrahenta (zawsze testuj)
    print("\n💡 Testuję dodanie nowego kontrahenta...")
    results['add_contractor'], new_contractor_id = test_add_contractor(token)
    
    # Użyj znalezionych kontrahentów do faktury (jeśli są)
    if not found_contractors and new_contractor_id:
        # Jeśli nie było kontrahentów, użyj nowo dodanego
        found_contractors = [{'id': new_contractor_id, 'name': 'Test Kontrahent'}]
    
    # Test 5: Wystawienie faktury dla znalezionego kontrahenta
    if found_contractors:
        results['invoices'], invoice_id = test_create_invoice(token, found_contractors, company_id)
    else:
        print("\n⚠️  Pomijam test faktury - brak kontrahentów")
    
    # Test 6: Pobieranie PDF faktury
    pdf_filename = None
    if invoice_id:
        results['download'], pdf_filename = test_download_invoice(token, invoice_id, company_id)
    else:
        print("\n⚠️  Pomijam test pobierania PDF - brak ID faktury")
    
    # Test 7: Wysyłanie faktury na email
    if invoice_id:
        test_email = "kochnik@gmail.com"
        results['send_email'] = test_send_invoice(token, invoice_id, test_email, company_id)
    else:
        print("\n⚠️  Pomijam test wysyłania email - brak ID faktury")
    
    # Podsumowanie
    print_summary(results)

def print_summary(results):
    """Wyświetl podsumowanie testów"""
    print_section("PODSUMOWANIE")
    
    print("\n📊 Wyniki testów:")
    print(f"   {'✅' if results['authorization'] else '❌'} Test 1: Autoryzacja")
    print(f"   {'✅' if results['companies'] else '⚠️ '} Test 2: Companies (odczyt Twojej firmy)")
    print(f"   {'✅' if results['find_contractors'] else '❌'} Test 3: Wyszukiwanie kontrahentów (po NIP)")
    print(f"   {'✅' if results['add_contractor'] else '⚠️ '} Test 4: Dodanie kontrahenta (opcjonalny)")
    print(f"   {'✅' if results['invoices'] else '❌'} Test 5: Invoices (wystawienie faktury)")
    print(f"   {'✅' if results['download'] else '❌'} Test 6: Download (pobieranie PDF)")
    print(f"   {'✅' if results['send_email'] else '❌'} Test 7: Send (wysyłanie na email)")
    
    # Test kluczowych funkcjonalności
    critical_tests = ['authorization', 'find_contractors', 'invoices', 'send_email']
    all_critical_ok = all(results.get(test, False) for test in critical_tests)
    
    if all_critical_ok:
        print("\n🎉 KLUCZOWE FUNKCJE DZIAŁAJĄ! Możesz używać API.")
    else:
        print("\n🔧 WYMAGANE DZIAŁANIA:")
        
        if not results['authorization']:
            print("   ❌ Autoryzacja nie działa - sprawdź CLIENT_ID i CLIENT_SECRET")
        
        if not results['companies']:
            print("   ⚠️  Brak firm - skonfiguruj swoją firmę w panelu wFirma")
            print("      Panel → Ustawienia → Moja firma")
        
        if not results['find_contractors']:
            print("   ❌ Nie można znaleźć kontrahentów - sprawdź scope contractors-read")
            print("      Sprawdź czy NIPy w TEST_CONTRACTORS_NIP są w systemie")
        
        if not results['add_contractor'] and not results['find_contractors']:
            print("   ❌ Nie można dodać kontrahenta - sprawdź scope contractors-write")
        
        if not results['invoices']:
            print("   ❌ Nie można wystawić faktury - sprawdź scope invoices-write")
        
        if not results['download']:
            print("   ❌ Nie można pobrać PDF faktury")
        
        if not results['send_email']:
            print("   ❌ Nie można wysłać faktury na email")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()
