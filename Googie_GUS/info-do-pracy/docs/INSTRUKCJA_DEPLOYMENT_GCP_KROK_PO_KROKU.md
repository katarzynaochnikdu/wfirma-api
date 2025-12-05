# 📘 KOMPLETNA INSTRUKCJA: Jak zalogować się i zdeployować backend na GCP

**Wersja:** 2.0 - FULL DATA (PKD, formy prawne, jednostki lokalne)  
**Data:** 2025-11-13

---

## 📋 SPIS TREŚCI
1. [Instalacja Google Cloud SDK](#1-instalacja-google-cloud-sdk)
2. [Logowanie do GCP](#2-logowanie-do-gcp)
3. [Konfiguracja projektu](#3-konfiguracja-projektu)
4. [Deployment (2 metody)](#4-deployment)
5. [Weryfikacja](#5-weryfikacja)
6. [Troubleshooting](#6-troubleshooting)

---

## 1. INSTALACJA GOOGLE CLOUD SDK

### Windows

#### Opcja A: Instalator (ZALECANE)
1. Pobierz: https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe
2. Uruchom instalator
3. Podczas instalacji zaznacz:
   - ✅ "Run gcloud init after installation"
   - ✅ "Install bundled Python"
4. Zrestartuj PowerShell/CMD

#### Opcja B: Chocolatey
```bash
choco install gcloudsdk
```

### Linux / macOS

```bash
# macOS (Homebrew)
brew install google-cloud-sdk

# Linux (Ubuntu/Debian)
sudo apt-get install google-cloud-sdk

# Linux (manual)
curl https://sdk.cloud.google.com | bash
exec -l $SHELL
```

### Weryfikacja instalacji
```bash
gcloud --version
```

**Oczekiwany output:**
```
Google Cloud SDK 456.0.0
bq 2.0.101
core 2024.11.08
gcloud-crc32c 1.0.0
gsutil 5.28
```

---

## 2. LOGOWANIE DO GCP

### Krok 1: Uruchom proces logowania

```bash
gcloud auth login
```

**Co się stanie:**
1. Otworzy się przeglądarka
2. Zobaczysz stronę logowania Google
3. Zaloguj się kontem Google (które ma dostęp do GCP)
4. Zatwierdź uprawnienia dla Google Cloud SDK

**W terminalu zobaczysz:**
```
You are now logged in as [your-email@gmail.com]
Your current project is [your-project-id].
```

### Krok 2: Sprawdź czy jesteś zalogowany

```bash
gcloud auth list
```

**Oczekiwany output:**
```
        Credentialed Accounts
ACTIVE  ACCOUNT
*       your-email@gmail.com
```

---

## 3. KONFIGURACJA PROJEKTU

### Opcja A: Masz już projekt GCP

Jeśli masz projekt (np. z GCP Console), ustaw go:

```bash
# Lista wszystkich projektów
gcloud projects list

# Ustaw aktywny projekt
gcloud config set project your-project-id
```

### Opcja B: Tworzysz nowy projekt

```bash
# Utwórz projekt (PROJECT_ID musi być unikalny globalnie)
gcloud projects create googie-gus-prod --name="Googie GUS Production"

# Ustaw jako aktywny
gcloud config set project googie-gus-prod

# Włącz billing (WYMAGANE dla Cloud Run)
# Przejdź do: https://console.cloud.google.com/billing
# Podłącz projekt do konta billing
```

### Sprawdź konfigurację

```bash
gcloud config list
```

**Oczekiwany output:**
```
[core]
account = your-email@gmail.com
project = your-project-id

Your active configuration is: [default]
```

---

## 4. DEPLOYMENT

Masz **2 opcje**: automatyczny skrypt lub ręczny deployment.

---

### OPCJA A: Automatyczny skrypt (ZALECANE) 🚀

#### Windows (PowerShell):

```powershell
# W katalogu projektu (Googie_GUS)
cd C:\Users\kochn\Widget\Googie_GUS

# Uruchom skrypt deployment
.\deploy-gcp-full.ps1
```

**Skrypt zapyta o:**
1. PROJECT_ID (jeśli nie ustawiony)
2. GUS_API_KEY (produkcyjny klucz)
3. Potwierdzenie deployment (y/n)

#### Linux / macOS (Bash):

```bash
# W katalogu projektu
cd ~/Googie_GUS

# Nadaj uprawnienia wykonywania
chmod +x deploy-gcp-full.sh

# Uruchom skrypt
./deploy-gcp-full.sh
```

**Skrypt automatycznie:**
- ✅ Sprawdzi czy gcloud jest zainstalowany
- ✅ Wykryje aktywny projekt GCP
- ✅ Zapyta o GUS_API_KEY
- ✅ Wykona deployment
- ✅ Pokaże URL serwisu

---

### OPCJA B: Ręczny deployment (krok po kroku)

#### Krok 1: Włącz Cloud Run API

```bash
gcloud services enable run.googleapis.com
```

#### Krok 2: Deployment

**Windows:**
```powershell
gcloud run deploy googie-gus-backend `
  --source . `
  --platform managed `
  --region europe-central2 `
  --allow-unauthenticated `
  --set-env-vars "NODE_ENV=production,GUS_API_KEY=TWOJ_KLUCZ_TUTAJ" `
  --min-instances 0 `
  --max-instances 10 `
  --memory 512Mi `
  --cpu 1 `
  --timeout 60
```

**Linux/macOS:**
```bash
gcloud run deploy googie-gus-backend \
  --source . \
  --platform managed \
  --region europe-central2 \
  --allow-unauthenticated \
  --set-env-vars "NODE_ENV=production,GUS_API_KEY=TWOJ_KLUCZ_TUTAJ" \
  --min-instances 0 \
  --max-instances 10 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 60
```

**Zastąp `TWOJ_KLUCZ_TUTAJ` swoim kluczem API GUS!**

#### Krok 3: Czekaj na deployment (~2-5 minut)

Zobaczysz:
```
Building using Buildpacks...
✓ Creating Container Repository...
✓ Uploading sources...
✓ Building Container... Logs are available at [...]
✓ Creating Revision...
✓ Routing traffic...
✓ Setting IAM Policy...
Done.
Service [googie-gus-backend] revision [...] has been deployed
Service URL: https://googie-gus-backend-xxxxx-ew.a.run.app
```

#### Krok 4: Skopiuj Service URL

```bash
# Automatycznie pobierz URL
gcloud run services describe googie-gus-backend \
  --region europe-central2 \
  --format="value(status.url)"
```

**Output:**
```
https://googie-gus-backend-324648591287-ew.a.run.app
```

**SKOPIUJ TEN URL** - będzie potrzebny w Zoho CRM!

---

## 5. WERYFIKACJA

### Test 1: Podstawowy endpoint (name-by-nip)

**Windows (PowerShell):**
```powershell
$URL = "https://your-backend.run.app"
$BODY = '{"nip":"5250001009"}'

Invoke-RestMethod -Uri "$URL/api/gus/name-by-nip" `
  -Method POST `
  -Headers @{
    "Content-Type" = "application/json"
    "x-gus-api-key" = "your_key"
  } `
  -Body $BODY
```

**Linux/macOS/Windows (curl):**
```bash
curl -X POST https://your-backend.run.app/api/gus/name-by-nip \
  -H "Content-Type: application/json" \
  -H "x-gus-api-key: your_key" \
  -d '{"nip":"5250001009"}'
```

**Oczekiwany rezultat:**
```json
{
  "data": [
    {
      "regon": "000331501",
      "nip": "5250001009",
      "nazwa": "PAŃSTWOWA WYŻSZA SZKOŁA ZAWODOWA...",
      "miejscowosc": "Głogów",
      ...
    }
  ]
}
```

### Test 2: Pełny raport (WSZYSTKIE pola)

```bash
curl -X POST https://your-backend.run.app/api/gus/full-report \
  -H "Content-Type: application/json" \
  -H "x-gus-api-key: your_key" \
  -d '{"regon":"321537875"}'
```

**Oczekiwany rezultat (55+ pól!):**
```json
{
  "data": {
    "praw_regon9": "321537875",
    "praw_nip": "8513176694",
    "praw_nazwa": "DERMADENT...",
    "praw_podstawowaFormaPrawna_Symbol": "1",
    "praw_podstawowaFormaPrawna_Nazwa": "OSOBA PRAWNA",
    "praw_szczegolnaFormaPrawna_Symbol": "101",
    "praw_szczegolnaFormaPrawna_Nazwa": "SPÓŁKA KOMANDYTOWA",
    "praw_formaFinansowania_Symbol": "...",
    "praw_formaWlasnosci_Symbol": "...",
    "praw_liczbaJednLokalnych": "5",
    ... ~50 więcej pól!
  },
  "reportName": "BIR11OsPrawna",
  "fieldsCount": 57
}
```

### Test 3: Raport PKD (kody działalności)

```bash
curl -X POST https://your-backend.run.app/api/gus/full-report \
  -H "Content-Type: application/json" \
  -H "x-gus-api-key: your_key" \
  -d '{"regon":"321537875","reportName":"BIR11OsPrawnaPkd"}'
```

**Oczekiwany rezultat:**
```json
{
  "data": {
    "pkdList": [
      {
        "praw_pkdKod": "86.23.Z",
        "praw_pkdNazwa": "Praktyka lekarska dentystyczna",
        "praw_pkdPrzewazajace": "1"
      },
      {
        "praw_pkdKod": "47.73.Z",
        "praw_pkdNazwa": "Sprzedaż detaliczna...",
        "praw_pkdPrzewazajace": "0"
      }
    ],
    "pkdCount": 2
  },
  "reportName": "BIR11OsPrawnaPkd",
  "fieldsCount": 2
}
```

### Test 4: Jednostki lokalne

```bash
curl -X POST https://your-backend.run.app/api/gus/full-report \
  -H "Content-Type: application/json" \
  -H "x-gus-api-key: your_key" \
  -d '{"regon":"321537875","reportName":"BIR11OsPrawnaListaJednLokalnych"}'
```

**Oczekiwany rezultat:**
```json
{
  "data": {
    "jednostkiLokalne": [
      {
        "praw_regon14JednLokalnej": "32153787500012",
        "praw_adSiedzNazwaMiejscowosci": "Szczecin",
        "praw_adSiedzNazwaUlicy": "Kazimierza Królewicza",
        "praw_numerNieruchomosci": "2L",
        "praw_numerLokalu": "1"
      },
      ... więcej jednostek
    ],
    "jednostkiCount": 5
  },
  "reportName": "BIR11OsPrawnaListaJednLokalnych",
  "fieldsCount": 5
}
```

### Test 5: Sprawdź logi GCP

```bash
# Logi na żywo
gcloud run services logs tail googie-gus-backend --region europe-central2

# Ostatnie 100 linii
gcloud run services logs read googie-gus-backend --region europe-central2 --limit 100
```

**Czego szukać w logach:**
```
✅ [GUS full-report REQUEST] REGON: 321537875 reportName: BIR11OsPrawnaPkd
✅ [GUS] Używam custom reportName: BIR11OsPrawnaPkd
✅ [GUS DEBUG] PKD Report: BIR11OsPrawnaPkd
✅ [GUS DEBUG] PKD - sparsowano 3 kodów PKD
✅ [GUS DEBUG] PKD - dane (pierwsze 2000 znaków): [{"praw_pkdKod":"86.23.Z",...}]
```

---

## 6. TROUBLESHOOTING

### Problem: "gcloud: command not found"

**Rozwiązanie:**
- **Windows:** Zrestartuj PowerShell/CMD po instalacji
- **Linux/Mac:** Wykonaj: `exec -l $SHELL` lub dodaj do PATH:
  ```bash
  echo 'source /path/to/google-cloud-sdk/path.bash.inc' >> ~/.bashrc
  source ~/.bashrc
  ```

### Problem: "You do not currently have an active account selected"

**Rozwiązanie:**
```bash
gcloud auth login
# Zaloguj się w przeglądarce
```

### Problem: "Permission denied" lub "Insufficient permissions"

**Rozwiązanie:**
1. Sprawdź uprawnienia konta w GCP Console
2. Potrzebne role:
   - **Cloud Run Admin** (`roles/run.admin`)
   - **Service Account User** (`roles/iam.serviceAccountUser`)
3. Dodaj role w: https://console.cloud.google.com/iam-admin/iam

### Problem: Deployment trwa bardzo długo (>10 minut)

**Możliwe przyczyny:**
- Wolne połączenie internetowe (upload kodu)
- Duży rozmiar `node_modules/`

**Rozwiązanie:**
```bash
# Usuń node_modules przed deployment (GCP zainstaluje sam)
rm -rf node_modules

# Deploy
gcloud run deploy ...
```

### Problem: Backend zwraca HTTP 500

**Diagnoza:**
```bash
# Sprawdź szczegółowe logi
gcloud run services logs read googie-gus-backend \
  --region europe-central2 \
  --limit 50 \
  | grep -i error
```

**Możliwe przyczyny:**
- Brak zmiennej `GUS_API_KEY`
- Błąd w kodzie (sprawdź logi)

**Rozwiązanie:**
```bash
# Zaktualizuj zmienne środowiskowe
gcloud run services update googie-gus-backend \
  --region europe-central2 \
  --update-env-vars GUS_API_KEY=your_key
```

---

## 📊 CO BACKEND TERAZ ZWRACA

### Format odpowiedzi `/api/gus/full-report`

```typescript
{
  // WSZYSTKIE dane z raportu (NIE obcięte, NIE filtrowane)
  data: {
    // Raport podstawowy (OsPrawna) - 55+ pól
    "praw_regon9": string,
    "praw_nip": string,
    "praw_nazwa": string,
    "praw_podstawowaFormaPrawna_Symbol": string,
    "praw_podstawowaFormaPrawna_Nazwa": string,
    "praw_szczegolnaFormaPrawna_Symbol": string,
    "praw_szczegolnaFormaPrawna_Nazwa": string,
    "praw_formaFinansowania_Symbol": string,
    "praw_formaFinansowania_Nazwa": string,
    "praw_formaWlasnosci_Symbol": string,
    "praw_formaWlasnosci_Nazwa": string,
    "praw_organZalozycielski_Symbol": string,
    "praw_organZalozycielski_Nazwa": string,
    "praw_organRejestrowy_Symbol": string,
    "praw_organRejestrowy_Nazwa": string,
    "praw_rodzajRejestruEwidencji_Symbol": string,
    "praw_rodzajRejestruEwidencji_Nazwa": string,
    "praw_liczbaJednLokalnych": string,
    "praw_numerTelefonu": string,
    "praw_numerFaksu": string,
    "praw_adresEmail": string,
    "praw_adresStronyinternetowej": string,
    "praw_dataPowstania": string,
    "praw_dataRozpoczeciaDzialalnosci": string,
    "praw_dataWpisuDoRegon": string,
    "praw_dataZaistnieniaZmiany": string,
    ... ~35 więcej pól adresowych, dat, itp.
    
    // LUB dla PKD:
    "pkdList": [
      {
        "praw_pkdKod": "86.23.Z",
        "praw_pkdNazwa": "Praktyka lekarska dentystyczna",
        "praw_pkdPrzewazajace": "1"
      }
    ],
    "pkdCount": 3
    
    // LUB dla jednostek lokalnych:
    "jednostkiLokalne": [
      {
        "praw_regon14JednLokalnej": "32153787500012",
        "praw_adSiedzNazwaMiejscowosci": "Szczecin",
        "praw_adSiedzNazwaUlicy": "Kazimierza Królewicza",
        "praw_numerNieruchomosci": "2L",
        "praw_numerLokalu": "1",
        "praw_kodPocztowy": "71-552"
      }
    ],
    "jednostkiCount": 5
  },
  
  // Nazwa użytego raportu (ZAWSZE)
  reportName: "BIR11OsPrawna" | "BIR11OsPrawnaPkd" | "BIR11OsPrawnaListaJednLokalnych" | ...,
  
  // Liczba pól/wpisów (ZAWSZE)
  fieldsCount: 57
}
```

---

## 📋 DOKUMENTACJA PARSOWANIA

### Jak backend przetwarza dane:

#### 1. **Raport podstawowy** (BIR11OsPrawna, BIR11OsFizyczna, etc.)

**Struktura XML z GUS:**
```xml
<root>
  <dane>
    <praw_regon9>321537875</praw_regon9>
    <praw_nip>8513176694</praw_nip>
    <praw_podstawowaFormaPrawna_Symbol>1</praw_podstawowaFormaPrawna_Symbol>
    ... 50+ więcej pól
  </dane>
</root>
```

**Parsowanie (linia ~703-748):**
```javascript
var dane = parsed.root.dane[0];  // Pierwszy element tablicy

// Konwertuj WSZYSTKIE pola
var result = {};
Object.keys(dane).forEach(function(key) {
  var value = dane[key];
  
  // xml2js zwraca tablice - wyciągnij pierwszy element
  result[key] = Array.isArray(value) ? value[0] : value;
});

// result zawiera WSZYSTKIE 55+ pól, nic nie jest obcięte!
```

**Zwrócone pola (przykłady):**
- Identyfikatory: `praw_regon9`, `praw_nip`, `praw_numerWRejestrzeEwidencji`
- Formy prawne: `praw_podstawowaFormaPrawna_Symbol`, `praw_podstawowaFormaPrawna_Nazwa`, `praw_szczegolnaFormaPrawna_Symbol`, `praw_szczegolnaFormaPrawna_Nazwa`
- Finansowanie: `praw_formaFinansowania_Symbol`, `praw_formaFinansowania_Nazwa`
- Własność: `praw_formaWlasnosci_Symbol`, `praw_formaWlasnosci_Nazwa`
- Organy: `praw_organZalozycielski_Symbol`, `praw_organZalozycielski_Nazwa`, `praw_organRejestrowy_Symbol`, `praw_organRejestrowy_Nazwa`
- Rejestr: `praw_rodzajRejestruEwidencji_Symbol`, `praw_rodzajRejestruEwidencji_Nazwa`
- Kontakt: `praw_numerTelefonu`, `praw_numerFaksu`, `praw_adresEmail`, `praw_adresStronyinternetowej`
- Adres: 20+ pól adresowych
- Daty: 15+ pól dat
- **WSZYSTKO bez wyjątku!**

#### 2. **Raporty PKD** (...Pkd)

**Struktura XML z GUS:**
```xml
<root>
  <dane>
    <praw_pkdKod>86.23.Z</praw_pkdKod>
    <praw_pkdNazwa>Praktyka lekarska dentystyczna</praw_pkdNazwa>
    <praw_pkdPrzewazajace>1</praw_pkdPrzewazajace>
  </dane>
  <dane>
    <praw_pkdKod>47.73.Z</praw_pkdKod>
    <praw_pkdNazwa>Sprzedaż detaliczna...</praw_pkdNazwa>
    <praw_pkdPrzewazajace>0</praw_pkdPrzewazajace>
  </dane>
  <!-- Więcej <dane> dla każdego PKD -->
</root>
```

**Parsowanie (linia ~645-670):**
```javascript
var daneArray = parsed.root.dane;  // TABLICA!

var pkdArray = [];
for (var i = 0; i < daneArray.length; i++) {
  var pkdEntry = daneArray[i];
  var pkdItem = {};
  
  // Konwertuj każde pole
  Object.keys(pkdEntry).forEach(function(key) {
    var value = pkdEntry[key];
    pkdItem[key] = Array.isArray(value) ? value[0] : value;
  });
  
  pkdArray.push(pkdItem);  // Dodaj do tablicy
}

result.pkdList = pkdArray;        // TABLICA wszystkich PKD
result.pkdCount = pkdArray.length;
```

**Zwraca:** Tablicę obiektów z WSZYSTKIMI polami dla każdego PKD (kod, nazwa, czy przeważający, itd.)

#### 3. **Jednostki lokalne** (...ListaJednLokalnych)

**Struktura XML z GUS:**
```xml
<root>
  <dane>
    <praw_regon14JednLokalnej>32153787500012</praw_regon14JednLokalnej>
    <praw_adSiedzNazwaMiejscowosci>Szczecin</praw_adSiedzNazwaMiejscowosci>
    <praw_adSiedzNazwaUlicy>Kazimierza Królewicza</praw_adSiedzNazwaUlicy>
    ... więcej pól
  </dane>
  <dane>
    <!-- Kolejna jednostka -->
  </dane>
</root>
```

**Parsowanie (linia ~674-699):**
```javascript
var daneArray = parsed.root.dane;  // TABLICA!

var jednostkiArray = [];
for (var i = 0; i < daneArray.length; i++) {
  var jednostkaEntry = daneArray[i];
  var jednostkaItem = {};
  
  // Konwertuj WSZYSTKIE pola jednostki
  Object.keys(jednostkaEntry).forEach(function(key) {
    var value = jednostkaEntry[key];
    jednostkaItem[key] = Array.isArray(value) ? value[0] : value;
  });
  
  jednostkiArray.push(jednostkaItem);
}

result.jednostkiLokalne = jednostkiArray;
result.jednostkiCount = jednostkiArray.length;
```

**Zwraca:** Tablicę obiektów z WSZYSTKIMI polami dla każdej jednostki lokalnej

---

## 🎯 GWARANCJE

### ✅ Backend NIE OBCINA żadnych danych:
- ✅ Raporty podstawowe: **WSZYSTKIE 55+ pól** z `<dane>`
- ✅ Raporty PKD: **KAŻDY** kod PKD z tablicy `<dane>` (wszystkie pola dla każdego)
- ✅ Jednostki lokalne: **KAŻDA** jednostka z tablicy `<dane>` (wszystkie pola dla każdej)

### ✅ Backend zawsze loguje:
- ✅ Żądanie: `[GUS full-report REQUEST] REGON: ... reportName: ...`
- ✅ Wynik: `[GUS] Raport podstawowy - zwrócono 57 pól`
- ✅ DEBUG PKD: `[GUS DEBUG] PKD - sparsowano X kodów PKD`
- ✅ DEBUG jednostki: `[GUS DEBUG] Jednostki - sparsowano X jednostek`

### ✅ Odpowiedź zawsze zawiera:
- ✅ `data` - pełne dane (obiekt lub tablica)
- ✅ `reportName` - nazwa użytego raportu
- ✅ `fieldsCount` - liczba pól/wpisów

---

## 🚀 SZYBKI START (TL;DR)

### Windows:
```powershell
cd C:\Users\kochn\Widget\Googie_GUS
gcloud auth login
.\deploy-gcp-full.ps1
```

### Linux/macOS:
```bash
cd ~/Googie_GUS
gcloud auth login
chmod +x deploy-gcp-full.sh
./deploy-gcp-full.sh
```

**To tyle!** Skrypt zrobi resztę. 🎉

---

**Ostatnia aktualizacja:** 2025-11-13  
**Wersja backendu:** 2.0 (FULL DATA)  
**Autor:** Digital Unity / AI Assistant

