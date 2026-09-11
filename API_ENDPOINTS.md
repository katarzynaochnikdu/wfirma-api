# wFirma API - Dokumentacja Endpointów

## Korekta struktury biletów — WO-599C2b2, v1 (LOCAL / NOT RELEASED)

Te dwa endpointy są oddzielne od starszego `/api/workflow/correction`.
Nie aktywować przed integracją trwałej blokady wysyłki w portalu (WO-599C2b3)
i bramką wydania. Sam `id_external` NIE zapewnia idempotencji w wFirma.
Nie wykonywać przykładowych żądań na prawdziwych dokumentach.

### Odczyt rodzica

`GET /api/workflow/participant-change-correction/parent/<invoice_id>?company=md_test`

Wymaga `X-API-Key`, jawnej firmy `md|md_test|test` i jej OAuth. Bez domyślnej
firmy, powtórzonych lub dodatkowych parametrów. `md_test` jest nadal prawdziwym
kontem Medidesk, NIE izolowaną bazą testową. Odczyt nie wysyła dokumentów.
HTTP 200: `{success:true, parent:{...}, parent_sha256:"..."}`, `Cache-Control:no-store`.
Przechowaj całą projekcję i SHA razem; nie odtwarzaj jej z sum zamówienia.

Projekcja obejmuje wersję, ID/typ dokumentu, firmę, nabywcę/odbiorcę i hash
ich danych, epokę ceny, PLN, dowód terminalności, powiązanie z poprzednim
dokumentem, `id_external`, wszystkie pozycje oraz trzy sumy w groszach.
Pozycja: ID, ewentualne ID poprzedniej pozycji, nazwa, jednostka, liczba,
cena sztuki w epoce rodzica, kod VAT i netto/VAT/brutto całej linii.
SHA-256: posortowane klucze JSON, UTF-8, bez białych znaków i NaN.

### Utworzenie korekty i ścisły odczyt kontrolny

`POST /api/workflow/participant-change-correction`, `Content-Type:application/json`.
API-key i firmowy OAuth jak wyżej. Zamknięty zestaw wymaganych pól:

| Pole | Znaczenie |
|---|---|
| `contract_version` | liczba całkowita `1` |
| `company`, `change_id` | jawna firma; trwałe ID zmiany z portalu |
| `parent`, `parent_sha256` | pełny wynik poprzedniego GET i jego SHA |
| `issue_date` | data ISO `YYYY-MM-DD` |
| `series_id`, `series_name` | obie wartości sprawdzane w tej samej firmie |
| `correction_reason` | niepusty opis, maksymalnie 500 bajtów UTF-8 |
| `price_model`, `currency` | `netto|brutto` zgodne z rodzicem; `PLN` |
| `positions` | kompletny stan pozycji po zmianie (1..500) |
| `after_totals` | dokładne `net_grosze`, `vat_grosze`, `gross_grosze` |

Przykładowe dwie pozycje w epoce netto (same pozycje, nie pełny request):

```json
[
  {"kind":"existing","line_key":"conference","parent_position_id":"8101",
   "quantity":1,"unit_price_grosze":10000,"vat_rate_code":"23"},
  {"kind":"new","line_key":"banquet","name":"Bankiet testowy","unit":"szt.",
   "quantity":1,"unit_price_grosze":5000,"vat_rate_code":"23"}
]
```

Sumy tego przykładu: 15000 netto + 3450 VAT = 18450 brutto. Każda stara
pozycja występuje dokładnie raz; zmiana ilości do zera pozostawia pozycję
w korekcie. Stare nazwy, jednostki, VAT i cena sztuki nie są przepisywane.
Zmiana ceny istniejącego biletu wymaga wyzerowania starej i nowej linii,
nie podziału kwoty proporcjonalnie. Nowa linia nie może mieć `parent_position_id`.

Przed wysłaniem: świeży odczyt całego rodzica i serii, porównanie projekcji/SHA
i wszystkich sum. Potem dokładnie jeden `invoices/add` (30 s, bez redirectów),
odczyt nowego dokumentu i porównanie firmy, stron, rodzica, serii, epoki,
identyfikatora zmiany, pozycji oraz trzech sum. GET-y mają limit 8 s / 2 MiB.
Brak PDF, emaila i ponawiania create. Obecny wspólny create transport ma
ograniczony czas, ale nie limit rozmiaru odpowiedzi (istniejące ograniczenie).

