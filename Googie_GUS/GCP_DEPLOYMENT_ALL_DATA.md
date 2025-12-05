# 🚀 Deployment GCP - Pełna wersja (WSZYSTKIE dane z GUS)

**Data:** 2025-11-13  
**Wersja:** 2.0 - Rozszerzona (PKD, formy prawne, jednostki lokalne)

---

## 📋 CO ZOSTAŁO ZMIENIONE

### Problem (PRZED):
```javascript
// Backend zwracał TYLKO:
{ "data": { "krs": "0000513541" } }

// Pomimo że GUS wysyłał 55+ pól!
```

### Rozwiązanie (PO):
```javascript
// Backend zwraca WSZYSTKIE pola:
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
    // ... + kolejne 50 pól!
  }
}
```

---

## ⚙️ ZMIANY W KODZIE BACKENDU

### 1. Nowy parametr `reportName` w request body

**Przed:**
```javascript
// Frontend nie mógł wybrać konkretnego raportu
POST /api/gus/full-report
{ "regon": "321537875" }
```

**Po:**
```javascript
// Frontend może żądać konkretnego raportu
POST /api/gus/full-report
{
  "regon": "321537875",
  "reportName": "BIR11OsPrawnaPkd"  // NOWE!
}
```

### 2. Whitelist dozwolonych raportów

```javascript
var allowedCustomReports = [
  // BIR11 - Osoby prawne
  'BIR11OsPrawna',                    // Podstawowe dane
  'BIR11OsPrawnaPkd',                 // Kody PKD ✨
  'BIR11OsPrawnaListaJednLokalnych',  // Lista jednostek lokalnych ✨
  
  // BIR11 - Jednostki lokalne osób prawnych
  'BIR11JednLokalnaOsPrawnej',
  'BIR11JednLokalnaOsPrawnejPkd',
  
  // BIR11 - Osoby fizyczne
  'BIR11OsFizyczna',
  'BIR11OsFizycznaPkd',
  'BIR11OsFizycznaListaJednLokalnych',
  
  // BIR11 - Jednostki lokalne osób fizycznych
  'BIR11JednLokalnaOsFizycznej',
  'BIR11JednLokalnaOsFizycznejPkd',
  
  // BIR12 (nowsze wersje - 2025+)
  'BIR12OsPrawna',
  'BIR12OsPrawnaPkd',
  'BIR12OsPrawnaListaJednLokalnych',
  'BIR12JednLokalnaOsPrawnej',
  'BIR12JednLokalnaOsPrawnejPkd',
  'BIR12OsFizyczna',
  'BIR12OsFizycznaPkd',
  'BIR12OsFizycznaListaJednLokalnych',
  'BIR12JednLokalnaOsFizycznej',
  'BIR12JednLokalnaOsFizycznejPkd'
];
```

### 3. Zwracanie WSZYSTKICH pól zamiast tylko KRS

**Przed (linia ~601):**
```javascript
var result = { krs: krs || null };  // ❌ Tylko KRS
return res.status(200).json({ data: result });
```

**Po:**
```javascript
// Konwersja WSZYSTKICH pól z XML do JSON
var result = {};
var keys = Object.keys(dane || {});

for (var i = 0; i < keys.length; i++) {
  var key = keys[i];
  var value = dane[key];
  
  // xml2js zwraca każde pole jako tablicę - wyciągnij pierwszy element
  if (Array.isArray(value) && value.length > 0) {
    result[key] = value[0] || null;
  } else {
    result[key] = value;
  }
}

// Backward compatibility: dodaj pole 'krs' jeśli nie istnieje
if (!result.krs && !result.praw_numerWRejestrzeEwidencji) {
  // ... logika dla KRS
}

return res.status(200).json({ data: result });  // ✅ WSZYSTKIE pola!
```

### 4. DEBUG logging dla raportów PKD i jednostek lokalnych

