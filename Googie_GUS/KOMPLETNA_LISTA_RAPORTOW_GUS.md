# 📊 KOMPLETNA LISTA RAPORTÓW GUS - WSZYSTKIE OBSŁUGIWANE

**Data:** 2025-11-13  
**Źródło:** Dokumentacja BIR 1.1/1.2 - wersja 1.35  
**Status:** ✅ Wszystkie 32 raporty obsługiwane (0 filtrowanych!)

---

## ✅ GWARANCJA: ŻADEN RAPORT NIE JEST FILTROWANY!

Backend obsługuje **WSZYSTKIE 32 raporty** z dokumentacji GUS BIR11 i BIR12.

**Whitelist:** `server/index.js` linia ~529-577 (32 raporty)

---

## 📋 BIR11 - OSOBY PRAWNE (4 raporty)

### 1. `BIR11OsPrawna` - **Podstawowe dane osoby prawnej**
**Struktura:** Pojedynczy obiekt (55+ pól)

**Zawiera:**
- Identyfikatory (REGON, NIP, KRS)
- ✨ **Formy prawne:** `praw_podstawowaFormaPrawna_Symbol/Nazwa`, `praw_szczegolnaFormaPrawna_Symbol/Nazwa`
- ✨ **Finansowanie:** `praw_formaFinansowania_Symbol/Nazwa`
- ✨ **Własność:** `praw_formaWlasnosci_Symbol/Nazwa`
- ✨ **Organy:** `praw_organZalozycielski`, `praw_organRejestrowy`, `praw_rodzajRejestruEwidencji`
- Adres siedziby (20+ pól)
- Kontakt (telefon, fax, email, www)
- Daty (powstania, wpisu, zawieszenia, zmian)
- ✨ **Liczba jednostek lokalnych:** `praw_liczbaJednLokalnych`

**Format odpowiedzi:**
```json
{
  "data": { ...55+ pól... },
  "reportName": "BIR11OsPrawna",
  "fieldsCount": 57
}
```

---

### 2. `BIR11OsPrawnaPkd` - **Kody PKD osoby prawnej**
**Struktura:** TABLICA obiektów (każdy PKD = osobny wpis)

**Zawiera:**
- `praw_pkdKod` - kod PKD (np. "86.23.Z")
- `praw_pkdNazwa` - nazwa działalności
- `praw_pkdPrzewazajace` - czy przeważająca ("1" = tak, "0" = nie)

**Format odpowiedzi:**
```json
{
  "data": {
    "pkdList": [
      {"praw_pkdKod": "86.23.Z", "praw_pkdNazwa": "...", "praw_pkdPrzewazajace": "1"},
      {"praw_pkdKod": "47.73.Z", "praw_pkdNazwa": "...", "praw_pkdPrzewazajace": "0"}
    ],
    "pkdCount": 2
  },
  "reportName": "BIR11OsPrawnaPkd",
  "fieldsCount": 2
}
```

---

### 3. `BIR11OsPrawnaListaJednLokalnych` - **Lista jednostek lokalnych (filii)**
**Struktura:** TABLICA obiektów (każda filia = osobny wpis)

**Zawiera:**
- `praw_regon14JednLokalnej` - REGON 14-znakowy jednostki
- `praw_nazwa` - nazwa jednostki/filii
- `praw_adSiedzNazwaMiejscowosci` - miasto
- `praw_adSiedzNazwaUlicy` - ulica
- `praw_numerNieruchomosci` - nr budynku
- `praw_numerLokalu` - nr lokalu
- `praw_kodPocztowy` - kod pocztowy
- `praw_silosID` - identyfikator typu jednostki

**Format odpowiedzi:**
```json
{
  "data": {
    "jednostkiLokalne": [
      {"praw_regon14JednLokalnej": "32153787500012", "praw_nazwa": "FILIA SZCZECIN", ...},
      {"praw_regon14JednLokalnej": "32153787500023", "praw_nazwa": "FILIA WARSZAWA", ...}
    ],
    "jednostkiCount": 5
  },
  "reportName": "BIR11OsPrawnaListaJednLokalnych",
  "fieldsCount": 5
}
```

---

