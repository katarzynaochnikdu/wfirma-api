# 📚 DOKUMENTACJA STRUKTURY DANYCH BACKENDU GUS

**Wersja:** 2.0 - FULL DATA  
**Data:** 2025-11-13

---

## 🎯 GWARANCJA: NIE UCINAMY ŻADNYCH DANYCH!

Backend zwraca **100% danych** otrzymanych z GUS. **Żadne pole nie jest filtrowane ani pomijane.**

---

## 📋 TYPY RAPORTÓW I ICH STRUKTURA

### 1️⃣ RAPORT PODSTAWOWY (BIR11OsPrawna)

#### Request:
```json
POST /api/gus/full-report
{
  "regon": "321537875"
}
```
lub
```json
{
  "regon": "321537875",
  "reportName": "BIR11OsPrawna"
}
```

#### Response (WSZYSTKIE pola - 55+):
```json
{
  "data": {
    // === IDENTYFIKATORY ===
    "praw_regon9": "321537875",
    "praw_nip": "8513176694",
    "praw_statusNip": "",
    "praw_nazwa": "DERMADENT SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ SPÓŁKA KOMANDYTOWA",
    "praw_nazwaSkrocona": "",
    "praw_numerWRejestrzeEwidencji": "0000513541",  // To jest KRS!
    
    // === DATY ===
    "praw_dataWpisuDoRejestruEwidencji": "2014-06-13",
    "praw_dataPowstania": "2014-06-13",
    "praw_dataRozpoczeciaDzialalnosci": "2014-06-13",
    "praw_dataWpisuDoRegon": "2014-07-01",
    "praw_dataZawieszeniaDzialalnosci": "",
    "praw_dataWznowieniaDzialalnosci": "",
    "praw_dataZaistnieniaZmiany": "2021-03-22",
    "praw_dataZakonczeniaDzialalnosci": "",
    "praw_dataSkresleniaZRegon": "",
    "praw_dataOrzeczeniaOUpadlosci": "",
    "praw_dataZakonczeniaPostepowaniaUpadlosciowego": "",
    
    // === ADRES SIEDZIBY ===
    "praw_adSiedzKraj_Symbol": "PL",
    "praw_adSiedzWojewodztwo_Symbol": "32",
    "praw_adSiedzPowiat_Symbol": "1",
    "praw_adSiedzGmina_Symbol": "063",
    "praw_adSiedzKodPocztowy": "71-552",
    "praw_adSiedzMiejscowoscPoczty_Symbol": "0918123",
    "praw_adSiedzMiejscowosc_Symbol": "0918123",
    "praw_adSiedzUlica_Symbol": "10359",
    "praw_adSiedzNumerNieruchomosci": "2L",
    "praw_adSiedzNumerLokalu": "1",
    "praw_adSiedzNietypoweMiejsceLokalizacji": "",
    "praw_adSiedzKraj_Nazwa": "POLSKA",
    "praw_adSiedzWojewodztwo_Nazwa": "ZACHODNIOPOMORSKIE",
    "praw_adSiedzPowiat_Nazwa": "Szczecin",
    "praw_adSiedzGmina_Nazwa": "Szczecin",
    "praw_adSiedzMiejscowosc_Nazwa": "Szczecin",
    "praw_adSiedzMiejscowoscPoczty_Nazwa": "Szczecin",
    "praw_adSiedzUlica_Nazwa": "ul. Kazimierza Królewicza",
    
    // === KONTAKT ===
    "praw_numerTelefonu": "914619999",
    "praw_numerWewnetrznyTelefonu": "",
    "praw_numerFaksu": "",
    "praw_adresEmail": "kontakt@dermadent.pl",
    "praw_adresStronyinternetowej": "www.dermadent.pl",
    
    // === ✨ FORMY PRAWNE ✨ ===
    "praw_podstawowaFormaPrawna_Symbol": "1",
    "praw_podstawowaFormaPrawna_Nazwa": "OSOBA PRAWNA",
    "praw_szczegolnaFormaPrawna_Symbol": "101",
    "praw_szczegolnaFormaPrawna_Nazwa": "SPÓŁKA KOMANDYTOWA",
    
    // === ✨ FINANSOWANIE I WŁASNOŚĆ ✨ ===
    "praw_formaFinansowania_Symbol": "1",
    "praw_formaFinansowania_Nazwa": "JEDNOSTKA SEKTORA PRYWATNEGO",
    "praw_formaWlasnosci_Symbol": "214",
    "praw_formaWlasnosci_Nazwa": "WŁASNOŚĆ PRYWATNA KRAJOWA OSÓB FIZYCZNYCH",
    
    // === ✨ ORGANY ✨ ===
    "praw_organZalozycielski_Symbol": "0",
    "praw_organZalozycielski_Nazwa": "BRAK",
    "praw_organRejestrowy_Symbol": "070",
    "praw_organRejestrowy_Nazwa": "SĄD REJONOWY SZCZECIN-CENTRUM W SZCZECINIE",
    
    // === ✨ REJESTR ✨ ===
    "praw_rodzajRejestruEwidencji_Symbol": "138",
    "praw_rodzajRejestruEwidencji_Nazwa": "REJESTR PRZEDSIĘBIORCÓW W KRS",
    
    // === ✨ JEDNOSTKI LOKALNE ✨ ===
    "praw_liczbaJednLokalnych": "5"
  },
  "reportName": "BIR11OsPrawna",
  "fieldsCount": 57
}
```