Sukces 200: `{success:true, contract_version:1, invoice_id:"...",
correction_invoice:{id:"...",fullnumber:"..."}, proof:{parent:{...},
parent_sha256:"...",position_mapping:[{line_key:"...",position_id:"..."}],
equivalent_position_groups:[{line_keys:["a","b"],position_ids:["1","2"]}]}}`.
Nowa projekcja jest rodzicem następnej korekty; mapowanie korzysta z treści
i powiązań, nigdy z kolejności zwróconej przez dostawcę.
Jawne powiązania parent_id są sprawdzane jako pierwsze. Jeżeli pozostałe linie
są jednakowe i dostawca nie zwrócił powiązań, `equivalent_position_groups`
potwierdza tylko równość całej grupy. NIE jest to przypisanie konkretnej osoby
do konkretnego ID. Każdy line_key i nowe ID występuje raz w mapping albo grupie.
Identyczne pozycje zachowują osobne ilości i zaokrąglenia — nie scala się ich.

Odmowy mają `success:false`, stały kod `error` i `outcome`. Przed create:
`rejected`; timeout / odpowiedź bez ID: `unknown`; istniejące ścisłe przypadki
przejściowej odmowy: `retryable`; znane ID i nieweryfikowalny wynik:
`created_unverified` (ID dołączane tylko, gdy kanoniczne). HTTP 409/502 NIE
upoważnia do ponowienia. Nie wolno przejść awaryjnie do starszego endpointu.
Auth: 401 brak klucza, 403 błędny klucz, 503 niedostępny OAuth/konfiguracja.

### Granice v1 i wymagania integratora

- Żądanie do 1 MiB, maks. 500 pozycji, ilość całkowita 0..5000 (nowa >0),
  pieniądze jako całkowite grosze 0..2^63-1. VAT: `23|8|5|0|zw|np`.
- Netto: VAT zaokrąglany od netto całej linii. Brutto: netto zaokrąglane
  od brutto całej linii. Nigdy `netto/brutto` dostawcy jako cena sztuki.
- Brak `price_type` oznacza wyłącznie historyczne netto; pusta/obca wartość
  jest odmową. Brak terminalności `corrections=0` też oznacza odmowę.
- Natywne rabaty na pozycji dostawcy, ułamkowe ilości, waluty inne niż PLN
  i nieznane kształty paginacji są odmawiane. Identyczne sygnatury przyjmowane
  tylko jako udowodniony multizbiór; brak parent_id nie pozwala zgadnąć ID osoby.
- W obrębie istniejących pozycji nie zmieniamy ceny jednostkowej. Przy upgrade
  integrator planuje ilość starej pozycji i jawne dodanie nowej.
- Caller jest właścicielem trwałej kolejki, blokady zamówienia i zapisu
  rozpoczętej wysyłki PRZED HTTP. Ponowne wywołanie tego endpointu może
  utworzyć kolejny dokument — sam endpoint nie jest trwałym deduplikatorem.
- Testy są syntetyczne, bez prawdziwego wFirma. Kontrakt wymaga kontrolowanego
  testu na dozwolonym wydarzeniu sandbox przed dopuszczeniem wydania.

## Wywołanie z zewnątrz (Make.com, Postman, curl, integracje)

Aby wywoływać endpointy tworzenia faktur, proform i korekt **z zewnątrz**, potrzebujesz:

| Potrzebne | Opis |
|-----------|------|
| **URL aplikacji** | Np. `https://wfirma-api.onrender.com` (produkcja) lub Twój adres Render |
| **Klucz API** | Wartość zmiennej środowiskowej **`MAKE_RENDER_API_KEY`** (ustawiona w Render ENV lub w `.env`) |

**Żadne inne zmienne** (np. `WFIRMA_SERVICE_URL`, `WFIRMA_SERVICE_API_KEY`) **nie są używane** przy wywołaniach z zewnątrz. Autoryzacja do wFirma (OAuth2) odbywa się po stronie serwera; klient tylko przekazuje `X-API-Key`.

### Przykład wywołania (curl)

