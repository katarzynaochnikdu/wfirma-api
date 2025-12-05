"""
Sprawdzanie NIP w wFirma używając OAuth 2.0 Authorization Code Flow
Uruchom: python sprawdz_nip_oauth_flow.py
"""

import requests
import json
import webbrowser
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading

# Plik do przechowywania tokenu
TOKEN_FILE = "wfirma_token.json"

# OAuth 2.0 z Oauth20.txt
CLIENT_ID = "017bd7d64f9c90ea409d84a69ffb9ab0"
CLIENT_SECRET = "620cbcabbc9b8e28e172701b6401c6d8"
REDIRECT_URI = "http://localhost:8000"
SCOPES = [
    "contractors-read",
    "contractors-write",
    "invoice_descriptions-read",
    "invoice_deliveries-read",
    "invoice_deliveries-write",
    "invoices-read",
    "invoices-write",
    "notes-read",
    "notes-write",
    "payments-read",
    "payments-write",
    "tags-read",
    "tags-write",
]

# Globalna zmienna na kod autoryzacyjny
authorization_code = None
server_running = True

class OAuthHandler(BaseHTTPRequestHandler):
    """Handler dla odbierania kodu OAuth"""
    
    def do_GET(self):
        global authorization_code, server_running
        
        # Parsuj URL
        query = urlparse(self.path).query
        params = parse_qs(query)
        
        if 'code' in params:
            authorization_code = params['code'][0]
            
            # Wyślij odpowiedź do przeglądarki
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b"""
                <html>
                <head><meta charset="utf-8"></head>
                <body>
                    <h2>Autoryzacja zakonczona!</h2>
                    <p>Mozesz zamknac to okno i wrocic do terminala.</p>
                </body>
                </html>
            """)
            
            # Zatrzymaj serwer
            server_running = False
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<h2>Blad: Brak kodu autoryzacyjnego</h2>")
    
    def log_message(self, format, *args):
        # Wyłącz domyślne logi serwera
        pass

def get_authorization_code():
    """Uruchom serwer i poczekaj na kod autoryzacyjny"""
    global authorization_code, server_running
    
    # Reset globalnych zmiennych
    authorization_code = None
    server_running = True
    
    # URL autoryzacji
    from urllib.parse import quote

    scope_str = " ".join(SCOPES)

    # Poprawny endpoint wg dokumentacji wFirma: /oauth2/auth (nie /authorize!)
    auth_url = (
        "https://wfirma.pl/oauth2/auth?"
        f"response_type=code&"
        f"client_id={CLIENT_ID}&"
        f"scope={quote(scope_str)}&"
        f"redirect_uri={quote(REDIRECT_URI, safe='')}"
    )
    
    print("\n[LOG] Otwieram przeglądarkę do autoryzacji...")
    print(f"[LOG] Jeśli nie otworzy się automatycznie, wejdź na:")
    print(f"[LOG] {auth_url}\n")
    
    # Otwórz przeglądarkę
    webbrowser.open(auth_url)
    
    # Uruchom serwer HTTP
    print("[LOG] Serwer HTTP uruchomiony na http://localhost:8000")
    print("[LOG] Czekam na autoryzację w przeglądarce...\n")
    
    server = HTTPServer(('localhost', 8000), OAuthHandler)
    
    # Obsługa requestów
    while server_running and not authorization_code:
        server.handle_request()
    
    server.server_close()
    
    return authorization_code

def save_token(access_token, expires_in):
    """Zapisz token do pliku"""
    token_data = {
        'access_token': access_token,
        'expires_at': time.time() + expires_in - 60  # 60 sek margines
    }
    with open(TOKEN_FILE, 'w') as f:
        json.dump(token_data, f)
    print(f"[LOG] Token zapisany do {TOKEN_FILE}")

def is_token_valid():
    """Sprawdź czy zapisany token jest ważny (bez komunikatów)"""
    if not os.path.exists(TOKEN_FILE):
        return False
    try:
        with open(TOKEN_FILE, 'r') as f:
            token_data = json.load(f)
        return time.time() < token_data.get('expires_at', 0)
    except:
        return False

def load_token(silent=False):
    """Wczytaj token z pliku jeśli istnieje i jest ważny"""
    if not os.path.exists(TOKEN_FILE):
        return None
    
    try:
        with open(TOKEN_FILE, 'r') as f:
            token_data = json.load(f)
        
        if time.time() < token_data.get('expires_at', 0):
            remaining = int(token_data['expires_at'] - time.time())
            if not silent:
                print(f"[LOG] ✓ Wczytano zapisany token (ważny jeszcze {remaining} sekund)")
            return token_data['access_token']
        else:
            if not silent:
                print("[LOG] Zapisany token wygasł, potrzebna nowa autoryzacja")
            return None
    except Exception as e:
        if not silent:
            print(f"[LOG] Błąd wczytywania tokenu: {e}")
        return None

