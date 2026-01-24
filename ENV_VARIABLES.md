# 🔐 ZMIENNE ŚRODOWISKOWE - AKTUALNA LISTA (Styczeń 2026)

## ⚡ KRYTYCZNE (bez nich aplikacja nie działa)

### PostgreSQL
| Zmienna | Opis | Przykład |
|---------|------|----------|
| `DATABASE_URL` | Connection string do PostgreSQL | `postgresql://user:pass@host:5432/db` |

### Stripe (płatności)
| Zmienna | Opis |
|---------|------|
| `STRIPE_RENDER_API_KEY` | Klucz API Stripe (produkcja) |
| `STRIPE_WEBHOOK_SECRET` | Secret do walidacji webhooków Stripe |
| `STRIPE_RENDER_API_KEY_SANDBOX` | Klucz API Stripe (sandbox/test) |
| `STRIPE_SANDBOX_WEBHOOK_SECRET` | Secret webhooków sandbox |

### Make.com (wysyłka emaili)
| Zmienna | Opis |
|---------|------|
| `MAKE_WEBHOOK_SEND_EMAIL_REQUEST` | URL webhooka Make do wysyłki emaili |
| `RENDER_EMAIL_KEY_SEND_REQUEST` | Klucz autoryzacji dla Make |

### API Key (autoryzacja webhooków)
| Zmienna | Opis |
|---------|------|
| `MAKE_RENDER_API_KEY` | Klucz X-API-Key dla webhooków (Zoho, Make) |

---

## 🏢 wFirma (faktury) - prefiks WFIRMA_MD_

| Zmienna | Opis | Wymagane |
|---------|------|----------|
| `WFIRMA_MD_CLIENT_ID` | OAuth2 Client ID dla wFirma (lub `CLIENT_ID` jako fallback) | ✅ |
| `WFIRMA_MD_CLIENT_SECRET` | OAuth2 Client Secret (lub `CLIENT_SECRET` jako fallback) | ✅ |
| `WFIRMA_MD_REDIRECT_URI` | **URL callback OAuth** (np. `https://your-app.onrender.com/callback`) | ✅ **WYMAGANE** |
| `WFIRMA_MD_ACCESS_TOKEN` | Token dostępu (auto-odświeżany) | auto |
| `WFIRMA_MD_REFRESH_TOKEN` | Token odświeżania (ważny ~30 dni) | auto |
| `WFIRMA_MD_TOKEN_EXPIRES` | Timestamp wygaśnięcia access token | auto |
| `WFIRMA_MD_REFRESH_TOKEN_EXPIRES` | Timestamp wygaśnięcia refresh token | auto |

**Alternatywnie (fallback):** `CLIENT_ID`, `CLIENT_SECRET` - używane gdy brak WFIRMA_MD_*

### wFirma TEST (opcjonalne - prefiks WFIRMA_TEST_)

| Zmienna | Opis | Wymagane |
|---------|------|----------|
| `WFIRMA_TEST_CLIENT_ID` | OAuth2 Client ID dla konta testowego | jeśli używasz test |
| `WFIRMA_TEST_CLIENT_SECRET` | OAuth2 Client Secret | jeśli używasz test |
| `WFIRMA_TEST_REDIRECT_URI` | **URL callback OAuth** dla konta testowego | jeśli używasz test |

**WAŻNE:** `WFIRMA_<COMPANY>_REDIRECT_URI` jest **wymagane** dla autoryzacji OAuth. Bez tej zmiennej `/auth` i `/callback` zwrócą błąd 500.

### Dodatkowe wFirma
| Zmienna | Opis | Domyślnie |
|---------|------|-----------|
| `WFIRMA_COMPANY` | Firma (md lub test) | `md` |
| `WFIRMA_SERIES_NAME` | Seria faktur | `FV/EV` |
| `WFIRMA_AUTH_URL_MD` | URL autoryzacji | auto |
| `WFIRMA_TOKEN_EXPIRES_ALERT_EMAIL` | Email do alertów o wygasającym tokenie | `adam.pragacz@medidesk.com` |

---

## 🔍 GUS/BIR (dane firm z REGON)