```bash
# Faktura VAT
curl -X POST "https://wfirma-api.onrender.com/api/workflow/create-invoice-from-nip" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: TWOJ_MAKE_RENDER_API_KEY" \
  -d '{"company":"md","nip":"1234567890","document_type":"normal","payment_status":"paid","invoice":{"positions":[{"name":"Usługa","quantity":1,"unit_price_net":100,"vat_rate":"23"}]}}'

# Proforma
curl -X POST "https://wfirma-api.onrender.com/api/workflow/create-invoice-from-nip" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: TWOJ_MAKE_RENDER_API_KEY" \
  -d '{"company":"md","nip":"1234567890","document_type":"proforma","payment_due_days":7,"invoice":{"positions":[{"name":"Zaliczka","quantity":1,"unit_price_net":500,"vat_rate":"23"}]}}'

# Korekta (wymaga parent_invoice_id = ID faktury oryginalnej w wFirma)
curl -X POST "https://wfirma-api.onrender.com/api/workflow/correction" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: TWOJ_MAKE_RENDER_API_KEY" \
  -d '{"company":"md","parent_invoice_id":12345,"positions":[{"parent_position_id":67890,"name":"Pozycja po korekcie","quantity":1,"unit_price_net":80,"vat_rate":"23"}]}'
```

W Make.com: ustaw w module HTTP **Header** `X-API-Key` na wartość `MAKE_RENDER_API_KEY` z ENV (lub wpisaną w scenariuszu).

### Zmienne środowiskowe w Renderze (ENV)

Te zmienne ustawiasz w **Render Dashboard → Service → Environment** i one definiują ścieżki oraz klucze do wywołań:

| Zmienna w Render ENV | Definiuje | Przykład / Uwagi |
|----------------------|-----------|-------------------|
| **`MAKE_RENDER_API_KEY`** | Klucz do nagłówka `X-API-Key` przy wywołaniach z zewnątrz (faktury, proformy, korekty, webhooki) | Dowolny bezpieczny string (np. wygenerowany UUID). Tę samą wartość podajesz w headerze `X-API-Key`. |
| **`WFIRMA_MD_REDIRECT_URI`** | Pełny URL callbacku OAuth wFirma (musi być zgodny z adresem Twojej aplikacji na Render) | `https://twoja-aplikacja.onrender.com/callback` – zamiast `twoja-aplikacja` wpisujesz nazwę swojego serwisu z Render. |

**Adres bazowy aplikacji (ścieżki)** nie jest trzymany w osobnej zmiennej – wynika z adresu serwisu w Render (np. `https://wfirma-api.onrender.com`). Endpointy to np.:

- `https://<twoja-aplikacja>.onrender.com/api/workflow/create-invoice-from-nip`
- `https://<twoja-aplikacja>.onrender.com/api/workflow/correction`

Inne zmienne (np. `WFIRMA_MD_CLIENT_ID`, `WFIRMA_MD_CLIENT_SECRET`) są potrzebne do działania wFirma po stronie serwera, ale **nie** do samego wywoływania endpointów z zewnątrz – z zewnątrz wystarczy **URL serwisu + `MAKE_RENDER_API_KEY`** w nagłówku.

---

## Autoryzacja

Wszystkie endpointy workflow (faktury, proformy, korekty) wymagają nagłówka:
```
X-API-Key: [wartość MAKE_RENDER_API_KEY]
Content-Type: application/json
```

Dla dwóch workflow objętych WO-502 błędy bramek autoryzacji są błędami przed create,
więc zachowują dotychczasowe `error`, `message` i status, a dostają
`success: false, outcome: "rejected"`:

| Przypadek | HTTP |
|---|---|
| brak nagłówka `X-API-Key` | `401` |
| podany, ale błędny `X-API-Key` | `403` |
| brak albo nieważny token OAuth w workflow korekty | `401` |

Udany `OPTIONS` po spełnieniu bramek zwraca `200 {"status":"ok"}` bez `success` i bez
`outcome`; nie wykonuje POST-u tworzącego dokument.

### Budżety transportowe readback i OAuth (WO-504A0)

| Transport | Maksymalny czas jednego requestu | Retry wewnętrzny | Zachowanie po awarii |
|---|---:|---|---|
| `GET invoices/get/<invoice_id>` | `8 s` | brak — dokładnie jeden GET | Helper zachowuje `(None, error)`. `GET /api/invoice/<invoice_id>` zachowuje dotychczasowe `404` oraz klucze `error/details`. Readback po otrzymaniu ID dokumentu kończy workflow jako `created_unverified`, bez drugiego create. |
| `POST https://api2.wfirma.pl/oauth2/token` | `15 s` | brak — dokładnie jeden POST | Timeout/awaria zwraca `None`, nie zapisuje tokenu i zwalnia advisory lock. Autoryzowany ręczny `POST /api/token/refresh` zachowuje `500`, a automatyczna bramka `@require_token` zachowuje `401`. |

