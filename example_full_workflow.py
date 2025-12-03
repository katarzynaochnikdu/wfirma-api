"""
Przykład pełnego workflow: wyszukanie kontrahenta po NIP, 
dodanie jeśli nie istnieje, utworzenie faktury i wysłanie

UWAGA: To jest przykład - nie uruchamiaj bez sprawdzenia danych!
"""

from wfirma_api import WFirmaAPI

# Konfiguracja - ZASTĄP PRAWDZIWYMI KLUCZAMI API!
ACCESS_KEY = "twoj_access_key"
SECRET_KEY = "twoj_secret_key"
APP_KEY = "twoj_app_key"

def main():
    # Inicjalizacja połączenia z API
    api = WFirmaAPI(access_key=ACCESS_KEY, secret_key=SECRET_KEY, app_key=APP_KEY)
    
    # NIP kontrahenta do wyszukania
    nip = "1234567890"  # Zastąp prawdziwym NIPem
    
    # Dane kontrahenta (używane jeśli nie istnieje w systemie)
    contractor_data = {
        "contractor": {
            "name": "Przykładowa Firma Sp. z o.o.",
            "tax_id": nip,
            "email": "kontrahent@example.com",
            "street": "ul. Przykładowa 1",
            "zip": "00-000",
            "city": "Warszawa",
            "country": "Polska"
        }
    }
    
    # KROK 1: Wyszukaj kontrahenta po NIP lub utwórz nowego
    print(f"Wyszukiwanie kontrahenta o NIP: {nip}...")
    contractor = api.find_or_create_contractor(nip, contractor_data)
    
    if contractor.get('id'):
        print(f"✓ Kontrahent znaleziony/utworzony: {contractor.get('name')} (ID: {contractor.get('id')})")
    else:
        print("✗ Nie udało się znaleźć ani utworzyć kontrahenta")
        return
    
    # KROK 2: Przygotowanie pozycji na fakturze
    items = [
        {
            "name": "Usługa konsultingowa",
            "count": 1,
            "price": 1000.00,
            "vat": 23,
            "unit": "szt."
        },
        {
            "name": "Dodatkowa usługa",
            "count": 2,
            "price": 500.00,
            "vat": 23,
            "unit": "szt."
        }
    ]
    
    # KROK 3: Utworzenie faktury
    print("Tworzenie faktury...")
    invoice_data = {
        "invoice": {
            "contractor": {
                "id": contractor.get('id')
            },
            "invoicecontent": items,
            "paymenttype": "transfer"
        }
    }
    
    try:
        create_response = api.create_invoice(invoice_data)
        invoice_id = create_response.get('invoices', [{}])[0].get('invoice', {}).get('id')
        
        if not invoice_id:
            raise ValueError("Nie udało się utworzyć faktury")
        
        print(f"✓ Faktura utworzona (ID: {invoice_id})")
        
        # KROK 4: Wysłanie faktury e-mailem
        recipient_email = contractor.get('email') or "klient@example.com"
        print(f"Wysyłanie faktury na adres: {recipient_email}...")
        
        send_response = api.send_invoice_email(
            invoice_id=invoice_id,
            email=recipient_email,
            subject="Faktura VAT",
            message="W załączeniu przesyłamy fakturę VAT."
        )
        
        print("✓ Faktura wysłana pomyślnie!")
        print(f"\nPodsumowanie:")
        print(f"  - Kontrahent: {contractor.get('name')}")
        print(f"  - Faktura ID: {invoice_id}")
        print(f"  - Wysłano do: {recipient_email}")
        
    except Exception as e:
        print(f"✗ Błąd: {e}")

if __name__ == "__main__":
    # UWAGA: Przed uruchomieniem uzupełnij klucze API!
    # main()
    print("Przed uruchomieniem uzupełnij klucze API w pliku!")
    print("Instrukcje jak uzyskać klucze znajdziesz w README.md")

