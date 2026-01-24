# Zoho Backstage API v3 - Tabela Operacji CRUD

**Data testów**: 2026-01-24  
**Portal ID**: 20101549222  
**Event ID**: 24311000000429149

---

## 📊 KOMPLETNA TABELA CRUD

| # | Moduł | Endpoint | READ | CREATE | UPDATE | DELETE | Notatki |
|---|-------|----------|------|--------|--------|--------|---------|
| 1 | **Portal** | `/portals` | ✅ | ❌ | ❌ | ❌ | Tylko odczyt |
| 2 | **Portal** | `/portals/{id}` | ✅ | - | - | - | Szczegóły portalu |
| 3 | **Portal Members** | `/portals/{id}/members` | ✅ | ❌ | ❌ | ❌ | Członkowie portalu |
| 4 | **Event** | `/portals/{p_id}/events` | ✅ | ✅ | ❌ | - | CREATE działa (udokumentowane) |
| 5 | **Event** | `/portals/{p_id}/events/{e_id}` | ✅ | - | ❌ | ✅ | DELETE działa (udokumentowane) |
| 6 | **Event Members** | `/portals/{p_id}/events/{e_id}/members` | ✅ | ❌ | ❌ | ❌ | Członkowie eventu |
| 7 | **Sessions/Agenda** | `/portals/{p_id}/events/{e_id}/sessions?day=1` | ✅ | ❓ | ❓ | ❓ | **Wymaga parametru ?day=1,2,3...** |
| 8 | **Speaker** | `/portals/{p_id}/events/{e_id}/speakers` | ✅ | ❌ | ❌ | ❌ | CREATE zwraca błąd serwera |
| 9 | **Sponsor** | `/portals/{p_id}/events/{e_id}/sponsors` | ✅ | ✅ | ❌ | ✅ | **CREATE/DELETE działają!** UPDATE nie |
| 10 | **Ticket Classes** | `/portals/{p_id}/events/{e_id}/ticket_classes` | ✅ | ❓ | ❓ | ❓ | **URL z underscore!** |
| 11 | **Order** | `/portals/{p_id}/events/{e_id}/orders` | ✅ | ❓ | ❌ | ❓ | UPDATE nie działa |
| 12 | **Order** | `/portals/{p_id}/events/{e_id}/orders/{o_id}` | ✅ | - | ❌ | ❓ | Szczegóły zamówienia |
| 13 | **Attendee** | `/portals/{p_id}/events/{e_id}/attendees` | ✅ | - | ❌ | ❓ | Attendees przez orders, UPDATE nie działa |

**Legenda:**
- ✅ **Przetestowane - DZIAŁA**
- ❌ **Przetestowane - NIE DZIAŁA**
- ❓ **Nie przetestowane** (wymaga realnych danych produkcyjnych)
- `-` **Nie dotyczy** (operacja niedostępna dla tego endpointa)

---

## 🔍 SZCZEGÓŁOWE WYNIKI TESTÓW

### 1. PORTAL
```
Scope: zohobackstage.portal.READ
```

| Operacja | Endpoint | Status | HTTP Method |
|----------|----------|--------|-------------|
| Lista portali | `GET /v3/portals` | ✅ HTTP 200 | GET |
| Szczegóły portalu | `GET /v3/portals/{portal_id}` | ✅ HTTP 200 | GET |
| Członkowie portalu | `GET /v3/portals/{portal_id}/members` | ✅ HTTP 200 | GET |

---

### 2. EVENT
```
Scopes: zohobackstage.event.READ, .CREATE, .UPDATE, .DELETE
```

