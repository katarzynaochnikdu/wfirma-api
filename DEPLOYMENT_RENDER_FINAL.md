# 🚀 DEPLOYMENT RENDER - FINALNA KONFIGURACJA

## ✅ CO ZOSTAŁO NAPRAWIONE

### Kluczowy problem: Brak wrapperów w API requests

Wszystkie funkcje w `app.py` zostały poprawione:

1. ✅ `wfirma_add_contractor()` - dodany wrapper `"contractors"`
2. ✅ `wfirma_create_invoice()` - dodany wrapper `"invoices"`  
3. ✅ `wfirma_get_company_id()` - nowa funkcja (pobiera ID Twojej firmy)
4. ✅ `wfirma_get_invoice_pdf()` - zmieniony endpoint + poprawna struktura
5. ✅ `wfirma_send_invoice_email()` - zmieniony endpoint + wrapper

---

## 🔐 AUTOMATYCZNE ODŚWIEŻANIE TOKENA (JUŻ DZIAŁA!)

`app.py` ma już wbudowany mechanizm:

```python
def load_token():
    # 1. Sprawdza czy token istnieje
    # 2. Sprawdza czy jest ważny (expires_at)
    # 3. Jeśli wygasł → używa refresh_token
    # 4. Zapisuje nowy token do pliku
    # 5. Aktualizuje WFIRMA_REFRESH_TOKEN w Render ENV
```

### Jak to działa na Render:

```
1. Pierwszy deploy → brak tokenu → musisz przejść do /auth
2. Po autoryzacji → zapisuje refresh_token do ENV
3. Każdy restart/redeploy → automatycznie odświeża z refresh_token
4. Przez ~30 dni NIE MUSISZ ponownie autoryzować!
```

---

## 📋 ZMIENNE ŚRODOWISKOWE NA RENDER

Masz już te zmienne (z Twojego screenshota):

```bash
CLIENT_ID=017bd7d64f9c90ea409d84a69ffb9ab0
CLIENT_SECRET=26b10097dcd5911ac1302f549f8f952d
GUS_API_KEY=(Twój klucz GUS)
REDIRECT_URI=(URL Twojej aplikacji + /callback)
REDIRECT_URI_TEMP=(opcjonalne)
RENDER_API_KEY=(opcjonalne)
RENDER_SERVICE_ID=(opcjonalne)
```

### ⚠️ WAŻNE: Po pierwszym deploy dodaj:

```bash
WFIRMA_REFRESH_TOKEN=(zostanie auto-uzupełnione po pierwszej autoryzacji)
```

---

## 🎯 GŁÓWNY ENDPOINT

### POST `/api/workflow/create-invoice-from-nip`

**Co robi:**
1. Pobiera `company_id` (ID Twojej firmy z wFirma)
2. Sprawdza czy kontrahent o danym NIP istnieje
3. Jeśli NIE → pobiera dane z GUS → dodaje do wFirma
4. Wystawia fakturę z podanymi pozycjami
5. Pobiera PDF i zapisuje w `invoices/faktura_{id}.pdf`
6. Wysyła email z fakturą

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

**Response (sukces):**
```json
{
  "success": true,
  "contractor_created": false,
  "contractor": {
    "id": "170307729",
    "name": "Hs1 Sp. z o. o.",
    "nip": "6682018672"
  },
  "invoice": {
    "id": "421314833",
    "fullnumber": "FV 7/2025",
    "total": "1.23",
    "netto": "1.00"
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

## 🔧 PIERWSZE URUCHOMIENIE NA RENDER

### Krok 1: Deploy aplikacji
```bash
git add .
git commit -m "Fixed wFirma API wrappers"
git push
```

### Krok 2: Autoryzacja (TYLKO RAZ!)
1. Otwórz w przeglądarce: `https://your-app.onrender.com/auth`
2. Zaloguj się do wFirma i autoryzuj
3. Zostaniesz przekierowany na `/callback`
4. `refresh_token` zostanie **automatycznie zapisany** do ENV `WFIRMA_REFRESH_TOKEN`

### Krok 3: Gotowe!
Od teraz każdy restart/redeploy:
- ✅ Automatycznie odświeży token z `WFIRMA_REFRESH_TOKEN`
- ✅ Działa przez ~30 dni bez ponownej autoryzacji
- ✅ Po 30 dniach musisz powtórzyć Krok 2

---

## 📁 STRUKTURA FOLDERÓW NA RENDER

```
/opt/render/project/src/
├── app.py                    ← Główny serwer (POPRAWIONY ✅)
├── requirements.txt          ← Zależności
├── wfirma_token.json         ← Auto-generowany przy starcie
└── invoices/                 ← PDF faktury (auto-tworzony)
    ├── faktura_421314833.pdf
    └── ...
```

---

## 🎯 TESTOWANIE WORKFLOW

### Opcja A: Postman/Insomnia

```
POST https://your-app.onrender.com/api/workflow/create-invoice-from-nip
Headers:
  Authorization: Bearer {access_token}
  Content-Type: application/json

Body: (przykład wyżej)
```

### Opcja B: Python script

```python
import requests

response = requests.post(
    "https://your-app.onrender.com/api/workflow/create-invoice-from-nip",
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    },
    json={
        "nip": "6682018672",
        "email": "klient@example.com",
        "send_email": True,
        "invoice": {
            "positions": [
                {
                    "name": "Test",
                    "quantity": 1,
                    "unit": "szt.",
                    "unit_price_net": 100.00,
                    "vat_rate": "23"
                }
            ]
        }
    }
)

print(response.json())
```

---

## 🔑 KLUCZOWE ZMIANY - PODSUMOWANIE

### Przed (❌ INPUT ERROR):
```python
{"invoice": {"contractor_id": 123}}
```

### Po (✅ DZIAŁA):
```python
{"invoices": {"invoice": {"contractor_id": 123}}}
```

**To samo dla:**
- `contractors` (dodawanie/szukanie)
- `invoices` (wystawianie)
- Wszystkie inne moduły

---

## 🎉 GOTOWE DO DEPLOYMENTU!

Wszystko przetestowane lokalnie i działa:
- ✅ Wyszukiwanie kontrahentów po NIP
- ✅ Dodawanie z GUS (automatyczne)
- ✅ Wystawianie faktur
- ✅ Pobieranie PDF do folderu `invoices/`
- ✅ Wysyłanie emailem
- ✅ Automatyczne odświeżanie tokena

**Zmień `REDIRECT_URI` w Render na adres Twojej aplikacji i zrób pierwszy `/auth`!** 🚀

