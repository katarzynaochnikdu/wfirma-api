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

| Zmienna | Opis |
|---------|------|
| `WFIRMA_MD_CLIENT_ID` | OAuth2 Client ID dla wFirma (lub `CLIENT_ID` jako fallback) |
| `WFIRMA_MD_CLIENT_SECRET` | OAuth2 Client Secret (lub `CLIENT_SECRET` jako fallback) |
| `WFIRMA_MD_ACCESS_TOKEN` | Token dostępu (auto-odświeżany) |
| `WFIRMA_MD_REFRESH_TOKEN` | Token odświeżania (ważny ~360 dni) |
| `WFIRMA_MD_TOKEN_EXPIRES` | Timestamp wygaśnięcia access token |
| `WFIRMA_MD_REFRESH_TOKEN_EXPIRES` | Timestamp wygaśnięcia refresh token |

**Alternatywnie (fallback):** `CLIENT_ID`, `CLIENT_SECRET` - używane gdy brak WFIRMA_MD_*

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

## 🔧 Render (auto-update ENV)

| Zmienna | Opis |
|---------|------|
| `RENDER_API_KEY` | API key Render (do aktualizacji ENV) |
| `RENDER_SERVICE_ID` | ID serwisu na Render |

---

## 🔐 Inne (opcjonalne)

| Zmienna | Opis |
|---------|------|
| `REDIRECT_URI` | URL callback OAuth | `https://wfirma-api.onrender.com/callback` |
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

# wFirma (po autoryzacji /auth?company=md)
WFIRMA_MD_CLIENT_ID=...      # lub CLIENT_ID
WFIRMA_MD_CLIENT_SECRET=...  # lub CLIENT_SECRET
WFIRMA_MD_ACCESS_TOKEN=auto  # wypełni się po /auth
WFIRMA_MD_REFRESH_TOKEN=auto # wypełni się po /auth

# Powiadomienia
BACKSTAGE_TECHNICAL_INFO_EMAIL=adminzoho@medidesk.com  # błędy
BACKSTAGE_EVENT_INFO_EMAIL=eventy@medidesk.com        # zamówienia/płatności
```

---

*Ostatnia aktualizacja: 19 stycznia 2026*
