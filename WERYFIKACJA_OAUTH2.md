# Proces weryfikacji do OAuth 2.0 w wFirma

## Krok 1: Weryfikacja firmy (wymagana przed OAuth 2.0)

Aby móc używać OAuth 2.0, Twoja firma musi być najpierw zweryfikowana w systemie wFirma.

### Jak zweryfikować firmę:

1. **Zaloguj się do wFirma.pl**
   - Wejdź na https://wfirma.pl
   - Zaloguj się na swoje konto

2. **Przejdź do ustawień weryfikacji:**
   - W menu wybierz: **Ustawienia** → **Moja firma** → **Weryfikacja**
   - Lub bezpośrednio: https://wfirma.pl/ustawienia/weryfikacja

3. **Rozpocznij proces weryfikacji:**
   - Kliknij przycisk **"Zweryfikuj"** lub **"Rozpocznij weryfikację"**

4. **Dokonaj przelewu weryfikacyjnego:**
   - System wyświetli dane do przelewu weryfikacyjnego
   - Wykonaj **jednorazowy przelew** na podane konto
   - Kwota przelewu jest symboliczna (zwykle kilka groszy)
   - W tytule przelewu wpisz kod weryfikacyjny podany przez system

5. **Czekaj na potwierdzenie:**
   - Weryfikacja może zająć kilka dni roboczych
   - Status weryfikacji możesz sprawdzić w panelu: **Ustawienia → Moja firma → Weryfikacja**
   - Po weryfikacji otrzymasz powiadomienie e-mailem

### Co jeśli firma jest już zweryfikowana?

- Jeśli Twoja firma jest już zweryfikowana, możesz od razu przejść do **Kroku 2**
- Sprawdź status w: **Ustawienia → Moja firma → Weryfikacja**

---

## Krok 2: Rejestracja aplikacji OAuth 2.0

Po weryfikacji firmy możesz zarejestrować aplikację OAuth 2.0.

### Jak dodać aplikację OAuth 2.0:

1. **Zaloguj się do wFirma.pl**

2. **Przejdź do ustawień aplikacji:**
   - W menu wybierz: **Ustawienia** → **Bezpieczeństwo** → **Aplikacje**
   - Kliknij na zakładkę **"Aplikacje OAuth 2.0"**

3. **Dodaj nową aplikację:**
   - Kliknij przycisk **"Dodaj"** lub **"Utwórz nową aplikację"**

4. **Wypełnij formularz:**

   **a) Nazwa aplikacji:**
   ```
   API_V1
   ```
   (lub dowolna nazwa Twojej aplikacji)

   **b) Zakres (scope):**
   ```
   invoices-read,invoices-write,contractors-read,contractors-write
   ```
   (zobacz `OAUTH2_SCOPES.md` dla szczegółów)

   **c) Adres zwrotny (redirect_uri):**
   ```
   http://localhost:8000
   ```
   (lub adres Twojej aplikacji produkcyjnej)

   **d) Adres IP klienta:**
   ```
   185.123.45.67
   ```
   (Twój publiczny adres IP - zobacz `JAK_sprawdzic_IP.md`)

5. **Zapisz formularz:**
   - Kliknij przycisk **"Zapisz"**
   - System wygeneruje **Client ID** i **Client Secret**

6. **Zapisz klucze:**
   - ⚠️ **Client Secret jest wyświetlany tylko raz!**
   - Zapisz go natychmiast w bezpiecznym miejscu
   - Będziesz potrzebował tych kluczy do autoryzacji OAuth 2.0

---

## Krok 3: Weryfikacja aplikacji przez wFirma (jeśli wymagana)

Niektóre aplikacje mogą wymagać dodatkowej weryfikacji przez wFirma:

1. **Sprawdź status aplikacji:**
   - W panelu: **Ustawienia → Bezpieczeństwo → Aplikacje OAuth 2.0**
   - Status może być: "Oczekuje na weryfikację", "Zweryfikowana", "Odrzucona"