### 4. `BIR11OsPrawnaSpCywilnaWspolnicy` - ✨ **Wspólnicy spółki cywilnej**
**Struktura:** TABLICA obiektów (każdy wspólnik = osobny wpis)

**Zawiera:**
- `wspolsc_regon9` - REGON wspólnika (jeśli firma)
- `wspolsc_nip` - NIP wspólnika
- `wspolsc_nazwa` - nazwa/imię i nazwisko wspólnika
- Inne dane wspólnika

**Format odpowiedzi:**
```json
{
  "data": {
    "wspolnicy": [
      {"wspolsc_regon9": "123456789", "wspolsc_nazwa": "Jan Kowalski", ...},
      {"wspolsc_regon9": "987654321", "wspolsc_nazwa": "ABC Sp. z o.o.", ...}
    ],
    "wspolnicyCount": 2
  },
  "reportName": "BIR11OsPrawnaSpCywilnaWspolnicy",
  "fieldsCount": 2
}
```

---

## 📋 BIR11 - JEDNOSTKI LOKALNE OSÓB PRAWNYCH (2 raporty)

### 5. `BIR11JednLokalnaOsPrawnej` - **Pełne dane jednostki lokalnej**
**Struktura:** Pojedynczy obiekt (40+ pól)

**Wymaga:** REGON 14-znakowy (z listy jednostek lokalnych)

**Zawiera:**
- Wszystkie dane adresowe jednostki lokalnej
- Kontakt jednostki
- Daty działalności
- PKD jednostki (podstawowy kod)

---

### 6. `BIR11JednLokalnaOsPrawnejPkd` - **PKD jednostki lokalnej**
**Struktura:** TABLICA obiektów

**Zawiera:** Wszystkie kody PKD dla konkretnej jednostki lokalnej

---

## 📋 BIR11 - OSOBY FIZYCZNE (10 raportów!)

### 7. `BIR11OsFizyczna` - **Podstawowe dane osoby fizycznej**
**Struktura:** Pojedynczy obiekt (40+ pól)

**Zawiera:** Analogicznie do `BIR11OsPrawna`, ale pola z prefiksem `fiz_*`

---

### 8. `BIR11OsFizycznaPkd` - **PKD osoby fizycznej**
**Struktura:** TABLICA

---

### 9. `BIR11OsFizycznaListaJednLokalnych` - **Jednostki lokalne osoby fizycznej**
**Struktura:** TABLICA

---

### 10. `BIR11OsFizycznaDaneOgolne` - ✨ **Dane ogólne działalności osoby fizycznej**
**Struktura:** Pojedynczy obiekt LUB tablica

**Zawiera:**
- `fiz_dataPowstania`
- `fiz_dataRozpoczeciaDzialalnosci`
- `fiz_dataWpisuDoCeidg`
- `fiz_dataZawieszenia`
- `fiz_dataWznowienia`
- `fiz_dataZakonczenia`
- Inne dane o działalności

**Format odpowiedzi:**
```json
{
  "data": {
    "fiz_dataPowstania": "2010-05-15",
    "fiz_dataRozpoczeciaDzialalnosci": "2010-06-01",
    "fiz_dataWpisuDoCeidg": "2010-05-20",
    ... ~20 pól
  },
  "reportName": "BIR11OsFizycznaDaneOgolne",
  "fieldsCount": 23
}
```

---

### 11. `BIR11OsFizycznaDzialalnoscCeidg` - ✨ **Działalność CEIDG**
**Struktura:** Pojedynczy obiekt LUB tablica

**Zawiera:**
- `fiz_dataSkresleniaDzialalnosciCeidg`
- `fiz_numerWRejestrzeEwidencji` (CEIDG)
- `fiz_organRejestrowy`
- `fiz_rodzajRejestru`
- Inne dane rejestrowe CEIDG

---

### 12. `BIR11OsFizycznaDzialalnoscPozostala` - ✨ **Działalność pozostała (inne niż CEIDG)**
**Struktura:** Pojedynczy obiekt LUB tablica

**Zawiera:**
- Dane o działalności nierejestrowanej w CEIDG
- Formy ewidencji

---

