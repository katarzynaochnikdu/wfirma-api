# Konfiguracja zmiennych organizacyjnych w Zoho CRM

## Gdzie skonfigurować?

Zoho CRM → Setup → Developer Space → Organization Variables

## Grupa zmiennych: GOOGIE_GUS

Utwórz grupę o nazwie **GOOGIE_GUS** (lub użyj istniejącej) i dodaj następujące zmienne:

---

### 1. GUS_API_KEY

**Wartość obecna (Twoje konto):**
```
d5de276c116140e49f39
```

**Opis:**
Klucz API do systemu REGON (Usługa BIR). Pobierz z:
https://api.stat.gov.pl/Home/RegonApi

**Typ:** String  
**Wymagane:** TAK  
**Grupa:** GOOGIE_GUS

---

### 2. GUS_BACKEND_URL

**Wartość obecna (Twoje konto):**
```
https://googie-gus-backend-324648591287.europe-central2.run.app
```

**Opis:**
URL backendu GCP Cloud Run, który komunikuje się z API GUS/REGON.

**Typ:** String  
**Wymagane:** TAK  
**Grupa:** GOOGIE_GUS

**Jak wdrożyć backend na inne konto GCP:**
```powershell
gcloud run deploy googie-gus-backend --source . --region europe-central2 --platform managed --allow-unauthenticated --set-env-vars GUS_API_KEY=TWOJ_KLUCZ --memory 512Mi --timeout 60
```

---

### 3. ZOHO_CRM_BASE_URL

**Wartość obecna (Twoje konto):**
```
https://crm.zoho.eu
```

**Opis:**
Bazowy URL Twojej instancji Zoho CRM. Zależy od datacenter:
- Europa: `https://crm.zoho.eu`
- USA: `https://crm.zoho.com`
- India: `https://crm.zoho.in`
- Australia: `https://crm.zoho.com.au`
- China: `https://crm.zoho.com.cn`

**Typ:** String  
**Wymagane:** NIE (auto-detect z URL widgetu)  
**Grupa:** GOOGIE_GUS

---

### 4. ZOHO_ORG_ID

**Wartość obecna (Twoje konto):**
```
org20101283812
```

**Opis:**
ID organizacji Zoho CRM (widoczne w URL: `crm.zoho.eu/crm/ORG_ID/...`)

**Typ:** String  
**Wymagane:** TAK (dla linków do rekordów)  
**Grupa:** GOOGIE_GUS

**Jak znaleźć:**
1. Zaloguj się do Zoho CRM
2. Otwórz dowolny rekord
3. Zobacz URL: `https://crm.zoho.eu/crm/org20101283812/tab/Accounts/123...`
4. Skopiuj część `org20101283812`

---

### 5. BRAND_LOGO_URL

**Wartość obecna (Twoje konto):**
```
MD_favicon.png
```

**Opis:**
Nazwa pliku logo brandu (wyświetlanego w nagłówku widgetu).
Plik musi znajdować się w katalogu `app/` obok `widget.html`.

**Typ:** String  
**Wymagane:** NIE (domyślnie MD_favicon.png)  
**Grupa:** GOOGIE_GUS

**Przykłady:**
- `MD_favicon.png` (Medidesk)
- `logo-firma.png` (własne logo)
- `brand-icon.svg` (SVG też działa)

**Logo stałe (nie zmienne):**
`DU_favicon.png` - logo Digital Unity (zawsze widoczne w rogu)

---

## Jak dodać zmienne w Zoho?

1. Setup → Developer Space → Organization Variables
2. Kliknij "New Variable"
3. Wypełnij:
   - **Variable Name:** (np. GUS_API_KEY)
   - **Variable Value:** (wartość z tabeli powyżej)
   - **Group:** GOOGIE_GUS
4. Kliknij "Save"
5. Powtórz dla wszystkich 5 zmiennych

---

## Migracja na inne konto Zoho/GCP

### Krok 1: Wdróż backend na GCP (nowe konto)
```powershell
gcloud run deploy googie-gus-backend --source . --region europe-central2 --platform managed --allow-unauthenticated --set-env-vars GUS_API_KEY=NOWY_KLUCZ_GUS --memory 512Mi --timeout 60
```

Skopiuj URL serwisu (np. `https://googie-gus-backend-XXXXX.run.app`)

### Krok 2: Skonfiguruj Org Variables w nowym Zoho

Dodaj 5 zmiennych (jak w tabeli powyżej), zmieniając wartości na nowe:
- `GUS_API_KEY` → nowy klucz GUS
- `GUS_BACKEND_URL` → nowy URL z kroku 1
- `ZOHO_CRM_BASE_URL` → odpowiedni datacenter (.eu / .com / .in)
- `ZOHO_ORG_ID` → nowy org ID (z URL CRM)
- `BRAND_LOGO_URL` → nazwa pliku logo (opcjonalnie)

### Krok 3: Wgraj widget

```powershell
zet pack
```

Upload `dist/Googie_GUS.zip` do Connected Apps w nowym Zoho.

### Krok 4: Test

Otwórz widget w rekordzie Accounts, wpisz NIP i kliknij "Pobierz dane z GUS".

---

## Troubleshooting

### Widget pokazuje błąd "GUS_BACKEND_URL nie został skonfigurowany"
→ Dodaj zmienną `GUS_BACKEND_URL` w Org Variables

### Widget pokazuje błąd "Nie udało się pobrać GUS_API_KEY"
→ Dodaj zmienną `GUS_API_KEY` w Org Variables

### Linki do rekordów nie działają
→ Ustaw `ZOHO_ORG_ID` w Org Variables

### Backend zwraca 404/502
→ Sprawdź czy backend na GCP działa:
```powershell
gcloud run services list --region europe-central2
```

---

**Wersja:** 1.0 (modułowa)  
**Data:** 2025-11-07

