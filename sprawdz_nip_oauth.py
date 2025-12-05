"""
Sprawdzanie NIP w wFirma używając OAuth 2.0
Uruchom: python sprawdz_nip_oauth.py
"""

import requests
import json

# OAuth 2.0 z Oauth20.txt
CLIENT_ID = "017bd7d64f9c90ea409d84a69ffb9ab0"
CLIENT_SECRET = "620cbcabbc9b8e28e172701b6401c6d8"

# Pyta o NIP
nip = input("Podaj NIP firmy: ").strip()

print(f"\nSprawdzam NIP: {nip}...")
print("=" * 60)

# KROK 1: Pobierz token OAuth 2.0
print("\n[LOG] Pobieranie tokenu OAuth 2.0...")
token_url = "https://api2.wfirma.pl/oauth2/token"
token_data = {
    'grant_type': 'client_credentials',
    'client_id': CLIENT_ID,
    'client_secret': CLIENT_SECRET
}

token_response = requests.post(token_url, data=token_data)
print(f"[LOG] Status tokenu: {token_response.status_code}")

if token_response.status_code != 200:
    print(f"[LOG] BŁĄD: Nie można uzyskać tokenu")
    print(f"[LOG] Odpowiedź: {token_response.text}")
    exit(1)

token_json = token_response.json()
access_token = token_json['access_token']
print(f"[LOG] ✓ Token otrzymany (ważny {token_json.get('expires_in', '?')} sekund)")

# KROK 2: Wyszukaj kontrahenta
clean_nip = nip.replace("-", "").replace(" ", "")
print(f"\n[LOG] Czyszczenie NIP: '{nip}' → '{clean_nip}'")

api_url = "https://api2.wfirma.pl/contractors/find"
headers = {
    'Authorization': f'Bearer {access_token}',
    'Content-Type': 'application/json',
    'Accept': 'application/json'
}

search_params = {
    "conditions": {
        "contractor": {
            "tax_id": clean_nip
        }
    }
}

print(f"\n[LOG] Endpoint: {api_url}")
print(f"[LOG] Parametry zapytania:")
print(json.dumps(search_params, indent=2, ensure_ascii=False))

print("\n[LOG] Wysyłanie zapytania do API...")
search_response = requests.get(api_url, headers=headers, params=search_params)

print(f"\n[LOG] Status HTTP: {search_response.status_code}")
print(f"[LOG] Content-Type: {search_response.headers.get('Content-Type')}")
print(f"\n[LOG] Surowa odpowiedź (pierwsze 500 znaków):")
print(search_response.text[:500])
print("...")

print("\n" + "=" * 60)

# KROK 3: Wyświetl wynik
if search_response.status_code == 200:
    try:
        data = search_response.json()
        print(f"\n[LOG] Odpowiedź JSON:")
        print(json.dumps(data, indent=2, ensure_ascii=False)[:1000])
        
        contractors = data.get('contractors', [])
        print(f"\n[LOG] Liczba znalezionych kontrahentów: {len(contractors)}")
        
        if contractors:
            firma = contractors[0].get('contractor')
            print("\n✅ FIRMA ISTNIEJE w wFirma")
            print(f"   ID: {firma.get('id')}")
            print(f"   Nazwa: {firma.get('name')}")
            print(f"   NIP: {firma.get('tax_id')}")
            print(f"   Miasto: {firma.get('city')}")
        else:
            print("\n❌ FIRMA NIE ISTNIEJE w wFirma")
            print("   Trzeba ją najpierw dodać, żeby wystawić fakturę")
    except Exception as e:
        print(f"[LOG] Błąd parsowania: {e}")
else:
    print(f"\n❌ BŁĄD API: Status {search_response.status_code}")