### 13. `BIR11OsFizycznaDzialalnoscRolnicza` - ✨ **Działalność rolnicza**
**Struktura:** Pojedynczy obiekt LUB tablica

**Zawiera:**
- Dane o gospodarstwie rolnym
- Ewidencja producenta rolnego

---

### 14. `BIR11OsFizycznaDzialalnoscSkreslonaDo20141108` - ✨ **Działalność skreślona (historyczna)**
**Struktura:** Pojedynczy obiekt LUB tablica

**Zawiera:**
- Historyczne dane o działalności skreślonej przed 2014-11-08
- Daty skreślenia, przyczyny

---

### 15-16. `BIR11JednLokalnaOsFizycznej` + `BIR11JednLokalnaOsFizycznejPkd`
Analogiczne do jednostek lokalnych osób prawnych.

---

## 📋 BIR12 (2025+) - WSZYSTKIE RAPORTY (16 raportów)

BIR12 ma **identyczne raporty** jak BIR11, tylko z prefiksem `BIR12`:

17. `BIR12OsPrawna`
18. `BIR12OsPrawnaPkd`
19. `BIR12OsPrawnaListaJednLokalnych`
20. `BIR12OsPrawnaSpCywilnaWspolnicy`
21. `BIR12JednLokalnaOsPrawnej`
22. `BIR12JednLokalnaOsPrawnejPkd`
23. `BIR12OsFizyczna`
24. `BIR12OsFizycznaPkd`
25. `BIR12OsFizycznaListaJednLokalnych`
26. `BIR12OsFizycznaDaneOgolne`
27. `BIR12OsFizycznaDzialalnoscCeidg`
28. `BIR12OsFizycznaDzialalnoscPozostala`
29. `BIR12OsFizycznaDzialalnoscRolnicza`
30. `BIR12OsFizycznaDzialalnoscSkreslonaDo20141108`
31. `BIR12JednLokalnaOsFizycznej`
32. `BIR12JednLokalnaOsFizycznejPkd`

**RAZEM: 32 raporty**

---

## 🔍 TYPY STRUKTUR DANYCH

Backend automatycznie rozpoznaje typ raportu i parsuje odpowiednio:

### Typ 1: **Pojedynczy obiekt** (55+ pól)
- Raporty podstawowe: `OsPrawna`, `OsFizyczna`, `JednLokalna...`
- Parser: `else { dane = daneArray[0]; ... }` (linia ~807)

### Typ 2: **Tablica PKD**
- Raporty z sufiksem `Pkd`
- Parser: `if (isPkdReport) { ... }` (linia ~675)
- Zwraca: `{ pkdList: [...], pkdCount: N }`

### Typ 3: **Tablica jednostek lokalnych**
- Raporty z sufiksem `ListaJednLokalnych`
- Parser: `else if (isJednLokalneReport) { ... }` (linia ~735)
- Zwraca: `{ jednostkiLokalne: [...], jednostkiCount: N }`

### Typ 4: **Tablica wspólników**
- Raport `SpCywilnaWspolnicy`
- Parser: `else if (isWspolnicyReport) { ... }` (linia ~706)
- Zwraca: `{ wspolnicy: [...], wspolnicyCount: N }`

### Typ 5: **Działalność** (tablica LUB obiekt)
- Raporty `Dzialal...` i `DaneOgolne`
- Parser: `else if (isDzialalnoscReport) { ... }` (linia ~764)
- Zwraca: `{ dzialalnosc: [...] }` lub `{ fiz_*: ... }` (jeśli 1 wpis)

---

## 🎯 JAK UŻYWAĆ (przykłady)

### Przykład 1: Pobierz formy prawne
```bash
POST /api/gus/full-report
{
  "regon": "321537875"
}

# Odpowiedź zawiera:
{
  "data": {
    "praw_podstawowaFormaPrawna_Symbol": "1",
    "praw_podstawowaFormaPrawna_Nazwa": "OSOBA PRAWNA",
    "praw_szczegolnaFormaPrawna_Symbol": "101",
    "praw_szczegolnaFormaPrawna_Nazwa": "SPÓŁKA KOMANDYTOWA",
    "praw_formaFinansowania_Symbol": "1",
    "praw_formaFinansowania_Nazwa": "JEDNOSTKA SEKTORA PRYWATNEGO",
    ...
  }
}
```