**PARSOWANIE:** Kod konwertuje KAŻDE pole z XML → JSON. **Nic nie jest pomijane!**

---

### 2️⃣ RAPORT PKD (BIR11OsPrawnaPkd)

#### Request:
```json
POST /api/gus/full-report
{
  "regon": "321537875",
  "reportName": "BIR11OsPrawnaPkd"
}
```

#### Response (TABLICA kodów PKD):
```json
{
  "data": {
    "pkdList": [
      {
        "praw_pkdKod": "86.23.Z",
        "praw_pkdNazwa": "Praktyka lekarska dentystyczna",
        "praw_pkdPrzewazajace": "1",
        "praw_pkdSekwens": "1"
      },
      {
        "praw_pkdKod": "47.73.Z",
        "praw_pkdNazwa": "Sprzedaż detaliczna wyrobów farmaceutycznych prowadzona w wyspecjalizowanych sklepach",
        "praw_pkdPrzewazajace": "0",
        "praw_pkdSekwens": "2"
      },
      {
        "praw_pkdKod": "32.50.Z",
        "praw_pkdNazwa": "Produkcja urządzeń, instrumentów oraz wyrobów medycznych, włączając dentystyczne",
        "praw_pkdPrzewazajace": "0",
        "praw_pkdSekwens": "3"
      }
    ],
    "pkdCount": 3
  },
  "reportName": "BIR11OsPrawnaPkd",
  "fieldsCount": 3
}
```

**PARSOWANIE (linia ~645-670):**
```javascript
// GUS zwraca TABLICĘ <dane> (jeden <dane> = jeden PKD)
var daneArray = parsed.root.dane;

var pkdArray = [];
for (var i = 0; i < daneArray.length; i++) {
  var pkdEntry = daneArray[i];
  var pkdItem = {};
  
  // Konwertuj WSZYSTKIE pola PKD (bez wyjątków!)
  Object.keys(pkdEntry).forEach(function(key) {
    pkdItem[key] = pkdEntry[key][0];  // Wyciągnij wartość z tablicy xml2js
  });
  
  pkdArray.push(pkdItem);  // KAŻDY PKD w tablicy
}
```

**GWARANCJA:** Backend zwraca **KAŻDY** kod PKD z GUS z **WSZYSTKIMI** jego polami!

---

### 3️⃣ JEDNOSTKI LOKALNE (BIR11OsPrawnaListaJednLokalnych)

#### Request:
```json
POST /api/gus/full-report
{
  "regon": "321537875",
  "reportName": "BIR11OsPrawnaListaJednLokalnych"
}
```

#### Response (TABLICA jednostek lokalnych):
```json
{
  "data": {
    "jednostkiLokalne": [
      {
        "praw_regon14JednLokalnej": "32153787500012",
        "praw_nazwa": "DERMADENT - FILIA SZCZECIN CENTRUM",
        "praw_adSiedzKraj_Symbol": "PL",
        "praw_adSiedzWojewodztwo_Symbol": "32",
        "praw_adSiedzPowiat_Symbol": "1",
        "praw_adSiedzGmina_Symbol": "063",
        "praw_adSiedzNazwaMiejscowosci": "Szczecin",
        "praw_adSiedzNazwaUlicy": "Kazimierza Królewicza",
        "praw_numerNieruchomosci": "2L",
        "praw_numerLokalu": "1",
        "praw_kodPocztowy": "71-552",
        "praw_miejscowoscPoczty": "Szczecin",
        "praw_silosID": "6"
      },
      {
        "praw_regon14JednLokalnej": "32153787500023",
        "praw_nazwa": "DERMADENT - FILIA SZCZECIN PRAWOBRZEŻE",
        ... wszystkie pola drugiej jednostki
      },
      ... więcej jednostek (do 5)
    ],
    "jednostkiCount": 5
  },
  "reportName": "BIR11OsPrawnaListaJednLokalnych",
  "fieldsCount": 5
}
```

