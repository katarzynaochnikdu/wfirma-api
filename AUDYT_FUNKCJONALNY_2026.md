# 🔍 AUDYT FUNKCJONALNY - MEDIDESK ADMIN PANEL V2
**Data audytu:** 24 stycznia 2026  
**Audytor:** AI Assistant (Claude Sonnet 4.5)  
**Zakres:** Aplikacja Medidesk Admin Panel V2 - pełny audyt funkcjonalny

---

## 📋 SPIS TREŚCI
1. [Podsumowanie wykonawcze](#1-podsumowanie-wykonawcze)
2. [Architektura i technologie](#2-architektura-i-technologie)
3. [Audyt modułów](#3-audyt-modułów)
4. [Wykryte problemy](#4-wykryte-problemy)
5. [Brakujące funkcje](#5-brakujące-funkcje)
6. [Rekomendacje](#6-rekomendacje)

---

## 1. PODSUMOWANIE WYKONAWCZE

### 1.1. Status ogólny aplikacji
✅ **Aplikacja jest funkcjonalna i działająca** na produkcji (https://wfirma-api.onrender.com)

**Ocena ogólna:** 7/10
- ✅ Rdzeń aplikacji działa poprawnie
- ✅ Integracje z Zoho Backstage, Stripe, wFirma działają
- ⚠️ Brak implementacji niektórych funkcji (placeholdery)
- ⚠️ Niekompletny moduł Work Queue
- ⚠️ Brak testów automatycznych

### 1.2. Kluczowe statystyki
- **Liczba endpointów API:** ~90
- **Liczba modułów Admin Panel V2:** 12
- **Liczba tabel w bazie:** 15
- **Liczba szablonów email:** 12
- **Linie kodu (Python):** ~30,000+

### 1.3. Krytyczne braki (wymagają natychmiastowej uwagi)
1. ❌ **Brak implementacji wysyłki przypomnień** (`/orders/<id>/send-reminder`)
2. ❌ **Brak implementacji ponownej wysyłki biletów** (`/orders/<id>/resend-ticket`)
3. ❌ **Brak funkcjonalności Work Queue** (tylko UI, brak logiki)
4. ⚠️ **Niekompletny Email Designer** (brak zapisu/edycji szablonów)
5. ⚠️ **Brak mechanizmu retry dla błędnych emaili**

---

## 2. ARCHITEKTURA I TECHNOLOGIE

### 2.1. Stack technologiczny
```
Backend:
- Flask 3.0.0 (Python web framework)
- PostgreSQL (Render hosted) - baza danych
- psycopg2-binary 2.9.11 (PostgreSQL adapter)
- Gunicorn 21.2.0 (WSGI server)

Frontend:
- Hybrid: React components + Jinja2 templates
- Vanilla JavaScript
- CSS3 (custom, no framework)

Integracje:
- Stripe API (płatności online)
- Zoho Backstage API (wydarzenia, zamówienia)
- wFirma OAuth2 (faktury, kontrahenci)
- Make.com webhooks (wysyłka emaili)
- GUS/REGON API (walidacja NIP)
```

### 2.2. Struktura bazy danych
**15 tabel:**
1. `events` - wydarzenia
2. `event_ticket_classes` - typy biletów
3. `payment_rules` - reguły płatności (FOC/PROFORMA/STRIPE)
4. `orders` - zamówienia
5. `order_tickets` - bilety w zamówieniu
6. `participants` - uczestnicy
7. `stripe_sessions` - sesje płatności Stripe
8. `wfirma_documents` - dokumenty wFirma (faktury/proformy)
9. `mail_log` - historia wysyłek email
10. `backstage_webhook_events` - logi webhooków Backstage
11. `admin_users` - konta administratorów
12. `admin_audit_log` - audyt akcji adminów
13. `token_monitor_state` - monitoring wygasania tokenów wFirma
14. `token_monitor_notifs` - powiadomienia o tokenach
15. `schema_migrations` - wersje schematu DB

**Indeksy:** ✅ Prawidłowo zdefiniowane (event_id, status, order_id, email)

**Unikalne ograniczenia:**
- ✅ Ochrona przed duplikacją faktur VAT (`uniq_wfirma_normal_per_order`)
- ✅ Ochrona przed duplikacją proform (`uniq_wfirma_proforma_per_order`)

---

## 3. AUDYT MODUŁÓW

### 3.1. 🔐 **Moduł: Autoryzacja i bezpieczeństwo**

#### Status: ✅ **DZIAŁA POPRAWNIE**

**Funkcje zaimplementowane:**
- ✅ Logowanie/wylogowanie (email + hasło)
- ✅ Haszowanie haseł (werkzeug.security)
- ✅ Sesje użytkownika (Flask session)
- ✅ Role użytkowników (admin, user)
- ✅ Uprawnienia per strona (allowed_pages)
- ✅ Audit log (wszystkie akcje admina)
- ✅ Blokada konta po nieudanych logowaniach
- ✅ Bootstrap pierwszego admina (z tokenem)

**Problemy:**
- ⚠️ **Brak mechanizmu "zapomniałem hasła"** - admin nie może odzyskać hasła
- ⚠️ **Brak wymuszenia zmiany hasła** (pole `must_change_password` nie jest używane w UI)
- ⚠️ **Brak dwuskładnikowego uwierzytelniania (2FA)**
- ⚠️ **Sesje nie wygasają** (brak timeout)

**Rekomendacje:**
1. Dodać endpoint `/admin-v2/forgot-password` z wysyłką linku resetującego
2. Wymuszać zmianę hasła przy pierwszym logowaniu
3. Dodać timeout sesji (np. 8h bezczynności)
4. Rozważyć 2FA dla kont admin

---

### 3.2. 📊 **Moduł: Dashboard**

#### Status: ✅ **DZIAŁA POPRAWNIE**

**Lokalizacja:** `/admin-v2/dashboard`

**Funkcje:**
- ✅ Statystyki globalne (zamówienia, przychód, uczestnicy, wydarzenia)
- ✅ Wykres przychodu wg miesięcy (ostatnie 6 miesięcy)
- ✅ Wykres metod płatności (pie chart)
- ✅ Lista ostatnich 5 zamówień
- ✅ Filtrowanie danych w czasie rzeczywistym

**Problemy:**
- ⚠️ **Wydajność:** Ładowanie wszystkich zamówień (limit 500) może być wolne przy dużej liczbie danych
- ⚠️ **Brak cache'owania** statystyk (każde odświeżenie = query do DB)
- ℹ️ **Brak możliwości wyboru zakresu dat** (zawsze ostatnie 6 miesięcy)

**Rekomendacje:**
1. Dodać cache Redis dla statystyk (odświeżanie co 5 min)
2. Paginacja zamówień zamiast limit 500
3. Dodać selector zakresu dat do wykresów

---

### 3.3. ⚠️ **Moduł: Work Queue (Monitoring)**

#### Status: ❌ **NIEKOMPLETNY - TYLKO UI**

**Lokalizacja:** `/admin-v2/work-queue`

**Zaimplementowane:**
- ✅ Interfejs użytkownika (lista zadań, filtry, kategorii)
- ✅ Statystyki (total, critical, errors, warnings)
- ✅ Lista wydarzeń wymagających konfiguracji

**BRAKUJE (krytyczne):**
- ❌ **Brak tabeli w bazie danych** dla zadań/błędów
- ❌ **Brak mechanizmu zbierania błędów** z innych modułów
- ❌ **Placeholder endpoint:** `/work-queue/retry-all` (linia 1275) - tylko przekierowanie
- ❌ **Placeholder endpoint:** `/work-queue/<task_id>/retry` (linia 1283) - tylko przekierowanie
- ❌ **Brak logiki ponowień (retry)** dla błędnych procesów

**Kod problematyczny:**
```python
# admin_v2_panel.py, linia 1275-1288
@admin_v2_bp.route("/work-queue/retry-all", methods=["POST"])
@_require_login
def work_queue_retry_all():
    """Ponów wszystkie możliwe do ponowienia zadania."""
    # Placeholder - w przyszłości implementacja
    return redirect(url_for("admin_v2_bp.work_queue"))

@admin_v2_bp.route("/work-queue/<task_id>/retry", methods=["POST"])
@_require_login
def work_queue_retry(task_id: str):
    """Ponów pojedyncze zadanie."""
    # Placeholder - w przyszłości implementacja
    return redirect(url_for("admin_v2_bp.work_queue"))
```

**Rekomendacje (PRIORYTET WYSOKI):**
1. Utworzyć tabelę `error_queue`:
```sql
CREATE TABLE error_queue (
  id BIGSERIAL PRIMARY KEY,
  category TEXT NOT NULL, -- wfirma/make/stripe/database/attendee/config
  severity TEXT NOT NULL, -- critical/error/warning
  title TEXT NOT NULL,
  description TEXT,
  event_order_id TEXT,
  event_id TEXT,
  error_data JSONB,
  can_retry BOOLEAN DEFAULT TRUE,
  retry_count INTEGER DEFAULT 0,
  last_retry_at TIMESTAMPTZ,
  resolved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

2. Dodać funkcje w `pg_storage.py`:
   - `save_error_task(category, severity, title, ...)`
   - `list_error_tasks(category, severity, limit)`
   - `retry_error_task(task_id)`
   - `resolve_error_task(task_id)`

3. Zintegrować z istniejącymi procesami (backstage_engine.py, stripe_integration.py, email_sender.py)

4. Implementować mechanizm retry z eksponential backoff

---

### 3.4. 🎫 **Moduł: Wydarzenia (Events)**

#### Status: ✅ **DZIAŁA POPRAWNIE**

**Lokalizacje:**
- `/admin-v2/events` - lista wydarzeń
- `/admin-v2/events/new` - tworzenie
- `/admin-v2/events/<id>/edit` - edycja
- `/admin-v2/events/<id>/room` - Event Room (dashboard wydarzenia)
- `/admin-v2/events/<id>/dashboard` - alternatywny dashboard

**Funkcje:**
- ✅ Lista wydarzeń (aktywne/nieaktywne)
- ✅ Tworzenie nowego wydarzenia
- ✅ Edycja wydarzenia z synchronizacją do Zoho Flow
- ✅ Event Room z zakładkami (sprzedaż, płatności, zamówienia, uczestnicy, komunikacja, konfiguracja)
- ✅ Statystyki per wydarzenie
- ✅ Linki do Backstage (konfiguracja, zamówienia, uczestnicy)
- ✅ Normalizacja danych z Backstage (mapowanie pól)

**Problemy:**
- ⚠️ **Webhook Zoho Flow hardcoded** w kodzie (linia 755):
```python
ZOHO_FLOW_EVENT_UPDATE_WEBHOOK = "https://flow.zoho.eu/20101689330/flow/webhook/incoming?zapikey=..."
```
  Powinno być w ENV jako `ZOHO_FLOW_EVENT_UPDATE_WEBHOOK`

- ⚠️ **Brak obsługi błędu webhooka** - jeśli webhook się nie powiedzie, użytkownik nie widzi błędu
- ℹ️ **Duplikacja dashboardów** - są 2 endpointy (`/dashboard` i `/room`), niepotrzebna redundancja

**Rekomendacje:**
1. Przenieść URL webhooka do ENV
2. Dodać wizualny feedback gdy webhook fail (toast notification)
3. Usunąć `/events/<id>/dashboard` lub `/events/<id>/room` (zostawić jeden)
4. Dodać możliwość duplikowania wydarzenia (template)

---

### 3.5. 📦 **Moduł: Zamówienia (Orders)**

#### Status: ⚠️ **DZIAŁA, ALE BRAKUJE FUNKCJI**

**Lokalizacje:**
- `/admin-v2/orders` - lista zamówień
- `/admin-v2/orders/<id>` - szczegóły zamówienia
- `/admin-v2/orders/export` - eksport CSV

**Funkcje działające:**
- ✅ Lista zamówień z filtrowaniem (status, wydarzenie, wyszukiwanie)
- ✅ Szczegóły zamówienia (kupujący, uczestnicy, dokumenty wFirma, historia)
- ✅ Zmiana statusu zamówienia (AJAX)
- ✅ Anulowanie zamówienia
- ✅ Eksport do CSV
- ✅ Operational Bar (akcje na zamówieniu)
- ✅ Historia zamówienia (emaile, płatności, dokumenty)

**BRAKUJĄCE FUNKCJE (placeholdery):**

1. ❌ **Wysyłka przypomnienia o płatności** (linia 615-621):
```python
@admin_v2_bp.route("/orders/<order_id>/send-reminder", methods=["POST"])
@_require_permission("orders")
def order_send_reminder(order_id: str):
    """Wysyła przypomnienie o płatności (placeholder)."""
    from flask import jsonify
    # TODO: Integracja z Make/email
    return jsonify({"success": True, "message": "Przypomnienie zostanie wysłane"})
```

2. ❌ **Ponowna wysyłka biletu** (linia 624-630):
```python
@admin_v2_bp.route("/orders/<order_id>/resend-ticket", methods=["POST"])
@_require_permission("orders")
def order_resend_ticket(order_id: str):
    """Ponownie wysyła bilet (placeholder)."""
    from flask import jsonify
    # TODO: Integracja z Make/email
    return jsonify({"success": True, "message": "Bilet zostanie ponownie wysłany"})
```

**Problemy:**
- ⚠️ **Brak mechanizmu zwrotu (refund)** - admin nie może zrobić zwrotu przez panel
- ⚠️ **Brak masowych operacji** (bulk actions) - nie można zaznaczyć wielu zamówień i wykonać akcji
- ⚠️ **Brak możliwości edycji zamówienia** (np. zmiana email kupującego)

**Rekomendacje (PRIORYTET WYSOKI):**
1. **Zaimplementować wysyłkę przypomnienia:**
```python
def order_send_reminder(order_id: str):
    order = get_order(order_id)
    event = get_event(order['event_id'])
    
    # Wygeneruj email przypomnienia
    from email_templates import render_checkout_reminder_email
    html = render_checkout_reminder_email(...)
    
    # Wyślij przez Make
    from stripe_integration import _send_email_via_make_stripe
    result = _send_email_via_make_stripe(...)
    
    # Zapisz w mail_log
    save_mail_log(...)
    
    return jsonify({"success": True})
```

2. **Zaimplementować ponowną wysyłkę biletu:**
   - Sprawdzić czy zamówienie jest opłacone
   - Pobrać uczestników
   - Wysłać email z biletem dla każdego uczestnika

3. **Dodać refund przez Stripe API:**
   - Endpoint `/orders/<id>/refund` (POST)
   - Integracja z `stripe.Refund.create()`
   - Aktualizacja statusu zamówienia na "refunded"

---

### 3.6. 👥 **Moduł: Uczestnicy (Participants)**

#### Status: ✅ **DZIAŁA POPRAWNIE**

**Lokalizacje:**
- `/admin-v2/participants` - lista uczestników
- `/admin-v2/participants/<id>` - szczegóły uczestnika
- `/admin-v2/participants/export` - eksport CSV

**Funkcje:**
- ✅ Lista uczestników z filtrowaniem (wydarzenie, status, wyszukiwanie)
- ✅ Statystyki (total, emailed, registered, pending)
- ✅ Szczegóły uczestnika (dane osobowe, bilet, historia komunikacji)
- ✅ Historia uczestnika (rejestracja, emaile)
- ✅ Eksport do CSV

**Problemy:**
- ⚠️ **Brak możliwości edycji danych uczestnika** (np. zmiana nazwiska, email)
- ⚠️ **Brak możliwości dodania uczestnika ręcznie**
- ⚠️ **Brak masowej wysyłki emaili do uczestników** (bulk email)
- ℹ️ **Mapowanie nazw biletów** - długie ID numeryczne są zastępowane "Bilet Standard" (linia 1051-1054)

**Rekomendacje:**
1. Dodać endpoint `/participants/<id>/edit` (POST) - edycja danych uczestnika
2. Dodać `/participants/new` - ręczne dodanie uczestnika do wydarzenia
3. Dodać bulk action "Wyślij email" (zaznacz uczestników → wyślij wiadomość)

---

### 3.7. 📧 **Moduł: Komunikacja (Communication)**

#### Status: ⚠️ **DZIAŁA, ALE BRAKUJE RETRY**

**Lokalizacje:**
- `/admin-v2/communication` - historia wysyłek i szablony
- `/admin-v2/communication/export` - eksport CSV
- `/admin-v2/templates/<key>/preview` - podgląd szablonu

**Funkcje działające:**
- ✅ Historia wysyłek email (ostatnie 200)
- ✅ Filtry (status, typ, wydarzenie, wyszukiwanie)
- ✅ Statystyki (wysłane dzisiaj, dostarczone, błędy, delivery rate)
- ✅ Lista błędnych emaili (top 10)
- ✅ Katalog szablonów email (12 szablonów w 3 kategoriach)
- ✅ Podgląd szablonów z przykładowymi danymi
- ✅ Eksport do CSV

**Szablony email (12):**
**Purchaser (6):**
1. `stripe_payment_link` - Link do płatności Stripe ✅
2. `proforma_sent` - Proforma wysłana ✅
3. `payment_confirmation` - Potwierdzenie płatności ✅
4. `registration_confirmation` - Potwierdzenie rejestracji FOC ✅
5. `checkout_reminder` - Przypomnienie o płatności ✅
6. `checkout_expired_new_link` - Nowy link po wygaśnięciu ✅

**Participant (1):**
7. `participant_ticket` - Bilet uczestnika ✅

**Internal (5):**
8. `internal_order_received` - Nowe zamówienie ✅
9. `internal_order_paid` - Zamówienie opłacone ✅
10. `internal_payment_expired` - Płatność wygasła ✅
11. `internal_payment_failed` - Płatność nieudana ✅
12. `internal_invoice_error` - Błąd faktury ✅

**BRAKUJĄCA FUNKCJA (placeholder):**
❌ **Retry błędnego emaila** (linia 1664-1669):
```python
@admin_v2_bp.route("/communication/<int:email_id>/retry", methods=["POST"])
@_require_permission("orders")
def email_retry(email_id: int):
    """Ponów wysyłkę emaila."""
    # Placeholder - w przyszłości implementacja ponownej wysyłki
    return redirect(url_for("admin_v2_bp.communication"))
```

**Problemy:**
- ⚠️ **Brak możliwości ponownej wysyłki** błędnego emaila
- ⚠️ **Brak automatycznego retry** dla failed emaili (3 próby z backoff)
- ⚠️ **Brak szczegółów błędu** w UI (tylko status "error")
- ⚠️ **Brak możliwości edycji szablonów** przez panel (tylko kod)

**Rekomendacje (PRIORYTET ŚREDNI):**
1. **Zaimplementować retry emaila:**
```python
def email_retry(email_id: int):
    email = get_mail_task(email_id)
    if not email or email['status'] != 'error':
        return jsonify({"success": False, "error": "Email nie może być wysłany ponownie"})
    
    # Odczytaj dane z JSON
    data = email.get('data', {})
    
    # Ponów wysyłkę
    result = _send_email_via_make_stripe(...)
    
    # Zaktualizuj status
    if result['success']:
        update_mail_task_status(email_id, 'sent', None)
    else:
        increment_retry_count(email_id)
    
    return jsonify({"success": result['success']})
```

2. **Dodać automatyczny retry w tle:**
   - Cron job (co 15 min) sprawdzający failed emaile
   - Retry z limitem (max 3 próby)
   - Exponential backoff (1 min, 5 min, 15 min)

3. **Dodać kolumnę `error_details` do `mail_log`** (pełny error stack)

---

### 3.8. ✏️ **Moduł: Email Designer**

#### Status: ⚠️ **TYLKO PODGLĄD, BRAK EDYCJI**

**Lokalizacja:** `/admin-v2/email-designer`

**Funkcje działające:**
- ✅ Dropdown wyboru wydarzenia
- ✅ Interfejs użytkownika (WYSIWYG editor)

**BRAKUJE:**
- ❌ **Brak możliwości zapisania zmian** - designer nie ma endpointu save
- ❌ **Brak faktycznej edycji szablonów** - szablony są hardcoded w `email_templates.py`
- ❌ **Brak wersjonowania szablonów** - nie ma historii zmian
- ❌ **Brak preview przed zapisem**

**Rekomendacje (PRIORYTET NISKI):**
1. Rozważyć czy Email Designer jest potrzebny (szablony są dość złożone)
2. Jeśli tak, zaimplementować:
   - Tabela `email_templates_custom` w DB
   - Endpoint `/email-designer/save` (POST)
   - Mechanizm override (custom template > default template)
   - Preview w iframe
3. Alternatywnie: przenieść edycję szablonów do kodu (jako konfiguracja JSON)

---

### 3.9. ⚙️ **Moduł: Ustawienia (Settings)**

#### Status: ⚠️ **TYLKO PLACEHOLDER**

**Lokalizacja:** `/admin-v2/settings`

**Aktualny stan:**
- ✅ Strona istnieje
- ❌ Brak jakiejkolwiek funkcjonalności

**Powinno zawierać:**
1. **Integracje:**
   - Stripe (status, klucze API, webhook URL)
   - wFirma (status tokenu, refresh, scopes)
   - Make.com (webhook URL, test connection)
   - GUS/REGON (klucz API, test)
   - Zoho Backstage (webhook URL, test)

2. **Email:**
   - Konfiguracja SMTP
   - Testowa wysyłka
   - Adresy powiadomień (BACKSTAGE_TECHNICAL_INFO_EMAIL, etc.)

3. **Ogólne:**
   - Logo firmy
   - Kolory brandingowe
   - Stopka email
   - Timezone

4. **Admini:**
   - Lista użytkowników admin (/admin-v2/users)
   - Dodawanie/edycja/usuwanie adminów
   - Zmiana uprawnień

**Rekomendacje (PRIORYTET ŚREDNI):**
1. Zaimplementować zakładki w Settings:
   - Integracje
   - Email
   - Ogólne
   - Użytkownicy (link do `/users`)

2. Dodać testy połączeń (Test Stripe, Test wFirma, Test Make)

3. Dodać możliwość zmiany hasła admina (obecnie tylko przez SQL)

---

### 3.10. 👤 **Moduł: Użytkownicy (Users)**

#### Status: ✅ **DZIAŁA, ALE BRAK EDYCJI**

**Lokalizacja:** `/admin-v2/users`

**Funkcje:**
- ✅ Lista kont administratorów
- ✅ Wyświetlanie roli, uprawnień, ostatniego logowania

**BRAKUJE:**
- ❌ **Brak możliwości dodania nowego admina** (przez panel)
- ❌ **Brak edycji admina** (zmiana uprawnień, roli)
- ❌ **Brak usuwania admina**
- ❌ **Brak blokowania/odblokowywania konta**

**Rekomendacje (PRIORYTET ŚREDNI):**
1. Dodać `/users/new` - formularz dodawania admina
2. Dodać `/users/<id>/edit` - edycja uprawnień
3. Dodać `/users/<id>/toggle-active` - blokuj/odblokuj konto
4. Dodać `/users/<id>/delete` - usuń admina (z potwierdzeniem)

---

### 3.11. 📜 **Moduł: Audit Log**

#### Status: ✅ **DZIAŁA POPRAWNIE**

**Lokalizacja:** `/admin-v2/audit-log`

**Funkcje:**
- ✅ Historia akcji administratorów (ostatnie 200)
- ✅ Filtry (akcja, wyszukiwanie)
- ✅ Wyświetlanie: admin, akcja, target, IP, timestamp
- ✅ Zapisywanie w `admin_audit_log` (logi nie są usuwane)

**Typy akcji logowanych:**
- `login_success`, `login_failed`
- `logout`
- `order_status_change`
- `order_cancelled`
- `bootstrap_create_admin`

**Problemy:**
- ⚠️ **Brak eksportu do CSV** (trudno analizować dużą liczbę logów)
- ⚠️ **Brak filtrowania po dacie** (tylko limit 200)
- ⚠️ **Brak szczegółów akcji** (pole `extra` jest w JSON, ale nie jest wyświetlane w UI)

**Rekomendacje:**
1. Dodać eksport audit log do CSV
2. Dodać filtr zakresu dat
3. Wyświetlać szczegóły akcji (`extra` JSON) w kolapsowanym panelu

---

### 3.12. 💳 **Moduł: Integracja Stripe**

#### Status: ✅ **DZIAŁA POPRAWNIE**

**Endpointy API:**
- `/api/stripe/status` - status konfiguracji ✅
- `/api/stripe/create-session` - tworzenie sesji płatności ✅
- `/api/stripe/webhook` - webhook płatności ✅
- `/api/stripe/sandbox/*` - tryb testowy ✅

**Funkcje:**
- ✅ Tworzenie Checkout Session
- ✅ Obsługa webhooków (paid, expired, failed)
- ✅ Zapisywanie sesji w DB (`stripe_sessions`)
- ✅ Aktualizacja statusu zamówienia
- ✅ Wysyłka emaili (payment confirmation, expired)
- ✅ Tryb sandbox (testowy)

**Problemy:**
- ⚠️ **Brak obsługi zwrotów (refunds)** - admin nie może zrobić refund
- ⚠️ **Brak logowania błędów** do Work Queue
- ⚠️ **Hardcoded TTL sesji** (24h) - powinno być konfigurowalne

**Rekomendacje:**
1. Dodać endpoint `/api/stripe/refund` (POST)
2. Wszystkie błędy Stripe logować do `error_queue`
3. Dodać możliwość konfiguracji TTL sesji (ENV: `STRIPE_CHECKOUT_TTL_HOURS`)

---

### 3.13. 🧾 **Moduł: Integracja wFirma**

#### Status: ✅ **DZIAŁA POPRAWNIE**

**Endpointy API:**
- `/auth` - autoryzacja OAuth2 ✅
- `/callback` - callback OAuth2 ✅
- `/api/token/refresh` - odświeżanie tokenu ✅
- `/api/token/status` - status tokenu ✅
- `/api/contractor/<nip>` - pobierz kontrahenta ✅
- `/api/contractor/add` - dodaj kontrahenta ✅
- `/api/invoice/create` - utwórz fakturę ✅
- `/api/invoice/<id>/pdf` - pobierz PDF ✅
- `/api/invoice/<id>/send` - wyślij emailem ✅
- `/api/series/list` - lista serii ✅
- `/api/workflow/create-invoice-from-nip` - główny endpoint ✅
- `/api/workflow/correction` - faktura korygująca ✅

**Funkcje:**
- ✅ OAuth2 flow (z refresh token)
- ✅ Automatyczne odświeżanie tokenu (gdy wygasa)
- ✅ Token monitor (powiadomienia o wygasaniu)
- ✅ Tworzenie faktur/proform/not księgowych/paragonów
- ✅ Pobieranie danych firmy z NIP (przez GUS)
- ✅ Generowanie PDF faktur
- ✅ Wysyłka faktur emailem (przez wFirma lub Make)
- ✅ Ochrona przed duplikacją dokumentów (UNIQUE indexes)

**Problemy:**
- ⚠️ **Webhook Zoho hardcoded** w `event_edit` (powinno być w ENV)
- ⚠️ **Brak retry dla błędów wFirma** (np. timeout, 500)
- ⚠️ **Brak dashboard wFirma** w Admin Panel (status tokenu, ostatnie faktury)

**Rekomendacje:**
1. Przenieść `ZOHO_FLOW_EVENT_UPDATE_WEBHOOK` do ENV
2. Wszystkie błędy wFirma logować do `error_queue` z retry
3. Dodać w Settings: sekcję wFirma (status tokenu, refresh, test connection)

---

### 3.14. 📬 **Moduł: Integracja Make.com (Email)**

#### Status: ✅ **DZIAŁA POPRAWNIE**

**Webhook:** `MAKE_WEBHOOK_SEND_EMAIL_REQUEST`

**Funkcje:**
- ✅ Wysyłka emaili przez Make.com
- ✅ Logowanie wysyłek w `mail_log`
- ✅ Autoryzacja (`RENDER_EMAIL_KEY_SEND_REQUEST`)
- ✅ Różne typy emaili (purchaser, participant, internal)

**Problemy:**
- ⚠️ **Brak retry dla failed emaili** (jeśli Make zwróci błąd)
- ⚠️ **Brak rate limiting** (można wysłać 1000 emaili naraz)
- ⚠️ **Brak queue** - emaile są wysyłane synchronicznie (blokujące)

**Rekomendacje:**
1. Dodać queue emaili (Celery + Redis) lub użyć `mail_log` jako queue
2. Worker w tle (cron/celery) wysyłający emaile z `mail_log` (status=queued)
3. Rate limiting (max 100 emaili/min)
4. Retry z exponential backoff

---

### 3.15. 🏢 **Moduł: Integracja GUS/REGON**

#### Status: ✅ **DZIAŁA POPRAWNIE**

**Endpointy API:**
- `/api/gus/validate-nip` - walidacja NIP ✅
- `/api/gus/name-by-nip` - nazwa firmy po NIP ✅

**Funkcje:**
- ✅ Walidacja NIP (checksum)
- ✅ Pobieranie danych z BIR/GUS (SOAP)
- ✅ Cache wyników (żeby nie pytać GUS za każdym razem)
- ✅ Fallback gdy GUS nie działa

**Problemy:**
- ⚠️ **Brak logowania błędów** (jeśli GUS timeout)
- ⚠️ **Brak cache w bazie** (tylko in-memory) - restart = strata cache
- ℹ️ **GUS czasem nie zwraca danych** (poprawny NIP, ale brak w bazie GUS)

**Rekomendacje:**
1. Dodać cache w PostgreSQL (tabela `gus_cache`)
2. Logować błędy GUS do `error_queue`
3. Dodać statystyki (ile zapytań, hit rate cache)

---

### 3.16. 🎯 **Moduł: Integracja Zoho Backstage**

#### Status: ✅ **DZIAŁA POPRAWNIE**

**Endpointy webhook (przychodzące):**
- `/api/backstage/event_create` - nowe wydarzenie ✅
- `/api/backstage/ticket_classes` - typy biletów ✅
- `/api/backstage/order` - nowe zamówienie ✅
- `/api/backstage/attendee` - nowy uczestnik ✅

**Funkcje:**
- ✅ Przyjmowanie webhooków od Backstage
- ✅ Deduplikacja (pole `dedupe_key`)
- ✅ Zapisywanie w bazie (`backstage_webhook_events`)
- ✅ Przetwarzanie zamówień (payment rules, FOC/PROFORMA/STRIPE)
- ✅ Wysyłka emaili automatyczna
- ✅ Tworzenie dokumentów wFirma
- ✅ Tworzenie sesji Stripe

**Problemy:**
- ⚠️ **Długi processing time** (synchroniczne) - webhook może timeout po 30s
- ⚠️ **Brak retry jeśli błąd** - jeśli wFirma fail, zamówienie nie ma faktury
- ⚠️ **Brak kolejkowania** - wszystkie webhooки przetwarzane od razu

**Rekomendacje (PRIORYTET ŚREDNI):**
1. Przenieść processing do queue (Celery/RQ)
2. Webhook tylko zapisuje do DB (`status=received`)
3. Worker w tle przetwarza (`status=processing` → `processed`/`failed`)
4. Retry z backoff dla błędów

---

## 4. WYKRYTE PROBLEMY

### 4.1. ❌ Krytyczne (wymagają natychmiastowej naprawy)

1. **Work Queue jest niekompletny** (tylko UI, brak logiki)
   - Brak tabeli w DB
   - Brak mechanizmu retry
   - Placeholdery w endpointach

2. **Brak implementacji wysyłki przypomnień** (`/orders/<id>/send-reminder`)
   - Placeholder w kodzie (linia 615-621)
   - Feature widoczny w UI, ale nie działa

3. **Brak implementacji ponownej wysyłki biletów** (`/orders/<id>/resend-ticket`)
   - Placeholder w kodzie (linia 624-630)
   - Feature widoczny w UI, ale nie działa

4. **Brak retry dla błędnych emaili** (`/communication/<id>/retry`)
   - Placeholder w kodzie (linia 1664-1669)
   - Błędne emaile pozostają w stanie `error` na zawsze

---

### 4.2. ⚠️ Wysokie (wymagają naprawy w najbliższym czasie)

5. **Hardcoded URL webhooka Zoho Flow** (linia 755 w `admin_v2_panel.py`)
   - Powinno być w ENV jako `ZOHO_FLOW_EVENT_UPDATE_WEBHOOK`

6. **Brak mechanizmu refund** (zwrotów Stripe)
   - Admin nie może zrobić zwrotu przez panel
   - Musi ręcznie przez Stripe Dashboard

7. **Synchroniczne przetwarzanie webhooków Backstage**
   - Długi processing time (3-10s)
   - Ryzyko timeout (30s limit)
   - Brak queue

8. **Brak automatycznego retry dla błędów**
   - wFirma errors nie są retry'owane
   - Stripe errors nie są retry'owane
   - Make errors nie są retry'owane

---

### 4.3. ⚠️ Średnie (nice-to-have)

9. **Brak mechanizmu "zapomniałem hasła"**
   - Admin nie może odzyskać hasła
   - Musi prosić super admina

10. **Brak timeout sesji**
    - Sesje nie wygasają
    - Ryzyko bezpieczeństwa

11. **Brak edycji danych uczestnika**
    - Nie można zmienić nazwiska, email
    - Trzeba ręcznie w DB

12. **Brak dashboard wFirma w Settings**
    - Nie widać statusu tokenu
    - Nie widać ostatnich faktur

13. **Email Designer jest placeholderem**
    - Brak save/edit szablonów
    - Tylko podgląd

14. **Settings jest pustym placeholderem**
    - Brak jakiejkolwiek funkcjonalności

---

### 4.4. ℹ️ Niskie (ulepszenia)

15. **Brak cache'owania statystyk Dashboard**
    - Każde odświeżenie = query do DB
    - Przy dużych danych może być wolne

16. **Duplikacja dashboardów wydarzeń** (`/dashboard` vs `/room`)
    - Niepotrzebna redundancja

17. **Brak eksportu audit log do CSV**
    - Trudno analizować duże logi

18. **Brak bulk actions**
    - Nie można zaznaczyć wielu zamówień/uczestników i wykonać akcji

19. **Brak możliwości duplikowania wydarzenia**
    - Trzeba ręcznie przepisywać dane

20. **Brak rate limiting dla emaili**
    - Można wysłać 1000 emaili naraz

---

## 5. BRAKUJĄCE FUNKCJE

### 5.1. Funkcje widoczne w UI, ale niedziałające (placeholdery)

| Funkcja | Lokalizacja | Status | Priorytet |
|---------|-------------|--------|-----------|
| Wysyłka przypomnienia | `/orders/<id>/send-reminder` | ❌ Placeholder | Wysoki |
| Ponowna wysyłka biletu | `/orders/<id>/resend-ticket` | ❌ Placeholder | Wysoki |
| Retry błędnego emaila | `/communication/<id>/retry` | ❌ Placeholder | Średni |
| Retry zadania Work Queue | `/work-queue/<id>/retry` | ❌ Placeholder | Wysoki |
| Retry wszystkich zadań | `/work-queue/retry-all` | ❌ Placeholder | Wysoki |
| Email Designer save | `/email-designer/save` | ❌ Nie istnieje | Niski |

### 5.2. Funkcje opisane w dokumentacji, ale niezaimplementowane

Brak (dokumentacja API jest zgodna z implementacją)

### 5.3. Funkcje oczekiwane w systemie CMS/Admin, ale brak

| Funkcja | Opis | Priorytet |
|---------|------|-----------|
| Refund zamówienia | Zwrot płatności Stripe | Wysoki |
| Edycja uczestnika | Zmiana danych osobowych | Średni |
| Dodanie uczestnika ręcznie | Rejestracja bez Backstage | Średni |
| Dodanie admina przez panel | Tworzenie konta admin w UI | Średni |
| Edycja admina | Zmiana uprawnień w UI | Średni |
| Bulk actions | Masowe operacje na zamówieniach/uczestnikach | Niski |
| Zapomniałem hasła | Reset hasła admina | Średni |
| 2FA | Dwuskładnikowe uwierzytelnianie | Niski |
| Duplikacja wydarzenia | Kopiowanie wydarzenia jako template | Niski |
| Dashboard integracji | Status Stripe, wFirma, Make, GUS | Średni |

---

## 6. REKOMENDACJE

### 6.1. 🚨 Priorytet 1: Krytyczne (do zrobienia natychmiast)

#### 1. Zaimplementować Work Queue

**Problem:** Moduł istnieje w UI, ale nie ma logiki. Wszystkie błędy systemowe nie są logowane ani retry'owane.

**Rozwiązanie:**
1. Utworzyć tabelę `error_queue` w bazie
2. Dodać funkcje w `pg_storage.py` (save/list/retry/resolve)
3. Zintegrować z wszystkimi modułami (backstage, stripe, wfirma, email)
4. Zaimplementować endpointy retry
5. Dodać cron job automatycznego retry (co 15 min)

**Czas realizacji:** 3-5 dni  
**Impact:** Krytyczny - obecnie błędy "giną w logach"

---

#### 2. Zaimplementować wysyłkę przypomnień i biletów

**Problem:** Funkcje są widoczne w UI (Operational Bar), ale nie działają.

**Rozwiązanie:**
1. Endpoint `/orders/<id>/send-reminder`:
   - Sprawdź status zamówienia (pending_payment)
   - Wygeneruj email przypomnienia (szablon `checkout_reminder`)
   - Wyślij przez Make
   - Zapisz w mail_log

2. Endpoint `/orders/<id>/resend-ticket`:
   - Sprawdź status zamówienia (paid)
   - Pobierz uczestników
   - Wygeneruj emaile z biletami (szablon `participant_ticket`)
   - Wyślij dla każdego uczestnika

**Czas realizacji:** 1-2 dni  
**Impact:** Wysoki - admin używa tych funkcji regularnie

---

#### 3. Przenieść hardcoded webhooki do ENV

**Problem:** Webhook Zoho Flow jest hardcoded w kodzie (unsafe).

**Rozwiązanie:**
1. Dodać do ENV:
   ```bash
   ZOHO_FLOW_EVENT_UPDATE_WEBHOOK=https://flow.zoho.eu/...
   ```
2. Zmienić w kodzie:
   ```python
   ZOHO_FLOW_EVENT_UPDATE_WEBHOOK = os.environ.get("ZOHO_FLOW_EVENT_UPDATE_WEBHOOK", "")
   ```

**Czas realizacji:** 15 minut  
**Impact:** Bezpieczeństwo

---

### 6.2. ⚠️ Priorytet 2: Wysokie (do zrobienia w ciągu tygodnia)

#### 4. Dodać mechanizm refund (zwrotów Stripe)

**Rozwiązanie:**
1. Endpoint `/orders/<id>/refund` (POST):
   ```python
   @admin_v2_bp.route("/orders/<order_id>/refund", methods=["POST"])
   def order_refund(order_id: str):
       order = get_order(order_id)
       stripe_session = get_stripe_session_by_order_id(order_id)
       
       # Refund przez Stripe API
       refund = stripe.Refund.create(
           payment_intent=stripe_session['payment_intent_id'],
           reason='requested_by_customer'
       )
       
       # Aktualizuj status
       update_order_status(order_id, 'refunded')
       
       # Wyślij email
       send_refund_confirmation_email(...)
       
       return jsonify({"success": True})
   ```

2. Dodać button "Refund" w Operational Bar

**Czas realizacji:** 1 dzień  
**Impact:** Wysoki - potrzebne dla obsługi klienta

---

#### 5. Zaimplementować retry dla błędnych emaili

**Rozwiązanie:**
1. Endpoint `/communication/<id>/retry`
2. Cron job automatycznego retry (co 15 min, max 3 próby)
3. Exponential backoff (1 min, 5 min, 15 min)

**Czas realizacji:** 1 dzień  
**Impact:** Wysoki - błędne emaile obecnie "giną"

---

#### 6. Przeprocesować webhooки Backstage asynchronicznie

**Problem:** Długi processing time (3-10s) może powodować timeout.

**Rozwiązanie:**
1. Użyć Celery + Redis lub prostego queue w PostgreSQL
2. Webhook tylko zapisuje do DB (`status=received`)
3. Worker przetwarza w tle
4. Retry z backoff dla błędów

**Czas realizacji:** 2-3 dni  
**Impact:** Średni - lepsze UX, mniej timeout

---

### 6.3. ⚠️ Priorytet 3: Średnie (nice-to-have)

#### 7. Dodać mechanizm "zapomniałem hasła"

**Rozwiązanie:**
1. Endpoint `/admin-v2/forgot-password` (GET/POST)
2. Generuj token reset (UUID)
3. Wyślij email z linkiem
4. Endpoint `/admin-v2/reset-password?token=...`
5. Zapisz token w `admin_users.password_reset_token` + expiry

**Czas realizacji:** 1 dzień  
**Impact:** UX dla adminów

---

#### 8. Dodać dashboard Settings z integracjami

**Rozwiązanie:**
1. Zakładki: Integracje, Email, Ogólne, Użytkownicy
2. W Integracje:
   - Stripe (status, test connection, webhook URL)
   - wFirma (status tokenu, expires, refresh, scopes)
   - Make (webhook URL, test)
   - GUS (klucz, test)
   - Backstage (webhook URL)

**Czas realizacji:** 2 dni  
**Impact:** Lepsze zarządzanie integracjami

---

#### 9. Dodać edycję danych uczestnika

**Rozwiązanie:**
1. Endpoint `/participants/<id>/edit` (GET/POST)
2. Formularz: email, imię, nazwisko, telefon, firma
3. Walidacja (nie pozwól na duplikat email w tym samym zamówieniu)

**Czas realizacji:** pół dnia  
**Impact:** UX

---

#### 10. Dodać cache statystyk Dashboard

**Rozwiązanie:**
1. Redis (lub tabela `dashboard_cache` w PostgreSQL)
2. Cache na 5 minut
3. Przycisk "Odśwież" force refresh

**Czas realizacji:** pół dnia  
**Impact:** Wydajność (przy dużych danych)

---

### 6.4. ℹ️ Priorytet 4: Niskie (przyszłość)

- Bulk actions (zaznacz wiele zamówień → wykonaj akcję)
- 2FA dla adminów
- Duplikacja wydarzenia
- Email Designer z save (jeśli naprawdę potrzebne)
- Eksport audit log do CSV
- Rate limiting emaili (max 100/min)
- Cache GUS w PostgreSQL
- Timeout sesji (8h bezczynności)

---

## 7. POZYTYWNE ASPEKTY (co działa dobrze)

### 7.1. ✅ Bardzo dobrze zaimplementowane

1. **Architektura bazy danych** - przemyślana, z indeksami i unique constraints
2. **OAuth2 wFirma** - pełna implementacja z auto-refresh
3. **Integracja Stripe** - kompletna (tworzenie sesji, webhooki, statusy)
4. **Szablony email** - 12 profesjonalnych szablonów, responsywne, z brandingiem
5. **Audit log** - każda akcja admina jest logowana
6. **Normalizacja danych Backstage** - mapowanie pól między systemami
7. **Ochrona przed duplikacją faktur** - UNIQUE indexes w DB
8. **Token monitor wFirma** - automatyczne powiadomienia o wygasającym tokenie
9. **Deduplikacja webhooków Backstage** - pole `dedupe_key`
10. **Walidacja NIP przez GUS** - sprawdzenie checksum + zapytanie do BIR
11. **UI/UX Admin Panel V2** - nowoczesny, responsywny, intuicyjny
12. **Event Room** - świetny hub z zakładkami dla pojedynczego wydarzenia
13. **Historia zamówienia** - kompletna timeline (emaile, płatności, dokumenty)
14. **Eksporty CSV** - zamówienia, uczestnicy, komunikacja
15. **Filtrowanie i wyszukiwanie** - w każdym module (wydarzenia, zamówienia, uczestnicy)

---

## 8. PODSUMOWANIE I WNIOSKI

### 8.1. Stan aplikacji

Aplikacja **Medidesk Admin Panel V2** jest **funkcjonalna i działająca na produkcji**. Rdzeń systemu (wydarzenia, zamówienia, płatności, faktury, komunikacja) działa poprawnie i obsługuje cały proces sprzedaży biletów:

1. Zoho Backstage → webhook → zapisanie zamówienia
2. Analiza payment rules → FOC/PROFORMA/STRIPE
3. Stripe → płatność → webhook → aktualizacja statusu
4. wFirma → faktura/proforma → PDF → wysyłka email
5. Make.com → wysyłka emaili (linki, potwierdzenia, bilety)
6. Admin Panel V2 → zarządzanie wszystkim

**Ocena końcowa:** 7/10

---

### 8.2. Co wymaga natychmiastowej naprawy (Priorytet 1)

1. **Work Queue** - kompletna implementacja (tabela DB + logika + retry)
2. **Wysyłka przypomnień i biletów** - usunięcie placeholderów
3. **Hardcoded webhooki** - przeniesienie do ENV

**Szacowany czas:** 5-7 dni roboczych

---

### 8.3. Co warto zrobić w najbliższym czasie (Priorytet 2)

1. **Refund zamówień** przez Stripe API
2. **Retry błędnych emaili** (automatyczne + manualne)
3. **Asynchroniczne przetwarzanie webhooków** (queue)

**Szacowany czas:** 4-5 dni roboczych

---

### 8.4. Roadmap rozwoju (Priorytet 3-4)

1. Dashboard Settings z integracjami (2 dni)
2. Zapomniałem hasła (1 dzień)
3. Edycja uczestnika (0.5 dnia)
4. Cache statystyk (0.5 dnia)
5. Bulk actions (2 dni)
6. 2FA dla adminów (2 dni)
7. Email Designer save (3 dni - jeśli potrzebne)

---

### 8.5. Metryki jakości kodu

**Pozytywne:**
- ✅ Kod jest czytelny i dobrze skomentowany
- ✅ Funkcje mają jasne nazwy i odpowiedzialności
- ✅ Baza danych jest znormalizowana (3NF)
- ✅ Używane są prepared statements (SQL injection safe)
- ✅ ENV variables dla konfiguracji
- ✅ Separacja logiki (pg_storage, email_templates, stripe_integration)

**Do poprawy:**
- ⚠️ Brak testów automatycznych (unit tests, integration tests)
- ⚠️ Brak CI/CD pipeline
- ⚠️ Brak monitoringu (Sentry, logging aggregation)
- ⚠️ Brak dokumentacji API (Swagger/OpenAPI)
- ⚠️ Niektóre funkcje są bardzo długie (>200 linii)

---

### 8.6. Rekomendacje strategiczne

#### Krótkoterminowe (1-2 tygodnie)
1. Naprawić placeholdery (Work Queue, przypomnienia, bilety)
2. Dodać retry dla błędów
3. Przenieść hardcoded wartości do ENV

#### Średnioterminowe (1-2 miesiące)
1. Zaimplementować refundy
2. Dodać queue dla webhooków i emaili
3. Rozbudować Settings
4. Dodać cache dla wydajności

#### Długoterminowe (3-6 miesięcy)
1. Napisać testy automatyczne (min. 50% coverage)
2. Dodać CI/CD (GitHub Actions + auto-deploy)
3. Dodać monitoring (Sentry, metrics)
4. Dokumentacja API (Swagger)
5. Rozważyć migrację z Jinja2 na full React SPA

---

## 9. KONTAKT I WSPARCIE

Ten audyt został przeprowadzony 24 stycznia 2026.

W razie pytań lub potrzeby pomocy w implementacji rekomendacji, skontaktuj się z zespołem deweloperskim.

---

**Koniec raportu**