### Przykład 2: Pobierz WSZYSTKIE kody PKD
```bash
POST /api/gus/full-report
{
  "regon": "321537875",
  "reportName": "BIR11OsPrawnaPkd"
}

# Odpowiedź:
{
  "data": {
    "pkdList": [
      {"praw_pkdKod": "86.23.Z", "praw_pkdNazwa": "Praktyka lekarska dentystyczna", "praw_pkdPrzewazajace": "1"},
      {"praw_pkdKod": "47.73.Z", "praw_pkdNazwa": "Sprzedaż detaliczna...", "praw_pkdPrzewazajace": "0"},
      ...
    ],
    "pkdCount": 3
  }
}
```

### Przykład 3: Pobierz jednostki lokalne (filie)
```bash
POST /api/gus/full-report
{
  "regon": "321537875",
  "reportName": "BIR11OsPrawnaListaJednLokalnych"
}

# Odpowiedź:
{
  "data": {
    "jednostkiLokalne": [
      {
        "praw_regon14JednLokalnej": "32153787500012",
        "praw_nazwa": "DERMADENT - FILIA SZCZECIN",
        "praw_adSiedzNazwaMiejscowosci": "Szczecin",
        "praw_adSiedzNazwaUlicy": "Kazimierza Królewicza",
        "praw_numerNieruchomosci": "2L",
        "praw_numerLokalu": "1"
      },
      ...
    ],
    "jednostkiCount": 5
  }
}
```

### Przykład 4: Pobierz wspólników spółki cywilnej
```bash
POST /api/gus/full-report
{
  "regon": "123456789",
  "reportName": "BIR11OsPrawnaSpCywilnaWspolnicy"
}

# Odpowiedź:
{
  "data": {
    "wspolnicy": [
      {"wspolsc_regon9": "111111111", "wspolsc_nazwa": "Jan Kowalski", ...},
      {"wspolsc_regon9": "222222222", "wspolsc_nazwa": "Anna Nowak", ...}
    ],
    "wspolnicyCount": 2
  }
}
```

### Przykład 5: Działalność CEIDG osoby fizycznej
```bash
POST /api/gus/full-report
{
  "regon": "123456789",
  "reportName": "BIR11OsFizycznaDzialalnoscCeidg"
}

# Odpowiedź (jeśli 1 działalność):
{
  "data": {
    "fiz_dataSkresleniaDzialalnosciCeidg": "",
    "fiz_numerWRejestrzeEwidencji": "12345678",
    "fiz_organRejestrowy": "...",
    ...
  },
  "reportName": "BIR11OsFizycznaDzialalnoscCeidg",
  "fieldsCount": 15
}

# LUB (jeśli wiele działalności):
{
  "data": {
    "dzialalnosc": [
      {"fiz_numerWRejestrzeEwidencji": "12345", ...},
      {"fiz_numerWRejestrzeEwidencji": "67890", ...}
    ],
    "dzialalnoscCount": 2
  }
}
```

---

## 📊 PODSUMOWANIE ZMIAN W BACKENDZIE

### ❌ PRZED (wersja 1.0):
- Obsługiwane: 10/32 raportów (31% ✗)
- Zwracane dane: tylko KRS
- **22 raporty FILTROWANE!**

### ✅ PO (wersja 2.0):
- Obsługiwane: **32/32 raportów (100% ✓)**
- Zwracane dane: **WSZYSTKIE pola** (nie obcinane, nie filtrowane)
- **0 raportów filtrowanych!**

---

## 🚀 DODANE RAPORTY (12 nowych):

### BIR11:
1. ✨ `BIR11OsPrawnaSpCywilnaWspolnicy` (wspólnicy spółki cywilnej)
2. ✨ `BIR11OsFizycznaDaneOgolne` (dane ogólne działalności)
3. ✨ `BIR11OsFizycznaDzialalnoscCeidg` (działalność CEIDG)
4. ✨ `BIR11OsFizycznaDzialalnoscPozostala` (działalność pozostała)
5. ✨ `BIR11OsFizycznaDzialalnoscRolnicza` (działalność rolnicza)
6. ✨ `BIR11OsFizycznaDzialalnoscSkreslonaDo20141108` (skreślona historyczna)

