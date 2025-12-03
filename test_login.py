"""
Prosty test logowania do wFirma API
Sprawdza czy klucze API działają poprawnie
"""

from wfirma_api import WFirmaAPI

# Konfiguracja - użyj swoich kluczy z example_usage.py
ACCESS_KEY = "bc7696aa5d1b68faf5aa36f6b5d6e632"
SECRET_KEY = "b3b1df3eb40b161088f0b6cb7bca9486"
APP_KEY = ""  # Opcjonalne

def test_login():
    """
    Test logowania do wFirma API
    """
    print("=" * 50)
    print("Test logowania do wFirma API")
    print("=" * 50)
    
    try:
        print("\n1. Inicjalizacja połączenia...")
        api = WFirmaAPI(
            access_key=ACCESS_KEY,
            secret_key=SECRET_KEY,
            app_key=APP_KEY
        )
        print("   ✓ Połączenie utworzone")
        
        print("\n2. Test połączenia - proste żądanie HTTP (bez JSON)...")
        #
        # Zamiast od razu parsować JSON (co dawało JSONDecodeError),
        # sprawdzamy najpierw samą odpowiedź HTTP: status, nagłówki, kawałek treści.
        #
        import requests  # tylko na potrzeby testu
        url = f"{api.BASE_URL}/invoices"
        try:
            raw_response = api.session.get(url, params={"limit": 1})
        except Exception as e:
            print(f"   ✗ Błąd przy wysyłaniu żądania HTTP: {e}")
            print("\n" + "=" * 50)
            print("⚠️  Połączenie z API nie powiodło się (problem sieciowy / DNS itp.)")
            print("=" * 50)
            return False

        print(f"   Status HTTP: {raw_response.status_code}")
        print(f"   Content-Type: {raw_response.headers.get('Content-Type')}")
        body_preview = raw_response.text[:400].replace("\n", " ")
        print(f"   Fragment odpowiedzi: {body_preview!r}")

        if raw_response.status_code == 200:
            print("\n" + "=" * 50)
            print("✅ SUKCES! Autoryzacja i żądanie HTTP działają (status 200).")
            print("   Kolejny krok: dopasować strukturę JSON do dokumentacji wFirma.")
            print("=" * 50)
            return True
        else:
            print("\n" + "=" * 50)
            print("⚠️  Odpowiedź nie jest 200 OK – coś jest nie tak.")
            print("   Na podstawie statusu i treści powyżej możesz sprawdzić w dokumentacji,")
            print("   czy to problem z uprawnieniami, endpointem czy czymś innym.")
            print("=" * 50)
            return False
            
    except Exception as e:
        print(f"\n✗ BŁĄD podczas logowania: {e}")
        print("\n" + "=" * 50)
        print("❌ BŁĄD LOGOWANIA")
        print("=" * 50)
        print(f"\nTyp błędu: {type(e).__name__}")
        print(f"Wiadomość: {e}")
        print("\nMożliwe przyczyny:")
        print("  - Nieprawidłowe ACCESS_KEY lub SECRET_KEY")
        print("  - Brak połączenia z internetem")
        print("  - Problem z API wFirma")
        return False

if __name__ == "__main__":
    print("\n🚀 Uruchamianie testu logowania do wFirma...\n")
    success = test_login()
    
    if success:
        print("\n✅ Możesz teraz używać API wFirma!")
        print("   Przejdź do example_usage.py aby zobaczyć przykłady użycia")
    else:
        print("\n⚠️  Sprawdź klucze API w pliku test_login.py")
        print("   Upewnij się, że ACCESS_KEY i SECRET_KEY są poprawne")