**PARSOWANIE (linia ~674-699):**
```javascript
// GUS zwraca TABLICĘ <dane> (jeden <dane> = jedna jednostka lokalna)
var daneArray = parsed.root.dane;

var jednostkiArray = [];
for (var i = 0; i < daneArray.length; i++) {
  var jednostkaEntry = daneArray[i];
  var jednostkaItem = {};
  
  // Konwertuj WSZYSTKIE pola jednostki (bez wyjątków!)
  Object.keys(jednostkaEntry).forEach(function(key) {
    jednostkaItem[key] = jednostkaEntry[key][0];
  });
  
  jednostkiArray.push(jednostkaItem);  // KAŻDA jednostka w tablicy
}
```

**GWARANCJA:** Backend zwraca **KAŻDĄ** jednostkę lokalną z **WSZYSTKIMI** jej polami!

---

## 🔍 DOSTĘPNE RAPORTY (20 typów)

### BIR11 - Osoby prawne (3 raporty)
1. `BIR11OsPrawna` - Podstawowe dane (55+ pól)
2. `BIR11OsPrawnaPkd` - Kody PKD (tablica)
3. `BIR11OsPrawnaListaJednLokalnych` - Jednostki lokalne (tablica)

### BIR11 - Jednostki lokalne osób prawnych (2 raporty)
4. `BIR11JednLokalnaOsPrawnej` - Dane jednostki (40+ pól)
5. `BIR11JednLokalnaOsPrawnejPkd` - PKD jednostki (tablica)

### BIR11 - Osoby fizyczne (3 raporty)
6. `BIR11OsFizyczna` - Podstawowe dane (50+ pól)
7. `BIR11OsFizycznaPkd` - Kody PKD (tablica)
8. `BIR11OsFizycznaListaJednLokalnych` - Jednostki lokalne (tablica)

### BIR11 - Jednostki lokalne osób fizycznych (2 raporty)
9. `BIR11JednLokalnaOsFizycznej` - Dane jednostki (40+ pól)
10. `BIR11JednLokalnaOsFizycznejPkd` - PKD jednostki (tablica)

### BIR12 (nowsze wersje - 2025+) - identyczne jak BIR11
11-20. `BIR12OsPrawna`, `BIR12OsPrawnaPkd`, ... (jak wyżej)

---

## 🛠️ JAK BACKEND PARSUJE DANE

### Proces parsowania (kod: linia ~621-761):

```javascript
// KROK 1: Parse XML → JavaScript obiekt
xml2js.parseStringPromise(decodedXml)

// KROK 2: Wyciągnij tablicę <dane>
var daneArray = parsed.root.dane;  // Zawsze tablica!

// KROK 3: Sprawdź TYP raportu
var isPkdReport = reportName.indexOf('Pkd') !== -1;
var isJednLokalneReport = reportName.indexOf('ListaJed') !== -1;

// KROK 4A: Jeśli PKD → zwróć tablicę obiektów
if (isPkdReport) {
  var pkdArray = [];
  for (var i = 0; i < daneArray.length; i++) {
    var pkdItem = {};
    Object.keys(daneArray[i]).forEach(function(key) {
      pkdItem[key] = daneArray[i][key][0];  // Wyciągnij wartość z tablicy xml2js
    });
    pkdArray.push(pkdItem);
  }
  return { data: { pkdList: pkdArray, pkdCount: pkdArray.length }, ... };
}

// KROK 4B: Jeśli jednostki lokalne → zwróć tablicę obiektów
else if (isJednLokalneReport) {
  var jednostkiArray = [];
  for (var i = 0; i < daneArray.length; i++) {
    var jednostkaItem = {};
    Object.keys(daneArray[i]).forEach(function(key) {
      jednostkaItem[key] = daneArray[i][key][0];
    });
    jednostkiArray.push(jednostkaItem);
  }
  return { data: { jednostkiLokalne: jednostkiArray, jednostkiCount: jednostkiArray.length }, ... };
}

// KROK 4C: Raport podstawowy → zwróć pojedynczy obiekt ze WSZYSTKIMI polami
else {
  var dane = daneArray[0];  // Pierwszy (i jedyny) element
  var result = {};
  Object.keys(dane).forEach(function(key) {
    result[key] = dane[key][0];  // Wyciągnij wartość
  });
  return { data: result, reportName: reportName, fieldsCount: Object.keys(result).length };
}
```

