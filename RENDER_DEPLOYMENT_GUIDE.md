# 🚀 Deployment na Render - wFirma API

## ✅ CO ZOSTAŁO NAPRAWIONE

### Kluczowe odkrycie: WSZYSTKIE requesty wymagają wrappera modułu!

#### ❌ PRZED (nie działało):
```json
{
  "invoice": { ... }
}
```

#### ✅ PO (działa):
```json
{
  "invoices": {
    "invoice": { ... }
  }
}
```

### Poprawione funkcje w `app.py`:

1. **`wfirma_add_contractor()`** - dodany wrapper `"contractors"`
2. **`wfirma_create_invoice()`** - dodany wrapper `"invoices"`
3. **`wfirma_get_invoice_pdf()`** - zmieniony endpoint z `/print` na `/download` + poprawna struktura
4. **`wfirma_send_invoice_email()`** - zmieniony endpoint z `/invoice_deliveries/send` na `/invoices/send` + poprawna struktura parametrów
5. **`wfirma_get_company_id()`** - nowa funkcja do pobierania ID firmy

---

## 📋 ENDPOINTY API

### 🚀 Główny Workflow (All-in-One)
```
POST /api/workflow/create-invoice-from-nip
```

**Request:**
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
      }
    ]
  }
}
```

**Co robi:**
1. ✅ Sprawdza czy kontrahent istnieje w wFirma (po NIP)
2. ✅ Jeśli nie ma - pobiera dane z GUS
3. ✅ Dodaje kontrahenta do wFirma
4. ✅ Wystawia fakturę
5. ✅ Pobiera PDF i zapisuje w `invoices/faktura_{id}.pdf`
6. ✅ Wysyła email z fakturą

**Response:**
```json
{
  "success": true,
  "contractor_created": false,
  "contractor": { "id": "170307729", "name": "Hs1 Sp. z o. o.", ... },
  "invoice": { "id": "421314833", "fullnumber": "FV 7/2025", ... },
  "email_sent": true,
  "email_response": { "status": { "code": "OK" } },
  "pdf_saved": "invoices/faktura_421314833.pdf"
}
```

---

### 📄 Osobne Endpointy

#### Pobierz PDF faktury
```
GET /api/invoice/<invoice_id>/pdf
```
Zwraca plik PDF do pobrania.

#### Wyślij fakturę emailem
```
POST /api/invoice/<invoice_id>/send
Body: {"email": "klient@example.com"}
```

#### Sprawdź kontrahenta po NIP
```
GET /api/contractor/<nip>
```

#### Pobierz dane z GUS
```
POST /api/gus/name-by-nip
Body: {"nip": "1234567890"}
```

---

## ⚙️ ZMIENNE ŚRODOWISKOWE (Render)

W panelu Render ustaw:

```bash
# wFirma OAuth 2.0 (WYMAGANE)
CLIENT_ID=017bd7d64f9c90ea409d84a69ffb9ab0
CLIENT_SECRET=26b10097dcd5911ac1302f549f8f952d
REDIRECT_URI=https://your-app.onrender.com/callback

# GUS API (WYMAGANE do pobierania danych firm)
GUS_API_KEY=your_gus_api_key
GUS_USE_TEST=false

# Render API (OPCJONALNE - do persystencji tokenów)
RENDER_API_KEY=
RENDER_SERVICE_ID=
```

---

## 🔧 LOKALNE TESTOWANIE

### 1. Uruchom serwer Flask:
```bash
py app.py
```
Serwer wystartuje na `http://localhost:5000`

### 2. Autoryzuj aplikację:
Otwórz w przeglądarce: `http://localhost:5000/auth`

### 3. Testuj workflow:
```bash
py test_workflow_local.py
```

---

## 📁 STRUKTURA FOLDERÓW

```
APIV1/
├── app.py                          ← Serwer Flask (POPRAWIONY)
├── diagnose_oauth_full.py          ← Diagnostyka (100% działa)
├── wfirma_token.json               ← Token OAuth (auto-generowany)
├── invoices/                       ← Folder na PDF faktury
│   ├── faktura_421314833.pdf
│   └── ...
└── test_workflow_local.py          ← Test lokalny
```

---

## 🎯 KLUCZOWE ZMIANY W STRUKTURZE API

### 1. Wyszukiwanie kontrahenta (contractors/find)
```python
{
  "contractors": {
    "parameters": {
      "conditions": {
        "condition": {
          "field": "nip",
          "operator": "eq",
          "value": "6682018672"
        }
      }
    }
  }
}
```

### 2. Dodawanie kontrahenta (contractors/add)
```python
{
  "contractors": {  # ← WRAPPER!
    "contractor": {
      "name": "Firma ABC",
      "nip": "1234567890",
      "tax_id_type": "nip",
      "street": "ul. Testowa 1",
      "zip": "00-001",
      "city": "Warszawa",
      "country": "PL"
    }
  }
}
```

### 3. Wystawienie faktury (invoices/add)
```python
{
  "invoices": {  # ← WRAPPER!
    "invoice": {
      "contractor_id": 170307729,
      "type": "normal",
      "invoicecontents": {
        "invoicecontent": [
          {
            "name": "Usługa",
            "count": 1,
            "unit": "szt.",
            "price": 100.00,
            "vat": "23"
          }
        ]
      }
    }
  }
}
```

### 4. Pobieranie PDF (invoices/download/{id})
```python
POST /invoices/download/{invoice_id}?company_id={company_id}
Body: {
  "invoices": {
    "parameters": {
      "parameter": [
        {"name": "page", "value": "invoice"}
      ]
    }
  }
}
```

### 5. Wysyłanie emailem (invoices/send/{id})
```python
POST /invoices/send/{invoice_id}?company_id={company_id}
Body: {
  "invoices": {
    "parameters": [
      {"parameter": {"name": "email", "value": "klient@example.com"}},
      {"parameter": {"name": "subject", "value": "Faktura"}},
      {"parameter": {"name": "page", "value": "invoice"}},
      {"parameter": {"name": "body", "value": "Treść wiadomości"}}
    ]
  }
}
```

---

## 🎉 WSZYSTKO DZIAŁA!

Workflow został przetestowany i działa w 100%:
- ✅ Wyszukiwanie kontrahentów
- ✅ Dodawanie z GUS
- ✅ Wystawianie faktur
- ✅ Pobieranie PDF
- ✅ Wysyłanie emailem

**Gotowe do deploymentu na Render!** 🚀