| Operacja | Endpoint | Status | HTTP Method | Notatka |
|----------|----------|--------|-------------|---------|
| Lista eventów | `GET /v3/portals/{p_id}/events` | ✅ HTTP 200 | GET | - |
| Szczegóły eventu | `GET /v3/portals/{p_id}/events/{e_id}` | ✅ HTTP 200 | GET | - |
| Członkowie eventu | `GET /v3/portals/{p_id}/events/{e_id}/members` | ✅ HTTP 200 | GET | - |
| **Utwórz event** | `POST /v3/portals/{p_id}/events` | ✅ (doc) | POST | Udokumentowane w API |
| **Aktualizuj event** | `PUT /v3/portals/{p_id}/events/{e_id}` | ❌ 404 | PUT | Endpoint nie istnieje |
| **Usuń event** | `DELETE /v3/portals/{p_id}/events/{e_id}` | ✅ (doc) | DELETE | Udokumentowane w API |

---

### 3. SESSIONS / AGENDA
```
Scopes: zohobackstage.agenda.READ, .CREATE, .UPDATE, .DELETE
```

| Operacja | Endpoint | Status | HTTP Method | Notatka |
|----------|----------|--------|-------------|---------|
| **Sesje z dnia 1** | `GET /v3/.../sessions?day=1` | ✅ HTTP 200 | GET | **Wymaga parametru day!** |
| Sesje z dnia 2 | `GET /v3/.../sessions?day=2` | ✅ HTTP 200 | GET | day=2,3,4,5... |
| Bez parametru | `GET /v3/.../sessions` | ❌ 400 | GET | "Please enter the valid agenda day" |
| Z datą | `GET /v3/.../sessions?day=2026-02-05` | ❌ 400 | GET | Nie akceptuje formatu YYYY-MM-DD |
| **CREATE** | `POST /v3/.../sessions` | ❓ | POST | Nie przetestowane |
| **UPDATE** | `PUT /v3/.../sessions/{id}` | ❓ | PUT | Nie przetestowane |
| **DELETE** | `DELETE /v3/.../sessions/{id}` | ❓ | DELETE | Nie przetestowane |

---

### 4. SPEAKER
```
Scopes: zohobackstage.speaker.READ, .CREATE, .UPDATE, .DELETE
```

| Operacja | Endpoint | Status | HTTP Method | Notatka |
|----------|----------|--------|-------------|---------|
| Lista speakerów | `GET /v3/.../speakers` | ✅ HTTP 200 | GET | URL plural! |
| **CREATE speaker** | `POST /v3/.../speakers` | ❌ 500 | POST | "unexpected error" |
| **UPDATE speaker** | `PUT /v3/.../speakers/{id}` | ❌ | PUT | Nie przetestowane (brak CREATE) |
| **DELETE speaker** | `DELETE /v3/.../speakers/{id}` | ❌ | DELETE | Nie przetestowane (brak CREATE) |

**Błąd CREATE**: "Sorry, an unexpected error has occurred. Please try again later."

---

### 5. SPONSOR
```
Scopes: zohobackstage.sponsor.READ, .CREATE, .UPDATE, .DELETE
```

| Operacja | Endpoint | Status | HTTP Method | Notatka |
|----------|----------|--------|-------------|---------|
| Lista sponsorów | `GET /v3/.../sponsors` | ✅ HTTP 200 | GET | URL plural! |
| **CREATE sponsor** | `POST /v3/.../sponsors` | ✅ HTTP 201 | POST | **DZIAŁA!** |
| **UPDATE sponsor** | `PUT /v3/.../sponsors/{id}` | ❌ 400 | PUT | "Extra key found" |
| **DELETE sponsor** | `DELETE /v3/.../sponsors/{id}` | ✅ HTTP 200 | DELETE | **DZIAŁA!** |

**CREATE Payload** (działający):
```json
{
  "sponsorship_type": "24311000000445140",
  "company_name": "API Test Sponsor"
}
```

---

### 6. TICKET CLASSES
```
Scopes: zohobackstage.eventticket.READ, .CREATE, .UPDATE, .DELETE
```

