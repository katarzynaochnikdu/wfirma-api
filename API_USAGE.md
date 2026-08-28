# 📘 JAK UŻYWAĆ API - PROSTY PRZEWODNIK

## 🚀 GŁÓWNY ENDPOINT (All-in-One)

### `POST /api/workflow/create-invoice-from-nip`

**Jeden request robi WSZYSTKO:**
1. ✅ Sprawdza kontrahenta w wFirma po NIP
2. ✅ Jeśli nie ma → pobiera dane z GUS → dodaje do wFirma
3. ✅ Wystawia fakturę z pozycjami
4. ✅ Pobiera PDF → zapisuje w `invoices/faktura_{id}.pdf`
5. ✅ Wysyła email z fakturą (jeśli podano)

---

## 📥 REQUEST

```json
{
  "nip": "6682018672",
  "email": "klient@example.com",
  "send_email": true,
  "invoice": {
    "positions": [
      {
        "name": "Konsultacja IT",
        "quantity": 2,
        "unit": "godz.",
        "unit_price_net": 150.00,
        "vat_rate": "23"
      },
      {
        "name": "Hosting roczny",
        "quantity": 1,
        "unit": "szt.",
        "unit_price_net": 500.00,
        "vat_rate": "23"
      }
    ]
  }
}
```

### Pola:
- **`nip`** (WYMAGANE) - NIP kontrahenta (10 cyfr)
- **`email`** (opcjonalne) - email do wysyłki faktury
- **`send_email`** (opcjonalne) - `true`/`false` - czy wysłać email
- **`invoice.positions`** (WYMAGANE) - lista pozycji faktury

#### Pozycja faktury:
- **`name`** - nazwa usługi/produktu
- **`quantity`** - ilość
- **`unit`** - jednostka (szt., godz., mb, itp.)
- **`unit_price_net`** - cena netto za jednostkę; jedyne pole ceny w domyślnej epoce netto
- **`unit_price_gross`** - cena brutto za jednostkę; jedyne pole ceny przy top-level
  **`price_mode: "brutto"`**
- **`vat_rate`** - stawka VAT ("23", "8", "0", "zw", "np")

Netto zachowuje kompatybilność: request **pomija** `price_mode`, pozycja zawiera wyłącznie
`unit_price_net`, a mikroserwis pomija `price_type` w payloadzie do wFirmy. Brutto jawnie
przekazuje `price_mode: "brutto"`, używa wyłącznie `unit_price_gross`, a payload do wFirmy
zawiera `price_type: "brutto"`. Nie wolno mieszać obu pól ceny w jednej pozycji.

---

## 📤 RESPONSE (SUKCES)

```json
{
  "success": true,
  "contractor_created": false,
  "contractor": {
    "id": "170307729",
    "name": "Hs1 Sp. z o. o.",
    "nip": "6682018672",
    "city": "Turek"
  },
  "invoice": {
    "id": "421314833",
    "fullnumber": "FV 7/2025",
    "date": "2025-12-08",
    "total": "369.00",
    "netto": "300.00",
    "tax": "69.00",
    "paymentstate": "unpaid",
    "paymentdate": "2025-12-08"
  },
  "email_sent": true,
  "email_response": {
    "status": {
      "code": "OK",
      "message": "Dokument FV 7/2025 został zlecony do wysyłki."
    }
  },
  "pdf_saved": "invoices/faktura_421314833.pdf"
}
```

Pole `outcome` występuje **wyłącznie przy błędzie**. Istniejący sukces pozostaje bez niego.

---

## ⚠️ RESPONSE (BŁĄD) I POLITYKA RETRY — WO-502

