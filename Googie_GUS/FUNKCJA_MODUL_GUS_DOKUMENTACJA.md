# 📘 DOKUMENTACJA: Automatyczny zapis do modułu GUS

**Data:** 2025-11-13  
**Wersja:** 2.1 - Moduł GUS

---

## 🎯 ZASADA DZIAŁANIA

### ✅ REGUŁA: 1 firma z "Siedziba" = 1 rekord GUS

```
Firma A w Accounts:
  ├─ Cecha: "Siedziba"
  ├─ NIP: 8513176694
  └─ [MUSI MIĆ] → Dokładnie 1 rekord w module GUS
  
Firma B w Accounts:
  ├─ Cecha: "Filia"
  ├─ NIP: 8513176694
  └─ [NIE MA] → Brak rekordu w module GUS (filia nie tworzy rekordu)
```

---

## 🔄 CO WIDGET ROBI (nowy flow):

### KROK 1: Pobierz dane z GUS
```
1. Sprawdź duplikaty NIP
2. Pobierz dane podstawowe (name-by-nip)
3. Wykryj typ: F (fizyczna) vs P (prawna)
4. Pobierz pełny raport (BIR11OsPrawna / BIR11OsFizycznaDaneOgolne)
5. Pobierz kody PKD (BIR11OsPrawnaPkd / BIR11OsFizycznaPkd)
```

### KROK 2: Zapisz w module GUS (NOWE!)
```
6. Sprawdź czy firma ma cechę "Siedziba"
   ├─ TAK → Kontynuuj
   └─ NIE (Filia) → Pomiń zapis do GUS
   
7. Szukaj istniejący rekord GUS po NIP
   ├─ Znaleziono → Aktualizuj istniejący
   └─ Brak → Utwórz nowy rekord
   
8. Zmapuj WSZYSTKIE dane:
   - Formy prawne (podstawowa, szczególna)
   - Finansowanie i własność
   - Organy (założycielski, rejestrowy)
   - Daty (powstania, wpisu, zawieszenia, etc.)
   - Kontakt (telefon, email, www)
   - Adres siedziby (ulica, miasto, województwo)
   - WSZYSTKIE kody PKD (jako tekst)
   - Checkboxy PKD (dla konkretnych kodów)
   - Dane osoby fizycznej (nazwisko, imię)
   
9. Zapisz w module GUS
```

### KROK 3: Wyświetl tabelę porównania
```
10. Pokaż tabele z danymi do zapisu w Accounts
11. Użytkownik wybiera pola i zapisuje
```

---

## 📊 JAKIE DANE TRAFIAJĄ DO MODUŁU GUS

### Przykład dla osoby prawnej (NIP: 8513176694):