Dane OAuth są wysyłane wyłącznie w body `data=`. `client_secret` i `refresh_token` nie
trafiają do URL-a ani logów. Access token i jego fragment nie są zwracane ani logowane;
log diagnostyczny zapisu zawiera wyłącznie nieodwracalny fingerprint. Surowe body błędu
OAuth również nie jest logowane, ponieważ zewnętrzna odpowiedź może odbić przesłany sekret.
Z tego samego powodu ścieżka refreshu nie loguje treści ani tracebacku wyjątku oraz nie
wylicza nazw kluczy odpowiedzi dostawcy; używa wyłącznie stałych markerów i statusu HTTP.

Ręczne odświeżenie jest operacją zmieniającą stan, dlatego kanoniczny i jedyny dozwolony
entrypoint to `POST /api/token/refresh?company=md&force=true` z nagłówkiem `X-API-Key`.
`GET` zwraca `405`. Brak klucza w `POST` zwraca standardowe `401`, błędny klucz `403`,
a oba przypadki kończą się przed odczytem Postgresa, advisory lockiem, OAuth POST-em i
zapisem tokenu. Klucz jest porównywany stałoczasowo. Udana odpowiedź zawiera wyłącznie
`success`, `message` i `company`; nie zawiera `access_token_preview`.

Po przejściu autoryzacji budżety czasu nie zmieniają pozostałych statusów HTTP ani
klasyfikacji `outcome`.

### Ścisły odczyt recovery dokumentu (WO-507A2-S)

Portal ma osobne, wewnętrzne wejście proof-only:

```http
GET /api/recovery/invoice/<invoice_id>?company=md|test|md_test
X-API-Key: <MAKE_RENDER_API_KEY>
```

`company` jest obowiązkowe i może wystąpić dokładnie raz. Endpoint nie używa firmy
domyślnej i nie wyszukuje firmy przez `companies/find`: przyjmuje wyłącznie przypięte
`WFIRMA_<COMPANY>_COMPANY_ID` albo znane ID `md`. `md_test` jawnie korzysta z credentiali
i ID firmy `md`, ale zachowuje etykietę `md_test` w proofie. Konto `test` bez przypiętego
`WFIRMA_TEST_COMPANY_ID` jest fail-closed (`503`).

Po autoryzacji wykonywane są wyłącznie:

1. jeden `GET invoices/get/<invoice_id>`;
2. jeden `GET series/get/<series_id>`;
3. jeden `GET contractors/get/<buyer_id>`;
4. opcjonalnie jeden `GET contractors/get/<receiver_id>`.

Każdy request ma 8 s timeout, `allow_redirects=False`, brak retry oraz limit 2 MiB
zdekompresowanego JSON. Sukces wymaga dokładnie jednego obiektu w każdej odpowiedzi i
zgodności wszystkich ID z żądaniem lub relacją dokumentu. Endpoint nie wykonuje
providerowego POST/PATCH/PUT/DELETE, wyszukania, maila ani PDF.

Sukces:

```json
{
  "success": true,
  "proof": {
    "version": 1,
    "company": "md",
    "company_id": "130706",
    "invoice": {},
    "series": {},
    "contractor": {},
    "receiver": null
  }
}
```

Proof zawiera pełny odczyt potrzebny portalowi do porównania z zamrożonym intentem i jest
przeznaczony wyłącznie dla zaufanego backendu. Portal nie może przekazywać tych surowych
danych do UI. Odpowiedzi błędów są zamknięte i nie zawierają treści ani wyjątków wFirma:
`400 invalid_request`, `401 oauth_unavailable`, `503 recovery_configuration_unavailable`,
`404 document_not_found` lub `502 recovery_read_unavailable`.

---

## Wynik tworzenia dokumentu (WO-502)

Poniższy kontrakt obowiązuje oba produkcyjne workflow:

- [`POST /api/workflow/create-invoice-from-nip`](app.py);
- [`POST /api/workflow/correction`](app.py).

