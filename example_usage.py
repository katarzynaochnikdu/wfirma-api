"""
Przykład użycia API wFirma do wystawienia i wysłania faktury

UWAGA: To jest przykład - nie uruchamiaj bez sprawdzenia danych!
"""

from wfirma_api import WFirmaAPI, create_and_send_invoice

# Konfiguracja - ZASTĄP PRAWDZIWYMI KLUCZAMI API!
# Klucze uzyskasz w wFirma: Ustawienia > Bezpieczeństwo > Klucze API
ACCESS_KEY = "bc7696aa5d1b68faf5aa36f6b5d6e632"
SECRET_KEY = "b3b1df3eb40b161088f0b6cb7bca9486"
APP_KEY = "twoj_app_key"  # Uzyskaj przez kontakt z wFirma

def main():
    # Inicjalizacja połączenia z API
    api = WFirmaAPI(access_key=ACCESS_KEY, secret_key=SECRET_KEY, app_key=APP_KEY)
    
    # Dane kontrahenta
    contractor = {
        "name": "Przykładowa Firma Sp. z o.o.",
        "tax_id": "1234567890",
        "email": "kontrahent@example.com",
        "street": "ul. Przykładowa 1",
        "zip": "00-000",
        "city": "Warszawa"
    }
    
    # Pozycje na fakturze
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
    
    # Adres e-mail odbiorcy faktury
    recipient_email = "klient@example.com"
    
    # Utworzenie i wysłanie faktury
    try:
        result = create_and_send_invoice(
            api=api,
            contractor_data=contractor,
            items=items,
            recipient_email=recipient_email
        )
        
        print(f"Faktura utworzona i wysłana!")
        print(f"ID faktury: {result['invoice_id']}")
        
    except Exception as e:
        print(f"Błąd: {e}")

if __name__ == "__main__":
    # UWAGA: Przed uruchomieniem uzupełnij klucze API!
    # main()
    print("Przed uruchomieniem uzupełnij klucze API w pliku!")
    print("Instrukcje jak uzyskać klucze znajdziesz w README.md")

