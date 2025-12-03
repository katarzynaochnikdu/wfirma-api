# API wFirma - Wystawianie i wysyłanie faktur

Moduł do integracji z API wFirma umożliwiający wystawianie faktur i wysyłanie ich do klientów.

## Dokumentacja API

Pełna dokumentacja API wFirma dostępna jest pod adresem: https://doc.wfirma.pl/

## Instalacja

```bash
pip install requests
```

## Konfiguracja

### Klucze API vs OAuth 2.0 - Którą metodę wybrać?

W wFirma dostępne są **dwie metody autoryzacji**:

#### 1. **Klucze API** (obecna implementacja)
- ✅ **Łatwe do uzyskania** - dostępne od razu po zalogowaniu
- ✅ **Bez weryfikacji firmy** - nie wymaga dodatkowych kroków
- ✅ **Szybka konfiguracja** - wystarczy wygenerować klucze w panelu
- ⚠️ **Ograniczony zakres dostępu** - mogą mieć mniej uprawnień
- ⚠️ **Mniej elastyczne** - trudniejsze zarządzanie uprawnieniami

**Kiedy używać:** Dla prostych integracji, testów, małych projektów, gdy nie potrzebujesz zaawansowanego zarządzania uprawnieniami.

#### 2. **OAuth 2.0** (wymaga weryfikacji firmy)
- ✅ **Bardziej bezpieczne** - standardowy protokół autoryzacji
- ✅ **Elastyczne zarządzanie uprawnieniami** - precyzyjne określenie zakresu dostępu
- ✅ **Lepsze dla aplikacji produkcyjnych** - profesjonalne podejście
- ✅ **Szerszy zakres dostępu** - dostęp do większej liczby zasobów
- ⚠️ **Wymaga weryfikacji firmy** - jednorazowy przelew weryfikacyjny
- ⚠️ **Bardziej skomplikowana konfiguracja** - wymaga redirect_uri, zakresów dostępu

**Kiedy używać:** Dla aplikacji produkcyjnych, integracji zewnętrznych, gdy potrzebujesz precyzyjnego zarządzania uprawnieniami.

### Jak uzyskać klucze API w wFirma?

1. **Zaloguj się do swojego konta w wFirma.pl**

2. **Przejdź do Ustawień**:
   - Kliknij na ikonę swojego konta użytkownika w prawym górnym rogu
   - Wybierz opcję **"Ustawienia"**

3. **Przejdź do sekcji Bezpieczeństwo**:
   - W menu po lewej stronie wybierz **"Bezpieczeństwo"**
   - Kliknij na zakładkę **"Klucze API"**

4. **Utwórz nowy klucz API**:
   - Kliknij przycisk **"Dodaj"** lub **"Utwórz nowy klucz API"**
   - Wprowadź nazwę aplikacji (np. nazwę Twojego projektu)
   - Potwierdź operację podając swoje hasło do wFirma
   - System wygeneruje:
     - **Access Key** – klucz dostępu
     - **Secret Key** – klucz tajny
   - ⚠️ **UWAGA**: Secret Key jest wyświetlany tylko raz! Zapisz go natychmiast w bezpiecznym miejscu.

5. **Uzyskaj App Key**:
   - Skontaktuj się z wFirma poprzez formularz kontaktowy: https://wfirma.pl/kontakt
   - W formularzu podaj informacje o planowanej integracji
   - Poproś o przyznanie **App Key**
   - Po weryfikacji otrzymasz App Key na podany adres e-mail

6. **Uzupełnij klucze w pliku `example_usage.py`**:
   - Otwórz plik `example_usage.py`
   - Zastąp wartości `ACCESS_KEY`, `SECRET_KEY` i `APP_KEY` swoimi kluczami

## Użycie

### Podstawowe użycie

```python
from wfirma_api import WFirmaAPI

# Inicjalizacja
api = WFirmaAPI(
    access_key="twoj_access_key",
    secret_key="twoj_secret_key", 
    app_key="twoj_app_key"
)

# Dane faktury
invoice_data = {
    "invoice": {
        "contractor": {
            "name": "Nazwa kontrahenta",
            "tax_id": "NIP",
            "email": "email@example.com"
        },
        "invoicecontent": [
            {
                "name": "Nazwa pozycji",
                "count": 1,
                "price": 100.00,
                "vat": 23
            }
        ]
    }
}

# Utworzenie faktury
response = api.create_invoice(invoice_data)
invoice_id = response['invoices'][0]['invoice']['id']

# Wysłanie faktury e-mailem
api.send_invoice_email(invoice_id, "klient@example.com")
```

### Użycie funkcji pomocniczej

```python
from wfirma_api import create_and_send_invoice

result = create_and_send_invoice(
    api=api,
    contractor_data=contractor,
    items=items,
    recipient_email="klient@example.com"
)
```

## UWAGI

- **Testy zaczynamy od 1 rekordu** - zawsze testuj najpierw na jednej fakturze
- **Nie uruchamiaj bez sprawdzenia danych** - upewnij się, że wszystkie dane są poprawne
- **Ostrożnie z danymi produkcyjnymi** - kod ma krytyczny wpływ na system

## Struktura projektu

- `wfirma_api.py` - główny moduł z klasą WFirmaAPI (używa Kluczy API)
- `example_usage.py` - przykłady użycia
- `example_full_workflow.py` - przykład pełnego workflow (wyszukanie kontrahenta → faktura → wysyłka)
- `README.md` - dokumentacja
- `ROZNICE_API_vs_OAUTH.md` - szczegółowe porównanie metod autoryzacji
- `OAUTH2_SCOPES.md` - wymagane scopes OAuth 2.0 dla różnych operacji
- `WERYFIKACJA_OAUTH2.md` - proces weryfikacji firmy i rejestracji aplikacji OAuth 2.0
- `JAK_uzyskac_klucze_API.md` - instrukcja uzyskania kluczy API
- `JAK_sprawdzic_IP.md` - jak sprawdzić adres IP klienta