Nieudana odpowiedź zachowuje dotychczasowe pola i status HTTP, a dodatkowo zawiera
`success: false` oraz dokładnie jedno pole `outcome`:

```json
{
  "success": false,
  "outcome": "rejected",
  "error": "Brak sekcji invoice"
}
```

| Sytuacja | `outcome` | Status HTTP | Czy wolno ponowić create? |
|---|---|---|---|
| Walidacja lokalna przed pierwszym `invoices/add` albo jawny błąd dowodzący, że dokument nie powstał | `rejected` | Zachowany status ścieżki; walidacja requestu `400` | Nie automatycznie. Najpierw napraw dane albo przyczynę odrzucenia. |
| Dokładny, znormalizowany komunikat tymczasowej blokady batch KSeF z zamkniętej allowlisty | `retryable` | Zachowane `500` workflow korekty | Tak, ale wyłącznie jako opóźnione ponowienie wdrożone przez WO-503. |
| Timeout, zerwane połączenie, `5xx`, brak odpowiedzi, uszkodzone `HTTP 200` albo brak rozstrzygającego ID | `unknown` | Zachowany status ścieżki; timeout invoice workflow `502` | **Nie.** Dokument mógł powstać — najpierw uzgodnij stan z wFirmą. |
| Otrzymano ID dokumentu, ale później zawiódł readback Odbiorcy/kwoty, inna weryfikacja albo wysyłka maila | `created_unverified` | Zachowany status ścieżki; błąd readback Odbiorcy `502` | **Nie.** Nie wysyłaj nowego create; dokument już ma ID. |

Zamknięta allowlista `retryable` zawiera jeden komunikat:

```text
Nie można wystawić korekty do faktury w trakcie wysyłki wsadowej do KSeF
```

Normalizacja obejmuje wielkość liter oraz zewnętrzne/powielone białe znaki. Substring
`KSeF`, podobne zdanie, inna interpunkcja lub brak znaków diakrytycznych nie wystarcza.
Exact match jest sprawdzany przed ogólną klasyfikacją `5xx`; każdy inny `5xx` daje `unknown`.

Reguły konsumenta są zamknięte:

1. Tylko `retryable` zezwala na późniejsze, automatyczne ponowienie create.
2. `unknown` i `created_unverified` bezwzględnie blokują nowy create.
3. Brak albo nierozpoznana wartość `outcome` jest traktowana fail-closed jak `unknown`.
4. Mikroserwis wykonuje najwyżej jeden POST `invoices/add` na request i nie ponawia go wewnętrznie.
5. Transport tworzący dokument lub korektę ma timeout `30 s`; timeout zawsze oznacza `unknown`.
6. HTTP status nie zastępuje `outcome` i nie może samodzielnie sterować retry.

Sukces zachowuje dotychczasowy kształt i **nie zawiera** pola `outcome`:

```json
{
  "success": true
}
```

WO-502 publikuje kontrakt mikroserwisu. Backend portalu zacznie go konsumować, utrwalać i
planować delayed retry dopiero w WO-503; do tego czasu wdrożenie samego WO-502 nie uruchamia
automatycznych ponowień.

### Epoki ceny pozostają rozłączne

| Epoka | Request workflow | Payload `invoices/add` |
|---|---|---|
| netto | pomija `price_mode`; pozycje zawierają wyłącznie `unit_price_net` | pomija `price_type` |
| brutto | jawnie zawiera `price_mode: "brutto"`; pozycje zawierają wyłącznie `unit_price_gross` | jawnie zawiera `price_type: "brutto"` |

Korekta dziedziczy epokę dokumentu rodzica: rodzic netto nie dostaje `price_type`, a rodzic
brutto dostaje `price_type: "brutto"`. `outcome` nie zależy od bieżącej flagi ceny.

---

## 1. Tworzenie dokumentów sprzedaży

### `POST /api/workflow/create-invoice-from-nip`

Tworzy fakturę, proformę, notę księgową lub paragon.

#### Parametry:

