# 🚀 Instrukcja Uruchomienia Produkcyjnego - Googie GUS

## 📋 Spis Treści
1. [Przygotowanie](#przygotowanie)
2. [Konfiguracja Środowiskowa](#konfiguracja-środowiskowa)
3. [Instalacja Zależności](#instalacja-zależności)
4. [Uruchomienie Lokalne](#uruchomienie-lokalne)
5. [Deployment na GCP Cloud Run](#deployment-na-gcp-cloud-run)
6. [Konfiguracja Zoho CRM](#konfiguracja-zoho-crm)
7. [Weryfikacja Działania](#weryfikacja-działania)
8. [Troubleshooting](#troubleshooting)

---

## 1. Przygotowanie

### Wymagania
- **Node.js** >= 14.x
- **npm** >= 6.x
- **Klucz API GUS** (https://api.stat.gov.pl/Home/RegonApi)
- **Konto GCP** (do deployment na Cloud Run)
- **Zoho CRM** z uprawnieniami Developer

### Checklist przed startem
- [ ] Uzyskano klucz API GUS (produkcyjny)
- [ ] Zainstalowano Node.js i npm
- [ ] Konto GCP skonfigurowane (opcjonalnie, jeśli deployment)
- [ ] Zoho CRM Developer Space dostępny

---

## 2. Konfiguracja Środowiskowa

### Zmienne środowiskowe

Stwórz plik `.env` w katalogu głównym projektu (skopiuj z `ENV_EXAMPLE.txt`):

```bash
# Tryb produkcyjny
NODE_ENV=production

# Port (opcjonalnie, domyślnie 5000)
PORT=5000

# Klucz API GUS - PRODUKCYJNY (nie testowy!)
GUS_API_KEY=twoj_produkcyjny_klucz_tutaj

# NIE używaj środowiska testowego GUS w produkcji
GUS_USE_TEST=false
```

**WAŻNE:** 
- W produkcji ZAWSZE używaj prawdziwego klucza API GUS
- Testowy klucz `abcde12345abcde12345` działa tylko z testowymi danymi

---

## 3. Instalacja Zależności

```bash
# Sklonuj repozytorium (jeśli jeszcze nie masz)
git clone <repo-url>
cd Googie_GUS

# Zainstaluj wszystkie zależności
npm install
```

**Nowe zależności (po naprawach bezpieczeństwa):**
- `express-rate-limit@6.7.0` - Rate limiting (100 req/15min/IP)

---

## 4. Uruchomienie Lokalne

### Windows
```bash
# Tryb produkcyjny
npm run start:windows

# Tryb development (verbose logging)
npm run dev:windows
```

### Linux / macOS
```bash
# Tryb produkcyjny
npm start

# Tryb development (verbose logging)
npm run dev
```

### Sprawdzenie czy działa
1. Otwórz http://127.0.0.1:5000
2. Powinieneś zobaczyć listę plików
3. Przejdź do http://127.0.0.1:5000/app/widget.html
4. Widget się załaduje (może wyświetlić błąd braku kontekstu - to OK lokalnie)

**Konsola powinna pokazać:**
```
========================================
Googie GUS Backend uruchomiony
========================================
Port: 5000
Środowisko: production
Rate limiting: 100 req/15min/IP
CORS: Tylko Zoho CRM domeny
HTTPS redirect: AKTYWNY
Logging: production (combined)
========================================
```

---

## 5. Deployment na GCP Cloud Run

### Krok 1: Instalacja Google Cloud SDK
```bash
# Sprawdź czy masz gcloud
gcloud --version

# Jeśli nie, zainstaluj: https://cloud.google.com/sdk/docs/install
```

### Krok 2: Logowanie i konfiguracja projektu
```bash
# Zaloguj się
gcloud auth login

# Ustaw projekt (jeśli masz wiele projektów)
gcloud config set project your-project-id

# Włącz Cloud Run API
gcloud services enable run.googleapis.com
```

### Krok 3: Deploy
```bash
# Z katalogu głównego projektu
gcloud run deploy googie-gus-backend \
  --source . \
  --platform managed \
  --region europe-central2 \
  --allow-unauthenticated \
  --set-env-vars NODE_ENV=production,GUS_API_KEY=twoj_klucz_tutaj \
  --min-instances 0 \
  --max-instances 10 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 60
```

**Wyjaśnienie parametrów:**
- `--source .` - deploy z lokalnego kodu
- `--region europe-central2` - Frankfurt (najbliżej Polski)
- `--allow-unauthenticated` - publiczny dostęp (widget Zoho potrzebuje)
- `--set-env-vars` - zmienne środowiskowe
- `--min-instances 0` - skalowanie do 0 gdy brak ruchu (tańsze)
- `--max-instances 10` - max 10 instancji
- `--memory 512Mi` - 512MB RAM (wystarczy)
- `--timeout 60` - 60s timeout (GUS może być wolny)

### Krok 4: Skopiuj URL
Po pomyślnym deploy zobaczysz:
```
Service URL: https://googie-gus-backend-xxxxx-ew.a.run.app
```

**Skopiuj ten URL** - będzie potrzebny w Zoho CRM.

### Krok 5: Weryfikacja
```bash
# Test endpointu (z testowym NIPem)
curl -X POST https://your-backend-url.run.app/api/gus/name-by-nip \
  -H "Content-Type: application/json" \
  -H "x-gus-api-key: twoj_klucz" \
  -d '{"nip":"5250001009"}'
```

Powinno zwrócić dane firmy w JSON.

---

## 6. Konfiguracja Zoho CRM

### Krok 1: Ustaw Organization Variables

1. Zaloguj się do Zoho CRM
2. Przejdź: **Setup → Developer Space → Organization Variables**
3. Kliknij **+ New Variable** i dodaj następujące zmienne:

| Nazwa zmiennej | Typ | Wartość | Opis |
|----------------|-----|---------|------|
| `GUS_API_KEY` | String | `twoj_produkcyjny_klucz` | Klucz API GUS |
| `GUS_BACKEND_URL` | String | `https://your-backend.run.app` | URL Cloud Run (BEZ `/api/gus/`) |
| `ZOHO_CRM_BASE_URL` | String | `https://crm.zoho.eu` | Twoja domena CRM (.eu / .com / .in) |
| `ZOHO_ORG_ID` | String | `org20101283812` | ID twojej organizacji (z URL CRM) |
| `BRAND_LOGO_URL` | String | `MD_favicon.png` | URL logo (opcjonalne) |

**Jak znaleźć ZOHO_ORG_ID:**
- Otwórz dowolny rekord w Zoho CRM
- Spójrz na URL: `https://crm.zoho.eu/crm/org20101283812/tab/Accounts/...`
- `org20101283812` to Twoje ZOHO_ORG_ID

### Krok 2: Zainstaluj/Zaktualizuj Widget

1. Przejdź: **Setup → Developer Space → Widgets**
2. Znajdź widget **Googie GUS** (jeśli istnieje) lub kliknij **+ New Widget**
3. Upload pliku `dist/Googie_GUS.zip` (jeśli masz) lub skonfiguruj hosting:
   - **Hosting:** Zoho lub External
   - **URL:** Jeśli external, podaj URL do `widget.html`

### Krok 3: Dodaj Widget do Modułu Accounts

1. Przejdź: **Setup → Customization → Modules and Fields → Accounts**
2. Kliknij **Links & Buttons**
3. Dodaj **Button** lub **Related List Widget**:
   - **Widget:** Googie GUS
   - **Location:** Button (Detail View)
   - **Label:** "Pobierz dane z GUS"

### Krok 4: Test w Zoho CRM

1. Otwórz dowolny rekord w **Accounts**
2. Powinieneś zobaczyć przycisk **"Pobierz dane z GUS"**
3. Kliknij przycisk → widget się otworzy
4. Wpisz NIP (np. `5250001009`)
5. Kliknij **"Pobierz dane z GUS"**
6. Dane firmy powinny się pobrać i wyświetlić

---

## 7. Weryfikacja Działania

### Test 1: Rate Limiting
```bash
# Wyślij 101 requestów szybko
for i in {1..101}; do 
  curl -X POST https://your-backend.run.app/api/gus/name-by-nip \
    -H "Content-Type: application/json" \
    -H "x-gus-api-key: key" \
    -d '{"nip":"5250001009"}'
done
```
**Oczekiwany rezultat:** 101. request zwróci HTTP 429 "Zbyt wiele zapytań"

### Test 2: CORS
```bash
# Request z niedozwolonej domeny
curl -H "Origin: https://evil.com" \
  https://your-backend.run.app/api/gus/name-by-nip
```
**Oczekiwany rezultat:** Brak nagłówka `Access-Control-Allow-Origin` w odpowiedzi

### Test 3: HTTPS Redirect (tylko jeśli NODE_ENV=production)
```bash
# Request HTTP (jeśli backend ma publiczny HTTP)
curl -I http://your-backend.run.app
```
**Oczekiwany rezultat:** HTTP 301 redirect na HTTPS

### Test 4: Widget w Zoho CRM
1. Otwórz rekord w Accounts
2. Kliknij "Pobierz dane z GUS"
3. Wpisz NIP: `5250001009` (Państwowa Wyższa Szkoła Zawodowa)
4. Kliknij "Pobierz dane z GUS"
5. **Oczekiwany rezultat:**
   - Spinner ładowania
   - Tabela porównania danych
   - Możliwość zapisania do CRM

---

## 8. Troubleshooting

### Problem: Backend nie startuje lokalnie
**Objaw:** Błąd `EADDRINUSE` lub `port already in use`

**Rozwiązanie:**
```bash
# Windows
netstat -ano | findstr :5000
taskkill /PID <pid> /F

# Linux/Mac
lsof -i :5000
kill -9 <pid>

# Lub zmień port
PORT=3000 npm start
```

### Problem: "Brak klucza GUS_API_KEY"
**Objaw:** HTTP 400 przy wywołaniu API

**Rozwiązanie:**
1. Sprawdź czy plik `.env` istnieje i zawiera `GUS_API_KEY=...`
2. Jeśli deployment: sprawdź zmienne środowiskowe w GCP
   ```bash
   gcloud run services describe googie-gus-backend --region europe-central2 --format="value(spec.template.spec.containers[0].env)"
   ```

### Problem: CORS error w widgecie
**Objaw:** `Access to fetch has been blocked by CORS policy`

**Rozwiązanie:**
1. Sprawdź czy Twoja domena Zoho jest na whiteliście w `server/index.js:67`
2. Dodaj brakującą domenę (np. `https://crm.zoho.com.au`)
3. Redeploy backend

### Problem: Timeout (przekroczono 30s)
**Objaw:** `Przekroczono limit czasu oczekiwania na odpowiedź z serwera (30s)`

**Rozwiązanie:**
1. GUS może być wolny - zwiększ timeout w `app/js/gus-client.js:34` do 60s
2. Sprawdź logi GCP: `gcloud run services logs read googie-gus-backend`
3. Może być problem z kluczem API GUS - sprawdź czy jest ważny

### Problem: "GUS nie znalazł podmiotu dla podanego NIP"
**Objaw:** HTTP 404 po wyszukaniu NIP

**Możliwe przyczyny:**
1. NIP faktycznie nie istnieje w bazie GUS
2. Używasz testowego klucza (`abcde12345abcde12345`) - działa tylko z testowymi NIPami
3. NIP ma błędną sumę kontrolną

**Rozwiązanie:**
1. Sprawdź NIP na https://wyszukiwarkaregon.stat.gov.pl/appBIR/index.aspx
2. Użyj produkcyjnego klucza API
3. Widget automatycznie waliduje sumę kontrolną - czerwony status = błędny NIP

### Problem: Rate limiting blokuje użytkowników
**Objaw:** Użytkownicy zgłaszają "Zbyt wiele zapytań"

**Rozwiązanie:**
1. Zwiększ limit w `server/index.js:69` z 100 na 200-300
2. Sprawdź logi - może być atak DDoS
3. Jeśli użytkownicy pracują za tym samym NAT, zwiększ limit

---

## 📊 Monitoring

### Logi GCP Cloud Run
```bash
# Ostatnie 50 linii
gcloud run services logs read googie-gus-backend --limit 50 --region europe-central2

# Streaming (na żywo)
gcloud run services logs tail googie-gus-backend --region europe-central2
```

### Metryki w GCP Console
1. Przejdź: https://console.cloud.google.com/run
2. Wybierz serwis `googie-gus-backend`
3. Zakładka **Metrics**:
   - Request count
   - Request latency
   - Container instance count
   - Memory/CPU utilization

---

## 🔒 Bezpieczeństwo

### Wprowadzone zabezpieczenia (2025-11-08):
✅ **XSS Protection** - wszystkie dane sanityzowane przed wyświetleniem  
✅ **SOAP Injection Protection** - dane escapowane przed wstawieniem do XML  
✅ **Rate Limiting** - 100 req/15min/IP  
✅ **CORS Restriction** - tylko Zoho domeny  
✅ **Input Validation** - maksymalna długość NIP/REGON  
✅ **Timeout Protection** - 30s dla fetch, abort dla SOAP  
✅ **HTTPS Enforcement** - redirect w produkcji  
✅ **Content-Type Validation** - tylko JSON dla POST  

### Best Practices:
- **NIE** hardcoduj klucza API w kodzie
- **NIE** commituj pliku `.env` do gita (jest w `.gitignore`)
- **NIE** udostępniaj logów z kluczami API
- **TAK** regularnie rotuj klucz API GUS
- **TAK** monitoruj logi pod kątem nietypowych requestów

---

## 📞 Wsparcie

### Kontakt
- **Dokumentacja GUS API:** https://api.stat.gov.pl/Home/RegonApi
- **Zoho CRM Widgets:** https://www.zoho.com/crm/developer/docs/widgets/
- **GCP Cloud Run:** https://cloud.google.com/run/docs

### Przydatne komendy
```bash
# Status serwisu w GCP
gcloud run services describe googie-gus-backend --region europe-central2

# Aktualizacja zmiennych środowiskowych (bez redeploy)
gcloud run services update googie-gus-backend \
  --region europe-central2 \
  --update-env-vars GUS_API_KEY=new_key

# Rollback do poprzedniej wersji
gcloud run services update-traffic googie-gus-backend \
  --region europe-central2 \
  --to-revisions PREVIOUS=100

# Usuń serwis (jeśli chcesz)
gcloud run services delete googie-gus-backend --region europe-central2
```

---

**Ostatnia aktualizacja:** 2025-11-08  
**Wersja:** 1.0 (Production Ready)  
**Autor:** Digital Unity / AI Assistant