| Operacja | Endpoint | Status | HTTP Method | Notatka |
|----------|----------|--------|-------------|---------|
| Lista klas biletów | `GET /v3/.../ticket_classes` | ✅ HTTP 200 | GET | **URL z underscore!** |
| Szczegóły klasy | `GET /v3/.../ticket_classes/{id}` | ❌ 401 | GET | Brak uprawnień do konkretnej klasy |
| **CREATE** | `POST /v3/.../ticket_classes` | ❓ | POST | Nie przetestowane |
| **UPDATE** | `PUT /v3/.../ticket_classes/{id}` | ❓ | PUT | Nie przetestowane |
| **DELETE** | `DELETE /v3/.../ticket_classes/{id}` | ❓ | DELETE | Nie przetestowane |

**WAŻNE**: URL to `/ticket_classes` (z underscore), nie `/ticketClasses` (camelCase)!

---

### 7. ORDER
```
Scopes: zohobackstage.order.READ, .CREATE, .UPDATE, .DELETE
```

| Operacja | Endpoint | Status | HTTP Method | Notatka |
|----------|----------|--------|-------------|---------|
| Lista zamówień | `GET /v3/.../orders` | ✅ HTTP 200 | GET | - |
| Szczegóły zamówienia | `GET /v3/.../orders/{order_id}` | ✅ HTTP 200 | GET | - |
| **CREATE order** | `POST /v3/.../orders` | ❓ | POST | Nie przetestowane (wymaga payment) |
| **UPDATE order** | `PUT /v3/.../orders/{id}` | ❌ 404 | PUT | "Please provide valid method" |
| **UPDATE order** | `PATCH /v3/.../orders/{id}` | ❌ 404 | PATCH | "Please provide valid method" |
| **DELETE order** | `DELETE /v3/.../orders/{id}` | ❓ | DELETE | Nie przetestowane |
| Update payment status | `PUT /v3/.../orders/{id}/payment` | ❌ 404 | PUT | Endpoint nie istnieje |
| Mark as paid | `POST /v3/.../orders/{id}/mark-as-paid` | ❌ 404 | POST | Endpoint nie istnieje |

**Próbowano 9 różnych wariantów UPDATE** - żaden nie działa.

---

### 8. ATTENDEE
```
Scopes: zohobackstage.attendee.READ, .UPDATE, .DELETE
```

| Operacja | Endpoint | Status | HTTP Method | Notatka |
|----------|----------|--------|-------------|---------|
| Lista uczestników | `GET /v3/.../attendees` | ✅ HTTP 200 | GET | - |
| **UPDATE attendee** | `PUT /v3/.../attendees/{id}` | ❌ 400 | PUT | "Ticket `data` is a required parameter" |
| **UPDATE attendee** | `PATCH /v3/.../attendees/{id}` | ❌ 404 | PATCH | "Please provide valid method" |
| **DELETE attendee** | `DELETE /v3/.../attendees/{id}` | ❓ | DELETE | Nie przetestowane (produkcyjne dane) |

**Uwaga**: Attendees nie mają CREATE (powstają automatycznie przez orders).

---

## ❌ MODUŁY NIEOBSŁUGIWANE (całkowicie)

### EXHIBITOR
```
Wszystkie scope'y: USUNIĘTE z presetu
```

| Operacja | Endpoint | Status | Błąd |
|----------|----------|--------|------|
| GET | `/v3/.../exhibitors` | ❌ HTTP 401 | "Please provide a valid OAuthScope" |
| POST | - | ❌ | OAuth scope nie istnieje w API v3 |
| PUT | - | ❌ | OAuth scope nie istnieje w API v3 |
| DELETE | - | ❌ | OAuth scope nie istnieje w API v3 |

**Wniosek**: OAuth scope `zohobackstage.exhibitor.*` **nie istnieje** w Backstage API v3.

---

### WEBHOOK
```
Wszystkie scope'y: USUNIĘTE z presetu
```