def exchange_code_for_token(code):
    """Wymień kod autoryzacyjny na token dostępu"""
    # Poprawny endpoint wg dokumentacji wFirma: api2.wfirma.pl z oauth_version=2
    token_url = "https://api2.wfirma.pl/oauth2/token?oauth_version=2"
    
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI
    }
    
    print("[LOG] Wymieniam kod na token...")
    response = requests.post(token_url, data=data)
    
    if response.status_code != 200:
        print(f"[LOG] BŁĄD: {response.status_code}")
        print(f"[LOG] {response.text}")
        return None
    
    token_data = response.json()
    expires_in = token_data.get('expires_in', 3600)
    access_token = token_data['access_token']
    
    # Zapisz token
    save_token(access_token, expires_in)
    
    print(f"[LOG] ✓ Token otrzymany (ważny {expires_in} sekund)\n")
    return access_token

def search_contractor(access_token, nip):
    """Wyszukaj kontrahenta po NIP"""
    clean_nip = nip.replace("-", "").replace(" ", "")
    
    # API endpoint z parametrami formatu JSON i oauth_version=2
    api_url = "https://api2.wfirma.pl/contractors/find?inputFormat=json&outputFormat=json&oauth_version=2"
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    # Struktura zapytania wg dokumentacji wFirma
    search_data = {
        "contractors": {
            "parameters": {
                "conditions": {
                    "condition": {
                        "field": "nip",
                        "operator": "eq",
                        "value": clean_nip
                    }
                }
            }
        }
    }
    
    print(f"[LOG] Szukam kontrahenta o NIP: {clean_nip}")
    print(f"[LOG] URL: {api_url}")
    
    # POST zamiast GET
    response = requests.post(api_url, headers=headers, json=search_data)
    
    print(f"[LOG] Status HTTP: {response.status_code}")
    print(f"[LOG] Content-Type: {response.headers.get('Content-Type')}")
    print(f"[LOG] Odpowiedź: {response.text[:500]}\n")
    
    if response.status_code == 200:
        try:
            data = response.json()
            contractors = data.get('contractors', {})
            
            if contractors:
                # wFirma zwraca dict z kluczami "0", "1", etc.
                if isinstance(contractors, dict):
                    # Szukamy pierwszego klucza numerycznego
                    for key in contractors:
                        if key.isdigit():
                            return contractors[key].get('contractor')
                    # Lub bezpośrednio contractor
                    if 'contractor' in contractors:
                        return contractors['contractor']
        except Exception as e:
            print(f"[LOG] Błąd parsowania: {e}")
    
    return None

def get_valid_token():
    """Pobierz ważny token (z pliku lub przez nową autoryzację)"""
    # Najpierw sprawdź czy jest zapisany token
    token = load_token()
    
    if token:
        return token
    
    # Potrzebna nowa autoryzacja
    code = get_authorization_code()
    
    if not code:
        print("❌ Nie udało się uzyskać kodu autoryzacyjnego")
        return None
    
    print(f"[LOG] ✓ Kod autoryzacyjny otrzymany\n")
    
    # Wymiana kodu na token
    token = exchange_code_for_token(code)
    return token

def main():
    print("=" * 60)
    print("Sprawdzanie NIP w wFirma (OAuth 2.0)")
    print("=" * 60)
    
    token = get_valid_token()
    
    if not token:
        print("❌ Nie udało się uzyskać tokenu")
        return
    
    # Pytaj o NIP i sprawdzaj
    while True:
        print("=" * 60)
        nip = input("\nPodaj NIP firmy (lub 'q' aby zakończyć): ").strip()
        
        if nip.lower() == 'q':
            break
        
        # Sprawdź czy token jest jeszcze ważny (cicho)
        if not is_token_valid():
            print("[LOG] Token wygasł, pobieram nowy...")
            token = get_valid_token()
            if not token:
                print("❌ Nie udało się odnowić tokenu")
                break
        
        firma = search_contractor(token, nip)
        
        print("=" * 60)
        if firma:
            print("\n✅ FIRMA ISTNIEJE w wFirma")
            print(f"   ID: {firma.get('id')}")
            print(f"   Nazwa: {firma.get('name')}")
            print(f"   NIP: {firma.get('nip', firma.get('tax_id'))}")
            print(f"   Miasto: {firma.get('city')}")
        else:
            print("\n❌ FIRMA NIE ISTNIEJE w wFirma")
            print("   Trzeba ją najpierw dodać, żeby wystawić fakturę")
        print()

if __name__ == "__main__":
    main()

