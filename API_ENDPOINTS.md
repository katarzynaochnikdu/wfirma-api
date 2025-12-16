# wFirma API - Dokumentacja Endpointów

## Autoryzacja

Wszystkie endpointy wymagają nagłówka:
```
X-API-Key: [MAKE_RENDER_API_KEY]
Content-Type: application/json
```

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
        "vat_rate": "23"
      }
    ]
  }
}
```

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
      "vat_rate": "23"
    }
  ]
}
```

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
| 401 | Brak autoryzacji (niepoprawny X-API-Key lub brak tokenu) |
| 404 | Nie znaleziono (kontrahent, faktura) |
| 500 | Błąd serwera |

---

## Wymagane scopes OAuth2 (wFirma)

```
invoices-read,invoices-write,contractors-read,contractors-write
```

Dla pełnej funkcjonalności:
```
companies-read,contractors-read,contractors-write,goods-read,goods-write,invoice_descriptions-read,invoice_deliveries-read,invoice_deliveries-write,invoices-read,invoices-write,payments-read,payments-write,series-read,series-write
```