```javascript
{
  // === PODSTAWOWE ===
  Name: "851-317-66-94",  // GUS - numer NIP (pole główne)
  REGON: "321537875",
  KRS: "0000513541",
  Nazwa_firmy: "DERMADENT SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ SPÓŁKA KOMANDYTOWA",
  Firmy: "751364000020824054",  // ID rekordu Accounts (powiązanie)
  
  // === FORMY PRAWNE ===
  Podstawowa_forma_prawna: "OSOBA PRAWNA",
  Szczegolna_forma_prawna: "SPÓŁKA KOMANDYTOWA",
  Kod_i_nazwa_podstawowej_formy_prawnej: "1 - OSOBA PRAWNA",
  Kod_i_nazwa_szczegolnej_formy_prawnej: "101 - SPÓŁKA KOMANDYTOWA",
  P_rodz_dzialalnosci: true,  // Checkbox
  F_rodz_dzialalnosci: false,
  
  // === FINANSOWANIE I WŁASNOŚĆ ===
  Forma_finansowania: "JEDNOSTKA SEKTORA PRYWATNEGO",
  Forma_wlasnosci: "WŁASNOŚĆ PRYWATNA KRAJOWA OSÓB FIZYCZNYCH",
  Kod_i_nazwa_formy_wlasnosci: "214 - WŁASNOŚĆ PRYWATNA...",
  
  // === ORGANY ===
  Organ_zalozycielski: "0 - BRAK",
  Organ_rejestrowy: "070 - SĄD REJONOWY SZCZECIN-CENTRUM W SZCZECINIE",
  Rodzaj_rejestru_lub_ewidencji: "138 - REJESTR PRZEDSIĘBIORCÓW W KRS",
  
  // === DATY ===
  Data_powstania: "2014-06-13",
  data_rozpoczecia_dzialalnosci: "2014-06-13",
  data_wpisu_do_REGON: "2014-07-01",
  data_wpisu_do_rejestru_lub_ewidencji: "2014-06-13",
  data_zawieszenia_dzialalnosci: "",
  data_wznowienia_dzialalnosci: "",
  data_zakonczenia_dzialalnosci: "",
  data_skreslenia_z_REGON: "",
  
  // === KONTAKT ===
  REGON_numer_telefonu: "914619999",
  REGON_adres_email: "kontakt@dermadent.pl",
  REGON_adres_www: "www.dermadent.pl",
  
  // === ADRES SIEDZIBY ===
  Siedziba_Ulica: "ul. Kazimierza Królewicza",
  Siedziba_Nr_domu: "2L",
  Siedziba_Nr_lokalu: "1",
  Siedziba_Miejscowosc: "Szczecin",
  Siedziba_Kod_pocztowy: "71-552",
  Siedziba_Gmina: "Szczecin",
  Siedziba_Powiat: "Szczecin",
  Siedziba_Wojewodztwo: "zachodniopomorskie",
  Siedziba_Ulica_dom_lokal: "ul. Kazimierza Królewicza 2L/1",
  
  // === JEDNOSTKI LOKALNE ===
  Liczba_jednostek_lokalnych: 5,
  
  // === KODY PKD ===
  PKD1_kod: "86.23.Z",  // Główny PKD
  PKD1_nazwa: "Praktyka lekarska dentystyczna",
  
  // Wszystkie PKD jako tekst (max 32000 znaków)
  Wszystkie_kody_PKD: "★ [GŁÓWNY] 86.23.Z - Praktyka lekarska dentystyczna\n47.73.Z - Sprzedaż detaliczna wyrobów farmaceutycznych\n32.50.Z - Produkcja urządzeń medycznych",
  
  // Checkboxy dla konkretnych PKD (tylko jeśli kod pasuje)
  PKD_8623Z: true,  // 86.23.Z → PKD_8623Z
  PKD_4773Z: true,  // 47.73.Z → PKD_4773Z
  PKD_3250Z: true   // 32.50.Z → PKD_3250Z
}
```

### Przykład dla osoby fizycznej (NIP: 8882712183):

```javascript
{
  Name: "888-271-21-83",
  REGON: "365335338",
  Nazwa_firmy: "GETADVENTURE MAŁGORZATA BRENDA",
  
  // Dane osoby fizycznej (nazwisko, imię)
  REGON_Nazwisko: "BRENDA",
  REGON_Imie: "MAŁGORZATA",
  REGON_Drugie_imie: "JOLANTA",
  
  Podstawowa_forma_prawna: "OSOBA FIZYCZNA",
  P_rodz_dzialalnosci: false,
  F_rodz_dzialalnosci: true,  // Checkbox zaznaczony
  
  Data_powstania: "2015-01-15",
  data_wpisu_do_REGON: "2016-09-07",
  
  // PKD dla osoby fizycznej
  Wszystkie_kody_PKD: "★ [GŁÓWNY] 47.91.Z - Sprzedaż detaliczna...\n79.11.Z - Działalność agencji...",
  PKD_4791Z: true,
  PKD_7911Z: true,
  
  ... wszystkie inne pola
}
```

---

## 📋 CO ZOSTAŁO DODANE

### 1. **Nowy plik:** `app/js/gus-module.js`

Zawiera funkcje:
- `findGusRecordForAccount(accountId, nip)` - szuka istniejący rekord GUS
- `buildGusModuleData(gusData, accountId)` - mapuje dane GUS → pola modułu GUS
- `createOrUpdateGusRecord(accountId, gusData)` - tworzy lub aktualizuje rekord

### 2. **Zmiany w:** `app/js/main.js`

Po pobraniu danych z GUS (linia ~185-209):
```javascript
// Sprawdź czy firma ma cechę "Siedziba"
if (CONFIG.adresWRekordzie.indexOf('Siedziba') !== -1) {
  // Zapisz w module GUS
  var result = await createOrUpdateGusRecord(CONFIG.currentRecordId, baseData);
  
  if (result.created) {
    appendLog('✓ Utworzono nowy rekord GUS');
  } else {
    appendLog('✓ Zaktualizowano rekord GUS');
  }
}
```

### 3. **Zmiany w:** `app/widget.html`

Dodano `<script src="js/gus-module.js"></script>` (linia 133)

### 4. **Zmiany w:** `app/js/config.js`

Dodano `CONSTANTS.MODULES.GUS = 'GUS'` (linia 90)

---

## 🔍 CO BĘDZIE W LOGACH

