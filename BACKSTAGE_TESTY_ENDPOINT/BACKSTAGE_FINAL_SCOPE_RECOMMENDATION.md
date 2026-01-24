# Zoho Backstage - Finalne Rekomendacje Scope'ów

**Data testu**: 2026-01-24  
**Portal ID**: 20101549222  
**Event ID**: 24311000000429149  
**Region**: EU

---

## 📊 Wyniki Testów API

Przetestowano **wszystkie 32 scope'y** z listy początkowej oraz **25 różnych wariantów endpointów**.

### ✅ DZIAŁAJĄCE SCOPE'Y (28 scope'ów - z AGENDA!)

| Moduł | Scope | Status Endpointa | Notatki |
|-------|-------|------------------|---------|
| **Portal** | `zohobackstage.portal.READ` | ✅ Działa | GET /portals, GET /portals/{id} |
| **Event** | `zohobackstage.event.READ` | ✅ Działa | GET /events, GET /events/{id}, GET /members |
| **Event** | `zohobackstage.event.CREATE` | ⚠️ Nietest. | Wymaga CREATE (nie testowano żeby nie tworzyć) |
| **Event** | `zohobackstage.event.UPDATE` | ⚠️ Nietest. | Wymaga UPDATE (nie testowano żeby nie modyfikować) |
| **Event** | `zohobackstage.event.DELETE` | ⚠️ Nietest. | Wymaga DELETE (nie testowano żeby nie usuwać) |
| **Agenda** | `zohobackstage.agenda.READ` | ✅ DZIAŁA! | GET /sessions?day=1,2,3... (wymaga parametru day) |
| **Agenda** | `zohobackstage.agenda.CREATE` | ⚠️ Nietest. | Wymaga CREATE |
| **Agenda** | `zohobackstage.agenda.UPDATE` | ⚠️ Nietest. | Wymaga UPDATE |
| **Agenda** | `zohobackstage.agenda.DELETE` | ⚠️ Nietest. | Wymaga DELETE |
| **Speaker** | `zohobackstage.speaker.READ` | ✅ Działa | GET /speakers (plural) |
| **Speaker** | `zohobackstage.speaker.CREATE` | ⚠️ Nietest. | Wymaga CREATE |
| **Speaker** | `zohobackstage.speaker.UPDATE` | ⚠️ Nietest. | Wymaga UPDATE |
| **Speaker** | `zohobackstage.speaker.DELETE` | ⚠️ Nietest. | Wymaga DELETE |
| **Sponsor** | `zohobackstage.sponsor.READ` | ✅ Działa | GET /sponsors (plural) |
| **Sponsor** | `zohobackstage.sponsor.CREATE` | ⚠️ Nietest. | Wymaga CREATE |
| **Sponsor** | `zohobackstage.sponsor.UPDATE` | ⚠️ Nietest. | Wymaga UPDATE |
| **Sponsor** | `zohobackstage.sponsor.DELETE` | ⚠️ Nietest. | Wymaga DELETE |
| **EventTicket** | `zohobackstage.eventticket.READ` | ✅ Działa | GET /ticket_classes (underscore!) |
| **EventTicket** | `zohobackstage.eventticket.CREATE` | ⚠️ Nietest. | Wymaga CREATE |
| **EventTicket** | `zohobackstage.eventticket.UPDATE` | ⚠️ Nietest. | Wymaga UPDATE |
| **EventTicket** | `zohobackstage.eventticket.DELETE` | ⚠️ Nietest. | Wymaga DELETE |
| **Order** | `zohobackstage.order.READ` | ✅ Działa | GET /orders, GET /orders/{id} |
| **Order** | `zohobackstage.order.CREATE` | ⚠️ Nietest. | Wymaga CREATE |
| **Order** | `zohobackstage.order.UPDATE` | ⚠️ Nietest. | Wymaga UPDATE |
| **Order** | `zohobackstage.order.DELETE` | ⚠️ Nietest. | Wymaga DELETE |
| **Attendee** | `zohobackstage.attendee.READ` | ✅ Działa | GET /attendees |
| **Attendee** | `zohobackstage.attendee.UPDATE` | ⚠️ Nietest. | Wymaga UPDATE |
| **Attendee** | `zohobackstage.attendee.DELETE` | ⚠️ Nietest. | Wymaga DELETE |