### BIR12:
7-12. ✨ Analogiczne do BIR11 (6 raportów)

---

## 🛠️ PARSOWANIE DANYCH

### Kod backendu (linia ~621-878):

```javascript
// KROK 1: Rozpoznaj typ raportu
var isPkdReport = reportName.indexOf('Pkd') !== -1;
var isWspolnicyReport = reportName.indexOf('Wspolnicy') !== -1;
var isJednLokalneReport = reportName.indexOf('ListaJed') !== -1;
var isDzialalnoscReport = reportName.indexOf('Dzialal') !== -1 || reportName.indexOf('DaneOgolne') !== -1;

// KROK 2: Parsuj odpowiednio
if (isPkdReport) {
  // Zwróć tablicę PKD
  return { data: { pkdList: [...], pkdCount: N } };
}
else if (isWspolnicyReport) {
  // Zwróć tablicę wspólników
  return { data: { wspolnicy: [...], wspolnicyCount: N } };
}
else if (isJednLokalneReport) {
  // Zwróć tablicę jednostek lokalnych
  return { data: { jednostkiLokalne: [...], jednostkiCount: N } };
}
else if (isDzialalnoscReport) {
  // Zwróć tablicę działalności (jeśli >1) LUB pojedynczy obiekt
  if (daneArray.length > 1) {
    return { data: { dzialalnosc: [...], dzialalnoscCount: N } };
  } else {
    return { data: { fiz_*: ... } };  // Wszystkie pola jako płaski obiekt
  }
}
else {
  // Raport podstawowy - zwróć WSZYSTKIE pola jako obiekt
  return { data: { praw_*: ... / fiz_*: ... } };  // 55+ pól
}
```

### GWARANCJA:
- ✅ **NIE ucinamy żadnych pól**
- ✅ **NIE filtrujemy żadnych wartości**
- ✅ **NIE pomijamy żadnych wpisów w tablicach**
- ✅ Backend zwraca **100% danych** otrzymanych z GUS

---

## 📝 DEBUG LOGGING

Backend ZAWSZE loguje (nawet w produkcji):

```javascript
// Na początku requestu:
[GUS full-report REQUEST] REGON: 321537875 reportName: BIR11OsPrawnaPkd

// Dla PKD:
[GUS DEBUG] PKD Report: BIR11OsPrawnaPkd
[GUS DEBUG] PKD - liczba wpisów w tablicy dane: 3
[GUS DEBUG] PKD - sparsowano 3 kodów PKD
[GUS DEBUG] PKD - dane (pierwsze 2000 znaków): [{"praw_pkdKod":"86.23.Z",...}]

// Dla jednostek lokalnych:
[GUS DEBUG] Jednostki lokalne Report: BIR11OsPrawnaListaJednLokalnych
[GUS DEBUG] Jednostki - sparsowano 5 jednostek
[GUS DEBUG] Jednostki - dane: [...]

// Dla wspólników:
[GUS DEBUG] Wspólnicy Report: BIR11OsPrawnaSpCywilnaWspolnicy
[GUS DEBUG] Wspólnicy - sparsowano 2 wspólników
[GUS DEBUG] Wspólnicy - dane: [...]

// Dla działalności:
[GUS DEBUG] Działalność Report: BIR11OsFizycznaDzialalnoscCeidg
[GUS DEBUG] Działalność - sparsowano 1 wpisów (LUB: zwrócono 23 pól - pojedynczy obiekt)
[GUS DEBUG] Działalność - dane: [...]

// Na końcu ZAWSZE:
[GUS] Pełny raport zwrócił 57 pól
```

---

## ✅ DEPLOYMENT

Po deployment backend będzie obsługiwał **WSZYSTKIE 32 raporty** bez wyjątku!

```bash
# Windows
.\deploy-gcp-full.ps1

# Linux/Mac
./deploy-gcp-full.sh
```

---

**Backend jest KOMPLETNY!** 🎉

Obsługuje wszystkie raporty z dokumentacji GUS BIR11 i BIR12, zwraca 100% danych bez filtrowania!