### Dla firmy z cechą "Siedziba":
```
[GUS] ========== KODY PKD POBRANE ==========
[GUS] Liczba kodów PKD: 3
[GUS] ★ [GŁÓWNY] PKD 86.23.Z: Praktyka lekarska dentystyczna
[GUS]   PKD 47.73.Z: Sprzedaż detaliczna...
[GUS] ========================================

[GUS-MODULE] Firma ma cechę "Siedziba" - zapisuję dane do modułu GUS
[GUS-MODULE] === ZAPIS DO MODUŁU GUS ===
[GUS-MODULE] Szukam rekordu GUS po NIP: 8513176694
[GUS-MODULE] Nie znaleziono rekordu GUS dla firmy 751364000020824054
[GUS-MODULE] Brak istniejącego rekordu - tworzę nowy
[GUS-MODULE] Przygotowano 48 pól do zapisu
[GUS-MODULE] Przykładowe pola: Name, REGON, KRS, Nazwa_firmy, Podstawowa_forma_prawna, ...
[GUS-MODULE] ✓ Utworzono nowy rekord GUS: 751364000099999999
```

### Przy kolejnym pobraniu (rekord już istnieje):
```
[GUS-MODULE] Szukam rekordu GUS po NIP: 8513176694
[GUS-MODULE] Znaleziono istniejący rekord GUS: 751364000099999999
[GUS-MODULE] Aktualizuję rekord...
[GUS-MODULE] ✓ Rekord GUS zaktualizowany pomyślnie!
```

### Dla firmy z cechą "Filia":
```
[GUS-MODULE] Firma NIE ma cechy "Siedziba" - pomijam zapis do modułu GUS
```

---

## ⚙️ JAK TO DZIAŁA

### 1. **Wyszukiwanie rekordu GUS:**
```javascript
// Szuka po NIP (pole Name w module GUS)
var criteria = '(Name:equals:851-317-66-94)';
var results = await searchRecords('GUS', criteria);

if (results.length > 0) {
  // Rekord istnieje - aktualizuj
} else {
  // Rekord nie istnieje - utwórz nowy
}
```

### 2. **Mapowanie danych:**

Backend zwraca pola z prefiksem `praw_*` (prawna) lub `fiz_*` (fizyczna):
```javascript
// Z backendu:
{
  "praw_podstawowaFormaPrawna_Symbol": "1",
  "praw_podstawowaFormaPrawna_Nazwa": "OSOBA PRAWNA"
}

// Do modułu GUS:
{
  "Podstawowa_forma_prawna": "OSOBA PRAWNA",
  "Kod_i_nazwa_podstawowej_formy_prawnej": "1 - OSOBA PRAWNA"
}
```

### 3. **Kody PKD:**

```javascript
// Z backendu (tablica):
{
  "pkdList": [
    {"praw_pkdKod": "86.23.Z", "praw_pkdNazwa": "Praktyka...", "praw_pkdPrzewazajace": "1"},
    {"praw_pkdKod": "47.73.Z", "praw_pkdNazwa": "Sprzedaż...", "praw_pkdPrzewazajace": "0"}
  ]
}

// Do modułu GUS:
{
  "PKD1_kod": "86.23.Z",  // Pierwszy (główny)
  "PKD1_nazwa": "Praktyka...",
  
  // Wszystkie jako tekst (textarea)
  "Wszystkie_kody_PKD": "★ [GŁÓWNY] 86.23.Z - Praktyka...\n47.73.Z - Sprzedaż...",
  
  // Checkboxy (dla konkretnych kodów)
  "PKD_8623Z": true,  // 86.23.Z → PKD_8623Z (kropki i myślniki usunięte)
  "PKD_4773Z": true   // 47.73.Z → PKD_4773Z
}
```

---

## 📊 ZMAPOWANE POLA (48+ pól!)