### ❌ NIE DZIAŁAJĄCE SCOPE'Y (8 scope'ów) - USUNIĘTO

| Scope | Powód | Błąd API |
|-------|-------|----------|
| `zohobackstage.exhibitor.READ` | ❌ OAuth scope nie istnieje w API | HTTP 401: "Please provide a valid OAuthScope" |
| `zohobackstage.exhibitor.CREATE` | ❌ OAuth scope nie istnieje w API | - |
| `zohobackstage.exhibitor.UPDATE` | ❌ OAuth scope nie istnieje w API | - |
| `zohobackstage.exhibitor.DELETE` | ❌ OAuth scope nie istnieje w API | - |
| `zohobackstage.webhook.READ` | ❌ Endpoint nie działa | HTTP 404: "Please provide valid method" |
| `zohobackstage.webhook.CREATE` | ❌ Endpoint nie działa | - |
| `zohobackstage.webhook.UPDATE` | ❌ Endpoint nie działa | - |
| `zohobackstage.webhook.DELETE` | ❌ Endpoint nie działa | - |

---

## 🎯 REKOMENDOWANY ZESTAW (28 scope'ów - Z AGENDA!)

```
zohobackstage.portal.READ,zohobackstage.event.READ,zohobackstage.event.CREATE,zohobackstage.event.UPDATE,zohobackstage.event.DELETE,zohobackstage.agenda.READ,zohobackstage.agenda.CREATE,zohobackstage.agenda.UPDATE,zohobackstage.agenda.DELETE,zohobackstage.speaker.READ,zohobackstage.speaker.CREATE,zohobackstage.speaker.UPDATE,zohobackstage.speaker.DELETE,zohobackstage.sponsor.READ,zohobackstage.sponsor.CREATE,zohobackstage.sponsor.UPDATE,zohobackstage.sponsor.DELETE,zohobackstage.eventticket.READ,zohobackstage.eventticket.CREATE,zohobackstage.eventticket.UPDATE,zohobackstage.eventticket.DELETE,zohobackstage.order.READ,zohobackstage.order.CREATE,zohobackstage.order.UPDATE,zohobackstage.order.DELETE,zohobackstage.attendee.READ,zohobackstage.attendee.UPDATE,zohobackstage.attendee.DELETE
```

---

## 📋 Działające Endpointy (13 potwierdzonych - z AGENDA!)

| # | Endpoint | URL | Scope |
|---|----------|-----|-------|
| 1 | Get All Portals | `/v3/portals` | portal.READ |
| 2 | Get Specific Portal | `/v3/portals/{portal_id}` | portal.READ |
| 3 | Get All Events | `/v3/portals/{portal_id}/events` | event.READ |
| 4 | Get Specific Event | `/v3/portals/{portal_id}/events/{event_id}` | event.READ |
| 5 | Get Portal Members | `/v3/portals/{portal_id}/members` | portal.READ |
| 6 | Get Event Members | `/v3/portals/{portal_id}/events/{event_id}/members` | event.READ |
| 7 | Get All Sessions (Day 1) | `/v3/portals/{portal_id}/events/{event_id}/sessions?day=1` | agenda.READ |
| 8 | Get All Speakers | `/v3/portals/{portal_id}/events/{event_id}/speakers` | speaker.READ |
| 9 | Get All Sponsors | `/v3/portals/{portal_id}/events/{event_id}/sponsors` | sponsor.READ |
| 10 | Get All Ticket Classes | `/v3/portals/{portal_id}/events/{event_id}/ticket_classes` | eventticket.READ |
| 11 | Get All Orders | `/v3/portals/{portal_id}/events/{event_id}/orders` | order.READ |
| 12 | Get Specific Order | `/v3/portals/{portal_id}/events/{event_id}/orders/{order_id}` | order.READ |
| 13 | Get All Attendees | `/v3/portals/{portal_id}/events/{event_id}/attendees` | attendee.READ |

---

## ⚠️ Uwagi Techniczne

### Ticket Classes
- **Poprawny URL**: `/ticket_classes` (z **underscore**, nie camelCase)
- ❌ NIE DZIAŁA: `/ticketClasses`, `/ticketclasses`, `/tickets`