| Parametr | Typ | Wymagany | Domyślnie | Opis |
|----------|-----|----------|-----------|------|
| `company` | string | Nie | `"md"` | Firma: `md`, `test`, `md_test` |
| `nip` | string | Warunkowo* | - | NIP kontrahenta (10 cyfr) |
| `purchaser_name` | string | Warunkowo* | - | Nazwa kontrahenta (jeśli brak NIP) |
| `purchaser_address` | string | Nie | - | Adres kontrahenta |
| `purchaser_zip` | string | Nie | - | Kod pocztowy |
| `purchaser_city` | string | Nie | - | Miasto |
| `document_type` | string | Nie | `"normal"` | Typ dokumentu (patrz tabela poniżej) |
| `series_name` | string | Nie | `"Eventy"` | Nazwa serii numeracji |
| `payment_status` | string | Nie | `"unpaid"` | `"paid"` lub `"unpaid"` |
| `payment_due_days` | int | Nie | - | Dni do terminu płatności |
| `issue_date` | string | Nie | dzisiaj | Data wystawienia (YYYY-MM-DD) |
| `description` | string | Nie | - | Komentarz/opis na dokumencie |
| `ereceipt_email` | string | Nie | - | Email do e-paragonu (tylko dla paragonów) |
| `email` | string | Nie | - | Email do wysyłki faktury |
| `send_email` | bool | Nie | `false` | Czy wysłać emailem |
| `price_mode` | string | Nie | netto (brak klucza) | Dla epoki brutto jawnie `"brutto"`; netto zachowuje brak klucza |
| `invoice` | object | **TAK** | - | Dane dokumentu (pozycje) |

*Wymagany `nip` LUB `purchaser_name`

#### Typy dokumentów (`document_type`):

| Wartość | Dokument |
|---------|----------|
| `normal` | Faktura VAT (domyślnie) |
| `proforma` | Faktura pro forma |
| `proforma_bill` | Pro forma bez VAT |
| `accounting_note` | Nota księgowa |
| `receipt_fiscal_normal` | Paragon fiskalny |

#### Struktura `invoice`:

```json
{
  "invoice": {
    "positions": [
      {
        "name": "Nazwa usługi/produktu",
        "quantity": 1,
        "unit_price_net": 100.00,
        "vat_rate": "23",
        "unit": "szt."
      }
    ]
  }
}
```

Pola pozycji:
| Pole | Typ | Wymagany | Domyślnie | Opis |
|------|-----|----------|-----------|------|
| `name` | string | Tak | - | Nazwa pozycji (np. nazwa biletu, usługi) |
| `quantity` | number | Tak | - | Ilość |
| `unit_price_net` | number | Warunkowo | - | Cena netto za jednostkę; wymagana i jedyna w epoce netto |
| `unit_price_gross` | number | Warunkowo | - | Cena brutto za jednostkę; wymagana i jedyna przy `price_mode: "brutto"` |
| `vat_rate` | string | Tak | - | Stawka VAT (patrz tabela poniżej) |
| `unit` | string | Nie | `"szt."` | Jednostka miary |

#### Stawki VAT (`vat_rate`):
- `"23"` - 23%
- `"8"` - 8%
- `"5"` - 5%
- `"0"` - 0%
- `"zw"` - zwolniony
- `"np"` - nie podlega

---

### Przykłady wywołań:

#### Faktura VAT (opłacona):
```json
{
  "company": "md",
  "nip": "1234567890",
  "document_type": "normal",
  "series_name": "Eventy",
  "payment_status": "paid",
  "description": "Konferencja IT 2025",
  "invoice": {
    "positions": [
      {
        "name": "Udział w konferencji",
        "quantity": 1,
        "unit_price_net": 500.00,
        "vat_rate": "23"
      }
    ]
  }
}
```

#### Faktura VAT (nieopłacona, termin 14 dni):
```json
{
  "company": "md",
  "nip": "1234567890",
  "document_type": "normal",
  "payment_status": "unpaid",
  "payment_due_days": 14,
  "invoice": {
    "positions": [
      {
        "name": "Usługa konsultingowa",
        "quantity": 2,
        "unit_price_net": 250.00,
        "vat_rate": "23"
      }
    ]
  }
}
```

#### Faktura pro forma:
```json
{
  "company": "md",
  "nip": "1234567890",
  "document_type": "proforma",
  "payment_due_days": 7,
  "invoice": {
    "positions": [
      {
        "name": "Zaliczka na usługę",
        "quantity": 1,
        "unit_price_net": 1000.00,
        "vat_rate": "23"
      }
    ]
  }
}
```