2. **Jeśli wymagana weryfikacja:**
   - Poczekaj na weryfikację przez zespół wFirma
   - Może to zająć kilka dni roboczych
   - Otrzymasz powiadomienie e-mailem o statusie weryfikacji

3. **Kontakt z wFirma (jeśli potrzebny):**
   - Jeśli masz pytania, skontaktuj się przez: https://wfirma.pl/kontakt
   - W formularzu podaj informacje o swojej aplikacji i celu integracji

---

## Podsumowanie - co potrzebujesz:

### Przed rozpoczęciem:
- ✅ Zweryfikowana firma w wFirma (przelew weryfikacyjny)
- ✅ Konto w wFirma z dostępem do ustawień

### Po rejestracji aplikacji:
- ✅ **Client ID** - identyfikator aplikacji
- ✅ **Client Secret** - tajny klucz aplikacji (zapisz bezpiecznie!)
- ✅ **Redirect URI** - adres zwrotny Twojej aplikacji
- ✅ **Scopes** - zakresy uprawnień

### Do implementacji OAuth 2.0:
- ✅ Endpoint autoryzacji: `https://api2.wfirma.pl/oauth2/authorize`
- ✅ Endpoint tokena: `https://api2.wfirma.pl/oauth2/token`
- ✅ Client ID i Client Secret

---

## Gdzie napisać do wFirma?

### Kontakt z wFirma:

1. **Formularz kontaktowy:**
   - https://wfirma.pl/kontakt
   - Wypełnij formularz z pytaniem o weryfikację lub OAuth 2.0

2. **E-mail:**
   - Sprawdź na stronie wFirma aktualny adres e-mail wsparcia

3. **Telefon:**
   - Sprawdź na stronie wFirma aktualny numer telefonu wsparcia

### Co napisać w formularzu kontaktowym?

**Przykładowa wiadomość:**

```
Temat: Weryfikacja aplikacji OAuth 2.0

Witam,

Chciałbym zweryfikować moją aplikację OAuth 2.0 w systemie wFirma.

Nazwa aplikacji: API_V1
Cel integracji: Automatyczne wystawianie i wysyłanie faktur
Zakres uprawnień: invoices-read, invoices-write, contractors-read, contractors-write

Proszę o informację, czy wymagana jest dodatkowa weryfikacja aplikacji.

Pozdrawiam,
[Twoje imię i nazwisko]
[Twoja firma]
```

---

## Często zadawane pytania:

### Q: Czy weryfikacja firmy jest obowiązkowa?
**A:** Tak, weryfikacja firmy jest wymagana przed użyciem OAuth 2.0.

### Q: Ile kosztuje weryfikacja?
**A:** Weryfikacja jest bezpłatna - wykonujesz symboliczny przelew (kilka groszy) w celu potwierdzenia danych.

### Q: Jak długo trwa weryfikacja firmy?
**A:** Zwykle kilka dni roboczych po wykonaniu przelewu.

### Q: Czy mogę użyć OAuth 2.0 bez weryfikacji?
**A:** Nie, weryfikacja firmy jest wymagana.

### Q: Co jeśli moja firma jest już zweryfikowana?
**A:** Możesz od razu przejść do rejestracji aplikacji OAuth 2.0 (Krok 2).

### Q: Czy każda aplikacja wymaga osobnej weryfikacji?
**A:** Nie, weryfikacja firmy jest jednorazowa. Możesz zarejestrować wiele aplikacji OAuth 2.0 po weryfikacji firmy.

---

## Następne kroki:

Po zakończeniu weryfikacji i rejestracji aplikacji:

1. ✅ Masz Client ID i Client Secret
2. ✅ Możesz zaimplementować flow OAuth 2.0 w swojej aplikacji
3. ✅ Zobacz dokumentację API: https://doc.wfirma.pl/

