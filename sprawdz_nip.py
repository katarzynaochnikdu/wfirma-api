"""
Prosty skrypt do sprawdzania czy firma o danym NIP istnieje w wFirma
Uruchom: python sprawdz_nip.py
"""

from wfirma_api import WFirmaAPI

# Twoje klucze API (jak w example_usage.py)
ACCESS_KEY = "bc7696aa5d1b68faf5aa36f6b5d6e632"
SECRET_KEY = "b3b1df3eb40b161088f0b6cb7bca9486"

# Pyta o NIP
nip = input("Podaj NIP firmy: ").strip()

print(f"\nSprawdzam NIP: {nip}...")

# Logowanie do wFirma
api = WFirmaAPI(access_key=ACCESS_KEY, secret_key=SECRET_KEY)

# Sprawdzanie czy istnieje
firma = api.find_contractor_by_nip(nip)

if firma:
    print("\n✅ FIRMA ISTNIEJE w wFirma")
    print(f"   ID: {firma.get('id')}")
    print(f"   Nazwa: {firma.get('name')}")
    print(f"   NIP: {firma.get('tax_id')}")
    print(f"   Miasto: {firma.get('city')}")
else:
    print("\n❌ FIRMA NIE ISTNIEJE w wFirma")
    print("   Trzeba ją najpierw dodać, żeby wystawić fakturę")