Oba endpointy tworzące dokument —
[`create-invoice-from-nip`](app.py#L4075) i [`correction`](app.py#L5269) — dodają do
nieudanej odpowiedzi maszynowe pole `outcome`, zachowując dotychczasowy `error`, pozostałe
pola i status HTTP:

Dotyczy to także bramek przed create: brak `X-API-Key` daje `401/rejected`, błędny klucz
`403/rejected`, a brak lub nieważny token OAuth korekty `401/rejected`. Udany `OPTIONS`
zwraca `200 {"status":"ok"}` bez `success` i bez `outcome`.

```json
{
  "success": false,
  "outcome": "rejected",
  "error": "Brak sekcji invoice"
}
```

| `outcome` | Znaczenie | Działanie konsumenta |
|---|---|---|
| `rejected` | Wiadomo, że dokument nie powstał. | Nie ponawiaj automatycznie. Popraw dane/przyczynę i dopiero wtedy rozpocznij nową, świadomą próbę. |
| `retryable` | Wiadomo, że dokument nie powstał; wystąpiła dokładnie rozpoznana tymczasowa blokada batch KSeF. | Jedyny wynik dopuszczający delayed retry, ale mechanizm powstaje dopiero w WO-503. |
| `unknown` | Nie wiadomo, czy create dotarł do wFirmy albo czy dokument powstał. | **Nie wysyłaj nowego create.** Najpierw uzgodnij stan z wFirmą. |
| `created_unverified` | Mikroserwis otrzymał ID dokumentu, lecz zawiodła późniejsza weryfikacja lub mail. | **Nie wysyłaj nowego create.** Dokument już istnieje albo ma rozstrzygające ID. |

`retryable` jest nadawane tylko dla dokładnego, znormalizowanego komunikatu:

```text
Nie można wystawić korekty do faktury w trakcie wysyłki wsadowej do KSeF
```

Normalizacja obejmuje wielkość liter oraz zewnętrzne/powielone białe znaki. Podobny tekst,
sam substring `KSeF`, inna interpunkcja lub brak znaków diakrytycznych **nie** wystarcza.
To jedyny wyjątek od reguły, że nierozstrzygający `5xx` daje `unknown`.

### Bezpieczna obsługa po stronie klienta

```python
KNOWN_OUTCOMES = {"rejected", "retryable", "unknown", "created_unverified"}

result = response.json()
if result.get("success") is True:
    handle_success(result)  # sukces nie ma pola outcome
else:
    outcome = result.get("outcome")
    if outcome not in KNOWN_OUTCOMES:
        outcome = "unknown"  # fail-closed

    if outcome == "retryable":
        record_for_delayed_retry(result)  # aktywne dopiero po WO-503
    elif outcome == "rejected":
        require_input_or_cause_fix(result)
    else:  # unknown albo created_unverified
        block_new_create_and_reconcile_with_wfirma(result)
```

Nie buduj logiki retry na samym statusie HTTP. Mikroserwis zachowuje dotychczasowe statusy,
wykonuje najwyżej jeden POST `invoices/add` na request i nie ma wewnętrznego retry. Timeout
transportu create wynosi `30 s` i daje `unknown`, ponieważ timeout nie dowodzi braku dokumentu.
Przykłady zachowanych statusów: walidacja `400/rejected`, exact blokada KSeF korekty
`500/retryable`, timeout `502/unknown`, nierozstrzygające `HTTP 200/unknown`, readback
Odbiorcy `502/created_unverified`, a błąd maila po ID `503/created_unverified`.

WO-502 udostępnia wyłącznie kontrakt mikroserwisu. Backend Event Orders Portal zacznie
rozpoznawać `outcome`, utrwalać stan i planować delayed retry dopiero po WO-503. Samo wdrożenie
WO-502 nie uruchamia żadnego automatycznego ponawiania.

---

## 🔧 PRZYKŁADY UŻYCIA

### Python
```python
import requests

response = requests.post(
    "https://your-app.onrender.com/api/workflow/create-invoice-from-nip",
    json={
        "nip": "6682018672",
        "email": "klient@example.com",
        "send_email": True,
        "invoice": {
            "positions": [
                {
                    "name": "Konsultacja IT",
                    "quantity": 2,
                    "unit": "godz.",
                    "unit_price_net": 150.00,
                    "vat_rate": "23"
                }
            ]
        }
    }
)

result = response.json()
print(f"Faktura: {result['invoice']['fullnumber']}")
print(f"PDF: {result['pdf_saved']}")
print(f"Email wysłany: {result['email_sent']}")
```

### cURL
```bash
curl -X POST https://your-app.onrender.com/api/workflow/create-invoice-from-nip \
  -H "Content-Type: application/json" \
  -d '{
    "nip": "6682018672",
    "email": "klient@example.com",
    "send_email": true,
    "invoice": {
      "positions": [
        {
          "name": "Konsultacja",
          "quantity": 1,
          "unit": "godz.",
          "unit_price_net": 200,
          "vat_rate": "23"
        }
      ]
    }
  }'
```

### JavaScript/Fetch
```javascript
const response = await fetch('https://your-app.onrender.com/api/workflow/create-invoice-from-nip', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    nip: '6682018672',
    email: 'klient@example.com',
    send_email: true,
    invoice: {
      positions: [
        {
          name: 'Konsultacja IT',
          quantity: 2,
          unit: 'godz.',
          unit_price_net: 150.00,
          vat_rate: '23'
        }
      ]
    }
  })
});

const result = await response.json();
console.log('Faktura:', result.invoice.fullnumber);
console.log('PDF:', result.pdf_saved);
```

---

## 📁 GDZIE SĄ PLIKI PDF?

Na Render: `/opt/render/project/src/invoices/`

Możesz pobrać przez:
```
GET /api/invoice/{invoice_id}/pdf
```

---

## ⚠️ BŁĘDY I ROZWIĄZANIA

### Błąd: "Brak autoryzacji"
**Rozwiązanie:** Przejdź do `/auth` i autoryzuj aplikację

### Błąd: "GUS nie znalazł firmy"
**Rozwiązanie:** Sprawdź czy NIP jest poprawny (10 cyfr)

### Błąd: "Nie udało się pobrać company_id"
**Rozwiązanie:** Skonfiguruj swoją firmę w panelu wFirma

### Błąd: "Kontrahent nie ma emaila"
**Rozwiązanie:** Podaj `"email": "adres@example.com"` w requeście

---

## 🎯 TO WSZYSTKO!

Jeden endpoint robi całą robotę:
```
NIP → GUS → Kontrahent → Faktura → PDF → Email
```

**Gotowe do użycia! 🚀**
