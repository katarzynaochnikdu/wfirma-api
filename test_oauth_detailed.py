"""
Szczegółowy test OAuth - sprawdza dokładnie co zwraca wFirma
"""

import requests
from urllib.parse import quote, urlencode

CLIENT_ID = "017bd7d64f9c90ea409d84a69ffb9ab0"
CLIENT_SECRET = "620cbcabbc9b8e28e172701b6401c6d8"
REDIRECT_URI = "http://localhost:8000"

# Wszystkie scope z panelu
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

print("=" * 70)
print("Szczegółowy test OAuth wFirma")
print("=" * 70)

# Test różnych formatów scope
scope_formats = [
    # Format 1: spacje
    " ".join(SCOPES),
    # Format 2: przecinki
    ",".join(SCOPES),
    # Format 3: tylko jeden scope
    "contractors-read",
]

for i, scope in enumerate(scope_formats, 1):
    print(f"\n--- Test {i}: scope format ---")
    print(f"Scope: {scope[:60]}...")
    
    # Buduj URL ręcznie
    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': scope,
    }
    
    url = f"https://wfirma.pl/oauth2/authorize?{urlencode(params)}"
    print(f"URL: {url[:100]}...")
    
    try:
        # Sprawdź co zwraca (bez przekierowań)
        response = requests.get(url, allow_redirects=False, timeout=10)
        
        print(f"Status: {response.status_code}")
        
        if response.status_code in [301, 302, 303, 307, 308]:
            location = response.headers.get('Location', '')
            print(f"Redirect: {location}")
            
            # Jeśli redirect do /logowanie, to dobrze
            if '/logowanie' in location:
                print("✓ Przekierowanie do logowania - to dobrze!")
            elif 'error' in location.lower():
                print("✗ Przekierowanie z błędem!")
        else:
            print(f"Body: {response.text[:300]}")
            
    except Exception as e:
        print(f"BŁĄD: {e}")

# Test dodatkowy - sprawdź czy redirect_uri musi mieć końcowy slash
print("\n--- Test dodatkowy: redirect_uri z / na końcu ---")
params_slash = {
    'client_id': CLIENT_ID,
    'redirect_uri': REDIRECT_URI + "/",  # z / na końcu
    'response_type': 'code',
    'scope': 'contractors-read',
}
url_slash = f"https://wfirma.pl/oauth2/authorize?{urlencode(params_slash)}"
try:
    response = requests.get(url_slash, allow_redirects=False, timeout=10)
    print(f"Status: {response.status_code}")
    if response.status_code in [301, 302, 303, 307, 308]:
        print(f"Redirect: {response.headers.get('Location', '')}")
    else:
        print(f"Body: {response.text[:300]}")
except Exception as e:
    print(f"BŁĄD: {e}")

print("\n" + "=" * 70)
print("Twoje dane z panelu wFirma:")
print(f"  Client ID: {CLIENT_ID}")
print(f"  Redirect URI: {REDIRECT_URI}")
print(f"  IP: 83.175.180.55")
print("=" * 70)