#### Nota księgowa:
```json
{
  "company": "md",
  "nip": "1234567890",
  "document_type": "accounting_note",
  "series_name": "Noty",
  "invoice": {
    "positions": [
      {
        "name": "Kara umowna",
        "quantity": 1,
        "unit_price_net": 500.00,
        "vat_rate": "zw"
      }
    ]
  }
}
```

#### Paragon fiskalny (e-paragon):
```json
{
  "company": "md",
  "purchaser_name": "Jan Kowalski",
  "document_type": "receipt_fiscal_normal",
  "ereceipt_email": "jan.kowalski@example.com",
  "invoice": {
    "positions": [
      {
        "name": "Produkt X",
        "quantity": 2,
        "unit_price_net": 81.30,
        "vat_rate": "23"
      }
    ]
  }
}
```

#### Faktura bez NIP (dane ręczne):
```json
{
  "company": "md",
  "purchaser_name": "Katarzyna Ochnik",
  "document_type": "normal",
  "payment_status": "paid",
  "invoice": {
    "positions": [
      {
        "name": "Usługa",
        "quantity": 1,
        "unit_price_net": 100.00,
        "vat_rate": "23"
      }
    ]
  }
}
```

**Uwaga:** Jeśli nie podasz danych adresowych, zostaną użyte domyślne:
- `purchaser_address` → `-`
- `purchaser_zip` → `00-000`
- `purchaser_city` → `-`

#### Faktura bez NIP z pełnymi danymi:
```json
{
  "company": "md",
  "purchaser_name": "Jan Kowalski",
  "purchaser_address": "ul. Testowa 123",
  "purchaser_zip": "00-001",
  "purchaser_city": "Warszawa",
  "document_type": "normal",
  "payment_status": "unpaid",
  "payment_due_days": 14,
  "invoice": {
    "positions": [
      {
        "name": "Usługa",
        "quantity": 1,
        "unit_price_net": 100.00,
        "vat_rate": "23"
      }
    ]
  }
}
```

#### Tryb testowy (z ostrzeżeniem na fakturze):
```json
{
  "company": "test",
  "nip": "1234567890",
  "document_type": "normal",
  "description": "Konferencja testowa",
  "invoice": {
    "positions": [
      {
        "name": "Test",
        "quantity": 1,
        "unit_price_net": 100.00,
        "vat_rate": "23"
      }
    ]
  }
}
```

---

## 2. Faktura korygująca

### `POST /api/workflow/correction`

Tworzy fakturę korygującą do istniejącej faktury.

#### Parametry:

| Parametr | Typ | Wymagany | Opis |
|----------|-----|----------|------|
| `company` | string | Nie | Firma: `md`, `test`, `md_test` |
| `parent_invoice_id` | int | **TAK** | ID faktury oryginalnej |
| `correction_reason` | string | Nie | Powód korekty |
| `positions` | array | **TAK** | Pozycje korekty |
| `issue_date` | string | Nie | Data wystawienia |
| `series_name` | string | Nie | Seria numeracji |

#### Struktura `positions`:

```json
{
  "positions": [
    {
      "parent_position_id": 67890,
      "name": "Nazwa (po korekcie)",
      "quantity": 1,
      "unit_price_net": 80.00,
      "vat_rate": "23",
      "unit": "szt."
    }
  ]
}
```

Pola pozycji korekty: `parent_position_id` (wymagane), `name`, `quantity`, `vat_rate` oraz
dokładnie jedno pole ceny zgodne z epoką rodzica: `unit_price_net` dla netto albo
`unit_price_gross` dla brutto; opcjonalnie `unit` (domyślnie `"szt."`). Epoki nie wybiera
bieżąca flaga ani request korekty — mikroserwis odczytuje ją z dokumentu rodzica.

#### Przykład:
```json
{
  "company": "md",
  "parent_invoice_id": 12345,
  "correction_reason": "Błąd w cenie usługi",
  "positions": [
    {
      "parent_position_id": 67890,
      "name": "Usługa (cena skorygowana)",
      "quantity": 1,
      "unit_price_net": 80.00,
      "vat_rate": "23"
    }
  ]
}
```

---

### `POST /api/test/correction-payment-flow` (TESTOWY)

Pełna korekta (zerowanie pozycji) + opcjonalne oznaczenie korekty jako rozliczonej. Używa serii **Eventy Korekta TEST**. Do testów na fakturach z serii Eventy Faktura VAT TEST.

