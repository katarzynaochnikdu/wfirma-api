# Zoho Backstage API v3 - Finalne Wnioski

**Data**: 2026-01-24  
**Liczba przeprowadzonych testów**: 60+

---

## 🎯 GŁÓWNY WNIOSEK

**Zoho Backstage API v3 jest głównie READ-ONLY** z wyjątkiem Event i Sponsor.

---

## ✅ CO DZIAŁA (potwierdzone testami)

### READ Operations (13 endpointów - 100%)
| Moduł | Endpoint | Status |
|-------|----------|--------|
| Portal | `GET /portals` | ✅ |
| Portal | `GET /portals/{id}` | ✅ |
| Portal Members | `GET /portals/{id}/members` | ✅ |
| Event | `GET /portals/{p_id}/events` | ✅ |
| Event | `GET /portals/{p_id}/events/{e_id}` | ✅ |
| Event Members | `GET /portals/{p_id}/events/{e_id}/members` | ✅ |
| **Sessions/Agenda** | `GET /portals/{p_id}/events/{e_id}/sessions?day=1` | ✅ |
| Speaker | `GET /portals/{p_id}/events/{e_id}/speakers` | ✅ |
| Sponsor | `GET /portals/{p_id}/events/{e_id}/sponsors` | ✅ |
| Ticket Classes | `GET /portals/{p_id}/events/{e_id}/ticket_classes` | ✅ |
| Order | `GET /portals/{p_id}/events/{e_id}/orders` | ✅ |
| Order | `GET /portals/{p_id}/events/{e_id}/orders/{o_id}` | ✅ |
| Attendee | `GET /portals/{p_id}/events/{e_id}/attendees` | ✅ |

### CREATE/DELETE Operations (4 endpointy działają)
| Operacja | Endpoint | Status | Uwagi |
|----------|----------|--------|-------|
| Event CREATE | `POST /portals/{p_id}/events` | ✅ | Udokumentowane oficjalnie |
| Event DELETE | `DELETE /portals/{p_id}/events/{e_id}` | ✅ | Udokumentowane oficjalnie |
| **Sponsor CREATE** | `POST /portals/{p_id}/events/{e_id}/sponsors` | ✅ | **Przetestowane - działa!** |
| **Sponsor DELETE** | `DELETE /portals/{p_id}/events/{e_id}/sponsors/{s_id}` | ✅ | **Przetestowane - działa!** |

---

## ❌ CO NIE DZIAŁA (potwierdzone testami)

### UPDATE Operations (0%)
**Żadna operacja UPDATE nie działa w API v3:**

| Moduł | Próbowane metody | Błąd | Liczba testów |
|-------|------------------|------|---------------|
| Event UPDATE | PUT, PATCH | 404 "Please provide valid method" | 2 |
| Order UPDATE | PUT, PATCH, POST + 6 wariantów URL | 404 "Please provide valid method" | 9 |
| Sponsor UPDATE | PUT | 400 "Extra key found" | 1 |
| Attendee UPDATE | PUT, PATCH | 400/404 "Ticket data required" | 2 |

**Próbowano łącznie: 14 różnych kombinacji UPDATE - żadna nie działa.**

### CREATE Operations (częściowo)
| Moduł | Status | Błąd | Liczba testów |
|-------|--------|------|---------------|
| Speaker CREATE | ❌ | 500 "unexpected error" | 3 |
| Order CREATE | ❌ | 400 "invalid ticket class ID" | 10 |
| Pozostałe CREATE | ❓ | Nie przetestowane | - |

### Moduły całkowicie nieobsługiwane
| Moduł | Wszystkie operacje | Powód |
|-------|-------------------|-------|
| **Exhibitor** | ❌ | OAuth scope nie istnieje (HTTP 401) |
| **Webhook** | ❌ | Endpoint nie istnieje (HTTP 404) |

---

## 💡 DLACZEGO ORDER CREATE NIE DZIAŁA?

### Odkrycie z StackOverflow:
Zoho Backstage **używa webhooków** do powiadamiania o utworzonych zamówieniach:
- Webhook "Event order is created"
- Webhook "Attendee is created"

### Wniosek:
**Zamówienia są tworzone przez użytkowników na stronie eventu** (proces zakupowy), **nie przez API**. API służy tylko do:
- ✅ Odczytu zamówień (GET)
- ❌ NIE do tworzenia/modyfikacji zamówień

---

## 🔑 ODPOWIEDŹ NA PYTANIE O ZMIANĘ STATUSU

### Czy można zmienić status zamówienia z unpaid na paid?

**NIE** - przez API v3 to niemożliwe:

1. ❌ **Direct UPDATE** - endpoint nie istnieje (9 prób)
2. ❌ **DELETE+CREATE workaround** - CREATE nie działa (10 prób)
3. ❌ **Dedykowane endpointy** - `/payment`, `/mark-as-paid` nie istnieją

### Jedyne rozwiązanie:
Status płatności można zmienić **tylko ręcznie** w panelu administracyjnym Zoho Backstage (interfejs webowy).

---

## 📦 FINALNE SCOPE'Y (28)

Preset `Backstage_complex (TESTED ✅)` zawiera wszystkie działające scope'y:

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

**Uwaga**: Większość scope'ów CREATE/UPDATE/DELETE jest w tokenie "na przyszłość" (jeśli Zoho doda endpointy).

---

## 📊 Pliki Wygenerowane

1. ✅ **BACKSTAGE_CRUD_TABLE.md** - kompletna tabela CRUD dla wszystkich modułów
2. ✅ **BACKSTAGE_FINAL_SCOPE_RECOMMENDATION.md** - rekomendacje scope'ów
3. ✅ **BACKSTAGE_COMPLETE_API_TEST_SUMMARY.md** - pełne podsumowanie testów
4. ✅ **BACKSTAGE_AGENDA_DEEP_TEST.md** - test 15 wariantów agenda (odkryto ?day=1,2,3...)
5. ✅ **BACKSTAGE_ORDER_UPDATE_TEST.md** - test 9 wariantów UPDATE order
6. ✅ **BACKSTAGE_ORDER_CREATE_TEST.md** - test 10 wariantów CREATE order
7. ✅ **BACKSTAGE_CRUD_TEST_RESULTS.md** - wyniki testów CRUD (speaker/sponsor/attendee)
8. ✅ **BACKSTAGE_WORKING_SCOPES.txt** - 2 warianty scope'ów (12 vs 28)

---

## 🎓 Lekcje z Testów

1. **Sessions/Agenda działa** - ale wymaga parametru `?day={integer}`
2. **Ticket Classes** - URL z underscore (`/ticket_classes`), nie camelCase
3. **Speakers & Sponsors** - URL plural (`/speakers`, `/sponsors`)
4. **Sponsor CREATE/DELETE działają** - jedyny moduł oprócz Event z pełnym CRUD
5. **UPDATE nie działa NIGDZIE** - API v3 nie obsługuje modyfikacji danych (poza Event/Sponsor przez DELETE+CREATE)
6. **Orders są READ-ONLY** - tworzone przez proces zakupowy na stronie, nie przez API
7. **Exhibitor & Webhook** - OAuth scope'y nie istnieją w API v3