| Zmienna | Opis | Wymagane |
|---------|------|----------|
| `GUS_API_KEY` | Klucz API do BIR/GUS (produkcja) | ✅ (lub BIR1_medidesk) |
| `BIR1_medidesk` | Alternatywna nazwa klucza GUS (fallback) | opcjonalne |
| `GUS_USE_TEST` | `false` = produkcja, `true` = test | `false` zawsze! |
| `REGON_API_KEY_TOKEN` | Token X-API-Key dla `/api/gus/*` endpointów | dla zewnętrznych wywołań |

**Uwaga:** System szuka klucza w kolejności: `GUS_API_KEY` → `BIR1_medidesk`

---

## 📧 Powiadomienia

| Zmienna | Opis |
|---------|------|
| `BACKSTAGE_TECHNICAL_INFO_EMAIL` | Email do powiadomień o **błędach** (GUS error, email error, payment failed) |
| `BACKSTAGE_EVENT_INFO_EMAIL` | Email do powiadomień o **zamówieniach/płatnościach** (nowe zamówienie, płatność OK) |
| `WFIRMA_TOKEN_EXPIRES_ALERT_EMAIL` | Email do alertów o wygasającym tokenie wFirma (domyślnie: adam.pragacz@medidesk.com) |
| `WEBHOOK_TOKEN_EXPIRE_NOTIFY` | URL webhooka do powiadomień o tokenie |

---

## 🔄 Zoho Flow

| Zmienna | Opis |
|---------|------|
| `ZOHO_FLOW_EVENT_UPDATE_WEBHOOK` | URL webhooka Zoho Flow do synchronizacji aktualizacji wydarzeń z panelu Admin V2 |

---

## 🎪 Zoho Backstage API (pobieranie danych wydarzeń)

| Zmienna | Opis | Wymagane |
|---------|------|----------|
| `BACKSTAGE_CLIENT_ID` | OAuth2 Client ID dla Zoho Backstage | ✅ |
| `BACKSTAGE_CLIENT_SECRET` | OAuth2 Client Secret | ✅ |
| `BACKSTAGE_REFRESH_TOKEN` | Refresh token (długowieczny) | ✅ |
| `BACKSTAGE_PORTAL_ID` | ID portalu Backstage (domyślnie: 20101549222) | opcjonalne |

**Użycie:** Umożliwia pobieranie pełnych danych wydarzenia z Backstage (venue, description, ticket_classes) przez przycisk "Pobierz z Backstage" w panelu Admin V2.

---

## 🔧 Render (auto-update ENV)

| Zmienna | Opis |
|---------|------|
| `RENDER_API_KEY` | API key Render (do aktualizacji ENV) |
| `RENDER_SERVICE_ID` | ID serwisu na Render |

---

## 🔐 Inne (opcjonalne)

| Zmienna | Opis |
|---------|------|
| ~~`REDIRECT_URI`~~ | ⚠️ **DEPRECATED** - użyj `WFIRMA_<COMPANY>_REDIRECT_URI` per firma |
| `GITHUB_STOPKA_TOKEN` | Token GitHub (stopka) |
| `HTML_GENERATOR_API_KEY_TOKEN` | Token HTML generator |
| `REGON_API_KEY_TOKEN` | Alternatywny klucz REGON |

---

## ✅ MINIMALNA KONFIGURACJA DO DZIAŁANIA

```bash
# Database
DATABASE_URL=postgresql://...

# Stripe
STRIPE_RENDER_API_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Make.com
MAKE_WEBHOOK_SEND_EMAIL_REQUEST=https://hook.eu1.make.com/...
MAKE_RENDER_API_KEY=twoj-klucz-api

# GUS
GUS_API_KEY=twoj-klucz-gus

# wFirma (wymagane przed autoryzacją /auth?company=md)
WFIRMA_MD_CLIENT_ID=...                              # lub CLIENT_ID
WFIRMA_MD_CLIENT_SECRET=...                          # lub CLIENT_SECRET
WFIRMA_MD_REDIRECT_URI=https://your-app.onrender.com/callback  # WYMAGANE! Musi zgadzać się z konfiguracją w wFirma
WFIRMA_MD_ACCESS_TOKEN=auto                          # wypełni się po /auth
WFIRMA_MD_REFRESH_TOKEN=auto                         # wypełni się po /auth

# Powiadomienia
BACKSTAGE_TECHNICAL_INFO_EMAIL=adminzoho@medidesk.com  # błędy
BACKSTAGE_EVENT_INFO_EMAIL=eventy@medidesk.com        # zamówienia/płatności
```

---

*Ostatnia aktualizacja: 20 stycznia 2026*
