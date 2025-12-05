"""
Prosty skrypt do sprawdzania czy firma o danym NIP istnieje w wFirma
Uruchom: python sprawdz_nip.py
"""

from wfirma_api import WFirmaAPI
import json

# Twoje klucze API (jak w example_usage.py)
ACCESS_KEY = "bc7696aa5d1b68faf5aa36f6b5d6e632"
SECRET_KEY = "b3b1df3eb40b161088f0b6cb7bca9486"

# Pyta o NIP
nip = input("Podaj NIP firmy: ").strip()

print(f"\nSprawdzam NIP: {nip}...")
print("=" * 60)

# Logowanie do wFirma
print("\n[LOG] Logowanie do wFirma...")
api = WFirmaAPI(access_key=ACCESS_KEY, secret_key=SECRET_KEY)
print("[LOG] ✓ Połączenie utworzone")

# Przygotowanie zapytania
clean_nip = nip.replace("-", "").replace(" ", "")
print(f"\n[LOG] Czyszczenie NIP: '{nip}' → '{clean_nip}'")

endpoint = "contractors/find"
search_params = {
    "conditions": {
        "contractor": {
            "tax_id": clean_nip
        }
    }
}

print(f"\n[LOG] Endpoint: {api.BASE_URL}/{endpoint}")
print(f"[LOG] Parametry zapytania:")
print(json.dumps(search_params, indent=2, ensure_ascii=False))

# Wykonanie zapytania z logowaniem
print("\n[LOG] Wysyłanie zapytania do API...")
try:
    # Bezpośrednie wywołanie GET z logowaniem odpowiedzi
    url = f"{api.BASE_URL}/{endpoint}"
    response = api.session.get(url, params=search_params)
    
    print(f"\n[LOG] Status HTTP: {response.status_code}")
    print(f"[LOG] Content-Type: {response.headers.get('Content-Type')}")
    print(f"\n[LOG] Surowa odpowiedź (pierwsze 500 znaków):")
    print(response.text[:500])
    print("...")
    
    # Próba parsowania JSON
    if response.status_code == 200:
        try:
            data = response.json()
            print(f"\n[LOG] Odpowiedź JSON:")
            print(json.dumps(data, indent=2, ensure_ascii=False)[:1000])
            
            contractors = data.get('contractors', [])
            print(f"\n[LOG] Liczba znalezionych kontrahentów: {len(contractors)}")
            
            if contractors:
                firma = contractors[0].get('contractor')
            else:
                firma = None
        except Exception as e:
            print(f"[LOG] Błąd parsowania JSON: {e}")
            firma = None
    else:
        print(f"[LOG] Nieoczekiwany status HTTP: {response.status_code}")
        firma = None
        
except Exception as e:
    print(f"\n[LOG] BŁĄD podczas zapytania: {type(e).__name__}: {e}")
    firma = None

print("\n" + "=" * 60)

if firma:
    print("\n✅ FIRMA ISTNIEJE w wFirma")
    print(f"   ID: {firma.get('id')}")
    print(f"   Nazwa: {firma.get('name')}")
    print(f"   NIP: {firma.get('tax_id')}")
    print(f"   Miasto: {firma.get('city')}")
else:
    print("\n❌ FIRMA NIE ISTNIEJE w wFirma")
    print("   Trzeba ją najpierw dodać, żeby wystawić fakturę")

