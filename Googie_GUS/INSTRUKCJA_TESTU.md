# Instrukcja testowania widgetu GUS (wersja modułowa)

## ✅ Co już działa (z logów):

1. **Wszystkie moduły załadowane** - brak błędów JavaScript
2. **Zmienne organizacyjne pobrane** - wszystkie 5 zmiennych OK
3. **Backend GCP działa** - HTTP 200, dane pobrane
4. **Parsowanie danych GUS** - firma rozpoznana

---

## 🧪 Scenariusze do przetestowania

### Test 1: NOWY REKORD (CreateOrCloneView)

**Kroki:**
1. Otwórz Accounts → "Create Account"
2. Uzupełnij pole "Adres_w_rekordzie" → wybierz "Siedziba" lub "Siedziba i Filia"
3. Kliknij przycisk widgetu GUS (jeśli dostępny w Create View)
4. Wpisz NIP (np. `4960254888`)
5. Kliknij "Pobierz dane z GUS"
6. Zaznacz pola do wypełnienia
7. Kliknij "Zapisz dane"

**Oczekiwany rezultat:**
- Widget wypełni pola formularza
- Widget zamknie się automatycznie
- Formularz pozostanie otwarty z wypełnionymi polami
- Zapisz rekord ręcznie (Save button w CRM)

---

### Test 2: ISTNIEJĄCY REKORD (DetailView)

**Kroki:**
1. Otwórz istniejący rekord Accounts
2. Kliknij przycisk widgetu GUS
3. Wpisz NIP (np. `5250001009`)
4. Kliknij "Pobierz dane z GUS"
5. Zaznacz/odznacz pola
6. Kliknij "Zapisz dane"
7. W modalu wpisz nazwę zwyczajową (opcjonalnie)
8. Kliknij "Zapisz nazwę i Zakończ"

**Oczekiwany rezultat:**
- Dane zapisane od razu do rekordu
- Modal sukcesu
- Po kliknięciu "Zamknij" - widget się zamyka
- Rekord odświeżony z nowymi danymi

---

### Test 3: DUPLIKAT NIP

**Kroki:**
1. Otwórz rekord lub utwórz nowy
2. Wpisz NIP który już istnieje w systemie (z cechą "Siedziba")
3. Kliknij "Pobierz dane"

**Oczekiwany rezultat:**
- Modal błędu z nazwą duplikatu
- Przycisk "Otwórz rekord" → otwiera duplikat w nowej karcie
- Link do rekordu używa zmiennych organizacyjnych (ZOHO_CRM_BASE_URL + ZOHO_ORG_ID)

---

### Test 4: ZMIENNE ORGANIZACYJNE

**Sprawdź w logach (przycisk LOG):**
```
[CONFIG] GUS_API_KEY: d5de...9f39
[CONFIG] GUS_BACKEND_URL: https://googie-gus-backend-324648591287...
[CONFIG] ZOHO_CRM_BASE_URL: https://crm.zoho.eu
[CONFIG] ZOHO_ORG_ID: org20101283812
[CONFIG] BRAND_LOGO_URL: MD_favicon.png
```

Wszystkie powinny być załadowane.

---

### Test 5: LOGO BRANDU

**Zmień logo:**
1. Setup → Org Variables → BRAND_LOGO_URL → zmień na `DU_favicon.png`
2. Odśwież widget
3. Logo w nagłówku powinno się zmienić

---

## ⚠️ Co sprawdzić jeśli coś nie działa

### 1. Console przeglądarki (F12)
Sprawdź czy są błędy JavaScript (czerwone linie). Jeśli tak - skopiuj i wyślij.

### 2. Panel LOG w widgecie
Kliknij "LOG" w prawym dolnym rogu i sprawdź:
- Czy wszystkie zmienne organizacyjne się załadowały
- Gdzie dokładnie występuje błąd

### 3. Typowe problemy

**"ZOHO is not defined"** lub **"CONFIG is not defined"**
→ Kolejność ładowania skryptów - sprawdź czy w widget.html są wszystkie `<script src="js/...">` w dobrej kolejności

**"GUS_BACKEND_URL nie został skonfigurowany"**
→ Dodaj zmienną w Org Variables (grupa GOOGIE_GUS)

**Dane nie zapisują się w nowym rekordzie**
→ Sprawdź logi - czy wywołana jest funkcja `populateAndClose`

**Linki do duplikatów 404**
→ Sprawdź czy ZOHO_ORG_ID jest poprawne (z URL CRM)

---

## 📝 Twoje obecne wartości Org Variables

Dodaj w Setup → Organization Variables → **Grupa: GOOGIE_GUS**:

```
GUS_API_KEY = d5de276c116140e49f39
GUS_BACKEND_URL = https://googie-gus-backend-324648591287.europe-central2.run.app
ZOHO_CRM_BASE_URL = https://crm.zoho.eu
ZOHO_ORG_ID = org20101283812
BRAND_LOGO_URL = MD_favicon.png
```

---

Przetestuj te 5 scenariuszy i daj znać co działa, a co nie 🎯