```javascript
// Specjalne logi dla raportów PKD
if (reportName.indexOf('Pkd') !== -1) {
  console.log(chalk.magenta('[GUS DEBUG] PKD Report:'), reportName);
  console.log(chalk.magenta('[GUS DEBUG] PKD - liczba pól:'), Object.keys(result).length);
  console.log(chalk.magenta('[GUS DEBUG] PKD - dane:'), JSON.stringify(result, null, 2).substring(0, 2000));
}

// Specjalne logi dla jednostek lokalnych
if (reportName.indexOf('ListaJed') !== -1) {
  console.log(chalk.magenta('[GUS DEBUG] Jednostki lokalne Report:'), reportName);
  console.log(chalk.magenta('[GUS DEBUG] Jednostki - liczba pól:'), Object.keys(result).length);
  console.log(chalk.magenta('[GUS DEBUG] Jednostki - dane:'), JSON.stringify(result, null, 2).substring(0, 2000));
}
```

### 5. LOG zawsze (nawet w produkcji) dla debugowania

```javascript
// LOG: ZAWSZE loguj żądanie (nawet w produkcji) dla debugowania
console.log(chalk.cyan('[GUS full-report REQUEST]'), 'REGON:', regon, 'reportName:', customReportName || '(default)');

// Log success
var fieldsCount = Object.keys(result).length;
console.log(chalk.green('[GUS] Pełny raport zwrócił'), fieldsCount, 'pól');
```

---

## 🚀 INSTRUKCJA DEPLOYMENT NA GCP

### Krok 1: Upewnij się że masz najnowszy kod

```bash
cd Googie_GUS

# Sprawdź czy masz zmiany
git status

# Jeśli są zmiany, commituj
git add server/index.js
git commit -m "feat: zwracaj WSZYSTKIE dane z raportów GUS (PKD, formy prawne, jednostki)"
```

### Krok 2: Deploy na GCP Cloud Run

```bash
# Zaloguj się do GCP
gcloud auth login

# Ustaw projekt
gcloud config set project your-project-id

# Deploy
gcloud run deploy googie-gus-backend \
  --source . \
  --platform managed \
  --region europe-central2 \
  --allow-unauthenticated \
  --set-env-vars NODE_ENV=production,GUS_API_KEY=twoj_produkcyjny_klucz \
  --min-instances 0 \
  --max-instances 10 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 60
```

**Oczekiwany output:**
```
✓ Deploying... Done.
  ✓ Creating Revision... Revision deployment finished. Waiting for health check to begin.
  ✓ Routing traffic...
Done.
Service [googie-gus-backend] revision [googie-gus-backend-00042-abc] has been deployed
```

### Krok 3: Weryfikacja deployment

```bash
# Test podstawowego endpointu
curl https://your-backend.run.app/api/gus/name-by-nip \
  -X POST \
  -H "Content-Type: application/json" \
  -H "x-gus-api-key: your_key" \
  -d '{"nip":"8513176694"}'

# Powinno zwrócić dane firmy (bez błędów)
```

### Krok 4: Sprawdź logi GCP

```bash
# Logi na żywo
gcloud run services logs tail googie-gus-backend --region europe-central2

# Ostatnie 50 linii
gcloud run services logs read googie-gus-backend --region europe-central2 --limit 50
```

**Czego szukać w logach:**
```
[GUS full-report REQUEST] REGON: 321537875 reportName: BIR11OsPrawna
[GUS] Używam custom reportName: BIR11OsPrawnaPkd
[GUS] Pełny raport zwrócił 57 pól
[GUS DEBUG] PKD Report: BIR11OsPrawnaPkd
[GUS DEBUG] PKD - liczba pól: 12
```

---

## 🧪 TESTOWANIE

### Test 1: Podstawowy raport (BIR11OsPrawna)

```bash
curl https://your-backend.run.app/api/gus/full-report \
  -X POST \
  -H "Content-Type: application/json" \
  -H "x-gus-api-key: your_key" \
  -d '{
    "regon": "321537875"
  }'
```

**Oczekiwany rezultat:**
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
    "praw_liczbaJednLokalnych": "5",
    ... ~50 więcej pól!
  }
}
```

### Test 2: Raport PKD

```bash
curl https://your-backend.run.app/api/gus/full-report \
  -X POST \
  -H "Content-Type: application/json" \
  -H "x-gus-api-key: your_key" \
  -d '{
    "regon": "321537875",
    "reportName": "BIR11OsPrawnaPkd"
  }'
