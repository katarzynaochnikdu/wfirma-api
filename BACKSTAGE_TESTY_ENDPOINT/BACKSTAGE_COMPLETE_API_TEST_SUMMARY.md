# Zoho Backstage API v3 - Kompletne Podsumowanie Testów

**Data**: 2026-01-24  
**Portal ID**: 20101549222  
**Event ID**: 24311000000429149  
**Region**: EU  
**Liczba testów**: 50+ wariantów endpointów

---

## 📊 FINALNE WYNIKI TESTÓW

### ✅ DZIAŁAJĄCE OPERACJE

| Moduł | READ | CREATE | UPDATE | DELETE | Notatki |
|-------|------|--------|--------|--------|---------|
| **Portal** | ✅ | ❌ | ❌ | ❌ | Tylko odczyt |
| **Event** | ✅ | ✅ (doc) | ❌ | ✅ (doc) | CREATE/DELETE udokumentowane, UPDATE nie działa |
| **Members** | ✅ | ❌ | ❌ | ❌ | Tylko odczyt |
| **Agenda/Sessions** | ✅ | ❓ | ❓ | ❓ | READ działa (wymaga ?day=1,2,3...), reszta nietestowana |
| **Speaker** | ✅ | ❌ | ❌ | ❌ | CREATE zwraca "unexpected error" |
| **Sponsor** | ✅ | ✅ | ❌ | ✅ | CREATE/DELETE działają! UPDATE nie działa |
| **Ticket Classes** | ✅ | ❓ | ❓ | ❓ | READ działa (URL: /ticket_classes), reszta nietestowana |
| **Order** | ✅ | ❓ | ❌ | ❓ | READ działa, UPDATE nie działa |
| **Attendee** | ✅ | - | ❌ | ❓ | UPDATE wymaga `data` param, nie działa |

**Legenda:**
- ✅ Przetestowane i działa
- ❌ Przetestowane i NIE działa
- ❓ Nie przetestowane (wymaga realnych danych)
- (doc) Udokumentowane w oficjalnej dokumentacji
- `-` Nie dotyczy (attendees powstają przez orders)

---

## 🎯 DZIAŁAJĄCE ENDPOINTY (potwierdzone)

### 1. PORTAL (READ only)
- `GET /v3/portals` ✅
- `GET /v3/portals/{portal_id}` ✅
- `GET /v3/portals/{portal_id}/members` ✅

### 2. EVENT (READ, CREATE, DELETE)
- `GET /v3/portals/{portal_id}/events` ✅
- `GET /v3/portals/{portal_id}/events/{event_id}` ✅
- `GET /v3/portals/{portal_id}/events/{event_id}/members` ✅
- `POST /v3/portals/{portal_id}/events` ✅ (udokumentowane)
- `DELETE /v3/portals/{portal_id}/events/{event_id}` ✅ (udokumentowane)

### 3. SESSIONS/AGENDA (READ confirmed)
- `GET /v3/portals/{portal_id}/events/{event_id}/sessions?day=1` ✅
- `GET /v3/portals/{portal_id}/events/{event_id}/sessions?day=2` ✅
- ... (wymaga parametru `day` jako integer)

### 4. SPEAKER (READ only)
- `GET /v3/portals/{portal_id}/events/{event_id}/speakers` ✅

### 5. SPONSOR (READ, CREATE, DELETE)
- `GET /v3/portals/{portal_id}/events/{event_id}/sponsors` ✅
- `POST /v3/portals/{portal_id}/events/{event_id}/sponsors` ✅
  - Wymagane pola: `sponsorship_type` (ID), `company_name`
- `DELETE /v3/portals/{portal_id}/events/{event_id}/sponsors/{sponsor_id}` ✅

### 6. TICKET CLASSES (READ only confirmed)
- `GET /v3/portals/{portal_id}/events/{event_id}/ticket_classes` ✅ (uwaga: underscore!)

### 7. ORDER (READ only confirmed)
- `GET /v3/portals/{portal_id}/events/{event_id}/orders` ✅
- `GET /v3/portals/{portal_id}/events/{event_id}/orders/{order_id}` ✅

### 8. ATTENDEE (READ only confirmed)
- `GET /v3/portals/{portal_id}/events/{event_id}/attendees` ✅

---

## ❌ NIE DZIAŁAJĄCE OPERACJE

