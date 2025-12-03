# Jak uzyskać klucze API w programie wFirma

## Krok po kroku

### 1. Zaloguj się do wFirma
- Wejdź na stronę https://wfirma.pl
- Zaloguj się do swojego konta

### 2. Przejdź do Ustawień
- Kliknij na ikonę swojego konta użytkownika w prawym górnym rogu
- Z rozwijanego menu wybierz opcję **"Ustawienia"**

### 3. Otwórz sekcję Bezpieczeństwo
- W menu po lewej stronie wybierz **"Bezpieczeństwo"**
- Kliknij na zakładkę **"Klucze API"** (w sekcji "Aplikacje")

### 4. Utwórz nowy klucz API
- Kliknij przycisk **"Dodaj"** lub **"Utwórz nowy klucz API"**
- Wprowadź nazwę aplikacji (np. "Integracja Python" lub nazwę Twojego projektu)
- Potwierdź operację podając swoje hasło do wFirma
- System wygeneruje i wyświetli:
  - **Access Key** – klucz dostępu
  - **Secret Key** – klucz tajny

### 5. ⚠️ WAŻNE - Zapisz Secret Key!
- **Secret Key jest wyświetlany tylko raz podczas tworzenia**
- Po zamknięciu okna nie będzie możliwości jego ponownego odczytania
- **Zapisz go natychmiast w bezpiecznym miejscu!**
- Jeśli zapomnisz Secret Key, musisz utworzyć nowy klucz API

### 6. Uzyskaj App Key
- Aby otrzymać **App Key**, skontaktuj się z wFirma:
  - Przejdź na stronę: https://wfirma.pl/kontakt
  - Wypełnij formularz kontaktowy
  - Podaj informacje o planowanej integracji
  - Poproś o przyznanie **App Key**
- Po pozytywnej weryfikacji otrzymasz App Key na podany adres e-mail

## Podsumowanie - potrzebne klucze

Do poprawnego działania integracji potrzebne są **wszystkie trzy klucze**:

1. ✅ **Access Key** - uzyskany w kroku 4
2. ✅ **Secret Key** - uzyskany w kroku 4 (zapisz natychmiast!)
3. ✅ **App Key** - uzyskany przez kontakt z wFirma (krok 6)

## Uwagi

- Każda modyfikacja klucza aplikacji spowoduje zmianę zarówno Access Key, jak i Secret Key
- Klucze są unikalne dla każdego konta wFirma
- Nie udostępniaj swoich kluczy osobom trzecim
- W przypadku utraty Secret Key, utwórz nowy klucz API

## Gdzie użyć kluczy?

Po uzyskaniu wszystkich trzech kluczy, uzupełnij je w pliku `example_usage.py`:

```python
ACCESS_KEY = "twoj_access_key"
SECRET_KEY = "twoj_secret_key"
APP_KEY = "twoj_app_key"
```