```

**Oczekiwany rezultat:**
```json
{
  "data": {
    "praw_pkdKod": "86.23.Z",
    "praw_pkdNazwa": "Praktyka lekarska dentystyczna",
    "praw_pkdPrzewazajace": "1",
    ... więcej kodów PKD
  }
}
```

**W logach GCP zobaczysz:**
```
[GUS full-report REQUEST] REGON: 321537875 reportName: BIR11OsPrawnaPkd
[GUS] Używam custom reportName: BIR11OsPrawnaPkd
[GUS DEBUG] PKD Report: BIR11OsPrawnaPkd
[GUS DEBUG] PKD - liczba pól: 12
[GUS DEBUG] PKD - dane (pierwsze 2000 znaków): {"praw_pkdKod":"86.23.Z",...}
```

### Test 3: Lista jednostek lokalnych

```bash
curl https://your-backend.run.app/api/gus/full-report \
  -X POST \
  -H "Content-Type: application/json" \
  -H "x-gus-api-key: your_key" \
  -d '{
    "regon": "321537875",
    "reportName": "BIR11OsPrawnaListaJednLokalnych"
  }'
```

**W logach GCP zobaczysz:**
```
[GUS full-report REQUEST] REGON: 321537875 reportName: BIR11OsPrawnaListaJednLokalnych
[GUS] Używam custom reportName: BIR11OsPrawnaListaJednLokalnych
[GUS DEBUG] Jednostki lokalne Report: BIR11OsPrawnaListaJednLokalnych
[GUS DEBUG] Jednostki - liczba pól: 8
[GUS DEBUG] Jednostki - dane: {...}
```

---

## 📊 JAKIE DANE TERAZ DOSTANIESZ

### Raport podstawowy (`BIR11OsPrawna`) - ~55 pól:

| Kategoria | Przykładowe pola |
|-----------|-----------------|
| **Identyfikatory** | `praw_regon9`, `praw_nip`, `praw_numerWRejestrzeEwidencji` (KRS) |
| **Nazwa** | `praw_nazwa`, `praw_nazwaSkrocona` |
| **Daty** | `praw_dataPowstania`, `praw_dataWpisuDoRegon`, `praw_dataZaistnieniaZmiany` |
| **Adres** | `praw_adSiedzKodPocztowy`, `praw_adSiedzMiejscowosc_Nazwa`, `praw_adSiedzUlica_Nazwa` |
| **Kontakt** | `praw_numerTelefonu`, `praw_numerFaksu`, `praw_adresEmail`, `praw_adresStronyinternetowej` |
| **✨ FORMY PRAWNE ✨** | `praw_podstawowaFormaPrawna_Symbol` + `_Nazwa` |
| | `praw_szczegolnaFormaPrawna_Symbol` + `_Nazwa` |
| **✨ FINANSOWANIE ✨** | `praw_formaFinansowania_Symbol` + `_Nazwa` |
| **✨ WŁASNOŚĆ ✨** | `praw_formaWlasnosci_Symbol` + `_Nazwa` |
| **✨ ORGANY ✨** | `praw_organZalozycielski_Symbol` + `_Nazwa` |
| | `praw_organRejestrowy_Symbol` + `_Nazwa` |
| **✨ REJESTR ✨** | `praw_rodzajRejestruEwidencji_Symbol` + `_Nazwa` |
| **✨ JEDNOSTKI ✨** | `praw_liczbaJednLokalnych` |

### Raport PKD (`BIR11OsPrawnaPkd`) - kody działalności:

```json
{
  "praw_pkdKod": "86.23.Z",
  "praw_pkdNazwa": "Praktyka lekarska dentystyczna",
  "praw_pkdPrzewazajace": "1"
}
```

### Raport jednostek lokalnych (`BIR11OsPrawnaListaJednLokalnych`):

```json
{
  "praw_regon14JednLokalnej": "32153787500012",
  "praw_adSiedzNazwaMiejscowosci": "Szczecin",
  "praw_adSiedzNazwaUlicy": "Kazimierza Królewicza",
  "praw_numerNieruchomosci": "2L",
  "praw_numerLokalu": "1"
}
```

---

## 🔍 DEBUGOWANIE

### Problem: Backend nadal zwraca tylko KRS

**Możliwe przyczyny:**
1. Kod nie został zdeployowany - sprawdź revision number:
   ```bash
   gcloud run services describe googie-gus-backend --region europe-central2 --format="value(status.latestCreatedRevisionName)"
   ```

2. Cache - wymuś pełne zbudowanie:
   ```bash
   gcloud run deploy googie-gus-backend --source . --no-cache
   ```

3. Stary kod w GCP - sprawdź ostatni commit:
   ```bash
   # Na GCP, w logach powinno być:
   [GUS] Pełny raport zwrócił 57 pół  # ✅ Nowa wersja
   # Zamiast:
   [GUS] Pełny raport zwrócił KRS: 0000513541  # ❌ Stara wersja
   ```

### Problem: "Brak danych" dla raportów PKD/jednostek

**Diagnoza z logów:**
```
[GUS DEBUG] PKD - liczba pól: 0  # ❌ GUS nie zwrócił danych
```

**Możliwe przyczyny:**
1. Firma nie ma jednostek lokalnych (`praw_liczbaJednLokalnych` = 0)
2. Niewłaściwy typ raportu dla REGON 14-znakowego (użyj `BIR11JednLokalnaOsPrawnej`)
3. Raport PKD wymaga innej struktury danych (lista vs pojedynczy obiekt)

**Rozwiązanie:** Sprawdź w logach GCP czy GUS faktycznie coś zwrócił:
```bash
gcloud run services logs read googie-gus-backend --region europe-central2 \
  | grep "DEBUG" | grep "dane"