### Dlaczego `[0]`?

`xml2js` zawsze zwraca wartości jako **tablice**:
```javascript
// XML:
<praw_nazwa>DERMADENT</praw_nazwa>

// Po xml2js:
{ "praw_nazwa": ["DERMADENT"] }  // Tablica!

// Backend konwertuje:
result["praw_nazwa"] = dane["praw_nazwa"][0];  // "DERMADENT"
```

---

## 📊 MAPOWANIE NA GUS_fields.csv

### Pola z raportu podstawowego → Zoho CRM:

| Pole GUS | Pole Zoho CRM | Opis |
|----------|---------------|------|
| `praw_regon9` | `Firma_REGON` | REGON 9-znakowy |
| `praw_nip` | `Firma_NIP` | NIP |
| `praw_numerWRejestrzeEwidencji` | `Firma_KRS` | Numer KRS |
| `praw_nazwa` | `Account_Name` | Nazwa firmy |
| `praw_podstawowaFormaPrawna_Symbol` | `Podstawowa_Forma_Prawna_Symbol` | Kod formy prawnej (1-9) |
| `praw_podstawowaFormaPrawna_Nazwa` | `Podstawowa_Forma_Prawna` | Nazwa formy (OSOBA PRAWNA, OSOBA FIZYCZNA) |
| `praw_szczegolnaFormaPrawna_Symbol` | `Szczegolna_Forma_Prawna_Symbol` | Kod szczegółowy (101, 102, ...) |
| `praw_szczegolnaFormaPrawna_Nazwa` | `Szczegolna_Forma_Prawna` | Nazwa (SPÓŁKA KOMANDYTOWA, ...) |
| `praw_formaFinansowania_Symbol` | `Forma_Finansowania_Symbol` | Kod |
| `praw_formaFinansowania_Nazwa` | `Forma_Finansowania` | Nazwa |
| `praw_formaWlasnosci_Symbol` | `Forma_Wlasnosci_Symbol` | Kod |
| `praw_formaWlasnosci_Nazwa` | `Forma_Wlasnosci` | Nazwa |
| `praw_organZalozycielski_Symbol` | `Organ_Zalozycielski_Symbol` | Kod |
| `praw_organZalozycielski_Nazwa` | `Organ_Zalozycielski` | Nazwa |
| `praw_organRejestrowy_Symbol` | `Organ_Rejestrowy_Symbol` | Kod |
| `praw_organRejestrowy_Nazwa` | `Organ_Rejestrowy` | Nazwa (np. SĄD REJONOWY...) |
| `praw_rodzajRejestruEwidencji_Symbol` | `Rodzaj_Rejestru_Symbol` | Kod |
| `praw_rodzajRejestruEwidencji_Nazwa` | `Rodzaj_Rejestru` | Nazwa (REJESTR PRZEDSIĘBIORCÓW W KRS) |
| `praw_liczbaJednLokalnych` | `Liczba_Jednostek_Lokalnych` | Liczba filii |
| `praw_numerTelefonu` | `Phone` | Telefon |
| `praw_adresEmail` | `Email` | Email |
| `praw_adresStronyinternetowej` | `Website` | Strona WWW |
| `praw_dataPowstania` | `Data_Powstania` | Data założenia |
| `praw_adSiedzMiejscowosc_Nazwa` | `Billing_City` | Miasto |
| `praw_adSiedzUlica_Nazwa` | `Billing_Street_Name` | Ulica |
| `praw_adSiedzNumerNieruchomosci` | `Billing_Building_Number` | Nr budynku |
| `praw_adSiedzNumerLokalu` | `Billing_Local_Number` | Nr lokalu |
| `praw_adSiedzKodPocztowy` | `Billing_Code` | Kod pocztowy |
| `praw_adSiedzWojewodztwo_Nazwa` | `Billing_State` | Województwo |
| `praw_adSiedzPowiat_Nazwa` | `Billing_Powiat` | Powiat |
| `praw_adSiedzGmina_Nazwa` | `Billing_Gmina` | Gmina |

### PKD → Zoho CRM (custom module)

Kody PKD można zapisać do:
1. **Custom module** `PKD_Codes` (Related List do Accounts)
2. **Pole tekstowe** `PKD_Lista` (concatenated string)
3. **Pole Long Text** `PKD_Szczegoly` (JSON)