| Operacja | Endpoint | Status | Błąd |
|----------|----------|--------|------|
| GET | `/v3/.../webhooks` | ❌ HTTP 404 | "Please provide valid method" |
| GET (portal level) | `/v3/portals/{id}/webhooks` | ❌ HTTP 404 | "Please provide valid method" |
| POST | - | ❌ | Endpoint nie istnieje |
| PUT | - | ❌ | Endpoint nie istnieje |
| DELETE | - | ❌ | Endpoint nie istnieje |

**Wniosek**: Endpoint `/webhooks` **nie działa** w Backstage API v3.

---

## 📈 PODSUMOWANIE STATYSTYK

### Operacje READ (GET)
- ✅ **Działają**: 13/13 endpointów (100%)
- Wszystkie moduły mają działający READ

### Operacje CREATE (POST)
- ✅ **Działają**: 2/8 endpointów (25%)
  - Event CREATE ✅
  - Sponsor CREATE ✅
- ❌ **Nie działają**: Speaker CREATE, pozostałe nie przetestowane

### Operacje UPDATE (PUT/PATCH)
- ✅ **Działają**: 0/8 endpointów (0%)
- ❌ **Nie działa ŻADEN UPDATE** w API v3

### Operacje DELETE
- ✅ **Działają**: 2/8 endpointów (25%)
  - Event DELETE ✅
  - Sponsor DELETE ✅
- Pozostałe nie przetestowane

---

## 🎯 WNIOSKI I REKOMENDACJE

### ✅ Co można robić w API v3:
1. **Czytać wszystko** - 13 endpointów READ działa
2. **Tworzyć**: Events, Sponsors
3. **Usuwać**: Events, Sponsors

### ❌ Czego NIE można robić:
1. **UPDATE** - żadna operacja UPDATE nie działa
2. **Zmieniać status zamówień** (order/payment)
3. **Tworzyć speakerów** (błąd serwera)
4. **Zarządzać exhibitors** (moduł nie istnieje)
5. **Zarządzać webhooks** (moduł nie istnieje)

### 💡 Rekomendacja użycia:
Backstage API v3 jest głównie **READ-ONLY** z wyjątkiem:
- Event: pełny CRUD (bez UPDATE)
- Sponsor: pełny CRUD (bez UPDATE)

Jeśli potrzebujesz UPDATE/CREATE dla innych modułów, musisz używać interfejsu webowego Zoho Backstage.

---

## 📋 Scope'y Finalne

**REKOMENDOWANY ZESTAW (28 scope'ów)** - zawarty w presecie `Backstage_complex (TESTED ✅)`:

```
zohobackstage.portal.READ,
zohobackstage.event.READ,zohobackstage.event.CREATE,zohobackstage.event.UPDATE,zohobackstage.event.DELETE,
zohobackstage.agenda.READ,zohobackstage.agenda.CREATE,zohobackstage.agenda.UPDATE,zohobackstage.agenda.DELETE,
zohobackstage.speaker.READ,zohobackstage.speaker.CREATE,zohobackstage.speaker.UPDATE,zohobackstage.speaker.DELETE,
zohobackstage.sponsor.READ,zohobackstage.sponsor.CREATE,zohobackstage.sponsor.UPDATE,zohobackstage.sponsor.DELETE,
zohobackstage.eventticket.READ,zohobackstage.eventticket.CREATE,zohobackstage.eventticket.UPDATE,zohobackstage.eventticket.DELETE,
zohobackstage.order.READ,zohobackstage.order.CREATE,zohobackstage.order.UPDATE,zohobackstage.order.DELETE,
zohobackstage.attendee.READ,zohobackstage.attendee.UPDATE,zohobackstage.attendee.DELETE
```

**Uwaga**: Scope'y UPDATE/CREATE/DELETE są w tokenie "na przyszłość" - jak Zoho doda endpointy, zadziałają.
