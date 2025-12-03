"""
Najprostszy test logowania do wFirma API
Tylko sprawdza czy można się zalogować
"""

from wfirma_api import WFirmaAPI

# Wklej tutaj swoje klucze z example_usage.py
ACCESS_KEY = "bc7696aa5d1b68faf5aa36f6b5d6e632"
SECRET_KEY = "b3b1df3eb40b161088f0b6cb7bca9486"

print("Logowanie do wFirma...")

try:
    # Logowanie
    api = WFirmaAPI(access_key=ACCESS_KEY, secret_key=SECRET_KEY)
    print("✅ Zalogowano pomyślnie!")
    print("Możesz używać obiektu 'api' do wykonywania operacji")
    
except Exception as e:
    print(f"❌ Błąd logowania: {e}")