Przykład zapisu:
```javascript
// Wariant 1: Custom module (zalecane)
for (var i = 0; i < pkdList.length; i++) {
  var pkd = pkdList[i];
  ZOHO.CRM.API.insertRecord({
    Entity: 'PKD_Codes',
    APIData: {
      Parent_Id: accountId,  // Powiązanie z firmą
      PKD_Code: pkd.praw_pkdKod,
      PKD_Description: pkd.praw_pkdNazwa,
      Is_Primary: pkd.praw_pkdPrzewazajace === '1'
    }
  });
}

// Wariant 2: Pole tekstowe (prostsze)
var pkdString = pkdList.map(function(p) {
  return p.praw_pkdKod + ' - ' + p.praw_pkdNazwa;
}).join('\n');

ZOHO.CRM.API.updateRecord({
  Entity: 'Accounts',
  APIData: {
    id: accountId,
    PKD_Lista: pkdString
  }
});
```

---

## 🔍 DEBUGGING: Co backend loguje

### W logach GCP zobaczysz (dla każdego requestu):

#### Raport podstawowy:
```
[GUS full-report REQUEST] REGON: 321537875 reportName: (default)
[GUS] Używam domyślny reportName: BIR11OsPrawna
[GUS] Raport podstawowy - zwrócono 57 pól
```

#### Raport PKD:
```
[GUS full-report REQUEST] REGON: 321537875 reportName: BIR11OsPrawnaPkd
[GUS] Używam custom reportName: BIR11OsPrawnaPkd
[GUS DEBUG] PKD Report: BIR11OsPrawnaPkd
[GUS DEBUG] PKD - liczba wpisów w tablicy dane: 3
[GUS DEBUG] PKD - sparsowano 3 kodów PKD
[GUS DEBUG] PKD - dane (pierwsze 2000 znaków): [
  {
    "praw_pkdKod": "86.23.Z",
    "praw_pkdNazwa": "Praktyka lekarska dentystyczna",
    "praw_pkdPrzewazajace": "1"
  },
  ...
]
```

#### Raport jednostek lokalnych:
```
[GUS full-report REQUEST] REGON: 321537875 reportName: BIR11OsPrawnaListaJednLokalnych
[GUS] Używam custom reportName: BIR11OsPrawnaListaJednLokalnych
[GUS DEBUG] Jednostki lokalne Report: BIR11OsPrawnaListaJednLokalnych
[GUS DEBUG] Jednostki - liczba wpisów w tablicy dane: 5
[GUS DEBUG] Jednostki - sparsowano 5 jednostek
[GUS DEBUG] Jednostki - dane (pierwsze 2000 znaków): [
  {
    "praw_regon14JednLokalnej": "32153787500012",
    "praw_adSiedzNazwaMiejscowosci": "Szczecin",
    ...
  },
  ...
]
```

---

## ✅ CHECKLIST PRZED DEPLOYMENTEM

- [ ] Zainstalowano Google Cloud SDK (`gcloud --version` działa)
- [ ] Zalogowano się (`gcloud auth login`)
- [ ] Projekt GCP skonfigurowany (`gcloud config set project ...`)
- [ ] Masz produkcyjny klucz GUS API
- [ ] Kod w `server/index.js` zawiera zmiany (linia ~468, ~526, ~621-761)
- [ ] Plik `package.json` ma `express-rate-limit` w dependencies

---

## 🚀 DEPLOYMENT

### Automatyczny (ZALECANE):

**Windows:**
```powershell
cd C:\Users\kochn\Widget\Googie_GUS
.\deploy-gcp-full.ps1
```

**Linux/macOS:**
```bash
cd ~/Googie_GUS
chmod +x deploy-gcp-full.sh
./deploy-gcp-full.sh
```

### Ręczny:

```bash
gcloud run deploy googie-gus-backend \
  --source . \
  --platform managed \
  --region europe-central2 \
  --allow-unauthenticated \
  --set-env-vars "NODE_ENV=production,GUS_API_KEY=your_key" \
  --min-instances 0 \
  --max-instances 10 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 60
```

---

## 📞 SUPPORT

### Sprawdź logi w czasie rzeczywistym:
```bash
gcloud run services logs tail googie-gus-backend --region europe-central2
```

### Eksportuj logi do pliku:
```bash
gcloud run services logs read googie-gus-backend \
  --region europe-central2 \
  --limit 200 > gcp-logs.txt
```

### Rollback do poprzedniej wersji:
```bash
gcloud run services update-traffic googie-gus-backend \
  --region europe-central2 \
  --to-revisions PREVIOUS=100
```

---

**Powodzenia z deploymentem!** 🎉

Backend zwróci **WSZYSTKIE** dane z GUS - formy prawne, PKD, jednostki lokalne i wiele więcej!

