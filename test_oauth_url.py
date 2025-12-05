"""
Test - sprawdza co zwraca strona autoryzacji wFirma
"""

import requests
from urllib.parse import quote

CLIENT_ID = "017bd7d64f9c90ea409d84a69ffb9ab0"
REDIRECT_URI = "http://localhost:8000"
SCOPES = "contractors-read contractors-write invoices-read invoices-write"

print("=" * 60)
print("Test URL autoryzacji wFirma OAuth 2.0")
print("=" * 60)

# Testujemy różne warianty URL
urls_to_test = [
    # Wariant 1: api.wfirma.pl
    f"https://api.wfirma.pl/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={quote(REDIRECT_URI, safe='')}&response_type=code&scope={quote(SCOPES)}",
    
    # Wariant 2: api2.wfirma.pl
    f"https://api2.wfirma.pl/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={quote(REDIRECT_URI, safe='')}&response_type=code&scope={quote(SCOPES)}",
    
    # Wariant 3: wfirma.pl
    f"https://wfirma.pl/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={quote(REDIRECT_URI, safe='')}&response_type=code&scope={quote(SCOPES)}",
]

for i, url in enumerate(urls_to_test, 1):
    print(f"\n--- Test {i} ---")
    print(f"URL: {url[:80]}...")
    
    try:
        # Nie podążamy za przekierowaniami, żeby zobaczyć co zwraca
        response = requests.get(url, allow_redirects=False, timeout=10)
        
        print(f"Status: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        
        if response.status_code in [301, 302, 303, 307, 308]:
            print(f"Redirect do: {response.headers.get('Location')}")
        else:
            print(f"Body (pierwsze 500 znaków):")
            print(response.text[:500])
            
    except Exception as e:
        print(f"BŁĄD: {e}")

print("\n" + "=" * 60)

