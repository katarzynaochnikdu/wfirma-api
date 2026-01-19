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

## 🏢 wFirma (faktury) - prefiks MD_

| Zmienna | Opis |
|---------|------|
| `MD_CLIENT_ID` | OAuth2 Client ID dla wFirma |
| `MD_CLIENT_SECRET` | OAuth2 Client Secret |
| `MD_ACCESS_TOKEN` | Token dostępu (auto-odświeżany) |
| `MD_REFRESH_TOKEN` | Token odświeżania (ważny ~360 dni) |
| `MD_TOKEN_EXPIRES` | Timestamp wygaśnięcia access token |
| `MD_REFRESH_TOKEN_EXPIRES` | Timestamp wygaśnięcia refresh token |

### Dodatkowe wFirma
| Zmienna | Opis | Domyślnie |
|---------|------|-----------|
| `WFIRMA_COMPANY` | Firma (md lub test) | `md` |
| `WFIRMA_SERIES_NAME` | Seria faktur | `FV/EV` |
| `WFIRMA_AUTH_URL_MD` | URL autoryzacji | auto |
| `WFIRMA_TOKEN_NOTIFY_EMAIL` | Email do powiadomień o tokenie | `adam.pragacz@medidesk.com` |

---

## 🔍 GUS/BIR (dane firm z REGON)

| Zmienna | Opis |
|---------|------|
| `GUS_API_KEY` | Klucz API do BIR/GUS (produkcja) |
| `GUS_USE_TEST` | Użyj testowego API GUS | `false` (zawsze!) |

---

## 📧 Powiadomienia

| Zmienna | Opis |
|---------|------|
| `BACKSTAGE_TECHNICAL_INFO_EMAIL` | Email do powiadomień technicznych (błędy itp.) |
| `EMAIL_REFRESH_TOKEN_EXPIRE` | Email do powiadomień o wygasającym tokenie |
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
MD_CLIENT_ID=...
MD_CLIENT_SECRET=...
MD_ACCESS_TOKEN=auto
MD_REFRESH_TOKEN=auto

# Powiadomienia
BACKSTAGE_TECHNICAL_INFO_EMAIL=adminzoho@medidesk.com
```

---

*Ostatnia aktualizacja: 19 stycznia 2026*