| Parametr | Typ | Wymagany | Opis |
|----------|-----|----------|------|
| `parent_invoice_id` | int | **TAK** | ID faktury VAT do skorygowania |
| `mark_correction_settled` | bool | Nie | `true` = oznaczyć korektę jako rozliczoną (alreadypaid_initial na FK) |

```bash
curl -X POST "https://wfirma-api.onrender.com/api/test/correction-payment-flow" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: TWOJ_MAKE_RENDER_API_KEY" \
  -d '{"parent_invoice_id": 12345, "mark_correction_settled": true}'
```

**Uwaga:** Seria „Eventy Korekta TEST” musi istnieć w wFirma (ENV: `WFIRMA_SERIES_CORRECTION_TEST`).

---

## 3. Walidacja NIP (GUS/REGON)

### `POST /api/gus/validate-nip`

Sprawdza poprawność NIP i pobiera dane z GUS/REGON.

#### Parametry:

| Parametr | Typ | Wymagany | Opis |
|----------|-----|----------|------|
| `nip` | string | **TAK** | NIP do sprawdzenia |

#### Przykład wywołania:
```json
{
  "nip": "1234567890"
}
```

#### Możliwe odpowiedzi:

**Brak NIP:**
```json
{
  "nip_status": "brak",
  "nip_provided": "",
  "gus_data": null
}
```

**Niepoprawny format (nie 10 cyfr):**
```json
{
  "nip_status": "niepoprawny",
  "nip_provided": "123",
  "nip_cleaned": "123",
  "nip_length": 3,
  "gus_data": null
}
```

**Poprawny NIP, znaleziony w GUS:**
```json
{
  "nip_status": "poprawny",
  "nip": "1234567890",
  "gus_data": {
    "name": "Nazwa Firmy Sp. z o.o.",
    "regon": "123456789",
    "street": "ul. Przykładowa 10/5",
    "zip": "00-001",
    "city": "Warszawa",
    "voivodeship": "mazowieckie",
    "krs": "0000123456"
  }
}
```

**Poprawny NIP, brak w GUS:**
```json
{
  "nip_status": "poprawny",
  "nip": "1234567890",
  "gus_data": null
}
```

---

## 4. Pomocnicze endpointy

### `GET /api/contractor/<nip>`
Pobiera dane kontrahenta z wFirma po NIP.

### `GET /api/series/list`
Lista dostępnych serii numeracji.

### `POST /api/invoice/<invoice_id>/send-email`
Wysyła fakturę emailem.

```json
{
  "email": "klient@example.com"
}
```

---

## 5. Firmy (`company`)

| Wartość | Opis |
|---------|------|
| `md` | Medidesk produkcja |
| `test` | Konto testowe (z ostrzeżeniem na fakturach) |
| `md_test` | Medidesk produkcja + ostrzeżenie testowe |

Dla `test` i `md_test` na fakturach pojawia się ostrzeżenie:
```
!!! FAKTURA NIEWAŻNA - TRYB TESTOWY !!!
*** DOKUMENT WYSTAWIONY W CELACH TESTOWYCH ***
*** NIE STANOWI PODSTAWY DO ZAPŁATY ***
```

---

## Kody błędów

| Kod | Opis |
|-----|------|
| 200 | Sukces |
| 400 | Błąd walidacji (brak wymaganych pól) |
| 401 | Brak `X-API-Key` albo brak/nieważny token OAuth |
| 403 | Podany, ale niepoprawny `X-API-Key` |
| 404 | Nie znaleziono (kontrahent, faktura) |
| 500 | Błąd serwera |

Statusy pozostają kompatybilne wstecz. Dla dwóch workflow tworzących dokument decyzję o
retry podejmuje się na podstawie `outcome`, nie samego kodu HTTP — patrz
[„Wynik tworzenia dokumentu (WO-502)”](#wynik-tworzenia-dokumentu-wo-502).

---

## Wymagane scopes OAuth2 (wFirma)

```
invoices-read,invoices-write,contractors-read,contractors-write
```

Dla pełnej funkcjonalności:
```
companies-read,contractors-read,contractors-write,goods-read,goods-write,invoice_descriptions-read,invoice_deliveries-read,invoice_deliveries-write,invoices-read,invoices-write,payments-read,payments-write,series-read,series-write
```