```

---

## ✅ CHECKLIST DEPLOYMENT

- [ ] Kod z `server/index.js` zawiera zmiany (sprawdź linia ~468, ~526, ~632)
- [ ] Zmienne środowiskowe ustawione (`NODE_ENV=production`, `GUS_API_KEY`)
- [ ] Deploy wykonany (`gcloud run deploy ...`)
- [ ] Sprawdzono logi - widać `[GUS full-report REQUEST]`
- [ ] Test podstawowy działa (NIP → dane firmy)
- [ ] Test raportu PKD działa (widać `[GUS DEBUG] PKD Report`)
- [ ] Test jednostek lokalnych działa (widać `[GUS DEBUG] Jednostki`)
- [ ] Frontend aktualizowany (opcjonalnie - backend jest backward compatible)

---

## 📞 NASTĘPNE KROKI

### 1. Przetestuj lokalnie (opcjonalnie)

```bash
# W katalogu projektu
NODE_ENV=development npm start

# W innym terminalu
curl http://localhost:5000/api/gus/full-report \
  -X POST \
  -H "Content-Type: application/json" \
  -H "x-gus-api-key: abcde12345abcde12345" \
  -d '{"regon":"321537875", "reportName":"BIR11OsPrawnaPkd"}'
```

### 2. Deploy na GCP

(patrz sekcja wyżej)

### 3. Sprawdź logi

```bash
gcloud run services logs tail googie-gus-backend --region europe-central2
```

**Czego szukać:**
- ✅ `[GUS full-report REQUEST] REGON: ... reportName: ...`
- ✅ `[GUS] Pełny raport zwrócił 57 pól`
- ✅ `[GUS DEBUG] PKD Report: ...` (dla PKD)
- ✅ `[GUS DEBUG] Jednostki lokalne Report: ...` (dla jednostek)

### 4. Prześlij mi logi

**Wyeksportuj logi do pliku:**
```bash
gcloud run services logs read googie-gus-backend --region europe-central2 --limit 200 > gcp-logs-full-data.txt
```

**Wyślij mi ten plik** - zobaczę dokładnie co GUS zwraca!

---

**Sukcesu z deploymentem!** 🚀

Po deploymencie zobaczysz w logach **WSZYSTKIE** pola z GUS - formy prawne, PKD, jednostki lokalne i wiele więcej!