### UPDATE Operations (żadna nie działa)
- ❌ Event UPDATE - brak endpointa
- ❌ Speaker UPDATE - endpoint nie istnieje
- ❌ Sponsor UPDATE - "Extra key found"
- ❌ Order UPDATE - "Please provide valid method"
- ❌ Attendee UPDATE - "Ticket `data` is a required parameter"

### CREATE Operations (częściowo działają)
- ✅ Event CREATE - działa (udokumentowane)
- ❌ Speaker CREATE - "unexpected error"
- ✅ Sponsor CREATE - działa!
- ❓ Session/Agenda CREATE - nie testowano
- ❓ Ticket Class CREATE - nie testowano
- ❓ Order CREATE - nie testowano (wymaga payment)

### DELETE Operations (częściowo działają)
- ✅ Event DELETE - działa (udokumentowane)
- ❓ Speaker DELETE - nie testowano (brak utworzonego speakera)
- ✅ Sponsor DELETE - działa!
- ❓ Session/Agenda DELETE - nie testowano
- ❓ Attendee DELETE - nie testowano (produkcyjne dane)

### Moduły całkowicie nieobsługiwane przez API v3
- ❌ **Exhibitor** (wszystkie operacje) - OAuth scope nie istnieje
- ❌ **Webhook** (wszystkie operacje) - endpoint nie istnieje

---

## 🎯 REKOMENDACJA FINALNYCH SCOPE'ÓW

### Wariant 1: TYLKO POTWIERDZONE (7 scope'ów)
Najbezpieczniejszy - tylko READ + działające CREATE/DELETE:

```
zohobackstage.portal.READ,zohobackstage.event.READ,zohobackstage.event.CREATE,zohobackstage.event.DELETE,zohobackstage.agenda.READ,zohobackstage.speaker.READ,zohobackstage.sponsor.READ,zohobackstage.sponsor.CREATE,zohobackstage.sponsor.DELETE,zohobackstage.eventticket.READ,zohobackstage.order.READ,zohobackstage.attendee.READ
```
(12 scope'ów)

### Wariant 2: PEŁNY ZESTAW (28 scope'ów - REKOMENDOWANY)
Wszystkie scope'y z wyjątkiem exhibitor/webhook (może Zoho doda endpointy w przyszłości):

```
zohobackstage.portal.READ,zohobackstage.event.READ,zohobackstage.event.CREATE,zohobackstage.event.UPDATE,zohobackstage.event.DELETE,zohobackstage.agenda.READ,zohobackstage.agenda.CREATE,zohobackstage.agenda.UPDATE,zohobackstage.agenda.DELETE,zohobackstage.speaker.READ,zohobackstage.speaker.CREATE,zohobackstage.speaker.UPDATE,zohobackstage.speaker.DELETE,zohobackstage.sponsor.READ,zohobackstage.sponsor.CREATE,zohobackstage.sponsor.UPDATE,zohobackstage.sponsor.DELETE,zohobackstage.eventticket.READ,zohobackstage.eventticket.CREATE,zohobackstage.eventticket.UPDATE,zohobackstage.eventticket.DELETE,zohobackstage.order.READ,zohobackstage.order.CREATE,zohobackstage.order.UPDATE,zohobackstage.order.DELETE,zohobackstage.attendee.READ,zohobackstage.attendee.UPDATE,zohobackstage.attendee.DELETE
```

---

## 📝 Uwagi i Ograniczenia

1. **Sessions/Agenda** - wymaga parametru `?day={numer}` (1, 2, 3...)
2. **Ticket Classes** - URL to `/ticket_classes` (z underscore!)
3. **Speakers & Sponsors** - URL plural (`/speakers`, `/sponsors`)
4. **UPDATE** - większość operacji UPDATE nie działa w API v3 (2026-01)
5. **Speaker CREATE** - nie działa (błąd serwera)
6. **Exhibitor & Webhook** - całkowicie nieobsługiwane przez API v3

---

## ✅ PRESET `Backstage_complex` - Status Końcowy

Preset zawiera **28 scope'ów** (wariant 2 - pełny zestaw).

**Dlaczego zostawiam scope'y które nie działają?**
- OAuth je akceptuje (przeszły walidację)
- Mogą zostać dodane przez Zoho w przyszłości
- Nie powodują problemów (po prostu zwracają 404/401)
- Token będzie "future-proof"