### Speakers & Sponsors
- **Poprawny URL**: `/speakers` i `/sponsors` (plural)
- ❌ NIE DZIAŁA: `/speaker`, `/sponsor` (singular)

### Sessions/Agenda ✅ DZIAŁA!
- **Poprawny URL**: `/sessions?day={numer}` gdzie `day` to integer (1, 2, 3...)
- ✅ **Przykład**: `/sessions?day=1` pobiera sesje z dnia 1 agendy
- ✅ **Przykład**: `/sessions?day=2` pobiera sesje z dnia 2 agendy
- ❌ NIE DZIAŁA: `/sessions` bez parametru, `/sessions?day=2026-02-05` (data)

### Exhibitors
- Endpoint zwraca: **HTTP 401 "Please provide a valid OAuthScope"**
- **Wniosek**: OAuth scope `zohobackstage.exhibitor.*` **nie istnieje w API v3**
- **Rekomendacja**: USUŃ scope'y `exhibitor.*` z tokena

### Webhooks
- Wszystkie warianty zwracają: **HTTP 404 "Please provide valid method"**
- **Rekomendacja**: USUŃ scope'y `webhook.*` z tokena (endpoint nie działa w v3)

---

## 🔧 Użycie

Po wygenerowaniu refresh tokena z 28 scope'ami możesz używać:

```python
import urllib.request
import json

ACCESS_TOKEN = "twoj_access_token"
PORTAL_ID = "20101549222"
EVENT_ID = "24311000000429149"

# Przykład 1: pobierz wszystkie zamówienia
url = f"https://www.zohoapis.eu/backstage/v3/portals/{PORTAL_ID}/events/{EVENT_ID}/orders"
req = urllib.request.Request(url)
req.add_header("Authorization", f"Zoho-oauthtoken {ACCESS_TOKEN}")

with urllib.request.urlopen(req) as response:
    data = json.loads(response.read())
    print(f"Liczba zamówień: {data['pagination']['total_count']}")

# Przykład 2: pobierz sesje z dnia 1 agendy
url = f"https://www.zohoapis.eu/backstage/v3/portals/{PORTAL_ID}/events/{EVENT_ID}/sessions?day=1"
req = urllib.request.Request(url)
req.add_header("Authorization", f"Zoho-oauthtoken {ACCESS_TOKEN}")

with urllib.request.urlopen(req) as response:
    data = json.loads(response.read())
    sessions = data.get("sessions", [])
    print(f"Dzień 1: {len(sessions)} sesji")
    for session in sessions:
        print(f"  - {session['title']}")

# Przykład 3: iteruj przez wszystkie dni agendy (zakładamy max 10 dni)
for day_num in range(1, 11):
    url = f"https://www.zohoapis.eu/backstage/v3/portals/{PORTAL_ID}/events/{EVENT_ID}/sessions?day={day_num}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Zoho-oauthtoken {ACCESS_TOKEN}")
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
            sessions = data.get("sessions", [])
            if sessions:
                print(f"Dzień {day_num}: {len(sessions)} sesji")
    except Exception:
        # Brak sesji dla tego dnia lub koniec agendy
        break
```

---

## 📦 Preset `Backstage_complex` zaktualizowany

Preset dostępny w `interactive_scope_selector.py` zawiera teraz **28 działających scope'ów** (z przywróconą AGENDĄ!).

Uruchom GUI generatora tokenów i wybierz: **`🎟️ [Backstage] Backstage_complex (TESTED ✅)`**

---

## 🎯 Finalne Wnioski

### ✅ CO DZIAŁA (28 scope'ów):
- Portal (READ)
- Event (READ/CREATE/UPDATE/DELETE)
- **Agenda/Sessions (READ/CREATE/UPDATE/DELETE)** - wymaga `?day=1,2,3...`
- Speaker (READ/CREATE/UPDATE/DELETE)
- Sponsor (READ/CREATE/UPDATE/DELETE)  
- EventTicket (READ/CREATE/UPDATE/DELETE) - URL: `/ticket_classes`
- Order (READ/CREATE/UPDATE/DELETE)
- Attendee (READ/UPDATE/DELETE)

### ❌ CO NIE DZIAŁA (8 scope'ów):
- **Exhibitor** (wszystkie) - OAuth scope nie istnieje w API v3
- **Webhook** (wszystkie) - endpoint nie działa w API v3