| Kategoria | Pola modułu GUS | Źródło (backend) |
|-----------|-----------------|------------------|
| **Identyfikatory** | Name, REGON, KRS | nip, regon, praw_numerWRejestrzeEwidencji |
| **Nazwa** | Nazwa_firmy | nazwa |
| **Formy prawne** | Podstawowa_forma_prawna, Szczegolna_forma_prawna | praw_podstawowaFormaPrawna_Nazwa, praw_szczegolnaFormaPrawna_Nazwa |
| **Finansowanie** | Forma_finansowania, Forma_wlasnosci | praw_formaFinansowania_Nazwa, praw_formaWlasnosci_Nazwa |
| **Organy** | Organ_zalozycielski, Organ_rejestrowy | praw_organZalozycielski_Nazwa, praw_organRejestrowy_Nazwa |
| **Rejestr** | Rodzaj_rejestru_lub_ewidencji | praw_rodzajRejestruEwidencji_Nazwa |
| **Typ** | P_rodz_dzialalnosci, F_rodz_dzialalnosci | typ (P/F) |
| **Daty** | Data_powstania, data_rozpoczecia_dzialalnosci, ... | praw_dataPowstania, praw_dataRozpoczeciaDzialalnosci, ... |
| **Kontakt** | REGON_numer_telefonu, REGON_adres_email, REGON_adres_www | praw_numerTelefonu, praw_adresEmail, praw_adresStronyinternetowej |
| **Adres** | Siedziba_Ulica, Siedziba_Miejscowosc, ... | praw_adSiedzUlica_Nazwa, praw_adSiedzMiejscowosc_Nazwa, ... |
| **Jednostki** | Liczba_jednostek_lokalnych | praw_liczbaJednLokalnych |
| **PKD** | PKD1_kod, PKD1_nazwa, Wszystkie_kody_PKD | pkdList[0], pkdList (wszystkie) |
| **PKD (checkboxy)** | PKD_8610Z, PKD_8621Z, PKD_8623Z, ... | Automatycznie zaznaczane na podstawie kodów |
| **Osoba fizyczna** | REGON_Nazwisko, REGON_Imie, REGON_Drugie_imie | fiz_nazwisko, fiz_imie1, fiz_imie2 |

---

## 🧪 TESTOWANIE

### Test 1: Nowa firma z "Siedziba"

1. Otwórz widget w rekordzie Accounts
2. Upewnij się że `Adres_w_rekordzie = "Siedziba"` lub "Siedziba i Filia"
3. Wpisz NIP: `8513176694`
4. Kliknij "Pobierz dane z GUS"
5. **W logach zobaczysz:**
   ```
   [GUS-MODULE] Firma ma cechę "Siedziba" - zapisuję dane do modułu GUS
   [GUS-MODULE] Szukam rekordu GUS po NIP: 8513176694
   [GUS-MODULE] Nie znaleziono rekordu GUS
   [GUS-MODULE] Brak istniejącego rekordu - tworzę nowy
   [GUS-MODULE] Przygotowano 48 pól do zapisu
   [GUS-MODULE] ✓ Utworzono nowy rekord GUS: 751364000099999999
   ```

6. **Sprawdź w Zoho CRM:**
   - Przejdź: Moduły → GUS
   - Znajdź rekord z Name = "851-317-66-94"
   - Sprawdź czy wszystkie pola są wypełnione!

### Test 2: Aktualizacja istniejącego rekordu

1. Otwórz ponownie widget w tym samym rekordzie
2. Wpisz ten sam NIP: `8513176694`
3. **W logach zobaczysz:**
   ```
   [GUS-MODULE] Znaleziono istniejący rekord GUS: 751364000099999999
   [GUS-MODULE] Aktualizuję rekord...
   [GUS-MODULE] ✓ Rekord GUS zaktualizowany pomyślnie!
   ```

### Test 3: Firma z cechą "Filia" (nie tworzy rekordu)

1. Otwórz widget w rekordzie z `Adres_w_rekordzie = "Filia"`
2. Wpisz NIP
3. **W logach zobaczysz:**
   ```
   [GUS-MODULE] Firma NIE ma cechy "Siedziba" - pomijam zapis do modułu GUS
   ```

---

## ⚠️ WYMAGANIA

### W Zoho CRM musi istnieć:
- ✅ Moduł **GUS** (custom module)
- ✅ Wszystkie pola z `GUS_fields.csv` utworzone
- ✅ Pole **Firmy** (multiselectlookup) wskazujące na moduł **Accounts**

### Uprawnienia API:
- ✅ Widget musi mieć uprawnienia do **tworzenia** rekordów w module GUS
- ✅ Widget musi mieć uprawnienia do **aktualizacji** rekordów w module GUS

---

## 🎯 PODSUMOWANIE

**Widget teraz automatycznie:**
1. ✅ Pobiera WSZYSTKIE dane z GUS (formy prawne, PKD, kontakt, daty)
2. ✅ Zapisuje w module GUS (dla firm z cechą "Siedziba")
3. ✅ Aktualizuje istniejące rekordy (1 firma = 1 rekord GUS)
4. ✅ Pomija filie (nie tworzą własnych rekordów GUS)
5. ✅ Zaznacza checkboxy PKD automatycznie
6. ✅ Formatuje wszystkie dane poprawnie (daty, NIP, telefon)

**Dane z GUS są teraz dostępne w 2 miejscach:**
- 📋 **Accounts** - podstawowe dane (nazwa, adres, NIP, REGON, KRS)
- 📚 **GUS** - **WSZYSTKIE** dane z systemu REGON (formy prawne, PKD, kontakt, daty, organy, etc.)

---

**Otwórz widget i przetestuj!** 🚀

