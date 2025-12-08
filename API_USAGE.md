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
- **`unit_price_net`** - cena netto za jednostkę
- **`vat_rate`** - stawka VAT ("23", "8", "0", "zw", "np")

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

