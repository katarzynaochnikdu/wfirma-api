""" 
wFirma API - Web Service dla Render
Flask web app z OAuth 2.0 i endpointami API
"""
from flask import Flask, request, redirect, jsonify, Response, send_file, session
import requests
import json
import os
import os
import time
import re
import datetime
import base64
import uuid
import traceback
import hashlib
import xml.etree.ElementTree as ET
from urllib.parse import quote
from functools import wraps
import threading

app = Flask(__name__)

# ---------------------------------------------------------------------------
# FLASK SECRET KEY (wymagany dla sesji i CSRF w panelu admin)
# ---------------------------------------------------------------------------
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "").strip()
if FLASK_SECRET_KEY:
    app.secret_key = FLASK_SECRET_KEY
    # Konfiguracja bezpiecznych sesji
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Secure=True tylko gdy jest HTTPS (na Render zawsze jest)
    # Lokalnie może być HTTP, więc sprawdzamy czy to produkcja
    if os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"):
        app.config["SESSION_COOKIE_SECURE"] = True
else:
    print("[WARN] Brak FLASK_SECRET_KEY w ENV - sesje admin nie będą działać")

# Panel admin (konfiguracja eventów w Postgres)
try:
    from admin_panel import admin_bp
    app.register_blueprint(admin_bp, url_prefix="/admin")
except Exception as e:
    # Nie blokuj startu serwera, jeśli zależności panelu nie są gotowe.
    print(f"[ADMIN] Panel admin nieaktywny: {e}")

# Panel admin V2 - nowy UI (włączany przez ADMIN_V2_ENABLED=1)
ADMIN_V2_ENABLED = os.environ.get("ADMIN_V2_ENABLED", "0").strip() == "1"
if ADMIN_V2_ENABLED:
    try:
        from admin_v2_panel import admin_v2_bp
        app.register_blueprint(admin_v2_bp, url_prefix="/admin-v2")
        print("[ADMIN V2] Panel admin V2 aktywny pod /admin-v2")
    except Exception as e:
        print(f"[ADMIN V2] Panel admin V2 nieaktywny: {e}")
else:
    print("[ADMIN V2] Panel admin V2 wyłączony (ustaw ADMIN_V2_ENABLED=1 aby włączyć)")

# ---------------------------------------------------------------------------
# JINJA2 TEMPLATE FILTERS (dla admin panel V2)
# ---------------------------------------------------------------------------

@app.template_filter('format_date_pl')
def format_date_pl_filter(value):
    """Formatuje datę po polsku (np. '23 stycznia 2026, 14:30')."""
    if not value:
        return '—'
    try:
        if isinstance(value, str):
            # Próbuj sparsować ISO format
            value = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        
        months_pl = ['stycznia', 'lutego', 'marca', 'kwietnia', 'maja', 'czerwca',
                     'lipca', 'sierpnia', 'września', 'października', 'listopada', 'grudnia']
        
        if hasattr(value, 'strftime'):
            day = value.day
            month = months_pl[value.month - 1]
            year = value.year
            time_str = value.strftime('%H:%M')
            return f"{day} {month} {year}, {time_str}"
        return str(value)
    except Exception:
        return str(value) if value else '—'


@app.template_filter('format_currency')
def format_currency_filter(value):
    """Formatuje kwotę jako PLN (np. '1 234,56 zł')."""
    if value is None:
        return '0,00 zł'
    try:
        num = float(value)
        # Format: 1 234,56 zł
        formatted = f"{num:,.2f}".replace(",", " ").replace(".", ",")
        return f"{formatted} zł"
    except (ValueError, TypeError):
        return '0,00 zł'


# Statyczne logo Backstage
@app.route('/backstage-logo.jpg', methods=['GET'])
def backstage_logo():
    """Serwuje logo Backstage."""
    logo_path = os.path.join(os.path.dirname(__file__), 'backstage-logo.jpg')
    return send_file(logo_path, mimetype='image/jpeg')


@app.route('/Empty_order_list.png', methods=['GET'])
def empty_order_list():
    """Serwuje obrazek pustej listy zamówień (PNG)."""
    image_path = os.path.join(os.path.dirname(__file__), 'Empty_order_list.png')
    return send_file(image_path, mimetype='image/png')


@app.route('/Empty_list_1.jpg', methods=['GET'])
def empty_list_1():
    """Serwuje obrazek pustej listy (JPG)."""
    image_path = os.path.join(os.path.dirname(__file__), 'Empty_list_1.jpg')
    return send_file(image_path, mimetype='image/jpeg')

# Konfiguracja z zmiennych środowiskowych (wFirma OAuth)
# UWAGA: Teraz obsługujemy dwa zestawy danych: WFIRMA_MD_* i WFIRMA_TEST_*
CLIENT_ID = os.environ.get('CLIENT_ID')
CLIENT_SECRET = os.environ.get('CLIENT_SECRET')
# DEPRECATED: REDIRECT_URI globalny - użyj WFIRMA_<COMPANY>_REDIRECT_URI per firma
# Pozostawiono tylko dla kompatybilności wstecznej (nie jest używany w OAuth)
REDIRECT_URI = os.environ.get('REDIRECT_URI', '')
TOKEN_FILE = "wfirma_token.json"

# Obsługiwane firmy/zestawy danych
# md = Medidesk produkcja
# test = Konto testowe (osobne tokeny)
# md_test = Medidesk produkcja + ostrzeżenie testowe na fakturach
SUPPORTED_COMPANIES = ['md', 'test', 'md_test']
DEFAULT_COMPANY = 'md'  # Domyślna firma jeśli nie podano


def _pg_company_name(company: str) -> str:
    """
    Mapuje nazwę firmy na nazwę używaną w Postgres dla tokenów.
    md_test używa tokenów MD, więc mapujemy na 'md'.
    """
    c = (company or DEFAULT_COMPANY).lower().strip()
    if c == 'md_test':
        return 'md'
    return c


def get_company_config(company: str = None) -> dict:
    """
    Pobierz konfigurację dla danej firmy (md, test, md_test).
    Zwraca dict z client_id, client_secret, redirect_uri oraz pg_company (nazwa w Postgres).
    
    md_test używa danych MD (te same tokeny co produkcja) ale z ostrzeżeniem testowym.
    
    WAŻNE: redirect_uri jest pobierane WYŁĄCZNIE z WFIRMA_<COMPANY>_REDIRECT_URI (bez fallbacków).
    WAŻNE: Tokeny NIE są już pobierane z ENV - używaj Postgres (pg_company).
    """
    company = (company or DEFAULT_COMPANY).lower().strip()
    if company not in SUPPORTED_COMPANIES:
        company = DEFAULT_COMPANY
    
    # md_test używa tych samych danych co md (prefix WFIRMA_MD_)
    if company == 'md_test':
        prefix = "WFIRMA_MD_"
    else:
        prefix = f"WFIRMA_{company.upper()}_"
    
    # redirect_uri: wyłącznie z WFIRMA_<COMPANY>_REDIRECT_URI (BEZ fallbacków!)
    redirect_uri = os.environ.get(f'{prefix}REDIRECT_URI')
    
    return {
        'company': company,
        'pg_company': _pg_company_name(company),  # nazwa firmy w Postgres dla tokenów
        'prefix': prefix,
        'client_id': os.environ.get(f'{prefix}CLIENT_ID') or CLIENT_ID,
        'client_secret': os.environ.get(f'{prefix}CLIENT_SECRET') or CLIENT_SECRET,
        'redirect_uri': redirect_uri,  # None jeśli nie ustawiono - wymaga 500 w /auth i /callback
    }

# Konfiguracja Render API (do trwałego zapisu tokenów)
RENDER_API_KEY = os.environ.get('RENDER_API_KEY')
RENDER_SERVICE_ID = os.environ.get('RENDER_SERVICE_ID')

# Bezpieczeństwo API - wymagany klucz dla Make.com (lub innych klientów)
MAKE_RENDER_API_KEY = os.environ.get('MAKE_RENDER_API_KEY')  # Ustaw w Render ENV!

# Konfiguracja GUS/BIR (przeniesiona z backendu Googie_GUS)
# Najpierw próbujemy standardowej zmiennej GUS_API_KEY,
# jeśli brak – użyjemy ewentualnej BIR1_medidesk (z GCP).
GUS_API_KEY = os.environ.get('GUS_API_KEY') or os.environ.get('BIR1_medidesk')
GUS_USE_TEST = (os.environ.get('GUS_USE_TEST', 'false') or '').lower() == 'true'

# GitHub token do uploadu zdjęć stopki email
GITHUB_STOPKA_TOKEN = os.environ.get('ADMINZOHO_GITHUB_STOPKA_TOKEN')

# Token dla endpointu stopka/upload-photo (osobny od MAKE_RENDER_API_KEY)
HTML_GENERATOR_API_KEY_TOKEN = os.environ.get('HTML_GENERATOR_API_KEY_TOKEN')

# Token dla endpointów GUS/REGON (osobny od MAKE_RENDER_API_KEY)
REGON_API_KEY_TOKEN = os.environ.get('REGON_API_KEY_TOKEN')

# Powiadomienia o wygasającym refresh tokenie
EMAIL_REFRESH_TOKEN_EXPIRE = os.environ.get('EMAIL_REFRESH_TOKEN_EXPIRE')  # Email do powiadomień
WEBHOOK_TOKEN_EXPIRE_NOTIFY = os.environ.get('WEBHOOK_TOKEN_EXPIRE_NOTIFY')  # URL webhooka (np. Make.com)

# Make.com email webhook (spójne z Backstage Engine)
MAKE_WEBHOOK_SEND_EMAIL_REQUEST = os.environ.get("MAKE_WEBHOOK_SEND_EMAIL_REQUEST", "")
RENDER_EMAIL_KEY_SEND_REQUEST = os.environ.get("RENDER_EMAIL_KEY_SEND_REQUEST", "")

# Token monitor: docelowy odbiorca
WFIRMA_TOKEN_EXPIRES_ALERT_EMAIL = os.environ.get("WFIRMA_TOKEN_EXPIRES_ALERT_EMAIL", "adam.pragacz@medidesk.com")

# Link do autoryzacji (MD)
WFIRMA_AUTH_URL_MD = os.environ.get("WFIRMA_AUTH_URL_MD", "https://wfirma-api.onrender.com/auth?company=md")

# SCOPES per firma - muszą odpowiadać konfiguracji w wFirma!
SCOPES_MD = [
    # Zgodne z konfiguracją w wFirma dla Medidesk (API_RENDER_ADMIN_ZOHO)
    "companies-read",
    "contractors-read", "contractors-write",
    "goods-read", "goods-write",
    "invoice_descriptions-read",
    "invoice_deliveries-read", "invoice_deliveries-write",
    "invoices-read", "invoices-write",
    "payments-read", "payments-write",
    "series-read", "series-write",
    "tags-read", "tags-write",
    "webhooks-read", "webhooks-write",
]

SCOPES_TEST = [
    # Zgodne z konfiguracją w wFirma dla TEST (API_render)
    "companies-read",
    "contractors-read", "contractors-write",
    "documents-read",
    "goods-read", "goods-write",
    "invoice_descriptions-read",
    "invoice_deliveries-read", "invoice_deliveries-write",
    "invoices-read", "invoices-write",
    "notes-read", "notes-write",
    "payments-read", "payments-write",
    "series-read", "series-write",
    "tags-read", "tags-write",
    "webhooks-read", "webhooks-write",
]

# Domyślne SCOPES (dla backward compatibility)
SCOPES = SCOPES_MD


def get_scopes_for_company(company: str = None) -> list:
    """Pobierz listę SCOPES dla danej firmy."""
    company = (company or DEFAULT_COMPANY).lower().strip()
    if company == 'test':
        return SCOPES_TEST
    return SCOPES_MD


def require_api_key(f):
    """Decorator wymagający API Key w headerze X-API-Key (ochrona przed nieuprawnionymi wywołaniami)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # BEZPIECZEŃSTWO: jeśli klucz nie jest ustawiony, NIE przepuszczaj requestów (fail-closed).
        # To chroni system, gdy ENV "zniknie" przy deployu.
        if not MAKE_RENDER_API_KEY:
            print("[SECURITY] Brak MAKE_RENDER_API_KEY w ENV - blokuję endpoint wymagający X-API-Key")
            return jsonify({
                'error': 'Server misconfigured',
                'message': 'Brak MAKE_RENDER_API_KEY w konfiguracji serwera'
            }), 503
        
        # Sprawdź header X-API-Key
        provided_key = request.headers.get('X-API-Key', '').strip()
        
        if not provided_key:
            return jsonify({
                'error': 'Brak autoryzacji',
                'message': 'Wymagany header X-API-Key'
            }), 401
        
        if provided_key != MAKE_RENDER_API_KEY:
            return jsonify({
                'error': 'Nieprawidłowy klucz API',
                'message': 'X-API-Key jest niepoprawny'
            }), 403
        
        return f(*args, **kwargs)
    return decorated_function


@app.route('/api/health', methods=['GET'])
def api_health():
    """
    Publiczny status serwisu (bez sekretów).
    Cel: szybka diagnostyka po deployu, gdy ENV bywa usuwane/niepełne.
    """
    def _present(name: str) -> bool:
        return bool((os.environ.get(name) or "").strip())

    critical = [
        # Autoryzacja internal API / webhooków (Zoho/Make)
        "MAKE_RENDER_API_KEY",
        # Stripe webhook signature verification
        "STRIPE_WEBHOOK_SECRET",
        # DB (Backstage core)
        "DATABASE_URL",
    ]
    backstage_optional = [
        "MAKE_WEBHOOK_SEND_EMAIL_REQUEST",
        "BACKSTAGE_TECHNICAL_INFO_EMAIL",
        "BACKSTAGE_EVENT_INFO_EMAIL",
        "STRIPE_RENDER_API_KEY",
    ]

    missing_critical = [k for k in critical if not _present(k)]
    missing_optional = [k for k in backstage_optional if not _present(k)]

    ok = len(missing_critical) == 0
    mode = "ok" if ok else "degraded"

    # Jeśli wykryto krytyczne braki, wyślij alert (z throttlingiem, bo endpoint jest publiczny).
    if not ok:
        try:
            _maybe_send_critical_env_alert(missing_critical, missing_optional)
        except Exception as e:
            print(f"[HEALTH] Alert send error: {e}")

    return jsonify({
        "ok": ok,
        "mode": mode,
        "missing_critical_env": missing_critical,
        "missing_optional_env": missing_optional,
    }), (200 if ok else 503)


@app.route('/api/events/<event_id>/calendar.ics', methods=['GET'])
def event_calendar_ics(event_id: str):
    """
    Generuje plik .ics (iCalendar) dla wydarzenia.
    Publiczny endpoint - można linkować w mailach/na stronach.
    Obsługuje Google Calendar, Outlook, Apple Calendar.
    
    Jeśli event_days_count > 1, generuje osobny wpis na każdy dzień
    (codziennie od tej samej godziny, 8h każdego dnia).
    """
    from pg_storage import get_event
    
    ev = get_event(event_id)
    if not ev:
        return "Nie znaleziono wydarzenia", 404
    
    data = ev.get("data") or {}
    event_name = ev.get("event_name") or data.get("eventName") or "Wydarzenie"
    
    import datetime as dt
    
    def _parse_iso_datetime(s: str) -> dt.datetime | None:
        """Parsuje datę (ISO + popularne formaty), zwraca None jeśli błąd."""
        if not s:
            return None
        raw = s.strip()
        if not raw:
            return None
        # ISO 8601 (z obsługą Z / offsetu)
        try:
            iso_val = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
            return dt.datetime.fromisoformat(iso_val)
        except Exception:
            pass
        # Popularne formaty z CSV / ręcznego wprowadzenia
        for fmt in (
            "%d-%m-%Y %H:%M",
            "%d-%m-%Y %H:%M:%S",
            "%d.%m.%Y %H:%M",
            "%d.%m.%Y %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%d.%m.%Y",
        ):
            try:
                return dt.datetime.strptime(raw, fmt)
            except Exception:
                continue
        return None
    
    # Data i czas START
    event_datetime_str = data.get("event_date_time") or ""
    first_day_start = _parse_iso_datetime(event_datetime_str)
    if not first_day_start:
        first_day_start = dt.datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    
    # Data i czas KONIEC (opcjonalne)
    event_end_datetime_str = data.get("event_end_date_time") or ""
    last_day_end = _parse_iso_datetime(event_end_datetime_str)
    
    # Liczba dni: automatycznie z dat lub ręcznie z event_days_count
    days_count = 1
    if last_day_end and last_day_end >= first_day_start:
        # Policz dni z różnicy dat (włącznie z dniem startu i końca)
        delta_days = (last_day_end.date() - first_day_start.date()).days + 1
        days_count = max(1, min(delta_days, 14))  # 1-14 dni
    else:
        # Fallback: użyj ręcznego event_days_count
        try:
            days_count_str = data.get("event_days_count") or "1"
            days_count = int(days_count_str)
            if days_count < 1:
                days_count = 1
            if days_count > 14:
                days_count = 14
        except (ValueError, TypeError):
            days_count = 1
    
    # Lokalizacja
    location_parts = []
    if data.get("event_location_place"):
        location_parts.append(data["event_location_place"])
    if data.get("event_location_address"):
        location_parts.append(data["event_location_address"])
    if data.get("event_location_city"):
        location_parts.append(data["event_location_city"])
    if data.get("event_country"):
        location_parts.append(data["event_country"])
    location = ", ".join(location_parts) if location_parts else ""
    
    # Godzina startu (zachowaj dla każdego dnia)
    start_hour = first_day_start.hour
    start_minute = first_day_start.minute
    
    # Format dla iCal: YYYYMMDDTHHmmss (local) albo YYYYMMDDTHHmmssZ (UTC)
    def to_ical_dt(d: dt.datetime) -> str:
        if d.tzinfo is None:
            return d.strftime("%Y%m%dT%H%M%S")
        return d.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    
    dtstamp = to_ical_dt(dt.datetime.utcnow())
    
    # Opis - usuń HTML i pozostaw czysty tekst
    def strip_html(html_str: str) -> str:
        """Usuwa tagi HTML i zwraca czysty tekst."""
        import re
        if not html_str:
            return ""
        # Zamień <br> i </p> na nowe linie
        text = re.sub(r'<br\s*/?>', '\n', html_str, flags=re.IGNORECASE)
        text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
        # Usuń wszystkie pozostałe tagi HTML
        text = re.sub(r'<[^>]+>', '', text)
        # Dekoduj encje HTML
        import html
        text = html.unescape(text)
        # Usuń wielokrotne puste linie
        text = re.sub(r'\n\s*\n', '\n\n', text)
        return text.strip()
    
    raw_description = data.get("event_description") or f"Wydarzenie: {event_name}"
    base_description = strip_html(raw_description)
    
    # Escape special characters for iCal
    def ical_escape(s: str) -> str:
        return s.replace("\r", "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    
    # Generuj VEVENT dla każdego dnia
    vevents = []
    for day_num in range(days_count):
        day_start = first_day_start + dt.timedelta(days=day_num)
        day_start = day_start.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
        day_end = day_start + dt.timedelta(hours=8)
        
        # Tytuł z numerem dnia (jeśli wielodniowe)
        if days_count > 1:
            day_title = f"{event_name} (Dzień {day_num + 1}/{days_count})"
            day_description = f"Dzień {day_num + 1} z {days_count}. {base_description}"
        else:
            day_title = event_name
            day_description = base_description
        
        vevent_lines = [
            "BEGIN:VEVENT",
            f"UID:event-{event_id}-day{day_num + 1}@medidesk.pl",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART:{to_ical_dt(day_start)}",
            f"DTEND:{to_ical_dt(day_end)}",
            f"SUMMARY:{ical_escape(day_title)}",
            f"LOCATION:{ical_escape(location)}",
            f"DESCRIPTION:{ical_escape(day_description)}",
            "STATUS:CONFIRMED",
            "END:VEVENT",
        ]
        vevents.append("\r\n".join(vevent_lines))
    
    # Generuj pełny .ics
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Medidesk//Events//PL",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        *vevents,
        "END:VCALENDAR",
        "",
    ]
    ics_content = "\r\n".join(ics_lines)
    
    # Zwróć jako plik do pobrania (nazwa pliku = nazwa wydarzenia)
    from flask import Response
    import re
    from urllib.parse import quote
    raw_filename = (event_name or "wydarzenie").strip()
    safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_filename).strip("_")
    if not safe_filename:
        safe_filename = str(event_id or "wydarzenie")
    filename = f"{safe_filename}.ics"
    filename_star = quote(f"{raw_filename}.ics")
    return Response(
        ics_content,
        content_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{filename_star}'
        }
    )


# Throttling alertów health (ochrona przed spamem, bo /api/health jest publiczne).
_HEALTH_ALERT_LAST_SENT_AT: float = 0.0
_HEALTH_ALERT_THROTTLE_SECONDS: int = 6 * 60 * 60  # 6h


def _make_email_configured() -> bool:
    # Dla alertów /api/health używamy samego URL webhooka (bez dodatkowego klucza),
    # bo `RENDER_EMAIL_KEY_SEND_REQUEST` jest u Ciebie zarezerwowany pod token-expiry.
    return bool((MAKE_WEBHOOK_SEND_EMAIL_REQUEST or "").strip())


def _maybe_send_critical_env_alert(missing_critical: list, missing_optional: list) -> None:
    global _HEALTH_ALERT_LAST_SENT_AT
    import time as _time

    now = _time.time()
    if _HEALTH_ALERT_LAST_SENT_AT and (now - _HEALTH_ALERT_LAST_SENT_AT) < _HEALTH_ALERT_THROTTLE_SECONDS:
        return

    # Jeśli nie mamy jak wysłać maila (Make webhook), tylko loguj.
    if not _make_email_configured():
        print(f"[HEALTH] Missing critical env={missing_critical} (no Make email configured)")
        return

    to_email = "adminzoho@medidesk.com"
    # Użytkownik chciał czytelny temat z wykrzyknikami.
    subject = f"!!! KRYTYCZNE BRAKI ENV !!! ({', '.join(missing_critical)})"

    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    body_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 16px;">
      <h2 style="color:#dc2626;">!!! KRYTYCZNE BRAKI ENV !!!</h2>
      <p><strong>Czas:</strong> {ts}</p>
      <p><strong>Missing critical:</strong> {', '.join(missing_critical) if missing_critical else '(none)'}</p>
      <p><strong>Missing optional:</strong> {', '.join(missing_optional) if missing_optional else '(none)'}</p>
      <hr>
      <p style="color:#6b7280; font-size:12px;">
        To jest automatyczny alert z <code>/api/health</code>. Nie zawiera wartości sekretów – tylko nazwy brakujących zmiennych.
      </p>
    </body>
    </html>
    """

    # Wyślij przez Make.com (spójny format jak inne emaile w systemie)
    try:
        payload = {
            "to": to_email,
            "subject": subject,
            "body_html": body_html,
            "event_order_id": "HEALTH",
            "template_type": "critical_env_missing",
        }
        headers = {
            "Content-Type": "application/json",
        }
        resp = requests.post(MAKE_WEBHOOK_SEND_EMAIL_REQUEST, json=payload, headers=headers, timeout=15)
        ok_send = resp.status_code in (200, 201, 202)
        print(f"[HEALTH] Alert email sent={ok_send} status={resp.status_code}")
        if ok_send:
            _HEALTH_ALERT_LAST_SENT_AT = now
    except Exception as e:
        print(f"[HEALTH] Alert exception: {e}")


# ==================== FUNKCJE POMOCNICZE ====================

def update_render_env_vars(values: dict, reason: str = "") -> bool:
    """
    Aktualizuje ENV w pamięci procesu oraz (jeśli skonfigurowane) w Render przez API.
    """
    if not values:
        return False

    for k, v in values.items():
        os.environ[str(k)] = str(v)

    if not RENDER_API_KEY or not RENDER_SERVICE_ID:
        print("[RENDER ENV] Pomijam zapis do Render (brak RENDER_API_KEY lub RENDER_SERVICE_ID)")
        return True

    try:
        url = f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/env-vars"
        headers = {
            "Authorization": f"Bearer {RENDER_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = [{"key": str(k), "value": str(v)} for k, v in values.items()]
        keys = ", ".join([str(k) for k in values.keys()])
        print(f"[RENDER ENV] START update keys=[{keys}] reason={reason or 'n/a'}")
        resp = requests.patch(url, headers=headers, json=payload, timeout=20)
        ok = resp.status_code in (200, 201, 202, 204)
        if not ok and resp.status_code in (404, 405):
            # NIE robimy fallback na PUT - PUT nadpisuje WSZYSTKIE zmienne (katastrofa!)
            # Render API nie obsługuje PATCH na /env-vars, tylko PUT który wymaga pełnej listy
            print(f"[RENDER ENV] PATCH niedostępny (status={resp.status_code}) — PUT WYŁĄCZONY (niebezpieczny)")
            print(f"[RENDER ENV] Zmienne zapisane tylko do pamięci procesu i Postgres")
            return True  # os.environ już zaktualizowany na początku funkcji
        if ok:
            print(f"[RENDER ENV] OK status={resp.status_code} keys=[{keys}]")
        else:
            print(f"[RENDER ENV] ERROR status={resp.status_code} keys=[{keys}] body={resp.text}")
        return ok
    except Exception as e:
        print(f"[RENDER ENV] EXCEPTION: {e}")
        traceback.print_exc()
        return False


def update_render_env_var(key, value, reason: str = "") -> bool:
    """Wrapper dla pojedynczej zmiennej ENV."""
    return update_render_env_vars({key: value}, reason=reason)


def _normalize_env_secret(value: str | None) -> str:
    """
    Normalizuje wartość sekretu z ENV:
    - strip whitespace
    - usuwa pojedyncze/dwukrotne cudzysłowy jeśli obejmują całość
    """
    v = (value or "").strip()
    if len(v) >= 2 and ((v[0] == v[-1]) and v[0] in ("'", '"')):
        v = v[1:-1].strip()
    return v


def _token_fingerprint(value: str | None) -> str:
    v = _normalize_env_secret(value)
    if not v:
        return "none"
    try:
        h = hashlib.sha256(v.encode("utf-8")).hexdigest()[:10]
        return f"len={len(v)} sha10={h}"
    except Exception:
        return f"len={len(v)} sha10=error"


def _send_new_refresh_token_email(company: str, refresh_token: str, refresh_expires_at: int, prefix: str):
    """
    Wysyła email z nowymi wartościami refresh tokena po wygenerowaniu.
    Token jest już zapisany w Postgres - email służy jako backup/audyt.
    """
    try:
        if not _is_make_email_configured():
            print(f"[TOKEN EMAIL] Make webhook nie skonfigurowany - pomijam wysyłkę")
            return
        
        to_email = "adminzoho@medidesk.com"
        expires_date = datetime.datetime.fromtimestamp(refresh_expires_at).strftime('%Y-%m-%d %H:%M:%S')
        
        subject = f"[wFirma {company.upper()}] Nowy Refresh Token zapisany w Postgres"
        
        body_html = f"""
<h2>Nowy Refresh Token wFirma - {company.upper()}</h2>
<p>Wygenerowano i <strong>zapisano w Postgres</strong> nowy refresh token. Poniżej kopia wartości (backup).</p>

<h3>Wartości zapisane w Postgres:</h3>
<table border="1" cellpadding="10" style="border-collapse: collapse;">
<tr>
<td><strong>refresh_token</strong></td>
<td style="font-family: monospace; word-break: break-all;">{refresh_token}</td>
</tr>
<tr>
<td><strong>refresh_token_expires_at</strong></td>
<td style="font-family: monospace;">{refresh_expires_at}</td>
</tr>
</table>

<h3>Dodatkowe info:</h3>
<ul>
<li><strong>Firma:</strong> {company.upper()}</li>
<li><strong>Data wygaśnięcia:</strong> {expires_date}</li>
<li><strong>Ważny przez:</strong> ~30 dni</li>
<li><strong>Źródło:</strong> Postgres (tabela wfirma_tokens)</li>
</ul>

<p style="color: #666; font-size: 12px;">
Wiadomość wygenerowana automatycznie po autoryzacji OAuth2 wFirma.
Token jest trwale zapisany w bazie - ten email służy tylko jako backup/audyt.
</p>
"""
        
        payload = {
            "to": to_email,
            "subject": subject,
            "body_html": body_html,
            "event_order_id": f"TOKEN-{company.upper()}",
            "template_type": "wfirma_new_token",
        }
        headers = {
            "Content-Type": "application/json",
            "x-make-apikey": RENDER_EMAIL_KEY_SEND_REQUEST,
        }
        resp = requests.post(MAKE_WEBHOOK_SEND_EMAIL_REQUEST, json=payload, headers=headers, timeout=20)
        ok = resp.status_code in (200, 201, 202)
        print(f"[TOKEN EMAIL] Wysłano email z refresh tokenem do {to_email} | status={resp.status_code} ok={ok}")
        
    except Exception as e:
        print(f"[TOKEN EMAIL] Błąd wysyłki: {e}")


def save_token(access_token, expires_in, refresh_token=None, company=None, send_refresh_email: bool = True, refresh_token_source: str | None = None):
    """
    Zapisz token do POSTGRES (główne źródło) + pamięć procesu.
    Postgres jest trwały - przetrwa restart/deploy.
    
    Args:
        access_token: Token dostępu
        expires_in: Czas ważności w sekundach
        refresh_token: Refresh token (opcjonalny - jeśli nowy)
        company: Firma/zestaw danych ('md' lub 'test')
        send_refresh_email: Czy wysyłać email z nowym refresh tokenem
        refresh_token_source: Źródło nowego refresh tokena (np. manual_auth, refresh_rotation)
    """
    config = get_company_config(company)
    prefix = config['prefix']
    company_name = config['company']
    pg_company = config['pg_company']  # nazwa firmy w Postgres (md_test -> md)
    
    expires_at = int(time.time() + expires_in - 60)  # 60 sek margines
    log_prefix = f"[TOKEN SAVE] [{company_name.upper()}]"
    
    # Pobierz istniejący refresh_token jeśli nowy nie podany
    final_refresh_token = refresh_token
    refresh_expires_at = None
    
    if not final_refresh_token:
        # Jedyne źródło prawdy: Postgres (bez ENV/file fallbacks)
        try:
            from pg_storage import get_wfirma_token
            pg_token = get_wfirma_token(pg_company)
            if pg_token and pg_token.get('refresh_token'):
                final_refresh_token = pg_token['refresh_token']
                refresh_expires_at = pg_token.get('refresh_token_expires_at')
                print(f"{log_prefix} refresh_source=pg fp={_token_fingerprint(final_refresh_token)}")
        except Exception as e:
            print(f"{log_prefix} Błąd odczytu z Postgres: {e}")
            traceback.print_exc()
    
    # Jeśli to NOWY refresh_token, ustaw nową datę ważności (30 dni)
    if refresh_token:
        refresh_expires_at = int(time.time() + 30 * 24 * 60 * 60)
        print(f"{log_prefix} refresh_provided source={refresh_token_source or 'manual'} fp={_token_fingerprint(refresh_token)}")
    
    print(f"{log_prefix} save_token: access={access_token[:20]}..., refresh={bool(final_refresh_token)}, expires_at={expires_at}")
    
    # 1. GŁÓWNE: Zapisz do POSTGRES (trwałe!)
    try:
        from pg_storage import save_wfirma_token
        pg_result = save_wfirma_token(
            company=pg_company,  # md_test zapisuje do 'md'
            access_token=access_token,
            access_token_expires_at=expires_at,
            refresh_token=final_refresh_token,
            refresh_token_expires_at=refresh_expires_at,
        )
        if pg_result.get('ok'):
            print(f"[LOG] [{company_name.upper()}] ✓ Token zapisany do POSTGRES (updated_at={pg_result.get('updated_at')})")
        else:
            print(f"[ERROR] [{company_name.upper()}] Błąd zapisu do Postgres: {pg_result.get('error')}")
    except Exception as e:
        print(f"[ERROR] [{company_name.upper()}] Wyjątek przy zapisie do Postgres: {e}")
    
    # 2. Aktualizuj pamięć procesu (os.environ) - dla bieżącej sesji
    os.environ[f"{prefix}ACCESS_TOKEN"] = access_token
    os.environ[f"{prefix}TOKEN_EXPIRES"] = str(expires_at)
    if final_refresh_token:
        os.environ[f"{prefix}REFRESH_TOKEN"] = final_refresh_token
    if refresh_expires_at:
        os.environ[f"{prefix}REFRESH_TOKEN_EXPIRES"] = str(refresh_expires_at)

    # 2b. Jeśli pojawił się NOWY refresh_token – NIE zapisuj do Render ENV (tylko Postgres)
    if refresh_token and refresh_expires_at:
        print(f"[RENDER ENV] Pominięto zapis (tylko Postgres) reason=wfirma_new_refresh_token:{company_name}")
    
    # 3. Jeśli nowy refresh_token - wyślij email jako backup
    if refresh_token and send_refresh_email:
        expires_date_str = datetime.datetime.fromtimestamp(refresh_expires_at).strftime('%Y-%m-%d %H:%M')
        print(f"[LOG] [{company_name.upper()}] Nowy refresh_token ważny do: {expires_date_str}")
        
        _send_new_refresh_token_email(
            company=company_name,
            refresh_token=refresh_token,
            refresh_expires_at=refresh_expires_at,
            prefix=prefix
        )

def refresh_access_token(company=None, skip_fresh_check=False):
    """
    Odśwież access_token używając refresh_token z Postgres.
    
    WAŻNE:
    - Ten kod NIGDY nie generuje refresh tokena (to tylko ręczne /auth).
    - Automatycznie odświeżamy WYŁĄCZNIE access_token.
    - Używamy advisory lock w Postgres, aby po deployu (wiele workerów) uniknąć
      równoległych refreshy i nie doprowadzić do invalid_grant.
    - Refresh token pobierany WYŁĄCZNIE z Postgres (bez ENV/file fallbacks).
    
    Args:
        company: Firma/zestaw danych ('md' lub 'test')
        skip_fresh_check: Jeśli True, pomija sprawdzanie czy token jest świeży (wymusza refresh)
    """
    config = get_company_config(company)
    prefix = config['prefix']
    company_name = config['company']
    pg_company = config['pg_company']  # nazwa firmy w Postgres (md_test -> md)

    lock_id = _wfirma_access_refresh_lock_id(pg_company)  # lock per-pg_company
    advisory_lock = None
    advisory_unlock = None
    get_wfirma_token = None
    try:
        from pg_storage import advisory_lock as _al, advisory_unlock as _au, get_wfirma_token as _gwt
        advisory_lock = _al
        advisory_unlock = _au
        get_wfirma_token = _gwt
    except Exception as e:
        print(f"[LOG] [{company_name.upper()}] Brak pg_storage dla locka (fallback bez locka): {e}")

    if advisory_lock and advisory_unlock:
        advisory_lock(lock_id)

    try:
        log_prefix = f"[TOKEN REFRESH] [{company_name.upper()}]"
        print(f"{log_prefix} START skip_fresh_check={skip_fresh_check} pg_company={pg_company}")
        # Jeśli inny worker już odświeżył token (i zapisał do Postgres) – użyj i nie rób refreshu ponownie
        now_ts = int(time.time())
        pg_tok = None
        if get_wfirma_token:
            pg_tok = get_wfirma_token(pg_company)
        
        # Pomijamy sprawdzanie świeżości jeśli skip_fresh_check=True (wymuszony refresh)
        if not skip_fresh_check and pg_tok and pg_tok.get("access_token") and int(pg_tok.get("access_token_expires_at") or 0) > (now_ts + 60):
            access_token = str(pg_tok["access_token"])
            expires_at = int(pg_tok["access_token_expires_at"])
            os.environ[f"{prefix}ACCESS_TOKEN"] = access_token
            os.environ[f"{prefix}TOKEN_EXPIRES"] = str(expires_at)
            if pg_tok.get("refresh_token"):
                os.environ[f"{prefix}REFRESH_TOKEN"] = str(pg_tok["refresh_token"])
            if pg_tok.get("refresh_token_expires_at"):
                os.environ[f"{prefix}REFRESH_TOKEN_EXPIRES"] = str(int(pg_tok["refresh_token_expires_at"]))
            print(f"{log_prefix} Token już świeży w Postgres – pomijam refresh")
            return access_token
        
        if skip_fresh_check:
            print(f"{log_prefix} WYMUSZONY REFRESH (skip_fresh_check=True)")

        # Wybór refresh tokena: WYŁĄCZNIE z Postgres (bez ENV/file fallbacks)
        refresh_token = None
        refresh_source = None

        # Jedyne źródło prawdy: Postgres
        if pg_tok and pg_tok.get("refresh_token"):
            refresh_token = _normalize_env_secret(pg_tok.get("refresh_token"))
            refresh_source = "pg"

        if not refresh_token:
            print(f"{log_prefix} Brak refresh tokena w Postgres - wymagana autoryzacja /auth?company={company_name}")
            return None

        old_refresh_fp = _token_fingerprint(refresh_token)
        print(f"{log_prefix} ========== WYWOŁANIE wFirma API ==========")
        print(f"{log_prefix} refresh_source={refresh_source}")
        print(f"{log_prefix} refresh_token_fp={old_refresh_fp}")
        print(f"{log_prefix} refresh_token_len={len(refresh_token) if refresh_token else 0}")
        
        token_url = "https://api2.wfirma.pl/oauth2/token"
        payload = {
            'grant_type': 'refresh_token',
            'client_id': config['client_id'],
            'client_secret': config['client_secret'],
            'refresh_token': refresh_token
        }

        print(f"{log_prefix} REQUEST URL: {token_url}")
        print(f"{log_prefix} REQUEST grant_type=refresh_token")
        print(f"{log_prefix} REQUEST client_id={config['client_id'][:12]}..." if config['client_id'] else f"{log_prefix} REQUEST client_id=BRAK!")
        print(f"{log_prefix} REQUEST client_secret={'***' if config['client_secret'] else 'BRAK!'}")
        print(f"{log_prefix} REQUEST refresh_token_fp={old_refresh_fp}")
        
        response = requests.post(token_url, data=payload)
        
        print(f"{log_prefix} ========== ODPOWIEDŹ wFirma API ==========")
        print(f"{log_prefix} RESPONSE status_code={response.status_code}")
        print(f"{log_prefix} RESPONSE headers Content-Type={response.headers.get('Content-Type', 'N/A')}")
        
        if response.status_code == 200:
            new_tokens = response.json()
            new_access = new_tokens.get('access_token')
            new_refresh = new_tokens.get('refresh_token')
            expires_in = int(new_tokens.get('expires_in', 3600))
            
            # Szczegółowe logowanie odpowiedzi
            print(f"{log_prefix} RESPONSE keys={list(new_tokens.keys())}")
            print(f"{log_prefix} RESPONSE access_token={'TAK len=' + str(len(new_access)) if new_access else 'BRAK'}")
            print(f"{log_prefix} RESPONSE refresh_token={'TAK len=' + str(len(new_refresh)) if new_refresh else 'BRAK'}")
            print(f"{log_prefix} RESPONSE expires_in={expires_in}")
            
            if new_access:
                new_access_fp = _token_fingerprint(new_access)
                print(f"{log_prefix} access_token_fp={new_access_fp}")
                
                if new_refresh:
                    new_refresh_fp = _token_fingerprint(new_refresh)
                    refresh_changed = (old_refresh_fp != new_refresh_fp)
                    print(f"{log_prefix} *** ROTACJA REFRESH TOKEN ***")
                    print(f"{log_prefix} refresh_old_fp={old_refresh_fp}")
                    print(f"{log_prefix} refresh_new_fp={new_refresh_fp}")
                    print(f"{log_prefix} refresh_CHANGED={refresh_changed}")
                else:
                    print(f"{log_prefix} refresh_token NIE zwrócony (brak rotacji)")
                
                print(f"{log_prefix} ========== ZAPIS TOKENA ==========")
                print(f"{log_prefix} save_token: access_fp={new_access_fp}, expires_in={expires_in}")
                print(f"{log_prefix} save_token: refresh={'TAK fp=' + _token_fingerprint(new_refresh) if new_refresh else 'NIE (zachowaj stary)'}")
                
                save_token(
                    new_access,
                    expires_in,
                    refresh_token=new_refresh,
                    company=company,
                    send_refresh_email=False,
                    refresh_token_source="refresh_rotation" if new_refresh else None,
                )
                print(f"{log_prefix} ========== SUKCES ==========")
                print(f"{log_prefix} Access token odświeżony pomyślnie")
                return new_access

            print(f"{log_prefix} ========== BŁĄD ==========")
            print(f"{log_prefix} Brak access_token w odpowiedzi!")
            print(f"{log_prefix} Otrzymane klucze: {list(new_tokens.keys())}")
            return None

        print(f"{log_prefix} ========== BŁĄD API ==========")
        print(f"{log_prefix} status_code={response.status_code}")
        print(f"{log_prefix} response_text={response.text[:500] if response.text else 'PUSTY'}")
        return None
    except Exception as e:
        print(f"[TOKEN REFRESH] [{company_name.upper()}] EXCEPTION: {e}")
        traceback.print_exc()
        return None
    finally:
        if advisory_unlock:
            try:
                advisory_unlock(lock_id)
            except Exception:
                pass
        try:
            print(f"{log_prefix} END")
        except Exception:
            pass

def is_token_valid():
    """Sprawdź czy zapisany token jest ważny dla domyślnej firmy"""
    return is_token_valid_for_company(None)


def is_token_valid_for_company(company=None):
    """Sprawdź czy zapisany token jest ważny dla danej firmy (tylko Postgres)"""
    config = get_company_config(company)
    pg_company = config['pg_company']  # md_test -> md
    
    # Jedyne źródło prawdy: Postgres
    try:
        from pg_storage import get_wfirma_token
        pg_tok = get_wfirma_token(pg_company)
        if pg_tok and pg_tok.get("access_token") and pg_tok.get("access_token_expires_at"):
            expires_at = float(pg_tok["access_token_expires_at"])
            return time.time() < expires_at
    except Exception:
        pass
    
    return False


def check_refresh_token_expiry():
    """
    Sprawdź ile dni zostało do wygaśnięcia refresh tokena (domyślna firma).
    Zwraca (days_remaining, warning_message) lub (None, None) jeśli brak danych.
    """
    return check_refresh_token_expiry_for_company(None)


def check_refresh_token_expiry_for_company(company=None):
    """
    Sprawdź ile dni zostało do wygaśnięcia refresh tokena dla danej firmy.
    Zwraca (days_remaining, warning_message) lub (None, None) jeśli brak danych.
    Źródło danych: wyłącznie Postgres.
    """
    config = get_company_config(company)
    company_name = config['company']
    pg_company = config['pg_company']  # md_test -> md
    
    # Jedyne źródło prawdy: Postgres
    refresh_expires = None
    try:
        from pg_storage import get_wfirma_token
        pg_tok = get_wfirma_token(pg_company)
        if pg_tok and pg_tok.get("refresh_token_expires_at"):
            refresh_expires = float(pg_tok["refresh_token_expires_at"])
    except Exception:
        pass
    
    if not refresh_expires:
        return None, None
    
    try:
        now = time.time()
        seconds_remaining = refresh_expires - now
        days_remaining = seconds_remaining / (24 * 60 * 60)
        
        company_label = company_name.upper()
        
        if days_remaining <= 0:
            return 0, f"🚨 [{company_label}] REFRESH TOKEN WYGASŁ! Przejdź przez /auth?company={company_name} NATYCHMIAST!"
        elif days_remaining <= 3:
            return days_remaining, f"🔴 [{company_label}] PILNE! Refresh token wygasa za {days_remaining:.1f} dni! Przejdź przez /auth?company={company_name}!"
        elif days_remaining <= 7:
            return days_remaining, f"⚠️ [{company_label}] UWAGA! Refresh token wygasa za {days_remaining:.1f} dni. Zaplanuj reautoryzację."
        elif days_remaining <= 14:
            return days_remaining, f"📅 [{company_label}] Refresh token wygasa za {days_remaining:.1f} dni."
        else:
            return days_remaining, None  # Brak ostrzeżenia
    except:
        return None, None


def get_token_status():
    """Zwraca pełny status tokenów dla domyślnej firmy"""
    return get_token_status_for_company(None)


def get_token_status_for_company(company=None):
    """Zwraca pełny status tokenów dla danej firmy (do endpointu /api/token/status). Źródło: Postgres."""
    config = get_company_config(company)
    company_name = config['company']
    pg_company = config['pg_company']  # md_test -> md
    
    # Pobierz dane z Postgres (jedyne źródło prawdy)
    pg_tok = None
    try:
        from pg_storage import get_wfirma_token
        pg_tok = get_wfirma_token(pg_company)
    except Exception:
        pass
    
    status = {
        'company': company_name,
        'pg_company': pg_company,  # pokaż skąd pochodzą tokeny
        'source': 'postgres',
        'access_token_valid': is_token_valid_for_company(company),
        'refresh_token_exists': bool(pg_tok and pg_tok.get('refresh_token')),
    }
    
    # Access token (z Postgres)
    if pg_tok and pg_tok.get('access_token_expires_at'):
        try:
            expires_at = float(pg_tok['access_token_expires_at'])
            status['access_token_expires_at'] = expires_at
            status['access_token_remaining_seconds'] = max(0, int(expires_at - time.time()))
        except:
            pass
    
    # Refresh token (z Postgres przez check_refresh_token_expiry_for_company)
    days_remaining, warning = check_refresh_token_expiry_for_company(company)
    if days_remaining is not None:
        status['refresh_token_days_remaining'] = round(days_remaining, 1)
    if pg_tok and pg_tok.get('refresh_token_expires_at'):
        status['refresh_token_expires_at'] = float(pg_tok['refresh_token_expires_at'])
    if warning:
        status['warning'] = warning
    
    return status


# Śledzenie czy powiadomienie zostało już wysłane (żeby nie spamować)
_notification_sent_for_days = None

def send_token_expiry_notification(days_remaining, warning_message):
    """
    Wyślij powiadomienie o wygasającym refresh tokenie.
    Używa webhooka (Make.com) lub bezpośredniego emaila.
    """
    global _notification_sent_for_days
    
    # Nie wysyłaj jeśli już wysłano dla tego samego progu
    threshold = int(days_remaining) if days_remaining else 0
    if _notification_sent_for_days == threshold:
        return False
    
    email = EMAIL_REFRESH_TOKEN_EXPIRE
    webhook_url = WEBHOOK_TOKEN_EXPIRE_NOTIFY
    
    if not email and not webhook_url:
        print("[LOG] Brak konfiguracji powiadomień (EMAIL_REFRESH_TOKEN_EXPIRE lub WEBHOOK_TOKEN_EXPIRE_NOTIFY)")
        return False
    
    # Pobierz service_url z per-firma redirect_uri (domyślnie MD)
    md_redirect = get_company_config('md').get('redirect_uri')
    if md_redirect:
        service_url = md_redirect.replace('/callback', '').rstrip('/')
    else:
        service_url = None  # Brak konfiguracji - pole będzie puste
    
    notification_data = {
        "type": "refresh_token_expiry_warning",
        "days_remaining": round(days_remaining, 1) if days_remaining else 0,
        "warning": warning_message,
        "email": email,
        "service_url": service_url,
        "action_required": "Przejdź na /auth aby odnowić token",
        "timestamp": datetime.datetime.now().isoformat(),
    }
    
    # Dodaj ostrzeżenie o braku konfiguracji redirect_uri
    if not service_url:
        notification_data["config_error"] = "Brak WFIRMA_MD_REDIRECT_URI w ENV"
    
    # Opcja 1: Webhook (Make.com)
    if webhook_url:
        try:
            resp = requests.post(webhook_url, json=notification_data, timeout=10)
            if resp.status_code in [200, 201, 202]:
                print(f"[LOG] Powiadomienie wysłane przez webhook: {warning_message}")
                _notification_sent_for_days = threshold
                return True
            else:
                print(f"[LOG] Błąd webhooka: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"[LOG] Błąd wysyłania webhooka: {e}")
    
    # Opcja 2: Email przez prosty POST do serwisu (np. formspree, emailjs)
    # Na razie tylko logujemy - user może skonfigurować webhook do Make.com
    if email and not webhook_url:
        print(f"[LOG] Powiadomienie email do {email}: {warning_message}")
        print(f"[LOG] Skonfiguruj WEBHOOK_TOKEN_EXPIRE_NOTIFY żeby automatycznie wysyłać emaile przez Make.com")
        _notification_sent_for_days = threshold
        return True
    
    return False


# ---------------------------------------------------------------------------
# WFIRMA TOKEN MONITOR (auto-email via Make.com)
# ---------------------------------------------------------------------------

WFIRMA_TOKEN_MONITOR_LOCK_ID = 83427519  # stały lock w Postgres (unikalny dla usługi)
WFIRMA_ACCESS_REFRESH_LOCK_BASE = 91000000  # bazowy zakres locków dla refresh access tokena (per-firma)


def _wfirma_access_refresh_lock_id(company: str) -> int:
    """
    Deterministyczny lock_id per firma (dla wielu workerów).
    Nie zawiera sekretów; służy wyłącznie do synchronizacji refreshu access_token.
    """
    import zlib
    c = (company or DEFAULT_COMPANY).lower().strip()
    return int(WFIRMA_ACCESS_REFRESH_LOCK_BASE + (zlib.crc32(c.encode("utf-8")) % 10_000_000))


def _is_make_email_configured() -> bool:
    return bool(MAKE_WEBHOOK_SEND_EMAIL_REQUEST and RENDER_EMAIL_KEY_SEND_REQUEST)


def _send_email_via_make_token_monitor(to_email: str, subject: str, body_html: str, template_type: str = "wfirma_token_monitor") -> bool:
    if not _is_make_email_configured():
        print("[TOKEN MONITOR] Make email webhook nie skonfigurowany")
        return False
    try:
        payload = {
            "to": to_email,
            "subject": subject,
            "body_html": body_html,
            "event_order_id": "TOKEN-MONITOR",
            "template_type": template_type,
        }
        headers = {
            "Content-Type": "application/json",
            "x-make-apikey": RENDER_EMAIL_KEY_SEND_REQUEST,
        }
        resp = requests.post(MAKE_WEBHOOK_SEND_EMAIL_REQUEST, json=payload, headers=headers, timeout=20)
        ok = resp.status_code in (200, 201, 202)
        print(f"[TOKEN MONITOR] Make response {resp.status_code} | ok={ok} | {resp.text[:120] if resp.text else ''}")
        return ok
    except Exception as e:
        print(f"[TOKEN MONITOR] Błąd wysyłki email przez Make: {e}")
        return False


def _format_dt(ts: float) -> str:
    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "-"


def _get_refresh_token_days_remaining(company: str = "md") -> tuple[float | None, float | None]:
    """Zwraca (days_remaining, expires_at_ts) lub (None, None) jeśli brak danych. Źródło: Postgres."""
    config = get_company_config(company)
    pg_company = config["pg_company"]  # md_test -> md
    
    # Jedyne źródło prawdy: Postgres
    refresh_expires = None
    try:
        from pg_storage import get_wfirma_token
        pg_tok = get_wfirma_token(pg_company)
        if pg_tok and pg_tok.get("refresh_token_expires_at"):
            refresh_expires = float(pg_tok["refresh_token_expires_at"])
    except Exception:
        pass
    
    if not refresh_expires:
        return None, None
    try:
        now = time.time()
        days_remaining = (refresh_expires - now) / (24 * 60 * 60)
        return days_remaining, refresh_expires
    except Exception:
        return None, None


def _should_send_token_email(now_ts: float, state: dict, days_remaining: float) -> tuple[bool, str]:
    """
    Zasady:
    - od 20 dni do 4 dni: max 1 mail/dzień
    - <=3 dni (w tym 0/expired): max 3 maile/dzień (co ~8h)
    """
    last_email_at = state.get("last_email_at")
    last_email_ts = None
    try:
        if last_email_at:
            # psycopg2 zwraca datetime; albo string; obsłuż oba
            if isinstance(last_email_at, datetime.datetime):
                last_email_ts = last_email_at.timestamp()
            else:
                # ISO-ish
                last_email_ts = datetime.datetime.fromisoformat(str(last_email_at).replace("Z", "+00:00")).timestamp()
    except Exception:
        last_email_ts = None

    if days_remaining <= 3:
        # 3 razy dziennie -> co 8h
        if last_email_ts is None or (now_ts - last_email_ts) >= (8 * 60 * 60 - 60):
            return True, "urgent_3x_daily"
        return False, "throttled_urgent"

    if days_remaining <= 20:
        # raz dziennie
        if last_email_ts is None or (now_ts - last_email_ts) >= (20 * 60 * 60):
            return True, "daily"
        return False, "throttled_daily"

    return False, "outside_window"


def _render_token_monitor_email(company: str, days_remaining: float | None, expires_at: float | None) -> tuple[str, str]:
    # Pobierz redirect_uri per firma (bez fallbacków!)
    config = get_company_config(company)
    redirect_uri = config.get('redirect_uri')
    company_label = (company or "md").upper()
    
    # Buduj auth_url z per-firma redirect_uri
    if redirect_uri:
        service_url = redirect_uri.replace('/callback', '').rstrip('/')
        auth_url = f"{service_url}/auth?company={company}"
    else:
        # Brak konfiguracji - użyj placeholdera i pokaż błąd w mailu
        service_url = None
        auth_url = f"[BRAK KONFIGURACJI - ustaw {config['prefix']}REDIRECT_URI]"

    if days_remaining is None or expires_at is None:
        subject = f"[wFirma] [{company_label}] Brak danych o wygaśnięciu refresh tokena"
        headline = "Brak danych o terminie ważności refresh tokena"
        badge = "INFO"
        color = "#0d6efd"
        details = "Brak wpisu refresh_token_expires_at w Postgres. System nie wie kiedy token wygaśnie. Przejdź /auth?company={} aby zapisać nowy token.".format(company or 'md')
    elif days_remaining <= 0:
        subject = f"[wFirma] [{company_label}] REFRESH TOKEN WYGASŁ — wymagana autoryzacja"
        headline = "Refresh token wygasł — wymagana autoryzacja"
        badge = "PILNE"
        color = "#dc3545"
        details = f"Token wygasł. Bez ponownej autoryzacji faktury i kontrahenci w wFirma nie będą działać."
    elif days_remaining <= 3:
        subject = f"[wFirma] [{company_label}] PILNE — token wygasa za {days_remaining:.1f} dni"
        headline = f"Refresh token wygasa za {days_remaining:.1f} dni"
        badge = "PILNE"
        color = "#dc3545"
        details = "Zbliża się wygaśnięcie refresh tokena. Prosimy o reautoryzację."
    else:
        subject = f"[wFirma] [{company_label}] Token wygasa za {days_remaining:.1f} dni"
        headline = f"Refresh token wygasa za {days_remaining:.1f} dni"
        badge = "UWAGA"
        color = "#fd7e14"
        details = "Zaplanuj reautoryzację, aby uniknąć przerwy w wystawianiu faktur."

    exp_txt = _format_dt(expires_at) if expires_at else "-"
    
    # Warunkowa sekcja z linkiem do autoryzacji
    if service_url:
        auth_link_row = f'<td style="padding: 8px 0;"><a href="{auth_url}" style="color:{color}; text-decoration: underline;">{auth_url}</a></td>'
        auth_button = f'''<div style="margin-top: 18px;">
              <a href="{auth_url}" style="display:inline-block; padding: 12px 16px; background:{color}; color:#ffffff; border-radius: 8px; text-decoration:none; font-weight:bold;">
                Odnów autoryzację wFirma
              </a>
            </div>'''
    else:
        auth_link_row = f'<td style="padding: 8px 0; color:#dc3545; font-weight:bold;">BŁĄD KONFIGURACJI: Brak {config["prefix"]}REDIRECT_URI w ENV</td>'
        auth_button = f'''<div style="margin-top: 18px; padding: 12px 16px; background:#dc3545; color:#ffffff; border-radius: 8px; font-weight:bold;">
              Skontaktuj się z administratorem - brak konfiguracji {config["prefix"]}REDIRECT_URI
            </div>'''

    body_html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; padding: 20px; background: #f6f8fb;">
        <div style="max-width: 720px; margin: 0 auto; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 10px; overflow: hidden;">
          <div style="padding: 16px 20px; background: {color}; color: #ffffff;">
            <div style="font-size: 14px; opacity: 0.95;">wFirma Token Monitor</div>
            <div style="font-size: 20px; font-weight: bold; margin-top: 4px;">{headline}</div>
          </div>
          <div style="padding: 18px 20px;">
            <div style="display:inline-block; padding: 4px 10px; border-radius: 999px; background: {color}; color:#fff; font-size: 12px; font-weight: bold;">{badge}</div>
            <p style="margin: 14px 0 0 0; color: #111827; line-height: 20px;">{details}</p>

            <table style="margin-top: 16px; width: 100%; border-collapse: collapse;">
              <tr>
                <td style="padding: 8px 0; color:#6b7280; width: 220px;">Firma</td>
                <td style="padding: 8px 0; color:#111827; font-weight: bold;">{company_label}</td>
              </tr>
              <tr>
                <td style="padding: 8px 0; color:#6b7280;">Ważny do</td>
                <td style="padding: 8px 0; color:#111827;">{exp_txt}</td>
              </tr>
              <tr>
                <td style="padding: 8px 0; color:#6b7280;">Panel autoryzacji</td>
                {auth_link_row}
              </tr>
            </table>

            {auth_button}

            <p style="margin-top: 18px; color:#6b7280; font-size: 12px;">
              Ten email jest wysyłany automatycznie. Jeśli autoryzacja została już wykonana, możesz go zignorować.
            </p>
          </div>
        </div>
      </body>
    </html>
    """

    return subject, body_html


def run_wfirma_token_monitor_once(company: str = "md") -> dict:
    """
    Jedno uruchomienie monitoringu:
    - oblicza days_remaining
    - throttle wg zasad (20d -> 1/dzień, <=3d -> 3/dzień)
    - wysyła email przez Make.com
    """
    now_ts = time.time()
    try:
        from pg_storage import (
            try_advisory_lock,
            advisory_unlock,
            get_token_monitor_state,
            upsert_token_monitor_state,
        )
    except Exception as e:
        print(f"[TOKEN MONITOR] Brak pg_storage: {e}")
        return {"ok": False, "error": "no_pg_storage"}

    if not try_advisory_lock(WFIRMA_TOKEN_MONITOR_LOCK_ID):
        return {"ok": True, "skipped": True, "reason": "lock_held"}

    try:
        state = get_token_monitor_state(company)
        days_remaining, expires_at = _get_refresh_token_days_remaining(company)

        upsert_token_monitor_state(
            company=company,
            last_check_at=datetime.datetime.utcnow().isoformat(),
            last_days_remaining=float(days_remaining) if days_remaining is not None else None,
            last_status="missing" if days_remaining is None else ("expired" if days_remaining <= 0 else ("warn" if days_remaining <= 20 else "ok")),
            last_error=None,
        )

        # jeśli nie mamy danych - wyślij tylko informacyjnie raz na dobę
        if days_remaining is None:
            send, kind = _should_send_token_email(now_ts, state, 20)  # traktuj jak „daily window”
            if not send:
                return {"ok": True, "skipped": True, "reason": kind, "company": company}
            subject, body_html = _render_token_monitor_email(company, None, None)
        else:
            send, kind = _should_send_token_email(now_ts, state, float(days_remaining))
            if not send:
                return {"ok": True, "skipped": True, "reason": kind, "company": company, "days_remaining": round(float(days_remaining), 2)}
            subject, body_html = _render_token_monitor_email(company, float(days_remaining), expires_at)

        ok = _send_email_via_make_token_monitor(WFIRMA_TOKEN_EXPIRES_ALERT_EMAIL, subject, body_html)
        if ok:
            upsert_token_monitor_state(
                company=company,
                last_email_at=datetime.datetime.utcnow().isoformat(),
                last_email_kind=kind,
            )
        return {"ok": ok, "company": company, "email_to": WFIRMA_TOKEN_EXPIRES_ALERT_EMAIL, "kind": kind, "days_remaining": round(float(days_remaining), 2) if days_remaining is not None else None}
    finally:
        advisory_unlock(WFIRMA_TOKEN_MONITOR_LOCK_ID)


def _wfirma_token_monitor_loop():
    print("[TOKEN MONITOR] start loop (md)")
    while True:
        try:
            # zawsze md (zgodnie z wymaganiem)
            result = run_wfirma_token_monitor_once(company="md")
            try:
                print(f"[TOKEN MONITOR] run result: {result}")
            except Exception:
                pass

            # Harmonogram: domyślnie 24h; w ostatnie 3 dni -> 8h
            days_remaining, _expires_at = _get_refresh_token_days_remaining("md")
            if days_remaining is not None and float(days_remaining) <= 3:
                sleep_s = 8 * 60 * 60
            else:
                sleep_s = 24 * 60 * 60
        except Exception as e:
            print(f"[TOKEN MONITOR] loop error: {e}")
            sleep_s = 6 * 60 * 60  # retry co 6h przy błędach

        time.sleep(sleep_s)


def start_wfirma_token_monitor():
    # Uruchamiaj tylko jeśli jest Make webhook (inaczej bez sensu)
    if not _is_make_email_configured():
        print("[TOKEN MONITOR] disabled (Make webhook not configured)")
        return
    # Wymaganie: próbkowanie automatyczne — uruchamiamy w tle
    t = threading.Thread(target=_wfirma_token_monitor_loop, name="wfirma-token-monitor", daemon=True)
    t.start()
    print("[TOKEN MONITOR] thread started")


# ---------------------------------------------------------------------------
# BACKSTAGE: monitor kompletności attendee-webhooków (internal info po 10 min)
# ---------------------------------------------------------------------------

BACKSTAGE_ATTENDEE_INCOMPLETE_TEMPLATE = "internal_attendee_incomplete_10m"
BACKSTAGE_ATTENDEE_INCOMPLETE_LOCK_ID = 8842001  # stały lock dla wielu workerów


def _backstage_attendee_incomplete_monitor_loop():
    import time
    while True:
        try:
            # lock globalny, żeby tylko 1 worker robił skan
            from pg_storage import try_advisory_lock, advisory_unlock
            if not try_advisory_lock(BACKSTAGE_ATTENDEE_INCOMPLETE_LOCK_ID):
                time.sleep(60)
                continue

            try:
                from pg_storage import list_orders_older_than_minutes, mail_log_exists, get_event
                from backstage_engine import attendee_webhooks_status
                from backstage_engine import _send_email_via_make

                candidates = list_orders_older_than_minutes(10, limit=200)
                for o in candidates:
                    order_id = o.get("event_order_id")
                    if not order_id:
                        continue

                    # sprawdź kompletność
                    comp = attendee_webhooks_status(order_id)
                    if comp.get("expected", 0) <= 0:
                        continue
                    if comp.get("complete"):
                        continue

                    # dedupe: wyślij tylko raz na zamówienie
                    if mail_log_exists(order_id, BACKSTAGE_ATTENDEE_INCOMPLETE_TEMPLATE, direction="internal"):
                        continue

                    # event i adresat
                    event_name = "Wydarzenie"
                    event_data = {}
                    try:
                        ev = get_event(o.get("event_id", ""))
                        if ev:
                            event_name = ev.get("event_name") or event_name
                            event_data = ev.get("data") or {}
                    except Exception:
                        pass

                    internal_to = (
                        event_data.get("md_email_techniczny")
                        or event_data.get("md_email_kontakt")
                        or os.environ.get("BACKSTAGE_EVENT_INFO_EMAIL", "")
                    )
                    if not internal_to:
                        continue

                    subject = f"[ATTENDEE] Brak kompletu po 10 min – {event_name}"
                    missing = comp.get("missing_ticket_ids") or []
                    body_html = f"""
                    <html>
                      <body style="font-family: Arial, sans-serif; padding: 16px;">
                        <h2>Brak kompletu attendee-webhooków po 10 minutach</h2>
                        <p><strong>Wydarzenie:</strong> {event_name}</p>
                        <p><strong>Zamówienie:</strong> {order_id}</p>
                        <p><strong>Oczekiwane bilety:</strong> {comp.get('expected')}</p>
                        <p><strong>Otrzymane webhooki:</strong> {comp.get('received')}</p>
                        <p><strong>Brakujące ticket_id:</strong></p>
                        <pre style="background:#f6f8fb; padding:12px; border:1px solid #e5e7eb; border-radius:8px; white-space:pre-wrap;">{chr(10).join(missing[:50])}</pre>
                        <p style="color:#6b7280; font-size:12px;">To jest mail informacyjny (nie wysyłamy jeszcze maili do klienta/uczestników).</p>
                      </body>
                    </html>
                    """

                    # 1. Zapisz do mail_log (status=queued)
                    from pg_storage import save_mail_log
                    mail_record = save_mail_log(
                        event_order_id=order_id,
                        direction="internal",
                        template_key=BACKSTAGE_ATTENDEE_INCOMPLETE_TEMPLATE,
                        to_email=internal_to,
                        subject=subject,
                        data={"event_name": event_name, "expected": comp.get("expected"), "received": comp.get("received"), "missing_count": len(missing)},
                    )
                    mail_id = mail_record.get("id") if mail_record else None
                    
                    # 2. Wyślij przez Make z mail_id (Make wywoła callback mark-sent)
                    _send_email_via_make(
                        to_email=internal_to,
                        subject=subject,
                        body_html=body_html,
                        event_order_id=order_id,
                        template_type=BACKSTAGE_ATTENDEE_INCOMPLETE_TEMPLATE,
                        mail_id=mail_id,
                    )

            finally:
                advisory_unlock(BACKSTAGE_ATTENDEE_INCOMPLETE_LOCK_ID)

        except Exception as e:
            print(f"[BACKSTAGE MONITOR] loop error: {e}")

        time.sleep(60)


def start_backstage_attendee_incomplete_monitor():
    # Uruchamiaj tylko jeśli jest Make webhook (inaczej nie wyśle maila)
    if not _is_make_email_configured():
        print("[BACKSTAGE MONITOR] disabled (Make webhook not configured)")
        return
    t = threading.Thread(target=_backstage_attendee_incomplete_monitor_loop, name="backstage-attendee-monitor", daemon=True)
    t.start()
    print("[BACKSTAGE MONITOR] thread started")

@app.route('/api/workflow/token-monitor/run', methods=['POST'])
@require_api_key
def token_monitor_run_endpoint():
    """Manualny trigger monitoringu tokenów (MD)."""
    res = run_wfirma_token_monitor_once(company="md")
    return jsonify(res), 200

def load_token(silent=False, company=None):
    """
    Wczytaj token i automatycznie odśwież access_token jeśli wygasł.

    Źródło danych: WYŁĄCZNIE Postgres.
    os.environ jest używane tylko jako cache procesu (nie do odczytu).
    
    Args:
        silent: Czy ukrywać logi
        company: Firma/zestaw danych ('md' lub 'test'). Jeśli None - używa domyślnego.
    """
    config = get_company_config(company)
    prefix = config['prefix']
    company_name = config['company']
    pg_company = config['pg_company']  # md_test -> md
    
    access_token = None
    expires_at = 0
    refresh_token = None
    
    # Jedyne źródło prawdy: Postgres
    pg_tok = None
    try:
        from pg_storage import get_wfirma_token
        pg_tok = get_wfirma_token(pg_company)
    except Exception as e:
        if not silent:
            print(f"[LOG] [{company_name.upper()}] Błąd odczytu tokena z Postgres (pg_company={pg_company}): {e}")

    if pg_tok:
        if pg_tok.get("access_token") and pg_tok.get("access_token_expires_at"):
            try:
                access_token = str(pg_tok["access_token"])
                expires_at = float(pg_tok["access_token_expires_at"])
                if not silent:
                    print(f"[LOG] [{company_name.upper()}] Tokeny wczytane z Postgres")
            except Exception:
                pass
        if pg_tok.get("refresh_token"):
            refresh_token = str(pg_tok["refresh_token"])
    
    # Jeśli token ważny - zwróć (i zapisz cache do os.environ)
    if access_token and time.time() < float(expires_at):
        remaining = int(expires_at - time.time())
        if not silent:
            print(f"[LOG] [{company_name.upper()}] ✓ Token ważny jeszcze {remaining} sekund")
        # Cache procesu (bez dotykania Render ENV)
        os.environ[f"{prefix}ACCESS_TOKEN"] = str(access_token)
        os.environ[f"{prefix}TOKEN_EXPIRES"] = str(int(float(expires_at)))
        if refresh_token:
            os.environ[f"{prefix}REFRESH_TOKEN"] = str(refresh_token)
        if pg_tok and pg_tok.get("refresh_token_expires_at"):
            os.environ[f"{prefix}REFRESH_TOKEN_EXPIRES"] = str(int(float(pg_tok["refresh_token_expires_at"])))
        return access_token
    
    # Token wygasł lub brak - spróbuj odświeżyć (refresh_access_token pobierze refresh z Postgres)
    if refresh_token:
        if not silent:
            print(f"[LOG] [{company_name.upper()}] Token wygasł/brak, próba odświeżenia... (source=pg)")
        new_token = refresh_access_token(company=company)
        if new_token:
            return new_token
    
    if not silent:
        print(f"[LOG] [{company_name.upper()}] Brak tokenu w Postgres - wymagana autoryzacja /auth?company={company_name}")
    return None

def require_token(f):
    """Decorator wymagający ważnego tokenu"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = load_token(silent=True)
        if not token or not is_token_valid():
            return jsonify({
                'error': 'Brak autoryzacji',
                'message': 'Przejdź do /auth aby się zalogować'
            }), 401
        return f(token, *args, **kwargs)
    return decorated_function


# ==================== POMOCNICZE: WFIRMA (kontrahenci, faktury, PDF, mail) ====================


def get_wfirma_headers(token: str, accept: str = "application/json", with_content_type: bool = True) -> dict:
    """Zwraca nagłówki autoryzacji do wFirma; łatwe do podmiany na M2M w przyszłości."""
    headers = {
        'Authorization': f'Bearer {token}',
    }
    if with_content_type:
        headers['Content-Type'] = 'application/json'
    if accept:
        headers['Accept'] = accept
    return headers


def wfirma_find_contractor_by_nip(token: str, nip: str, company_id: str = None) -> tuple[dict | None, requests.Response | None]:
    """Znajdź kontrahenta po NIP; zwraca (contractor_dict|None, response)."""
    clean_nip = nip.replace("-", "").replace(" ", "")
    api_url = "https://api2.wfirma.pl/contractors/find?inputFormat=json&outputFormat=json&oauth_version=2"
    if company_id:
        api_url += f"&company_id={company_id}"
    print(f"[WFIRMA DEBUG] find_contractor URL: {api_url}")
    headers = get_wfirma_headers(token)
    search_data = {
        "contractors": {
            "parameters": {
                "conditions": {
                    "condition": {
                        "field": "nip",
                        "operator": "eq",
                        "value": clean_nip
                    }
                }
            }
        }
    }
    resp = None
    try:
        resp = requests.post(api_url, headers=headers, json=search_data)
        if resp.status_code == 200:
            data = resp.json()
            contractors = data.get('contractors', {})
            if contractors and isinstance(contractors, dict):
                for key in contractors:
                    if key.isdigit():
                        return contractors[key].get('contractor'), resp
                if 'contractor' in contractors:
                    return contractors['contractor'], resp
        return None, resp
    except Exception:
        return None, resp


def wfirma_add_contractor(token: str, contractor_payload: dict, company_id: str = None) -> tuple[dict | None, requests.Response | None]:
    """Dodaj kontrahenta; zwraca (contractor_dict|None, response)."""
    api_url = "https://api2.wfirma.pl/contractors/add?inputFormat=json&outputFormat=json&oauth_version=2"
    if company_id:
        api_url += f"&company_id={company_id}"
    headers = get_wfirma_headers(token)
    resp = None
    try:
        # KLUCZOWE: Wrapper "contractors"!
        resp = requests.post(api_url, headers=headers, json={"contractors": {"contractor": contractor_payload}})
        if resp.status_code == 200:
            result = resp.json()
            # Odpowiedź: contractors.0.contractor
            contractors = result.get('contractors', {})
            if isinstance(contractors, dict):
                for key in contractors:
                    if key.isdigit() or key == 'contractor':
                        contractor = contractors[key].get('contractor', {})
                        if not contractor:
                            contractor = contractors[key]
                        if contractor:
                            return contractor, resp
            return None, resp
        return None, resp
    except Exception:
        return None, resp


def _extract_contractor_id(contractor: dict | None) -> int | None:
    """
    Wyciąga ID kontrahenta z różnych możliwych kształtów odpowiedzi wFirma.
    wFirma API czasem zwraca ID pod różnymi kluczami lub zagnieżdżone.
    """
    if not contractor or not isinstance(contractor, dict):
        return None
    
    # Próbuj różnych kluczy/ścieżek
    for key in ('id', 'contractor_id', 'Id', 'ID'):
        val = contractor.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
    
    # Może być zagnieżdżone jako contractor.contractor.id
    nested = contractor.get('contractor')
    if nested and isinstance(nested, dict):
        for key in ('id', 'contractor_id', 'Id', 'ID'):
            val = nested.get(key)
            if val is not None:
                try:
                    return int(val)
                except (ValueError, TypeError):
                    pass
    
    return None


# ==================== POMOCNICZE: PRODUKTY (GOODS) ====================


def wfirma_find_good_by_name(token: str, name: str) -> tuple[dict | None, requests.Response | None]:
    """Znajdź produkt po nazwie; zwraca (good_dict|None, response)."""
    api_url = "https://api2.wfirma.pl/goods/find?inputFormat=json&outputFormat=json&oauth_version=2"
    headers = get_wfirma_headers(token)
    
    search_data = {
        "goods": {
            "parameters": {
                "conditions": {
                    "condition": {
                        "field": "name",
                        "operator": "eq",
                        "value": name
                    }
                }
            }
        }
    }
    
    resp = None
    try:
        resp = requests.post(api_url, headers=headers, json=search_data)
        if resp.status_code == 200:
            data = resp.json()
            goods = data.get('goods', {})
            if goods and isinstance(goods, dict):
                for key in goods:
                    if key.isdigit():
                        good = goods[key].get('good', {})
                        if good and good.get('id'):
                            return good, resp
        return None, resp
    except Exception:
        return None, resp


def wfirma_add_good(token: str, name: str, price: float, unit: str = "szt.", vat_code_id: int = 222) -> tuple[dict | None, requests.Response | None]:
    """
    Dodaj produkt do katalogu wFirma.
    vat_code_id: 222 = 23%, 223 = 8%, 224 = 5%, 225 = 0%, 226 = zw
    """
    api_url = "https://api2.wfirma.pl/goods/add?inputFormat=json&outputFormat=json&oauth_version=2"
    headers = get_wfirma_headers(token)
    
    good_payload = {
        "goods": {
            "good": {
                "name": name,
                "unit": unit,
                "netto": str(price),
                "type": "service",  # "good" dla towaru, "service" dla usługi
                "warehouse_type": "simple",
                "vat_code": {
                    "id": vat_code_id
                }
            }
        }
    }
    
    resp = None
    try:
        print(f"[WFIRMA DEBUG] Adding good: {name}, price: {price}, unit: {unit}")
        resp = requests.post(api_url, headers=headers, json=good_payload)
        print(f"[WFIRMA DEBUG] add_good status: {resp.status_code}")
        
        if resp.status_code == 200:
            result = resp.json()
            print(f"[WFIRMA DEBUG] add_good response: {resp.text[:500]}")
            goods = result.get('goods', {})
            if isinstance(goods, dict):
                for key in goods:
                    if key.isdigit():
                        good = goods[key].get('good', {})
                        if good and good.get('id'):
                            print(f"[WFIRMA DEBUG] Created good with ID: {good.get('id')}")
                            return good, resp
        else:
            print(f"[WFIRMA DEBUG] add_good error: {resp.text[:500]}")
        return None, resp
    except Exception as e:
        print(f"[WFIRMA DEBUG] add_good exception: {e}")
        return None, resp


def wfirma_get_or_create_good(token: str, name: str, price: float, unit: str = "szt.", vat_rate: str = "23") -> dict | None:
    """
    Pobierz produkt po nazwie lub utwórz nowy.
    Zwraca dict z 'id' produktu lub None.
    """
    # Mapowanie stawek VAT na ID w wFirma
    vat_code_map = {
        "23": 222,
        "8": 223,
        "5": 224,
        "0": 225,
        "zw": 226,
        "np": 227
    }
    vat_code_id = vat_code_map.get(str(vat_rate), 222)
    
    # 1. Szukaj istniejącego produktu
    existing_good, _ = wfirma_find_good_by_name(token, name)
    if existing_good and existing_good.get('id'):
        print(f"[WFIRMA DEBUG] Found existing good: {name} -> ID {existing_good.get('id')}")
        return existing_good
    
    # 2. Nie znaleziono - utwórz nowy
    print(f"[WFIRMA DEBUG] Good not found, creating: {name}")
    new_good, _ = wfirma_add_good(token, name, price, unit, vat_code_id)
    if new_good and new_good.get('id'):
        return new_good
    
    return None


def wfirma_create_invoice(token: str, invoice_payload: dict, company_id: str = None) -> tuple[dict | None, requests.Response | None]:
    """Utwórz fakturę; zwraca (invoice_dict|None, response)."""
    api_url = "https://api2.wfirma.pl/invoices/add?inputFormat=json&outputFormat=json&oauth_version=2"
    if company_id:
        api_url += f"&company_id={company_id}"
    headers = get_wfirma_headers(token)
    resp = None
    try:
        # KLUCZOWE: Wrapper "invoices"!
        request_body = {"invoices": {"invoice": invoice_payload}}
        # LOG: pełny request body
        try:
            import json as json_lib
            print("[WFIRMA DEBUG] FULL invoice request body:", json_lib.dumps(request_body, ensure_ascii=False, indent=2))
        except Exception:
            pass
        
        resp = requests.post(api_url, headers=headers, json=request_body)
        if resp.status_code == 200:
            result = resp.json()
            # Odpowiedź: invoices.0.invoice
            invoices = result.get('invoices', {})
            if isinstance(invoices, dict):
                for key in invoices:
                    if key.isdigit():
                        invoice = invoices[key].get('invoice', {})
                        if invoice:
                            return invoice, resp
            return None, resp
        return None, resp
    except Exception:
        return None, resp


def wfirma_create_correction(
    token: str,
    source_invoice_id: str,
    correction_description: str = "Anulowanie zamówienia",
    company_id: str = None
) -> tuple[dict | None, requests.Response | None]:
    """
    Utwórz fakturę korygującą (pełna korekta - zerowanie wszystkich pozycji).
    
    Używa wfirma_create_invoice z type="correction" i zeruje pozycje.
    
    Args:
        token: Token OAuth wFirma
        source_invoice_id: ID faktury źródłowej do skorygowania
        correction_description: Powód korekty
        company_id: ID firmy
    
    Returns:
        (correction_dict|None, response)
    """
    print(f"[WFIRMA DEBUG] Creating correction for invoice {source_invoice_id}")
    
    try:
        # 1) Pobierz oryginalną fakturę żeby uzyskać dane kontrahenta i pozycji
        original_invoice, err = wfirma_get_invoice(token, str(source_invoice_id), company_id)
        if err or not original_invoice:
            print(f"[WFIRMA DEBUG] Nie udało się pobrać faktury oryginalnej: {err}")
            return None, None
        
        print(f"[WFIRMA DEBUG] Pobrano fakturę oryginalną: {original_invoice.get('fullnumber')}")
        
        # Pobierz contractor_id z oryginalnej faktury
        contractor_data = original_invoice.get('contractor', {})
        contractor_id = contractor_data.get('id') if isinstance(contractor_data, dict) else None
        if not contractor_id:
            print(f"[WFIRMA DEBUG] Nie można odczytać kontrahenta z faktury oryginalnej")
            return None, None
        
        # 2) Pobierz pozycje z oryginalnej faktury
        # Pozycje mogą być w invoicecontents
        original_contents = original_invoice.get('invoicecontents', {})
        positions = []
        
        if isinstance(original_contents, dict):
            for key, val in original_contents.items():
                if isinstance(val, dict) and 'invoicecontent' in val:
                    content = val['invoicecontent']
                    positions.append({
                        'id': content.get('id'),
                        'name': content.get('name'),
                        'count': content.get('count'),
                        'price': content.get('price'),
                        'vat_code_id': content.get('vat_code', {}).get('id') if isinstance(content.get('vat_code'), dict) else 222,
                    })
        
        if not positions:
            print(f"[WFIRMA DEBUG] Brak pozycji na fakturze oryginalnej")
            return None, None
        
        print(f"[WFIRMA DEBUG] Znaleziono {len(positions)} pozycji do skorygowania")
        
        # 3) Buduj pozycje korekty (zerowanie - count=0 i price=0)
        invoice_contents_dict = {}
        for idx, pos in enumerate(positions):
            content = {
                "invoicecontent": {
                    "name": pos.get('name', f'Pozycja {idx+1}'),
                    "unit": "szt.",
                    "count": 0,  # Zerujemy ilość
                    "price": 0,  # Zerujemy cenę
                    "vat_code": {"id": pos.get('vat_code_id', 222)},
                    "parent": {"id": int(pos.get('id'))}  # Powiązanie z oryginalną pozycją
                }
            }
            invoice_contents_dict[str(idx)] = content
        
        # 4) Payload faktury korygującej
        import datetime
        correction_payload = {
            "contractor_id": int(contractor_id),
            "date": datetime.date.today().isoformat(),
            "type": "correction",
            "parent": {"id": int(source_invoice_id)},  # Powiązanie z fakturą oryginalną
            "description": correction_description,
            "invoicecontents": invoice_contents_dict
        }
        
        print(f"[WFIRMA DEBUG] Correction payload: contractor_id={contractor_id}, parent_id={source_invoice_id}, positions={len(positions)}")
        
        # 5) Utwórz fakturę korygującą
        invoice_result, resp = wfirma_create_invoice(token, correction_payload, company_id)
        
        if invoice_result and invoice_result.get('id'):
            print(f"[WFIRMA DEBUG] Correction created: id={invoice_result.get('id')}, number={invoice_result.get('fullnumber')}")
            return invoice_result, resp
        else:
            print(f"[WFIRMA DEBUG] Nie udało się utworzyć korekty: {resp.text[:500] if resp and resp.text else 'brak odpowiedzi'}")
            return None, resp
            
    except Exception as e:
        print(f"[WFIRMA DEBUG] Correction exception: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def wfirma_list_series(token: str, company_id: str = None) -> list:
    """
    Pobierz listę wszystkich serii faktur.
    Zwraca listę dict z 'id', 'name', 'template' itp.
    """
    api_url = "https://api2.wfirma.pl/series/find?inputFormat=json&outputFormat=json&oauth_version=2"
    if company_id:
        api_url += f"&company_id={company_id}"
    headers = get_wfirma_headers(token)
    
    # Pobierz wszystkie serie (limit 100)
    search_data = {
        "series": {
            "parameters": {
                "limit": 100
            }
        }
    }
    
    try:
        print(f"[WFIRMA DEBUG] Pobieram listę serii...")
        resp = requests.post(api_url, headers=headers, json=search_data)
        print(f"[WFIRMA DEBUG] list_series status: {resp.status_code}")
        
        result = []
        if resp.status_code == 200:
            data = resp.json()
            series_list = data.get('series', {})
            if series_list and isinstance(series_list, dict):
                for key in series_list:
                    if key.isdigit():
                        series = series_list[key].get('series', {})
                        if series and series.get('id'):
                            result.append({
                                'id': series.get('id'),
                                'name': series.get('name'),
                                'template': series.get('template'),
                                'module': series.get('module')
                            })
            print(f"[WFIRMA DEBUG] Znaleziono {len(result)} serii")
            for s in result:
                print(f"[WFIRMA DEBUG]   - ID: {s['id']}, Nazwa: {s['name']}, Szablon: {s['template']}")
        else:
            print(f"[WFIRMA DEBUG] list_series error: {resp.text[:300]}")
        return result
    except Exception as e:
        print(f"[WFIRMA DEBUG] list_series exception: {e}")
        return []


def wfirma_find_series_by_name(token: str, series_name: str, company_id: str = None) -> dict | None:
    """
    Znajdź serię faktur po nazwie (case insensitive).
    Pobiera wszystkie serie i szuka pasującej nazwy.
    Zwraca dict z 'id' serii lub None.
    """
    try:
        print(f"[WFIRMA DEBUG] Szukam serii: {series_name} (case insensitive)")
        
        # Pobierz wszystkie serie
        all_series = wfirma_list_series(token, company_id)
        
        if not all_series:
            print(f"[WFIRMA DEBUG] Brak serii w systemie")
            return None
        
        # Szukaj case insensitive
        series_name_lower = series_name.lower().strip()
        for series in all_series:
            if series.get('name', '').lower().strip() == series_name_lower:
                print(f"[WFIRMA DEBUG] Znaleziono serię: {series.get('name')} -> ID {series.get('id')}")
                return series
        
        # Nie znaleziono - loguj dostępne serie
        print(f"[WFIRMA DEBUG] Nie znaleziono serii '{series_name}'. Dostępne serie:")
        for s in all_series:
            print(f"[WFIRMA DEBUG]   - '{s.get('name')}'")
        
        return None
    except Exception as e:
        print(f"[WFIRMA DEBUG] find_series exception: {e}")
        return None


def wfirma_get_company_id(token: str) -> str | None:
    """Pobierz ID pierwszej firmy użytkownika"""
    api_url = "https://api2.wfirma.pl/companies/find?inputFormat=json&outputFormat=json&oauth_version=2"
    headers = get_wfirma_headers(token)
    body = {"companies": {"parameters": {"limit": "1"}}}
    
    try:
        resp = requests.post(api_url, headers=headers, json=body)
        print(f"[WFIRMA DEBUG] get_company_id status: {resp.status_code}")
        print(f"[WFIRMA DEBUG] get_company_id response: {resp.text[:500]}")
        
        if resp.status_code == 200:
            data = resp.json()
            companies = data.get('companies', {})
            print(f"[WFIRMA DEBUG] companies keys: {list(companies.keys()) if companies else None}")
            
            if isinstance(companies, dict):
                for key in companies:
                    if key.isdigit() or key == '0':
                        comp = companies[key].get('company', {})
                        company_id = comp.get('id')
                        if company_id:
                            print(f"[WFIRMA DEBUG] Found company_id: {company_id}")
                            return str(company_id)
        return None
    except Exception as e:
        print(f"[WFIRMA DEBUG] get_company_id exception: {e}")
        return None


def wfirma_get_invoice_pdf(token: str, invoice_id: str, company_id: str | None = None) -> requests.Response:
    """
    Pobierz PDF faktury z wFirma.
    Używamy endpointu invoices/download (zgodnie z diagnostyką).
    company_id jest opcjonalny - jeśli brak, API użyje domyślnej firmy.
    """
    # Poprawny endpoint z Postmana
    api_url = f"https://api2.wfirma.pl/invoices/download/{invoice_id}"
    params = {
        "inputFormat": "json",
        "outputFormat": "json",
        "oauth_version": "2",
    }
    if company_id:
        params["company_id"] = company_id
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/pdf"
    }
    
    # Body z parametrami
    body = {
        "invoices": {
            "parameters": {
                "parameter": [
                    {"name": "page", "value": "invoice"},
                    {"name": "address", "value": "0"},
                    {"name": "leaflet", "value": "0"},
                    {"name": "duplicate", "value": "0"}
                ]
            }
        }
    }
    
    return requests.post(api_url, headers=headers, params=params, json=body, stream=True)


def wfirma_add_payment(token: str, invoice_id: str, amount: float, payment_date: str = None, company_id: str | None = None, payment_cashbox_id: str | int | None = None) -> tuple[dict | None, requests.Response | None]:
    """
    Dodaj płatność do faktury (oznacz jako opłaconą).
    
    Args:
        invoice_id: ID faktury
        amount: Kwota płatności (powinna być równa total faktury)
        payment_date: Data płatności (domyślnie dzisiaj)
        company_id: ID firmy
        payment_cashbox_id: ID kasy (opcjonalnie - pobrane z faktury)
    """
    import datetime
    if not payment_date:
        payment_date = datetime.date.today().isoformat()
    
    api_url = "https://api2.wfirma.pl/payments/add?inputFormat=json&outputFormat=json&oauth_version=2"
    if company_id:
        api_url += f"&company_id={company_id}"
    
    headers = get_wfirma_headers(token)
    
    # Struktura zgodna z dokumentacją
    payment_obj = {
        "object_name": "invoice",
        "object_id": int(invoice_id),
        "value": amount,
        "date": payment_date,
        "payment_method": "transfer"  # Metoda płatności
    }
    
    # Dodaj kasę jeśli podana
    if payment_cashbox_id and int(payment_cashbox_id) > 0:
        payment_obj["payment_cashbox"] = {"id": int(payment_cashbox_id)}
    
    payment_data = {
        "payments": {
            "payment": payment_obj
        }
    }
    
    resp = None
    try:
        print(f"[WFIRMA DEBUG] Dodaję płatność: invoice_id={invoice_id}, amount={amount}, date={payment_date}")
        print(f"[WFIRMA DEBUG] Payment request body: {json.dumps(payment_data, indent=2)}")
        resp = requests.post(api_url, headers=headers, json=payment_data)
        print(f"[WFIRMA DEBUG] add_payment status: {resp.status_code}")
        print(f"[WFIRMA DEBUG] add_payment response: {resp.text[:1000]}")
        
        if resp.status_code == 200:
            result = resp.json()
            status = result.get('status', {}).get('code')
            if status == 'OK':
                print(f"[WFIRMA DEBUG] Płatność dodana pomyślnie")
                payments = result.get('payments', {})
                if isinstance(payments, dict):
                    for key in payments:
                        if key.isdigit():
                            payment = payments[key].get('payment', {})
                            if payment:
                                print(f"[WFIRMA DEBUG] Utworzona płatność: id={payment.get('id')}, value={payment.get('value')}")
                                return payment, resp
                return {}, resp
            else:
                print(f"[WFIRMA DEBUG] add_payment error: {result.get('status', {}).get('message')}")
        else:
            print(f"[WFIRMA DEBUG] add_payment HTTP error: {resp.text[:500]}")
        return None, resp
    except Exception as e:
        print(f"[WFIRMA DEBUG] add_payment exception: {e}")
        return None, resp


def wfirma_mark_invoice_paid(token: str, invoice_id: str, amount: float, company_id: str | None = None) -> tuple[bool, requests.Response | None]:
    """
    Oznacz fakturę jako opłaconą przez edycję pola alreadypaid_initial.
    
    To jest alternatywne podejście do payments/add - bezpośrednia edycja faktury.
    
    Args:
        invoice_id: ID faktury
        amount: Kwota zapłacona (powinna być równa total faktury)
        company_id: ID firmy
        
    Returns:
        (success: bool, response: Response)
    """
    api_url = f"https://api2.wfirma.pl/invoices/edit/{invoice_id}?inputFormat=json&outputFormat=json&oauth_version=2"
    if company_id:
        api_url += f"&company_id={company_id}"
    
    headers = get_wfirma_headers(token)
    
    # Edytuj fakturę - ustaw alreadypaid_initial na pełną kwotę
    edit_data = {
        "invoices": {
            "invoice": {
                "alreadypaid_initial": str(amount)
            }
        }
    }
    
    resp = None
    try:
        print(f"[WFIRMA DEBUG] Oznaczam fakturę jako opłaconą (edit): invoice_id={invoice_id}, amount={amount}")
        print(f"[WFIRMA DEBUG] Invoice edit request body: {json.dumps(edit_data, indent=2)}")
        resp = requests.post(api_url, headers=headers, json=edit_data)
        print(f"[WFIRMA DEBUG] invoice_edit status: {resp.status_code}")
        print(f"[WFIRMA DEBUG] invoice_edit response: {resp.text[:1000]}")
        
        if resp.status_code == 200:
            result = resp.json()
            status = result.get('status', {}).get('code')
            if status == 'OK':
                # Sprawdź czy faktura ma teraz paymentstate = paid
                invoices = result.get('invoices', {})
                if isinstance(invoices, dict):
                    for key in invoices:
                        if key.isdigit():
                            invoice = invoices[key].get('invoice', {})
                            if invoice:
                                new_state = invoice.get('paymentstate')
                                new_alreadypaid = invoice.get('alreadypaid')
                                print(f"[WFIRMA DEBUG] Po edycji: paymentstate={new_state}, alreadypaid={new_alreadypaid}")
                                return True, resp
                return True, resp
            else:
                print(f"[WFIRMA DEBUG] invoice_edit error: {result.get('status', {}).get('message')}")
        else:
            print(f"[WFIRMA DEBUG] invoice_edit HTTP error: {resp.text[:500]}")
        return False, resp
    except Exception as e:
        print(f"[WFIRMA DEBUG] invoice_edit exception: {e}")
        return False, resp


def wfirma_send_invoice_email(token: str, invoice_id: str, email: str, company_id: str | None = None) -> requests.Response:
    """
    Wyślij fakturę e-mailem przez wFirma.
    Używamy endpointu invoices/send (zgodnie z diagnostyką).
    company_id jest opcjonalny - jeśli brak, API użyje domyślnej firmy.
    """
    # Poprawny endpoint z Postmana
    api_url = f"https://api2.wfirma.pl/invoices/send/{invoice_id}"
    params = {
        "inputFormat": "json",
        "outputFormat": "json",
        "oauth_version": "2",
    }
    if company_id:
        params["company_id"] = company_id
    
    headers = get_wfirma_headers(token)
    
    # KLUCZOWE: Wrapper "invoices" + struktura parametrów
    payload = {
        "invoices": {
            "parameters": [
                {"parameter": {"name": "email", "value": email}},
                {"parameter": {"name": "subject", "value": "Otrzymałeś fakturę"}},
                {"parameter": {"name": "page", "value": "invoice"}},
                {"parameter": {"name": "leaflet", "value": "0"}},
                {"parameter": {"name": "duplicate", "value": "0"}},
                {"parameter": {"name": "body", "value": "Przesyłam fakturę"}}
            ]
        }
    }
    
    return requests.post(api_url, headers=headers, params=params, json=payload)


# ==================== POMOCNICZE: GUS LOOKUP (do ponownego użycia w workflow) ====================


def gus_lookup_nip(clean_nip: str) -> tuple[list[dict] | None, str | None]:
    """
    Minimalny helper do ponownego użycia w workflow (bez HTTP round-trip do własnego endpointu).
    Zwraca (lista rekordów lub None, komunikat błędu lub None).
    """
    print(f"[GUS-LOOKUP] === START dla NIP={clean_nip} ===")
    from_header_key = ''
    api_key = GUS_API_KEY or ''

    if not api_key:
        print(f"[GUS-LOOKUP] BŁĄD: Brak klucza GUS_API_KEY")
        return None, 'Brak klucza GUS_API_KEY'

    use_test_env = api_key == 'abcde12345abcde12345' or GUS_USE_TEST
    bir_host = 'wyszukiwarkaregontest.stat.gov.pl' if use_test_env else 'wyszukiwarkaregon.stat.gov.pl'
    bir_url = f'https://{bir_host}/wsBIR/UslugaBIRzewnPubl.svc'
    print(f"[GUS-LOOKUP] Środowisko: {'TEST' if use_test_env else 'PROD'}, host={bir_host}")

    safe_api_key = escape_xml(api_key)
    login_envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:ns="http://CIS/BIR/PUBL/2014/07">'
        '<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">'
        f'<wsa:To>{bir_url}</wsa:To>'
        '<wsa:Action>http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/Zaloguj</wsa:Action>'
        '</soap:Header>'
        '<soap:Body>'
        '<ns:Zaloguj>'
        f'<ns:pKluczUzytkownika>{safe_api_key}</ns:pKluczUzytkownika>'
        '</ns:Zaloguj>'
        '</soap:Body>'
        '</soap:Envelope>'
    )

    print(f"[GUS-LOOKUP] Wysyłam Zaloguj request...")
    try:
        login_resp = post_soap_gus(bir_host, login_envelope, sid=None, timeout=10)
        print(f"[GUS-LOOKUP] Zaloguj response status={login_resp.status_code}")
    except Exception as e:
        print(f"[GUS-LOOKUP] BŁĄD logowania: {e}")
        return None, f'Błąd komunikacji z GUS podczas logowania: {e}'

    sid_match = re.search(r'<ZalogujResult>([^<]*)</ZalogujResult>', login_resp.text or '')
    sid = sid_match.group(1).strip() if sid_match else ''
    print(f"[GUS-LOOKUP] SID={'[JEST]' if sid else '[BRAK]'} (długość={len(sid) if sid else 0})")
    if not sid:
        print(f"[GUS-LOOKUP] BŁĄD: Brak SID, response body={login_resp.text[:500] if login_resp.text else 'EMPTY'}")
        return None, 'Logowanie do GUS nie powiodło się (brak SID)'

    safe_nip = escape_xml(clean_nip)
    search_envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:ns="http://CIS/BIR/PUBL/2014/07" '
        'xmlns:q1="http://CIS/BIR/PUBL/2014/07/DataContract" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">'
        f'<wsa:To>{bir_url}</wsa:To>'
        '<wsa:Action>http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/DaneSzukajPodmioty</wsa:Action>'
        '</soap:Header>'
        '<soap:Body>'
        '<ns:DaneSzukajPodmioty>'
        '<ns:pParametryWyszukiwania>'
        '<q1:Krs xsi:nil="true"/>'
        '<q1:Krsy xsi:nil="true"/>'
        f'<q1:Nip>{safe_nip}</q1:Nip>'
        '<q1:Nipy xsi:nil="true"/>'
        '<q1:Regon xsi:nil="true"/>'
        '<q1:Regony14zn xsi:nil="true"/>'
        '<q1:Regony9zn xsi:nil="true"/>'
        '</ns:pParametryWyszukiwania>'
        '</ns:DaneSzukajPodmioty>'
        '</soap:Body>'
        '</soap:Envelope>'
    )

    print(f"[GUS-LOOKUP] Wysyłam DaneSzukajPodmioty dla NIP={clean_nip}...")
    try:
        search_resp = post_soap_gus(bir_host, search_envelope, sid=sid, timeout=10)
        print(f"[GUS-LOOKUP] Search response status={search_resp.status_code}")
    except Exception as e:
        print(f"[GUS-LOOKUP] BŁĄD wyszukiwania: {e}")
        return None, f'Błąd komunikacji z GUS podczas wyszukiwania: {e}'

    soap_part = search_resp.text or ''
    print(f"[GUS-LOOKUP] Raw response length={len(soap_part)}")
    
    if 'Content-Type: application/xop+xml' in soap_part:
        match = re.search(
            r'Content-Type: application/xop\+xml[^\r\n]*\r?\n\r?\n([\s\S]*?)\r?\n--uuid:',
            soap_part,
            re.MULTILINE | re.DOTALL,
        )
        if match:
            soap_part = match.group(1)
            print(f"[GUS-LOOKUP] Extracted SOAP part length={len(soap_part)}")

    if re.search(r'<DaneSzukajResult\s*/>', soap_part):
        print(f"[GUS-LOOKUP] WYNIK: Pusty <DaneSzukajResult/> - NIP nie znaleziony")
        return [], None

    result_match = re.search(
        r'<DaneSzukajPodmiotyResult>([\s\S]*?)</DaneSzukajPodmiotyResult>',
        soap_part,
        re.MULTILINE | re.DOTALL,
    )
    inner_xml = result_match.group(1) if result_match else ''
    print(f"[GUS-LOOKUP] inner_xml length={len(inner_xml)}, preview={inner_xml[:200] if inner_xml else 'EMPTY'}...")
    if not inner_xml:
        print(f"[GUS-LOOKUP] BŁĄD: Brak DaneSzukajPodmiotyResult, soap_part={soap_part[:500]}")
        return None, 'Brak danych w odpowiedzi GUS (DaneSzukajPodmiotyResult pusty)'

    decoded_xml = decode_bir_inner_xml(inner_xml)
    print(f"[GUS-LOOKUP] decoded_xml length={len(decoded_xml) if decoded_xml else 0}")
    if not decoded_xml:
        print(f"[GUS-LOOKUP] BŁĄD: decode_bir_inner_xml zwrócił None/pusty")
        return None, 'Brak danych po dekodowaniu odpowiedzi GUS'

    try:
        root = ET.fromstring(decoded_xml)
    except ET.ParseError as e:
        return None, f'Nie udało się sparsować danych GUS: {e}'

    data_list: list[dict] = []
    for dane in root.findall('.//dane'):
        def get_text(tag: str) -> str | None:
            el = dane.find(tag)
            return el.text if el is not None else None

        # Sprawdź czy to błąd GUS (ErrorCode) zamiast danych podmiotu
        error_code = get_text('ErrorCode')
        if error_code:
            error_msg = get_text('ErrorMessagePl') or get_text('ErrorMessageEn') or ''
            print(f"[GUS-LOOKUP] GUS zwrócił ErrorCode={error_code}: {error_msg}")
            continue  # Pomiń ten "rekord" - to błąd, nie dane

        mapped = {
            'regon': get_text('Regon'),
            'nip': get_text('Nip'),
            'nazwa': get_text('Nazwa'),
            'wojewodztwo': get_text('Wojewodztwo'),
            'powiat': get_text('Powiat'),
            'gmina': get_text('Gmina'),
            'miejscowosc': get_text('Miejscowosc'),
            'kodPocztowy': get_text('KodPocztowy'),
            'ulica': get_text('Ulica'),
            'nrNieruchomosci': get_text('NrNieruchomosci'),
            'nrLokalu': get_text('NrLokalu'),
            'typ': get_text('Typ'),
            'silosId': get_text('SilosID'),
            'miejscowoscPoczty': get_text('MiejscowoscPoczty'),
            'krs': get_text('Krs'),
        }
        
        # Dodaj tylko jeśli jest nazwa (prawdziwy podmiot)
        if mapped.get('nazwa'):
            data_list.append(mapped)
        else:
            print(f"[GUS-LOOKUP] Pominięto rekord bez nazwy: {mapped}")

    print(f"[GUS-LOOKUP] === KONIEC NIP={clean_nip} znaleziono {len(data_list)} rekordów ===")
    if data_list:
        print(f"[GUS-LOOKUP] Pierwszy rekord: nazwa={data_list[0].get('nazwa')}, regon={data_list[0].get('regon')}")
    return data_list, None


# ==================== FUNKCJE GUS/BIR (prosty port z Googie_GUS) ====================

def validate_nip_checksum(nip: str) -> bool:
    """
    Walidacja sumy kontrolnej NIP (cyfra kontrolna).
    NIP musi mieć dokładnie 10 cyfr. Zwraca True jeśli suma kontrolna poprawna.
    Gdy reszta z dzielenia przez 11 = 10, NIP jest nieważny (cyfra kontrolna 0-9).
    """
    if len(nip) != 10 or not nip.isdigit():
        return False
    weights = [6, 5, 7, 2, 3, 4, 5, 6, 7]
    checksum = sum(int(nip[i]) * weights[i] for i in range(9)) % 11
    # Reszta 10 oznacza NIP nieważny - nie można zakodować w jednej cyfrze
    if checksum == 10:
        return False
    return checksum == int(nip[9])


def escape_xml(unsafe: str) -> str:
    """
    Bezpieczne wstawianie wartości do SOAP XML (ochrona przed SOAP injection).
    Port funkcji escapeXml z backendu Googie_GUS (Node).
    """
    if not isinstance(unsafe, str):
        return ""
    return (
        unsafe.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def decode_bir_inner_xml(encoded: str) -> str:
    """
    Dekodowanie wewnętrznego XML zwracanego przez GUS (DaneSzukajPodmiotyResult).
    Port funkcji decodeBirInnerXml z backendu Googie_GUS.
    """
    if not isinstance(encoded, str):
        return ""

    return (
        encoded.lstrip("\ufeff")
        .replace("&amp;amp;", "&amp;")
        .replace("&#xD;", "\r")
        .replace("&#xA;", "\n")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
        .strip()
    )


def post_soap_gus(bir_host: str, envelope: str, sid: str | None, timeout: int = 10) -> requests.Response:
    """
    Minimalna wersja postSoap z Googie_GUS – wysyła envelope SOAP do GUS/BIR.
    Używa requests, timeout domyślnie 10s. Nagłówek 'sid' ustawiany jeśli podano.
    """
    url = f"https://{bir_host}/wsBIR/UslugaBIRzewnPubl.svc"
    headers = {
        "Content-Type": "application/soap+xml; charset=utf-8",
        "Accept": "application/soap+xml",
        "User-Agent": "Googie_GUS Widget/0.0.1",
    }
    if sid:
        headers["sid"] = str(sid)

    # Wysyłamy surowy envelope jako dane POST
    response = requests.post(url, data=envelope.encode("utf-8"), headers=headers, timeout=timeout)
    return response


# ==================== ENDPOINTY OAUTH ====================

@app.route('/')
def index():
    """Strona główna z dokumentacją API"""
    return jsonify({
        'message': 'wFirma API Service',
        'version': '2.0',
        'status': 'operational',
        'security': {
            'note': 'Wszystkie endpointy POST wymagają nagłówka X-API-Key',
            'header': 'X-API-Key: your-secret-key'
        },
        'endpoints': {
            '🔐 OAuth': {
                '/auth?company=md': 'Rozpocznij autoryzację OAuth 2.0 dla Medidesk',
                '/auth?company=test': 'Rozpocznij autoryzację OAuth 2.0 dla testów',
                '/callback': 'Callback OAuth (automatyczny redirect)',
                '/api/token/status?company=md': 'GET - Sprawdź status tokenu dla Medidesk',
                '/api/token/status?company=test': 'GET - Sprawdź status tokenu dla testów'
            },
            '👥 Kontrahenci': {
                '/api/contractor/<nip>': 'GET - Sprawdź kontrahenta po NIP (wFirma)',
                '/api/contractor/add': 'POST - Dodaj nowego kontrahenta'
            },
            '📄 Faktury': {
                '/api/invoice/create': 'POST - Utwórz fakturę',
                '/api/invoice/<invoice_id>/pdf': 'GET - Pobierz PDF faktury',
                '/api/invoice/<invoice_id>/send': 'POST - Wyślij fakturę emailem (body: {"email": "..."})',
                '/api/series/list?company=test': 'GET - Lista dostępnych serii faktur'
            },
            '🚀 Workflow (All-in-One)': {
                '/api/workflow/create-invoice-from-nip': 'POST - NIP→GUS→Kontrahent→Faktura→Email→PDF'
            },
            '🏢 GUS/REGON': {
                '/api/gus/name-by-nip': 'POST - Pobierz dane firmy z GUS (body: {"nip": "..."})'
            }
        },
        'workflow_example': {
            "company": "md",  # lub "test" - wybór zestawu danych wFirma
            "nip": "1234567890",
            "email": "klient@example.com",
            "send_email": True,
            "invoice": {
                "positions": [
                    {
                        "name": "Usługa",
                        "quantity": 1,
                        "unit": "szt.",
                        "unit_price_net": 100.00,
                        "vat_rate": "23"
                    }
                ]
            }
        },
        'supported_companies': SUPPORTED_COMPANIES,
        'note': 'Parametr "company" określa zestaw danych wFirma: "md" (Medidesk) lub "test" (testowe)'
    })


@app.route('/api/db/status', methods=['GET'])
@require_api_key
def db_status():
    """
    Diagnostyka Render Postgres.
    Wymaga X-API-Key (MAKE_RENDER_API_KEY) – ten sam mechanizm co reszta API.
    """
    try:
        from pg_storage import get_db_status
        return jsonify(get_db_status())
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------
# BACKSTAGE ENGINE - obsługa webhooków z Zoho Backstage
# ---------------------------------------------------------------------------


@app.route('/api/backstage/event_create', methods=['POST'])
@require_api_key
def backstage_event_create():
    """
    Endpoint do tworzenia/aktualizacji wydarzeń z Zoho Backstage.
    
    Tworzy wydarzenie jako "draft" (szkic do zatwierdzenia) w panelu admina.
    Automatycznie mapuje pola z webhooka na strukturę danych wydarzenia.
    
    Headers:
        X-API-Key: klucz API (MAKE_RENDER_API_KEY)
    
    Body (JSON): payload z Backstage (pełne dane wydarzenia)
    
    Response:
    {
        "status": "ok" | "error",
        "event_id": "...",
        "event_name": "...",
        "action": "created" | "updated",
        "message": "...",
        "mapped_fields": [...],
        "error": "..."  // tylko gdy status=error
    }
    """
    try:
        from backstage_engine import process_backstage_event
        
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({
                'status': 'error',
                'error': 'Brak JSON payload w request body'
            }), 400
        
        result = process_backstage_event(payload)
        
        if result.get('status') == 'error':
            return jsonify(result), 400
        
        return jsonify(result), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/backstage/ticket_classes', methods=['POST'])
@require_api_key
def backstage_ticket_classes():
    """
    Endpoint do odbierania typów biletów z Zoho Flow.
    
    Wywoływany przez Zoho Flow po pobraniu ticket classes z Backstage.
    
    Headers:
        X-API-Key: klucz API (MAKE_RENDER_API_KEY)
    
    Body (JSON):
    {
        "event_id": "...",
        "ticket_classes": [
            {
                "ticket_class_id": "...",
                "ticket_name": "...",
                "price": 100.00,
                "currency": "PLN",
                "quantity": 50,
                ...
            }
        ]
    }
    
    Response:
    {
        "status": "ok",
        "event_id": "...",
        "saved_count": 3
    }
    """
    try:
        from pg_storage import replace_ticket_classes, get_event
        
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({
                'status': 'error',
                'error': 'Brak JSON payload w request body'
            }), 400
        
        event_id = str(payload.get("event_id") or "").strip()
        ticket_classes = payload.get("ticket_classes") or []
        
        if not event_id:
            return jsonify({
                'status': 'error',
                'error': 'Brak wymaganego pola event_id'
            }), 400
        
        # Sprawdź czy wydarzenie istnieje
        event = get_event(event_id)
        if not event:
            return jsonify({
                'status': 'error',
                'error': f'Wydarzenie {event_id} nie istnieje'
            }), 404
        
        # Zapisz ticket classes
        classes_to_save = []
        for tc in ticket_classes:
            ticket_class_id = str(tc.get("ticket_class_id") or tc.get("id") or "").strip()
            ticket_name = str(tc.get("ticket_name") or tc.get("name") or "").strip()
            
            if ticket_class_id:
                classes_to_save.append({
                    "ticket_class_id": ticket_class_id,
                    "ticket_name": ticket_name or f"Bilet {ticket_class_id}",
                    "data": tc,  # Całe dane z webhooka
                })
        
        replace_ticket_classes(event_id, classes_to_save)
        
        print(f"[TICKET CLASSES] Zapisano {len(classes_to_save)} typów biletów dla wydarzenia {event_id}")
        
        return jsonify({
            'status': 'ok',
            'event_id': event_id,
            'saved_count': len(classes_to_save),
        }), 200
        
    except Exception as e:
        print(f"[TICKET CLASSES] Error: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


# Webhook do Zoho Flow - pobieranie typów biletów
ZOHO_FLOW_FETCH_TICKETS_WEBHOOK = os.environ.get(
    "ZOHO_FLOW_FETCH_TICKETS_WEBHOOK",
    "https://flow.zoho.eu/20101689330/flow/webhook/incoming?zapikey=1001.da7bd8d507af6cb38280e14ef6f8e18b.663769721c5063f905bf924cfbefdc98&isdebug=false"
)


@app.route('/api/events/<event_id>/fetch-tickets', methods=['POST'])
def api_fetch_event_tickets(event_id: str):
    """
    Wywołuje Zoho Flow webhook do pobrania typów biletów z Backstage.
    
    Tylko dla zalogowanych adminów.
    
    Zoho Flow powinien:
    1. Pobrać ticket classes z Backstage dla danego event_id
    2. Wywołać /api/backstage/ticket_classes z wynikami
    
    Returns:
    {
        "success": true,
        "message": "Żądanie wysłane do Zoho Flow"
    }
    """
    try:
        from pg_storage import get_event
        
        # Sprawdź czy użytkownik jest zalogowany jako admin
        admin_user = session.get("admin_v2_user")
        if not admin_user:
            return jsonify({"success": False, "error": "Wymagane zalogowanie"}), 401
        
        # Sprawdź czy wydarzenie istnieje
        event = get_event(event_id)
        if not event:
            return jsonify({"success": False, "error": "Wydarzenie nie znalezione"}), 404
        
        # Sprawdź czy webhook jest skonfigurowany
        if not ZOHO_FLOW_FETCH_TICKETS_WEBHOOK:
            return jsonify({
                "success": False, 
                "error": "Webhook do pobierania biletów nie jest skonfigurowany (ZOHO_FLOW_FETCH_TICKETS_WEBHOOK)"
            }), 500
        
        # Wyślij request do Zoho Flow
        callback_url = request.url_root.rstrip('/') + '/api/backstage/ticket_classes'
        
        webhook_payload = {
            "event_id": event_id,
            "event_key": event_id,  # W Backstage event_key = event_id
            "event_name": event.get("event_name", ""),
            "callback_url": callback_url,
            "api_key": os.environ.get("MAKE_RENDER_API_KEY", ""),  # Do autoryzacji callbacku
        }
        
        resp = requests.post(
            ZOHO_FLOW_FETCH_TICKETS_WEBHOOK,
            json=webhook_payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        
        if resp.status_code not in (200, 201, 202):
            return jsonify({
                "success": False,
                "error": f"Zoho Flow zwrócił błąd: HTTP {resp.status_code}"
            }), 500
        
        print(f"[FETCH TICKETS] Wysłano żądanie do Zoho Flow dla wydarzenia {event_id}")
        
        return jsonify({
            "success": True,
            "message": "Żądanie wysłane do Zoho Flow. Typy biletów zostaną zaktualizowane.",
            "event_id": event_id,
        }), 200
        
    except Exception as e:
        print(f"[FETCH TICKETS] Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/backstage/order', methods=['POST'])
@require_api_key
def backstage_order():
    """
    Endpoint do obsługi webhooków z Zoho Backstage.
    
    Przyjmuje payload z zamówieniem, routuje do odpowiedniego flow:
    - FOC (Free of Charge) - total=0
    - PROFORMA - wystawiamy proformę w wFirma
    - STRIPE - generujemy link do płatności online
    
    Zwraca listę mail_tasks do wysłania przez Make.com
    oraz (opcjonalnie) akcje do wykonania w wFirma/Stripe.
    
    Headers:
        X-API-Key: klucz API (MAKE_RENDER_API_KEY)
    
    Body (JSON): payload z Backstage (struktura zależna od konfiguracji webhooka)
    
    Response:
    {
        "status": "ok" | "error" | "duplicate",
        "order_id": "...",
        "flow": "FOC" | "PROFORMA" | "STRIPE",
        "order_status": "paid" | "pending_payment",
        "mail_tasks": [...],
        "wfirma_action": {...},  // tylko dla PROFORMA
        "stripe_action": {...},  // tylko dla STRIPE
        "error": "..."  // tylko gdy status=error
    }
    """
    try:
        from backstage_engine import process_backstage_order
        
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({
                'status': 'error',
                'error': 'Brak JSON payload w request body'
            }), 400
        
        result = process_backstage_order(payload)
        
        # Zwróć odpowiedni status HTTP
        if result.get('status') == 'error':
            return jsonify(result), 400
        if result.get('status') == 'duplicate':
            return jsonify(result), 200  # OK, ale już przetworzony
        
        return jsonify(result), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/backstage/attendee', methods=['POST'])
@require_api_key
def backstage_attendee():
    """
    Endpoint do odbierania danych uczestnika z Zoho Backstage.
    
    Zoho Backstage wysyła webhook "Attendee registered for event" gdy uczestnik
    wypełni swoje dane dla biletu.
    
    Body (JSON) - pola z Zoho Backstage:
    {
        "order_id": "24311000000805066",       // lub "Order ID"
        "ticket_id": "243110000008050661",     // lub "Ticket ID"
        "ticket_class": "24311000000547201",   // lub "Ticket class"
        "attendee_id": "...",                  // lub "Attendee ID"
        "email": "jan@example.com",            // lub "Email address"
        "first_name": "Jan",                   // lub "First name" lub "Imię"
        "last_name": "Kowalski",               // lub "Last name" lub "Nazwisko"
        "phone": "+48123456789",               // lub "Phone number" lub "telefon uczestnika"
        "event": "24311000000429149",          // ID wydarzenia
        ...
    }
    
    Response:
    {
        "status": "ok" | "error",
        "order_id": "...",
        "ticket_id": "...",
        "participant_updated": true,
        "email_sent": true | false,
        "message": "..."
    }
    """
    try:
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({
                'status': 'error',
                'error': 'Brak JSON payload'
            }), 400
        
        # Bezpieczeństwo: NIE loguj pełnego payloadu (PII). Zostaw tylko metadane.
        try:
            keys = list(payload.keys())
        except Exception:
            keys = []
        print(f"[ATTENDEE WEBHOOK] Otrzymano payload keys: {keys}")
        
        # Ekstrakcja danych z różnych możliwych nazw pól
        order_id = (
            payload.get("order_id") or 
            payload.get("Order ID") or 
            payload.get("orderId") or
            payload.get("event_order_id") or
            str(payload.get("Order_ID", ""))
        )
        
        ticket_id = (
            payload.get("ticket_id") or 
            payload.get("Ticket ID") or 
            payload.get("ticketId") or
            str(payload.get("Ticket_ID", ""))
        )
        
        ticket_class_id = (
            payload.get("ticket_class") or 
            payload.get("Ticket class") or 
            payload.get("ticketClass") or
            payload.get("ticket_class_id") or
            str(payload.get("Ticket_class", ""))
        )
        
        attendee_id = (
            payload.get("attendee_id") or 
            payload.get("Attendee ID") or 
            payload.get("attendeeId") or
            str(payload.get("Attendee_ID", ""))
        )
        
        # PRIORYTET: dane uczestnika z formularza Backstage (polskie nazwy)
        email = (
            payload.get("email_uczestnika") or  # główne pole uczestnika
            payload.get("email") or 
            payload.get("Email") or 
            payload.get("Email address") or
            payload.get("email_address") or
            ""
        )
        
        first_name = (
            payload.get("imie_uczestnika") or  # główne pole uczestnika
            payload.get("first_name") or 
            payload.get("First name") or 
            payload.get("firstName") or
            payload.get("firstName_system_crm") or  # fallback z CRM
            payload.get("Imię") or
            payload.get("imie") or
            ""
        )
        
        last_name = (
            payload.get("nazwisko_uczestnika") or  # główne pole uczestnika
            payload.get("last_name") or 
            payload.get("Last name") or 
            payload.get("lastName") or
            payload.get("lastName_system_crm") or  # fallback z CRM
            payload.get("Nazwisko") or
            payload.get("nazwisko") or
            ""
        )
        
        phone = (
            payload.get("telefon_uczestnika") or  # główne pole uczestnika
            payload.get("phone") or 
            payload.get("Phone number") or 
            payload.get("phoneNumber") or
            payload.get("phone_number") or
            ""
        )
        
        event_id = (
            payload.get("event") or 
            payload.get("Event") or 
            payload.get("event_id") or
            payload.get("eventId") or
            ""
        )
        
        # Walidacja wymaganych pól
        if not order_id:
            return jsonify({
                'status': 'error',
                'error': 'Brak order_id w payload',
                'received_keys': list(payload.keys())
            }), 400
        
        if not ticket_id:
            return jsonify({
                'status': 'error',
                'error': 'Brak ticket_id w payload',
                'received_keys': list(payload.keys())
            }), 400
        
        # UWAGA: zgodnie z ustaleniami, webhook attendee liczy się do "kompletności"
        # po ticket_id — nie wymagamy emaila (nie weryfikujemy wnętrza).
        print(f"[ATTENDEE WEBHOOK] order={order_id}, ticket={ticket_id}, email_present={bool(email)}, name={first_name} {last_name}")
        
        # Zapisz/zaktualizuj uczestnika w bazie
        from pg_storage import (
            update_participant_details, 
            get_participant_by_ticket, 
            save_participant,
            get_order,
            get_participants_for_order,
        )
        
        # WALIDACJA: Sprawdź czy zamówienie istnieje (z retry dla race condition)
        # Zoho wysyła webhooki równolegle i czasem attendee przychodzi przed order
        import time as time_module
        order = None
        max_retries = 3
        retry_delay_seconds = 1.5  # 1.5s między próbami
        
        for attempt in range(max_retries):
            order = get_order(order_id)
            if order:
                if attempt > 0:
                    print(f"[ATTENDEE WEBHOOK] Zamówienie {order_id} znalezione po {attempt + 1} próbach (race condition resolved)")
                break
            
            if attempt < max_retries - 1:
                print(f"[ATTENDEE WEBHOOK] Zamówienie {order_id} nie istnieje (próba {attempt + 1}/{max_retries}), czekam {retry_delay_seconds}s...")
                time_module.sleep(retry_delay_seconds)
        
        if not order:
            print(f"[ATTENDEE WEBHOOK] BŁĄD: Zamówienie {order_id} nie istnieje w bazie po {max_retries} próbach!")
            return jsonify({
                'status': 'error',
                'error': f'Zamówienie {order_id} nie istnieje',
                'order_id': order_id,
                'ticket_id': ticket_id,
                'retries': max_retries,
                'hint': 'Webhook order nie dotarł w czasie oczekiwania. Sprawdź czy Zoho wysyła webhooki poprawnie.'
            }), 404
        
        # WALIDACJA: Sprawdź czy bilet należy do tego zamówienia
        existing_participants = get_participants_for_order(order_id)
        valid_ticket_ids = [p.get("ticket_id") for p in existing_participants]
        
        if valid_ticket_ids and ticket_id not in valid_ticket_ids:
            print(f"[ATTENDEE WEBHOOK] OSTRZEŻENIE: Bilet {ticket_id} nie jest zarejestrowany dla zamówienia {order_id}")
            print(f"[ATTENDEE WEBHOOK] Znane bilety dla tego zamówienia: {valid_ticket_ids[:5]}")
            # Nie blokujemy - może to być nowy bilet, który jeszcze nie był w order webhook
        
        # Sprawdź czy uczestnik już istnieje
        existing = get_participant_by_ticket(order_id, ticket_id)
        
        # Dodatkowe dane uczestnika (firma, stanowisko, identyfikator)
        company = payload.get("company_system_crm") or payload.get("company") or ""
        position = payload.get("stanowisko_system_crm") or payload.get("designation") or ""
        badge_name = payload.get("nazwa_placowki_na_identyfikator") or ""
        
        import time
        extra_data = {
            "attendee_id": attendee_id,
            "event_id": event_id,
            "source": "zoho_attendee_webhook",
            "attendee_webhook_received": True,
            "attendee_webhook_received_at": int(time.time()),
            "company": company,
            "position": position,
            "badge_name": badge_name,  # nazwa placówki na identyfikator
            "raw_payload_keys": list(payload.keys())[:20],
        }
        
        if existing:
            # Aktualizuj istniejącego (nie nadpisuj statusu emailed)
            existing_status = (existing.get("status") if isinstance(existing, dict) else "") or ""
            new_status = "emailed" if existing_status.lower() == "emailed" else "registered"
            effective_email = email or (existing.get("email") if isinstance(existing, dict) else "") or ""
            effective_first_name = first_name or (existing.get("first_name") if isinstance(existing, dict) else "") or ""
            effective_last_name = last_name or (existing.get("last_name") if isinstance(existing, dict) else "") or ""
            effective_phone = phone or (existing.get("phone") if isinstance(existing, dict) else "") or ""
            success = update_participant_details(
                event_order_id=order_id,
                ticket_id=ticket_id,
                email=effective_email,
                first_name=effective_first_name,
                last_name=effective_last_name,
                phone=effective_phone,
                status=new_status,
                extra_data=extra_data,
            )
            print(f"[ATTENDEE WEBHOOK] Zaktualizowano uczestnika: {success}")
        else:
            # Utwórz nowego
            participant_id = save_participant(
                event_order_id=order_id,
                ticket_id=ticket_id,
                ticket_class_id=ticket_class_id,
                email=email or "",
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                status="registered",
                data=extra_data,
            )
            success = participant_id is not None
            print(f"[ATTENDEE WEBHOOK] Utworzono uczestnika: ID={participant_id}")

        # Po każdym webhooku attendee sprawdź kompletność i ewentualnie wyślij maile (gated)
        send_result = None
        try:
            from backstage_engine import maybe_send_backstage_emails_when_complete
            send_result = maybe_send_backstage_emails_when_complete(order_id)
            print(f"[ATTENDEE WEBHOOK] maybe_send_backstage_emails_when_complete | complete={bool((send_result or {}).get('complete'))}")
        except Exception as e:
            print(f"[ATTENDEE WEBHOOK] Błąd triggera wysyłek po kompletności: {e}")
        
        email_sent = False
        try:
            # Informacyjnie: tylko email do uczestnika (nie purchaser)
            if send_result and send_result.get("sent"):
                participants_sent = int(((send_result.get("sent") or {}).get("participants") or {}).get("sent", 0))
                email_sent = participants_sent > 0
        except Exception:
            pass
        
        return jsonify({
            'status': 'ok',
            'order_id': order_id,
            'ticket_id': ticket_id,
            'attendee_id': attendee_id,
            'participant': {
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'phone': phone,
                'company': company,
                'position': position,
                'badge_name': badge_name,
            },
            'participant_updated': success,
            'email_sent': email_sent,
            'order_status': order.get("status") if order else None,
            'message': 'Dane uczestnika zapisane' + (' i email wysłany' if email_sent else ''),
        }), 200
        
    except Exception as e:
        print(f"[ATTENDEE WEBHOOK] Błąd: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/backstage/attendee_cancel', methods=['POST'])
@require_api_key
def backstage_attendee_cancel():
    """
    Endpoint do obsługi anulowania rezerwacji przez uczestnika z Zoho Backstage.
    
    Zoho Backstage wysyła webhook gdy uczestnik sam anuluje swoją rezerwację.
    
    Body (JSON):
    {
        "attendee_id": "...",
        "order_id": "...",
        "ticket_id": "...",
        "ticket_class": "...",
        "event": "...",
        "email": "...",
        "name": "...",
        "last_name": "...",
        ...
    }
    """
    from flask import jsonify
    import json
    import re
    
    try:
        # Próbuj najpierw standardowo
        try:
            payload = request.get_json(force=True) or {}
        except Exception as json_err:
            # Jeśli JSON ma trailing comma, spróbuj naprawić
            raw_data = request.get_data(as_text=True)
            print(f"[ATTENDEE CANCEL] Błąd parsowania JSON: {json_err}")
            print(f"[ATTENDEE CANCEL] Raw data: {raw_data[:500]}")
            
            # Usuń trailing commas przed } lub ]
            fixed_data = re.sub(r',\s*([}\]])', r'\1', raw_data)
            try:
                payload = json.loads(fixed_data) if fixed_data else {}
                print(f"[ATTENDEE CANCEL] JSON naprawiony (usunięto trailing comma)")
            except Exception as fix_err:
                print(f"[ATTENDEE CANCEL] Nie udało się naprawić JSON: {fix_err}")
                return jsonify({'status': 'error', 'error': f'Invalid JSON: {str(json_err)}'}), 400
        
        print(f"[ATTENDEE CANCEL] Otrzymano webhook: {list(payload.keys())}")
        
        # Mapowanie pól z Zoho (obsługa różnych formatów nazw)
        attendee_id = (
            payload.get("attendee_id") or 
            payload.get("Attendee ID") or 
            payload.get("attendeeId") or
            ""
        )
        
        order_id = (
            payload.get("order_id") or 
            payload.get("orderId") or 
            payload.get("Order ID") or
            ""
        )
        
        ticket_id = (
            payload.get("ticket_id") or 
            payload.get("ticketId") or 
            payload.get("Ticket ID") or
            ""
        )
        
        ticket_class = (
            payload.get("ticket_class") or 
            payload.get("ticketClass") or 
            payload.get("Ticket class") or
            ""
        )
        
        event_id = (
            payload.get("event") or 
            payload.get("event_id") or 
            payload.get("brand_id") or
            ""
        )
        
        email = (
            payload.get("email") or 
            payload.get("emailId") or 
            payload.get("Email address") or
            ""
        )
        
        first_name = payload.get("name") or payload.get("first_name") or ""
        last_name = payload.get("last_name") or payload.get("lastName") or ""
        
        print(f"[ATTENDEE CANCEL] Anulowanie: attendee={attendee_id}, order={order_id}, ticket={ticket_id}, email={email}")
        
        if not order_id and not ticket_id:
            return jsonify({
                'status': 'error',
                'error': 'Brak order_id lub ticket_id',
                'received_keys': list(payload.keys())
            }), 400
        
        # Zaktualizuj status uczestnika na "cancelled"
        from pg_storage import get_participants_for_order, save_participant
        
        participant_updated = False
        
        if order_id:
            participants = get_participants_for_order(order_id) or []
            
            for p in participants:
                # Znajdź uczestnika po ticket_id lub email
                if (ticket_id and p.get("ticket_id") == ticket_id) or \
                   (email and p.get("email", "").lower() == email.lower()):
                    
                    # Aktualizuj status na cancelled
                    existing_data = p.get("data") or {}
                    existing_data["cancelled"] = True
                    existing_data["cancelled_at"] = int(__import__('time').time())
                    existing_data["cancelled_source"] = "zoho_attendee_cancel_webhook"
                    existing_data["attendee_id"] = attendee_id
                    
                    save_participant(
                        event_order_id=order_id,
                        ticket_id=p.get("ticket_id"),
                        ticket_class_id=p.get("ticket_class_id"),
                        email=p.get("email"),
                        first_name=p.get("first_name"),
                        last_name=p.get("last_name"),
                        phone=p.get("phone"),
                        status="cancelled",
                        data=existing_data,
                    )
                    participant_updated = True
                    print(f"[ATTENDEE CANCEL] Uczestnik {p.get('email')} oznaczony jako anulowany")
                    break
        
        # Loguj w audit
        from admin_v2_panel import insert_admin_audit_log
        insert_admin_audit_log(
            action="attendee_cancelled_by_webhook",
            admin_user_id=None,
            target_id=order_id or ticket_id,
            extra={
                "attendee_id": attendee_id,
                "ticket_id": ticket_id,
                "email": email,
                "name": f"{first_name} {last_name}".strip(),
                "source": "zoho_backstage",
            },
            ip=request.remote_addr,
        )
        
        return jsonify({
            'status': 'ok',
            'attendee_id': attendee_id,
            'order_id': order_id,
            'ticket_id': ticket_id,
            'participant_updated': participant_updated,
            'message': 'Rezerwacja uczestnika anulowana' if participant_updated else 'Nie znaleziono uczestnika do anulowania',
        }), 200
        
    except Exception as e:
        print(f"[ATTENDEE CANCEL] Błąd: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


# ---------------------------------------------------------------------------
# PARTICIPANTS - uczestnicy wydarzeń (przypisani do biletów)
# ---------------------------------------------------------------------------


@app.route('/api/participants/<event_order_id>', methods=['GET'])
@require_api_key
def get_participants(event_order_id: str):
    """
    Pobiera listę uczestników dla zamówienia.
    
    Response:
    {
        "event_order_id": "...",
        "participants": [
            {
                "id": 1,
                "ticket_id": "...",
                "ticket_class_id": "...",
                "email": "...",
                "first_name": "...",
                "last_name": "...",
                "phone": "...",
                "status": "pending|registered|emailed|cancelled",
                "data": {...}
            }
        ],
        "stats": {"pending": 2, "registered": 1}
    }
    """
    try:
        from pg_storage import get_participants_for_order, count_participants_by_status
        
        participants = get_participants_for_order(event_order_id)
        stats = count_participants_by_status(event_order_id)
        
        # Konwertuj daty na ISO format
        for p in participants:
            if p.get("created_at"):
                p["created_at"] = p["created_at"].isoformat() if hasattr(p["created_at"], "isoformat") else str(p["created_at"])
            if p.get("updated_at"):
                p["updated_at"] = p["updated_at"].isoformat() if hasattr(p["updated_at"], "isoformat") else str(p["updated_at"])
        
        return jsonify({
            "event_order_id": event_order_id,
            "participants": participants,
            "stats": stats,
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/participants/<event_order_id>/<ticket_id>', methods=['PUT'])
@require_api_key
def update_participant(event_order_id: str, ticket_id: str):
    """
    Aktualizuje dane uczestnika przypisanego do biletu.
    Używane gdy uczestnik wypełnia swoje dane (np. przez link w emailu).
    
    Body (JSON):
    {
        "email": "...",
        "first_name": "...",
        "last_name": "...",
        "phone": "...",
        "extra_data": {...}  // opcjonalne dodatkowe dane
    }
    
    Response:
    {
        "success": true,
        "event_order_id": "...",
        "ticket_id": "...",
        "status": "registered"
    }
    """
    try:
        from pg_storage import update_participant_details, get_participant_by_ticket
        
        data = request.get_json(silent=True) or {}
        
        email = data.get("email", "")
        if not email:
            return jsonify({"error": "Email jest wymagany"}), 400
        
        success = update_participant_details(
            event_order_id=event_order_id,
            ticket_id=ticket_id,
            email=email,
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            phone=data.get("phone", ""),
            status="registered",
            extra_data=data.get("extra_data"),
        )
        
        if success:
            return jsonify({
                "success": True,
                "event_order_id": event_order_id,
                "ticket_id": ticket_id,
                "status": "registered",
            }), 200
        else:
            # Sprawdź czy uczestnik istnieje
            participant = get_participant_by_ticket(event_order_id, ticket_id)
            if not participant:
                return jsonify({"error": "Nie znaleziono uczestnika dla podanego biletu"}), 404
            return jsonify({"error": "Nie udało się zaktualizować danych uczestnika"}), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/participants/<event_order_id>/pending', methods=['GET'])
@require_api_key
def get_pending_participants_endpoint(event_order_id: str):
    """
    Pobiera uczestników ze statusem 'pending' (do wypełnienia).
    
    Response:
    {
        "event_order_id": "...",
        "pending_count": 2,
        "participants": [...]
    }
    """
    try:
        from pg_storage import get_pending_participants
        
        participants = get_pending_participants(event_order_id)
        
        return jsonify({
            "event_order_id": event_order_id,
            "pending_count": len(participants),
            "participants": participants,
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/participants/<int:participant_id>/status', methods=['POST'])
def update_participant_status_api(participant_id: int):
    """
    Aktualizuje status uczestnika po ID.
    Używane przez panel admina.
    
    Body (JSON):
    {
        "status": "registered|emailed|checked_in|cancelled"
    }
    
    Response:
    {
        "success": true,
        "participant_id": 123,
        "status": "emailed"
    }
    """
    # Sprawdź sesję admina
    if not session.get("admin_user_id"):
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        from pg_storage import update_participant_status
        
        data = request.get_json(silent=True) or {}
        new_status = data.get("status", "")
        
        if new_status not in ("registered", "emailed", "checked_in", "cancelled"):
            return jsonify({"error": "Invalid status"}), 400
        
        success = update_participant_status(participant_id, new_status)
        
        if success:
            return jsonify({
                "success": True,
                "participant_id": participant_id,
                "status": new_status,
            }), 200
        else:
            return jsonify({
                "success": False,
                "error": "Participant not found or update failed",
            }), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# ORDER STATUS CHANGES (API)
# ---------------------------------------------------------------------------

ZOHO_FLOW_ORDER_CANCEL_WEBHOOK = "https://flow.zoho.eu/20101689330/flow/webhook/incoming?zapikey=1001.aa6aef3799c7e535d8338b7a98b2ea12.9dee6ba3ef5763bce1f3bba145a0261f&isdebug=false"


@app.route('/api/orders/<event_order_id>/cancel', methods=['POST'])
def api_cancel_order(event_order_id: str):
    """
    Anuluje zamówienie i wysyła webhook do Zoho Flow.
    
    Wymaga aktywnej sesji admin (sprawdza session['admin_v2_user']).
    
    Response:
    {
        "success": true,
        "event_order_id": "...",
        "status": "cancelled",
        "webhook_sent": true
    }
    """
    try:
        from pg_storage import get_order, update_order_status, get_event
        
        # Sprawdź czy użytkownik jest zalogowany jako admin
        admin_user = session.get("admin_v2_user")
        if not admin_user:
            return jsonify({"success": False, "error": "Wymagane zalogowanie"}), 401
        
        # Pobierz zamówienie
        order = get_order(event_order_id)
        if not order:
            return jsonify({"success": False, "error": "Zamówienie nie znalezione"}), 404
        
        # Sprawdź czy można anulować
        current_status = order.get("status", "")
        if current_status in ("cancelled", "refunded"):
            return jsonify({"success": False, "error": f"Zamówienie już ma status: {current_status}"}), 400
        
        # Zaktualizuj status
        updated = update_order_status(event_order_id, "cancelled")
        if not updated:
            return jsonify({"success": False, "error": "Nie udało się zaktualizować statusu"}), 500
        
        # Pobierz dane eventu
        event_name = "Nieznane wydarzenie"
        try:
            event = get_event(order.get("event_id", ""))
            if event:
                event_name = event.get("event_name", event_name)
        except Exception:
            pass
        
        # Wyślij webhook do Zoho Flow
        webhook_sent = False
        webhook_error = None
        try:
            webhook_payload = {
                "order_id": event_order_id,
                "cancel_reason": "na życzenie",
                "event_order_id": event_order_id,
                "event_id": order.get("event_id", ""),
                "event_name": event_name,
                "purchaser_email": order.get("purchaser_email", ""),
                "purchaser_first_name": order.get("purchaser_first_name", ""),
                "purchaser_last_name": order.get("purchaser_last_name", ""),
                "purchaser_phone": order.get("purchaser_phone", ""),
                "total": float(order.get("total") or 0),
            }
            
            resp = requests.post(
                ZOHO_FLOW_ORDER_CANCEL_WEBHOOK,
                json=webhook_payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            webhook_sent = resp.status_code in (200, 201, 202)
            if not webhook_sent:
                webhook_error = f"HTTP {resp.status_code}: {resp.text[:100]}"
            print(f"[ORDER CANCEL] Webhook sent to Zoho Flow: {webhook_sent}, order={event_order_id}")
        except Exception as e:
            webhook_error = str(e)
            print(f"[ORDER CANCEL] Webhook error: {e}")
        
        # Zapisz audit log
        try:
            from pg_storage import insert_admin_audit_log
            insert_admin_audit_log(
                action="order_cancelled",
                admin_user_id=admin_user.get("id"),
                target_id=event_order_id,
                extra={"webhook_sent": webhook_sent, "webhook_error": webhook_error},
                ip=request.remote_addr,
            )
        except Exception as audit_err:
            print(f"[ORDER CANCEL] Audit log error: {audit_err}")
        
        return jsonify({
            "success": True,
            "event_order_id": event_order_id,
            "status": "cancelled",
            "webhook_sent": webhook_sent,
            "webhook_error": webhook_error,
        }), 200
        
    except Exception as e:
        print(f"[ORDER CANCEL] Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/orders/<event_order_id>/delete', methods=['POST'])
def api_delete_order(event_order_id: str):
    """
    Usuwa zamówienie i wszystkie powiązane dane (nieodwracalne!).
    
    Tylko dla zalogowanych adminów.
    
    Response:
    {
        "success": true,
        "deleted": { "participants": 2, "orders": 1, ... }
    }
    """
    try:
        from pg_storage import delete_order, get_order, insert_admin_audit_log
        
        # Sprawdź czy użytkownik jest zalogowany jako admin
        admin_user = session.get("admin_v2_user")
        if not admin_user:
            return jsonify({"success": False, "error": "Wymagane zalogowanie"}), 401
        
        # Pobierz dane zamówienia przed usunięciem (do audytu)
        order = get_order(event_order_id)
        if not order:
            return jsonify({"success": False, "error": "Zamówienie nie znalezione"}), 404
        
        # Usuń zamówienie
        deleted = delete_order(event_order_id)
        
        if "error" in deleted:
            return jsonify({"success": False, "error": deleted["error"]}), 500
        
        # Zapisz audit log
        try:
            insert_admin_audit_log(
                action="order_deleted",
                admin_user_id=admin_user.get("id"),
                target_id=event_order_id,
                extra={
                    "deleted": deleted,
                    "purchaser_email": order.get("purchaser_email"),
                    "total": float(order.get("total") or 0),
                },
                ip=request.remote_addr,
            )
        except Exception as audit_err:
            print(f"[ORDER DELETE] Audit log error: {audit_err}")
        
        print(f"[ORDER DELETE] Order {event_order_id} deleted by {admin_user.get('email')}")
        
        return jsonify({
            "success": True,
            "event_order_id": event_order_id,
            "deleted": deleted,
        }), 200
        
    except Exception as e:
        print(f"[ORDER DELETE] Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# EVENT UPDATE (API)
# ---------------------------------------------------------------------------

ZOHO_FLOW_EVENT_UPDATE_WEBHOOK = "https://flow.zoho.eu/20101689330/flow/webhook/incoming?zapikey=1001.fd0397adf2d2daf0194fb08d80fd3530.3f05b43c8fad5bf3f6761b5aaef1cf2c&isdebug=false"


@app.route('/api/events/<event_id>/update', methods=['POST'])
def api_update_event(event_id: str):
    """
    Aktualizuje dane wydarzenia i wysyła webhook do Zoho Flow.
    
    Tylko dla zalogowanych adminów.
    
    Body (JSON):
    {
        "event_name": "...",        // opcjonalnie
        "status": "...",            // opcjonalnie
        "notes": "...",             // opcjonalnie
        "is_active": true/false,    // opcjonalnie
        "data": {...}               // opcjonalnie - dodatkowe dane
    }
    
    Returns:
    {
        "success": true,
        "event_id": "...",
        "updated_fields": [...],
        "webhook_sent": true
    }
    """
    try:
        from pg_storage import get_event, upsert_event, insert_admin_audit_log
        
        # Sprawdź czy użytkownik jest zalogowany jako admin
        admin_user = session.get("admin_v2_user")
        if not admin_user:
            return jsonify({"success": False, "error": "Wymagane zalogowanie"}), 401
        
        # Pobierz aktualne dane wydarzenia
        event = get_event(event_id)
        if not event:
            return jsonify({"success": False, "error": "Wydarzenie nie znalezione"}), 404
        
        # Pobierz dane do aktualizacji z request body
        req_data = request.get_json() or {}
        
        # Zbierz pola do aktualizacji
        updated_fields = []
        
        # Aktualizuj event_name
        new_event_name = req_data.get("event_name", event.get("event_name", ""))
        if req_data.get("event_name") and req_data.get("event_name") != event.get("event_name"):
            updated_fields.append("event_name")
        
        # Aktualizuj status
        new_status = req_data.get("status", event.get("status", ""))
        if req_data.get("status") and req_data.get("status") != event.get("status"):
            updated_fields.append("status")
        
        # Aktualizuj notes
        new_notes = req_data.get("notes", event.get("notes", ""))
        if "notes" in req_data and req_data.get("notes") != event.get("notes"):
            updated_fields.append("notes")
        
        # Aktualizuj is_active
        new_is_active = req_data.get("is_active", event.get("is_active", True))
        if "is_active" in req_data and req_data.get("is_active") != event.get("is_active"):
            updated_fields.append("is_active")
        
        # Aktualizuj data (merge z istniejącymi danymi)
        current_data = event.get("data") or {}
        new_data = current_data.copy()
        if req_data.get("data"):
            new_data.update(req_data.get("data"))
            updated_fields.append("data")
        
        # Jeśli nie ma zmian
        if not updated_fields:
            return jsonify({
                "success": True,
                "event_id": event_id,
                "message": "Brak zmian do zapisania",
                "updated_fields": [],
                "webhook_sent": False,
            }), 200
        
        # Zapisz zmiany w bazie
        upsert_event(
            event_id=event_id,
            event_name=new_event_name,
            status=new_status,
            notes=new_notes,
            data=new_data,
            is_active=new_is_active,
        )
        
        # Wyślij webhook do Zoho Flow
        webhook_sent = False
        webhook_error = None
        try:
            # Pobierz daty i opisy z event data
            event_start_date = new_data.get("event_date_time") or ""  # format: 2026-01-09T00:00:00
            event_end_date = new_data.get("event_end_date_time") or ""  # format: 2026-01-09T00:00:00
            event_description = new_data.get("event_description") or ""
            event_summary = new_data.get("event_summary") or new_data.get("event_day_text_1") or ""
            
            webhook_payload = {
                "event_id": event_id,
                "event_name": new_event_name,
                "status": new_status,
                "notes": new_notes,
                "is_active": new_is_active,
                "start_date": event_start_date,
                "end_date": event_end_date,
                "event_description": event_description,
                "event_summary": event_summary,
                "data": new_data,
                "updated_fields": updated_fields,
                "updated_by": admin_user.get("email", "unknown"),
            }
            
            resp = requests.post(
                ZOHO_FLOW_EVENT_UPDATE_WEBHOOK,
                json=webhook_payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            webhook_sent = resp.status_code in (200, 201, 202)
            if not webhook_sent:
                webhook_error = f"HTTP {resp.status_code}: {resp.text[:100]}"
            print(f"[EVENT UPDATE] Webhook sent to Zoho Flow: {webhook_sent}, event={event_id}, fields={updated_fields}")
        except Exception as e:
            webhook_error = str(e)
            print(f"[EVENT UPDATE] Webhook error: {e}")
        
        # Zapisz audit log
        try:
            insert_admin_audit_log(
                action="event_updated",
                admin_user_id=admin_user.get("id"),
                target_id=event_id,
                extra={
                    "updated_fields": updated_fields,
                    "webhook_sent": webhook_sent,
                    "webhook_error": webhook_error,
                },
                ip=request.remote_addr,
            )
        except Exception as audit_err:
            print(f"[EVENT UPDATE] Audit log error: {audit_err}")
        
        return jsonify({
            "success": True,
            "event_id": event_id,
            "updated_fields": updated_fields,
            "webhook_sent": webhook_sent,
            "webhook_error": webhook_error,
        }), 200
        
    except Exception as e:
        print(f"[EVENT UPDATE] Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# STRIPE INTEGRATION
# ---------------------------------------------------------------------------


@app.route('/api/stripe/status', methods=['GET'])
@require_api_key
def stripe_status():
    """
    Diagnostyka Stripe - sprawdza czy klucz API jest skonfigurowany.
    """
    try:
        from stripe_integration import _get_stripe_status
        return jsonify(_get_stripe_status())
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/stripe/create-session', methods=['POST'])
@require_api_key
def stripe_create_session():
    """
    Tworzy Stripe Checkout Session.
    
    Headers:
        X-API-Key: klucz API (MAKE_RENDER_API_KEY)
    
    Body (JSON):
    {
        "event_order_id": "...",
        "amount": 299.00,  // kwota w PLN (zostanie przeliczona na grosze)
        "currency": "PLN",
        "customer_email": "...",
        "description": "...",
        "success_url": "https://...",
        "cancel_url": "https://...",
        "metadata": {...}
    }
    
    Response:
    {
        "status": "ok",
        "checkout_session_id": "cs_...",
        "url": "https://checkout.stripe.com/...",
        "amount_cents": 29900,
        "currency": "PLN"
    }
    """
    try:
        from stripe_integration import create_checkout_session, is_stripe_configured
        
        if not is_stripe_configured():
            return jsonify({
                'status': 'error',
                'error': 'Stripe nie jest skonfigurowany (brak STRIPE_RENDER_API_KEY)'
            }), 500
        
        body = request.get_json(silent=True) or {}
        
        event_order_id = (body.get('event_order_id') or '').strip()
        if not event_order_id:
            return jsonify({
                'status': 'error',
                'error': 'Wymagany parametr: event_order_id'
            }), 400
        
        # Kwota - przyjmujemy w PLN, przeliczamy na grosze
        amount = body.get('amount', 0)
        try:
            amount_cents = int(float(amount) * 100)
        except (ValueError, TypeError):
            return jsonify({
                'status': 'error',
                'error': 'Nieprawidłowa kwota (amount)'
            }), 400
        
        if amount_cents <= 0:
            return jsonify({
                'status': 'error',
                'error': 'Kwota musi być większa od 0'
            }), 400
        
        currency = (body.get('currency') or 'PLN').upper()
        customer_email = (body.get('customer_email') or '').strip() or None
        description = (body.get('description') or '').strip() or None
        success_url = (body.get('success_url') or '').strip()
        cancel_url = (body.get('cancel_url') or '').strip()
        metadata = body.get('metadata') or {}
        
        result, error = create_checkout_session(
            event_order_id=event_order_id,
            amount_cents=amount_cents,
            currency=currency.lower(),
            customer_email=customer_email,
            description=description,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata,
        )
        
        if error:
            return jsonify({
                'status': 'error',
                'error': error
            }), 400
        
        return jsonify({
            'status': 'ok',
            **result
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/stripe/webhook', methods=['POST'])
def stripe_webhook():
    """
    Webhook Stripe - odbiera eventy o płatnościach.
    
    UWAGA: Ten endpoint NIE wymaga X-API-Key!
    Zamiast tego weryfikuje podpis Stripe (header Stripe-Signature).
    
    Obsługiwane eventy:
    - checkout.session.completed - płatność zakończona sukcesem
    
    Response:
    {
        "status": "ok",
        "order_id": "...",
        "order_status": "paid",
        "mail_tasks": [...],
        "wfirma_action": {...}
    }
    """
    try:
        from stripe_integration import verify_webhook_signature, process_webhook_event
        
        # Pobierz raw body (potrzebne do weryfikacji podpisu)
        payload = request.get_data()
        signature = request.headers.get('Stripe-Signature', '')
        
        # Weryfikuj podpis (lub wykryj brak konfiguracji)
        is_valid, error = verify_webhook_signature(payload, signature)
        if not is_valid:
            status_code = 400
            if error and ("missing" in error.lower() or "not configured" in error.lower() or "secret" in error.lower()):
                status_code = 503
            return jsonify({
                'status': 'error',
                'error': error or 'Invalid signature'
            }), status_code
        
        # Parsuj JSON
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return jsonify({
                'status': 'error',
                'error': 'Invalid JSON payload'
            }), 400
        
        event_type = event.get('type', '')
        event_data = event.get('data', {}).get('object', {})
        try:
            meta = event_data.get("metadata") or {}
            order_id_dbg = meta.get("event_order_id") or event_data.get("client_reference_id") or ""
            print(f"[STRIPE WEBHOOK] event_type={event_type}, order={order_id_dbg}")
        except Exception:
            pass
        
        # Przetwórz event
        result = process_webhook_event(event_type, event_data)

        # Upewnij się, że zwracany JSON nie zawiera Decimal itp.
        try:
            from decimal import Decimal
            def _json_safe(v):
                if isinstance(v, Decimal):
                    return float(v)
                if isinstance(v, dict):
                    return {k: _json_safe(x) for k, x in v.items()}
                if isinstance(v, list):
                    return [_json_safe(x) for x in v]
                return v
            result = _json_safe(result)
        except Exception:
            pass
        
        # Stripe wymaga 200 OK nawet dla zignorowanych eventów
        try:
            return jsonify(result), 200
        except Exception as e:
            # Ostatnia deska ratunku: wymuś serializację (np. Decimal)
            print(f"[STRIPE WEBHOOK] jsonify error: {e}")
            try:
                safe = json.loads(json.dumps(result, default=str))
                return jsonify(safe), 200
            except Exception as e2:
                return jsonify({'status': 'error', 'error': str(e2)}), 200
        
    except Exception as e:
        # Bezpieczeństwo/niezawodność: zwróć 500, żeby Stripe mógł ponowić event przy awariach.
        print(f"[STRIPE WEBHOOK ERROR] {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


# ---------------------------------------------------------------------------
# STRIPE SANDBOX (testowe endpointy)
# ---------------------------------------------------------------------------


@app.route('/api/stripe/sandbox/status', methods=['GET'])
@require_api_key
def stripe_sandbox_status():
    """
    Diagnostyka Stripe SANDBOX - sprawdza czy klucz testowy jest skonfigurowany.
    """
    try:
        from stripe_integration import _get_stripe_status
        return jsonify(_get_stripe_status(sandbox=True))
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/stripe/sandbox/create-session', methods=['POST'])
@require_api_key
def stripe_sandbox_create_session():
    """
    Tworzy Stripe Checkout Session w trybie SANDBOX (testowym).
    
    Używa STRIPE_RENDER_API_KEY_SANDBOX zamiast produkcyjnego klucza.
    Idealne do testowania bez prawdziwych płatności.
    
    Headers:
        X-API-Key: klucz API (MAKE_RENDER_API_KEY)
    
    Body (JSON):
    {
        "event_order_id": "...",
        "amount": 299.00,
        "currency": "PLN",
        "customer_email": "...",
        "description": "...",
        "success_url": "https://...",
        "cancel_url": "https://..."
    }
    
    Response:
    {
        "status": "ok",
        "mode": "sandbox",
        "checkout_session_id": "cs_test_...",
        "url": "https://checkout.stripe.com/c/pay/cs_test_..."
    }
    """
    try:
        from stripe_integration import create_checkout_session, is_stripe_configured
        
        if not is_stripe_configured(sandbox=True):
            return jsonify({
                'status': 'error',
                'error': 'Stripe sandbox nie jest skonfigurowany (brak STRIPE_RENDER_API_KEY_SANDBOX)'
            }), 500
        
        body = request.get_json(silent=True) or {}
        
        event_order_id = (body.get('event_order_id') or '').strip()
        if not event_order_id:
            return jsonify({
                'status': 'error',
                'error': 'Wymagany parametr: event_order_id'
            }), 400
        
        # Kwota - przyjmujemy w PLN, przeliczamy na grosze
        amount = body.get('amount', 0)
        try:
            amount_cents = int(float(amount) * 100)
        except (ValueError, TypeError):
            return jsonify({
                'status': 'error',
                'error': 'Nieprawidłowa kwota (amount)'
            }), 400
        
        if amount_cents <= 0:
            return jsonify({
                'status': 'error',
                'error': 'Kwota musi być większa od 0'
            }), 400
        
        currency = (body.get('currency') or 'PLN').upper()
        customer_email = (body.get('customer_email') or '').strip() or None
        description = (body.get('description') or '').strip() or None
        success_url = (body.get('success_url') or '').strip()
        cancel_url = (body.get('cancel_url') or '').strip()
        metadata = body.get('metadata') or {}
        
        result, error = create_checkout_session(
            event_order_id=event_order_id,
            amount_cents=amount_cents,
            currency=currency.lower(),
            customer_email=customer_email,
            description=description,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata,
            sandbox=True,  # <-- SANDBOX MODE
        )
        
        if error:
            return jsonify({
                'status': 'error',
                'error': error
            }), 400
        
        return jsonify({
            'status': 'ok',
            'mode': 'sandbox',
            **result
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/stripe/sandbox/webhook', methods=['POST'])
def stripe_sandbox_webhook():
    """
    Webhook Stripe SANDBOX - odbiera testowe eventy o płatnościach.
    
    Używa STRIPE_SANDBOX_WEBHOOK_SECRET do weryfikacji podpisu.
    """
    try:
        from stripe_integration import verify_webhook_signature, process_webhook_event
        
        payload = request.get_data()
        signature = request.headers.get('Stripe-Signature', '')
        
        # Weryfikuj podpis (sandbox)
        is_valid, error = verify_webhook_signature(payload, signature, sandbox=True)
        if not is_valid:
            status_code = 400
            if error and ("missing" in error.lower() or "not configured" in error.lower() or "secret" in error.lower()):
                status_code = 503
            return jsonify({
                'status': 'error',
                'error': error or 'Invalid signature'
            }), status_code
        
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return jsonify({
                'status': 'error',
                'error': 'Invalid JSON payload'
            }), 400
        
        event_type = event.get('type', '')
        event_data = event.get('data', {}).get('object', {})
        try:
            meta = event_data.get("metadata") or {}
            order_id_dbg = meta.get("event_order_id") or event_data.get("client_reference_id") or ""
            print(f"[STRIPE SANDBOX WEBHOOK] event_type={event_type}, order={order_id_dbg}")
        except Exception:
            pass
        
        result = process_webhook_event(event_type, event_data)
        result['mode'] = 'sandbox'
        try:
            print(f"[STRIPE SANDBOX WEBHOOK] result_status={(result or {}).get('status')}, order_id={(result or {}).get('order_id')}")
        except Exception:
            pass

        # Upewnij się, że zwracany JSON nie zawiera Decimal itp.
        try:
            from decimal import Decimal
            def _json_safe(v):
                if isinstance(v, Decimal):
                    return float(v)
                if isinstance(v, dict):
                    return {k: _json_safe(x) for k, x in v.items()}
                if isinstance(v, list):
                    return [_json_safe(x) for x in v]
                return v
            result = _json_safe(result)
        except Exception:
            pass
        
        try:
            return jsonify(result), 200
        except Exception as e:
            print(f"[STRIPE SANDBOX WEBHOOK] jsonify error: {e}")
            try:
                safe = json.loads(json.dumps(result, default=str))
                return jsonify(safe), 200
            except Exception as e2:
                return jsonify({'status': 'error', 'error': str(e2)}), 200

    except Exception as e:
        # Niezawodność: 500 -> Stripe może ponowić event (także w sandbox).
        print(f"[STRIPE SANDBOX WEBHOOK ERROR] {str(e)}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


# Start background monitors (after routes are defined)
try:
    start_wfirma_token_monitor()
except Exception as e:
    print(f"[TOKEN MONITOR] failed to start: {e}")

try:
    start_backstage_attendee_incomplete_monitor()
except Exception as e:
    print(f"[BACKSTAGE MONITOR] failed to start: {e}")


# ---------------------------------------------------------------------------
# MAIL TASKS API (dla Make.com)
# ---------------------------------------------------------------------------


@app.route('/api/mail-tasks', methods=['GET'])
@require_api_key
def list_mail_tasks():
    """
    Pobiera listę oczekujących maili do wysłania.
    Make.com może pollować ten endpoint żeby pobierać nowe taski.
    
    Headers:
        X-API-Key: klucz API (MAKE_RENDER_API_KEY)
    
    Query params:
        limit: max liczba tasków (domyślnie 50)
    
    Response:
    {
        "status": "ok",
        "count": 3,
        "mail_tasks": [
            {
                "id": 123,
                "event_order_id": "...",
                "direction": "purchaser",
                "template": "payment_confirmation",
                "to": "klient@email.com",
                "subject": "Potwierdzenie płatności",
                "data": {...},
                "created_at": "..."
            }
        ]
    }
    """
    try:
        from pg_storage import list_pending_mail_tasks
        
        limit = int(request.args.get('limit', 50))
        if limit < 1:
            limit = 1
        if limit > 200:
            limit = 200
        
        tasks = list_pending_mail_tasks(limit=limit)
        
        # Formatuj odpowiedź w strukturze dla Make.com
        formatted_tasks = []
        for t in tasks:
            formatted_tasks.append({
                "id": t.get("id"),
                "event_order_id": t.get("event_order_id"),
                "direction": t.get("direction"),
                "template": t.get("template_key"),
                "to": t.get("to_email"),
                "subject": t.get("subject"),
                "data": t.get("data") or {},
                "created_at": str(t.get("created_at", "")),
            })
        
        return jsonify({
            "status": "ok",
            "count": len(formatted_tasks),
            "mail_tasks": formatted_tasks,
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/mail-tasks/<int:mail_id>', methods=['GET'])
@require_api_key
def get_mail_task_detail(mail_id: int):
    """
    Pobiera szczegóły pojedynczego mail taska.
    
    Headers:
        X-API-Key: klucz API (MAKE_RENDER_API_KEY)
    
    Response:
    {
        "status": "ok",
        "mail_task": {
            "id": 123,
            "event_order_id": "...",
            "direction": "purchaser",
            "template": "payment_confirmation",
            "to": "klient@email.com",
            "subject": "Potwierdzenie płatności",
            "data": {...},
            "status": "queued",
            "created_at": "..."
        }
    }
    """
    try:
        from pg_storage import get_mail_task
        
        task = get_mail_task(mail_id)
        if not task:
            return jsonify({
                'status': 'error',
                'error': 'Mail task nie znaleziony'
            }), 404
        
        return jsonify({
            "status": "ok",
            "mail_task": {
                "id": task.get("id"),
                "event_order_id": task.get("event_order_id"),
                "direction": task.get("direction"),
                "template": task.get("template_key"),
                "to": task.get("to_email"),
                "subject": task.get("subject"),
                "data": task.get("data") or {},
                "status": task.get("status"),
                "error": task.get("error"),
                "created_at": str(task.get("created_at", "")),
            },
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/mail-tasks/<int:mail_id>/mark-sent', methods=['POST'])
@require_api_key
def mark_mail_task_sent(mail_id: int):
    """
    Oznacza mail task jako wysłany (lub nieudany).
    Make.com wywołuje ten endpoint po wysłaniu maila.
    
    Headers:
        X-API-Key: klucz API (MAKE_RENDER_API_KEY)
    
    Body (JSON, opcjonalnie):
    {
        "error": "Treść błędu jeśli wysyłka nieudana"
    }
    
    Response:
    {
        "status": "ok",
        "mail_task": {
            "id": 123,
            "status": "sent"
        }
    }
    """
    try:
        from pg_storage import mark_mail_sent, get_mail_task
        
        # Sprawdź czy task istnieje
        task = get_mail_task(mail_id)
        if not task:
            return jsonify({
                'status': 'error',
                'error': 'Mail task nie znaleziony'
            }), 404
        
        # Pobierz opcjonalny błąd z body
        body = request.get_json(silent=True) or {}
        error = (body.get('error') or '').strip() or None
        
        # Oznacz jako wysłany/nieudany
        updated = mark_mail_sent(mail_id, error=error)
        
        return jsonify({
            "status": "ok",
            "mail_task": {
                "id": updated.get("id") if updated else mail_id,
                "status": updated.get("status") if updated else ("failed" if error else "sent"),
                "error": updated.get("error") if updated else error,
            },
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


# ---------------------------------------------------------------------------
# EMAIL API - bezpośrednia wysyłka maili przez SMTP
# ---------------------------------------------------------------------------


@app.route('/api/email/status', methods=['GET'])
def email_status():
    """
    Sprawdza status konfiguracji email SMTP.
    Publiczny endpoint (bez auth) - pokazuje tylko czy skonfigurowane.
    """
    try:
        from email_sender import get_email_status
        return jsonify(get_email_status()), 200
    except Exception as e:
        return jsonify({
            'error': str(e),
            'configured': False,
        }), 500


@app.route('/api/email/test', methods=['POST'])
@require_api_key
def email_test():
    """
    Wysyła testowy email.
    
    Body (opcjonalne):
    {
        "to": "adres@email.pl"  // domyślnie wysyła do EMAIL_ADDRESS
    }
    """
    try:
        from email_sender import send_test_email
        
        data = request.get_json(force=True, silent=True) or {}
        to_email = data.get("to")
        
        result = send_test_email(to_email)
        
        status_code = 200 if result.get("success") else 500
        return jsonify(result), status_code
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/email/send', methods=['POST'])
@require_api_key
def email_send():
    """
    Wysyła email z podanymi parametrami.
    
    Body:
    {
        "to": "adres@email.pl",
        "subject": "Temat",
        "body_html": "<html>...</html>",
        "body_text": "Opcjonalny tekst",  // opcjonalne
        "reply_to": "reply@email.pl"  // opcjonalne
    }
    """
    try:
        from email_sender import send_email
        
        data = request.get_json(force=True)
        if not data:
            return jsonify({'success': False, 'error': 'Brak body JSON'}), 400
        
        to_email = data.get("to")
        subject = data.get("subject")
        body_html = data.get("body_html")
        
        if not to_email or not subject or not body_html:
            return jsonify({
                'success': False,
                'error': 'Wymagane pola: to, subject, body_html'
            }), 400
        
        result = send_email(
            to_email=to_email,
            subject=subject,
            body_html=body_html,
            body_text=data.get("body_text"),
            reply_to=data.get("reply_to"),
        )
        
        status_code = 200 if result.get("success") else 500
        return jsonify(result), status_code
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/email/stripe-test', methods=['POST'])
@require_api_key
def email_stripe_test():
    """
    Wysyła testowy email z linkiem do płatności Stripe.
    
    Body:
    {
        "to": "adres@email.pl",
        "template_type": "personal" | "nip_valid" | "nip_invalid",
        "event_name": "Nazwa eventu",
        "purchaser_first_name": "Imię",
        "purchaser_last_name": "Nazwisko",
        "total_gross": 1234.56,
        "stripe_payment_url": "https://checkout.stripe.com/...",
        "purchaser_nip": "1234567890",  // opcjonalne
        "gus_data": {...}  // opcjonalne, dla nip_valid
    }
    """
    try:
        from email_sender import send_email
        from email_templates import render_stripe_payment_email
        
        data = request.get_json(force=True)
        if not data:
            return jsonify({'success': False, 'error': 'Brak body JSON'}), 400
        
        to_email = data.get("to")
        template_type = data.get("template_type", "personal")
        event_name = data.get("event_name", "Testowe Wydarzenie")
        
        if not to_email:
            return jsonify({'success': False, 'error': 'Wymagane pole: to'}), 400
        
        # Renderuj HTML
        body_html = render_stripe_payment_email(
            template_type=template_type,
            event_name=event_name,
            purchaser_first_name=data.get("purchaser_first_name", "Test"),
            purchaser_last_name=data.get("purchaser_last_name", "User"),
            purchaser_email=to_email,
            purchaser_phone=data.get("purchaser_phone", "+48 000 000 000"),
            purchaser_nip=data.get("purchaser_nip"),
            total_gross=float(data.get("total_gross", 123.00)),
            stripe_payment_url=data.get("stripe_payment_url", "https://example.com/test-payment"),
            event_config=data.get("event_config"),
            tickets=data.get("tickets", [{"name": "Bilet testowy", "quantity": 1, "price": 100.0}]),
            gus_data=data.get("gus_data"),
        )
        
        subject = f"Link do płatności – {event_name}"
        
        result = send_email(
            to_email=to_email,
            subject=subject,
            body_html=body_html,
        )
        
        status_code = 200 if result.get("success") else 500
        return jsonify(result), status_code
        
    except Exception as e:
        import traceback
        return jsonify({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500


@app.route('/api/email/confirm-sent', methods=['POST'])
@require_api_key
def email_confirm_sent():
    """
    Callback z Make.com - potwierdza że email został wysłany.
    
    Body:
    {
        "event_order_id": "24311000000805010",
        "status": "sent" | "failed",
        "to": "email@example.com",
        "direction": "purchaser" | "internal" | "participant" (opcjonalnie, domyślnie purchaser),
        "mail_id": 123 (opcjonalnie - jeśli podane, aktualizuje po ID),
        "message_id": "opcjonalnie - ID z Make/SMTP",
        "error": "opcjonalnie - komunikat błędu"
    }
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        
        event_order_id = data.get("event_order_id")
        status = data.get("status", "sent")
        to_email = data.get("to", "")
        direction = data.get("direction", "purchaser")
        mail_id = data.get("mail_id")
        message_id = data.get("message_id", "")
        error = data.get("error", "")
        
        print(f"[EMAIL CALLBACK] order={event_order_id}, status={status}, to={to_email}, direction={direction}, mail_id={mail_id}")
        
        if not event_order_id:
            return jsonify({
                'success': False,
                'error': 'Brak event_order_id'
            }), 400
        
        # Zaktualizuj mail_log w bazie (zgodnie ze schematem w pg_storage.py)
        try:
            from pg_storage import _with_conn, _put_conn
            pool, conn = _with_conn()
            cur = conn.cursor()

            # Normalizacja statusu z Make
            status_in = (status or "").lower().strip()
            if status_in in ("sent", "ok", "success", "delivered"):
                status_db = "sent"
            elif status_in in ("failed", "error", "fail"):
                status_db = "failed"
            else:
                status_db = status_in or "sent"

            # Aktualizuj mail_log - priorytet: mail_id > (event_order_id + direction)
            if mail_id:
                # Aktualizuj po mail_id (najdokładniejsze)
                cur.execute("""
                    UPDATE mail_log
                    SET status = %s, error = %s
                    WHERE id = %s AND status = 'queued'
                """, (status_db, (error or None), int(mail_id)))
            else:
                # Fallback: znajdź ostatni queued rekord dla order + direction
                cur.execute("""
                    UPDATE mail_log
                    SET status = %s,
                        error = %s
                    WHERE id = (
                        SELECT id
                        FROM mail_log
                        WHERE event_order_id = %s
                          AND direction = %s
                          AND status = 'queued'
                          AND (%s = '' OR to_email = %s)
                        ORDER BY id DESC
                        LIMIT 1
                    )
                """, (
                    status_db,
                    (error or None),
                    event_order_id,
                    direction,
                    to_email or "",
                    to_email or "",
                ))
            
            rows_updated = cur.rowcount
            conn.commit()
            cur.close()
            _put_conn(pool, conn)
            
            print(f"[EMAIL CALLBACK] Updated {rows_updated} mail_log rows for order {event_order_id}")
            
        except Exception as db_err:
            print(f"[EMAIL CALLBACK] DB error: {db_err}")
        
        return jsonify({
            'success': True,
            'message': f'Email status updated to {status}',
            'event_order_id': event_order_id,
            'status': status,
        }), 200
        
    except Exception as e:
        print(f"[EMAIL CALLBACK] Error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/auth')
def auth():
    """
    Rozpocznij autoryzację OAuth 2.0.
    Parametr ?company=md lub ?company=test określa dla której firmy autoryzować.
    """
    # Pobierz company z query string
    company = (request.args.get('company') or DEFAULT_COMPANY).lower().strip()
    if company not in SUPPORTED_COMPANIES:
        return jsonify({
            'error': f'Nieobsługiwana firma: {company}',
            'supported': SUPPORTED_COMPANIES,
            'usage': '/auth?company=md lub /auth?company=test'
        }), 400
    
    config = get_company_config(company)
    client_id = config['client_id']
    redirect_uri = config['redirect_uri']
    
    if not client_id:
        return jsonify({
            'error': f'CLIENT_ID nie jest ustawiony dla firmy {company.upper()}',
            'expected_env': f'{config["prefix"]}CLIENT_ID'
        }), 500
    
    # WYMAGANE: redirect_uri musi być ustawiony per firma (bez fallbacków!)
    if not redirect_uri:
        return jsonify({
            'error': f'REDIRECT_URI nie jest ustawiony dla firmy {company.upper()}',
            'expected_env': f'{config["prefix"]}REDIRECT_URI',
            'hint': f'Ustaw zmienną {config["prefix"]}REDIRECT_URI w ENV (np. https://your-app.onrender.com/callback)'
        }), 500

    # Wygeneruj i zapisz state dla ręcznego /auth -> /callback
    try:
        import secrets as _secrets
        from pg_storage import save_oauth_state
        oauth_state = _secrets.token_urlsafe(16)
        save_res = save_oauth_state(oauth_state, company)
        if not save_res.get("ok"):
            return jsonify({
                'error': 'Nie udało się zapisać state OAuth',
                'message': save_res.get("error") or "unknown",
                'company': company
            }), 500
    except Exception as e:
        return jsonify({
            'error': 'Nie udało się wygenerować state OAuth',
            'message': str(e),
            'company': company
        }), 500
    
    # Pobierz SCOPES dla danej firmy
    scopes = get_scopes_for_company(company)
    scope_str = " ".join(scopes)
    
    # WAŻNE: Używamy parametru 'state' do przekazania company
    # redirect_uri musi być DOKŁADNIE taki jak zarejestrowany w wFirma!
    auth_url = (
        "https://wfirma.pl/oauth2/auth?"
        f"response_type=code&"
        f"client_id={client_id}&"
        f"scope={quote(scope_str)}&"
        f"redirect_uri={quote(redirect_uri, safe='')}&"
        f"state={oauth_state}"  # state jest zwracany bez zmian w callbacku
    )
    
    print(f"[AUTH] Rozpoczynam autoryzację dla firmy: {company.upper()}")
    print(f"[AUTH] Client ID: {client_id[:10]}...")
    print(f"[AUTH] Redirect URI: {redirect_uri}")
    print(f"[AUTH] State (company): {company}")
    print(f"[AUTH] Scopes count: {len(scopes)}")
    
    return redirect(auth_url)

@app.route('/callback')
def callback():
    """
    Odbierz kod autoryzacyjny i wymień na token.
    Parametr 'state' (zwrócony przez wFirma) określa dla której firmy zapisać tokeny.
    """
    code = request.args.get('code')
    error = request.args.get('error')
    # WAŻNE: company jest pobierane z zapisanej mapy state (nie z query param!)
    state = request.args.get('state', '')
    company = None
    state_ok = False
    try:
        from pg_storage import consume_oauth_state
        res = consume_oauth_state(state, max_age_seconds=900)
        state_ok = bool(res.get("ok"))
        if state_ok:
            company = (res.get("company") or "").lower().strip()
    except Exception as e:
        return jsonify({
            'error': 'Błąd weryfikacji state OAuth',
            'message': str(e),
        }), 500

    if not state_ok or not company:
        return jsonify({
            'error': 'Nieprawidłowy lub wygasły state OAuth',
            'message': 'Rozpocznij autoryzację od /auth',
        }), 403

    if company not in SUPPORTED_COMPANIES:
        return jsonify({
            'error': f'Nieobsługiwana firma: {company}',
            'supported': SUPPORTED_COMPANIES,
            'usage': '/auth?company=md lub /auth?company=test'
        }), 400
    config = get_company_config(company)
    redirect_uri = config['redirect_uri']
    
    try:
        import hashlib as _hh
        _state_fp = _hh.sha256(state.encode("utf-8")).hexdigest()[:8] if state else None
    except Exception:
        _state_fp = None
    print(f"[CALLBACK] Otrzymano callback, state_fp={_state_fp}, company={company.upper()}")
    
    if error:
        return jsonify({
            'error': 'Błąd autoryzacji',
            'details': error,
            'company': company
        }), 400
    
    if not code:
        return jsonify({'error': 'Brak kodu autoryzacyjnego', 'company': company}), 400
    
    # WYMAGANE: redirect_uri musi być ustawiony per firma (bez fallbacków!)
    if not redirect_uri:
        return jsonify({
            'error': f'REDIRECT_URI nie jest ustawiony dla firmy {company.upper()}',
            'expected_env': f'{config["prefix"]}REDIRECT_URI',
            'hint': f'Ustaw zmienną {config["prefix"]}REDIRECT_URI w ENV (np. https://your-app.onrender.com/callback)'
        }), 500
    
    # WAŻNE: redirect_uri musi być DOKŁADNIE taki jak w /auth (bez query params!)
    # Wymień kod na token używając credentials dla danej firmy
    token_url = "https://api2.wfirma.pl/oauth2/token?oauth_version=2"
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': config['client_id'],
        'client_secret': config['client_secret'],
        'redirect_uri': redirect_uri  # Musi być identyczny jak zarejestrowany w wFirma!
    }
    
    print(f"[CALLBACK] [{company.upper()}] Wymiana kodu na token...")
    print(f"[CALLBACK] [{company.upper()}] Client ID: {config['client_id'][:10] if config['client_id'] else 'BRAK'}...")
    print(f"[CALLBACK] [{company.upper()}] Redirect URI: {redirect_uri}")
    
    try:
        response = requests.post(token_url, data=data)
        if response.status_code != 200:
            return jsonify({
                'error': 'Błąd wymiany tokenu',
                'status': response.status_code,
                'details': response.text,
                'company': company
            }), 400
        
        token_data = response.json()
        expires_in = token_data.get('expires_in', 3600)
        access_token = token_data['access_token']
        refresh_token = token_data.get('refresh_token')
        
        # Zapisz token dla danej firmy (wraz z refresh_token)
        save_token(
            access_token,
            expires_in,
            refresh_token,
            company=company,
            refresh_token_source="manual_auth",
        )
        
        print(f"[CALLBACK] [{company.upper()}] ✓ Tokeny zapisane pomyślnie!")
        
        return jsonify({
            'message': f'Autoryzacja zakończona pomyślnie dla firmy {company.upper()}',
            'company': company,
            'token_valid_for': f"{expires_in} sekund",
            'expires_in': expires_in,
            'refresh_token_saved': bool(refresh_token),
            'refresh_token_valid_for': '30 dni',
            'env_prefix': config['prefix']
        })
    except Exception as e:
        return jsonify({
            'error': 'Błąd podczas wymiany tokenu',
            'details': str(e),
            'company': company
        }), 500

# ==================== ENDPOINTY API ====================

@app.route('/api/token/refresh')
def token_refresh():
    """
    Ręcznie odśwież access token używając refresh tokena.
    Parametry:
      ?company=md lub ?company=test
      ?force=true - wymusza refresh nawet jeśli token jest świeży (pomija cache)
    """
    company = (request.args.get('company') or DEFAULT_COMPANY).lower().strip()
    if company not in SUPPORTED_COMPANIES:
        company = DEFAULT_COMPANY
    
    # Parametr force - wymusza faktyczne wywołanie do wFirma API
    force = request.args.get('force', '').lower() in ('true', '1', 'yes')
    
    config = get_company_config(company)
    pg_company = config['pg_company']  # md_test -> md
    
    # Sprawdź refresh token w Postgres (jedyne źródło prawdy)
    pg_tok = None
    pg_error = None
    try:
        from pg_storage import get_wfirma_token
        pg_tok = get_wfirma_token(pg_company)
    except Exception as e:
        pg_error = str(e)
        print(f"[TOKEN REFRESH] Błąd odczytu z Postgres: {e}")
    
    # Jeśli Postgres nie odpowiada - 500, nie 400
    if pg_error:
        return jsonify({
            'error': 'Błąd połączenia z bazą danych',
            'details': pg_error,
            'company': company
        }), 500
    
    pg_refresh_exists = bool(pg_tok and pg_tok.get('refresh_token'))
    
    print(f"[TOKEN REFRESH] Próba odświeżenia tokenu dla firmy: {company.upper()} (force={force}) pg_company={pg_company}")
    print(f"[TOKEN REFRESH] Client ID exists: {bool(config['client_id'])}")
    print(f"[TOKEN REFRESH] Client Secret exists: {bool(config['client_secret'])}")
    print(f"[TOKEN REFRESH] Refresh Token exists (Postgres): {pg_refresh_exists}")
    
    if not config['client_id'] or not config['client_secret']:
        return jsonify({
            'error': f'Brak CLIENT_ID lub CLIENT_SECRET dla firmy {company.upper()}',
            'expected_vars': [f'{config["prefix"]}CLIENT_ID', f'{config["prefix"]}CLIENT_SECRET'],
            'company': company
        }), 400
    
    if not pg_refresh_exists:
        return jsonify({
            'error': f'Brak REFRESH_TOKEN w Postgres dla firmy {company.upper()}',
            'message': f'Przejdź do /auth?company={company} żeby uzyskać nowy token',
            'company': company,
            'pg_company': pg_company
        }), 400
    
    # Próba odświeżenia (skip_fresh_check=True gdy force=True)
    # Nie wymuszaj refresh_tokena z ENV – Postgres jest źródłem prawdy.
    new_token = refresh_access_token(company=company, skip_fresh_check=force)
    
    if new_token:
        return jsonify({
            'success': True,
            'message': f'Token odświeżony pomyślnie dla firmy {company.upper()}',
            'company': company,
            'access_token_preview': new_token[:20] + '...'
        })
    else:
        return jsonify({
            'error': 'Nie udało się odświeżyć tokenu',
            'message': 'Sprawdź logi na Render dla szczegółów błędu',
            'hint': f'Możliwe że refresh_token wygasł. Przejdź do /auth?company={company}',
            'company': company
        }), 500


@app.route('/api/token/status')
def token_status():
    """
    Sprawdź status tokenu i refresh tokena.
    Parametr ?company=md lub ?company=test określa dla której firmy sprawdzić.
    """
    company = (request.args.get('company') or DEFAULT_COMPANY).lower().strip()
    if company not in SUPPORTED_COMPANIES:
        company = DEFAULT_COMPANY
    
    status = get_token_status_for_company(company)
    
    # Sprawdź czy access token jest ważny
    token = load_token(silent=True, company=company)
    
    if token and status.get('access_token_valid'):
        status['status'] = 'valid'
        # Loguj ostrzeżenie o refresh tokenie jeśli jest
        if status.get('warning'):
            print(f"[WARNING] [{company.upper()}] {status['warning']}")
        return jsonify(status)
    
    status['status'] = 'invalid'
    status['message'] = f'Brak ważnego tokenu dla firmy {company.upper()}. Przejdź do /auth?company={company}'
    return jsonify(status)

@app.route('/api/wfirma/ping')
def wfirma_ping():
    """
    Health check wFirma API - sprawdza czy połączenie działa.
    Pobiera listę kontrahentów (limit 1) jako test.
    Parametr ?company=md lub ?company=test określa firmę.
    """
    import time
    start_time = time.time()
    
    company = (request.args.get('company') or DEFAULT_COMPANY).lower().strip()
    if company not in SUPPORTED_COMPANIES:
        company = DEFAULT_COMPANY
    
    config = get_company_config(company)
    company_name = config['company'].upper()
    
    # 1. Sprawdź czy mamy token
    token = load_token(silent=True, company=company)
    if not token:
        return jsonify({
            'ok': False,
            'company': company_name,
            'error': 'no_token',
            'message': f'Brak ważnego tokenu. Przejdź do /auth?company={company}',
            'elapsed_ms': int((time.time() - start_time) * 1000)
        }), 401
    
    # 2. Pobierz company_id (wymagane przez wFirma API) + lekki retry
    wfirma_company_id = wfirma_get_company_id(token)
    if not wfirma_company_id:
        for _ in range(2):
            time.sleep(0.4)
            wfirma_company_id = wfirma_get_company_id(token)
            if wfirma_company_id:
                break
    if not wfirma_company_id:
        return jsonify({
            'ok': False,
            'company': company_name,
            'error': 'no_company_id',
            'message': 'Nie udało się pobrać company_id z wFirma (token może być nieważny)',
            'elapsed_ms': int((time.time() - start_time) * 1000)
        }), 502
    
    # 3. Wykonaj testowe zapytanie do wFirma (pobierz 1 kontrahenta)
    try:
        test_url = f"https://api2.wfirma.pl/contractors/find?inputFormat=json&outputFormat=json&oauth_version=2&company_id={wfirma_company_id}"
        test_payload = {
            "contractors": [{
                "parameters": [
                    {"limit": 1}
                ]
            }]
        }
        headers = get_wfirma_headers(token)
        
        resp = requests.post(test_url, json=test_payload, headers=headers, timeout=10)
        elapsed_ms = int((time.time() - start_time) * 1000)
        
        if resp.status_code == 200:
            data = resp.json()
            # Sprawdź czy odpowiedź zawiera oczekiwaną strukturę
            # wFirma zwraca dict z kluczami "0", "1", "parameters" (nie list!)
            contractors = data.get('contractors', {})
            total = 0
            if isinstance(contractors, dict):
                params = contractors.get('parameters', {})
                total = params.get('total', 0)
            
            return jsonify({
                'ok': True,
                'company': company_name,
                'wfirma_company_id': wfirma_company_id,
                'wfirma_status': resp.status_code,
                'contractors_total': total,
                'message': 'Połączenie z wFirma działa poprawnie',
                'elapsed_ms': elapsed_ms
            })
        else:
            return jsonify({
                'ok': False,
                'company': company_name,
                'wfirma_company_id': wfirma_company_id,
                'error': 'wfirma_error',
                'wfirma_status': resp.status_code,
                'wfirma_response': resp.text[:500],
                'message': 'wFirma zwróciła błąd',
                'elapsed_ms': elapsed_ms
            }), 502
            
    except requests.exceptions.Timeout:
        return jsonify({
            'ok': False,
            'company': company_name,
            'error': 'timeout',
            'message': 'wFirma nie odpowiada (timeout 10s)',
            'elapsed_ms': int((time.time() - start_time) * 1000)
        }), 504
    except Exception as e:
        return jsonify({
            'ok': False,
            'company': company_name,
            'error': 'exception',
            'message': str(e),
            'elapsed_ms': int((time.time() - start_time) * 1000)
        }), 500


@app.route('/api/contractor/<nip>')
@require_api_key
@require_token
def check_contractor(token, nip):
    """Sprawdź czy kontrahent istnieje po NIP"""
    company_id = wfirma_get_company_id(token)
    contractor, resp = wfirma_find_contractor_by_nip(token, nip, company_id)
    if contractor:
        return jsonify({'exists': True, 'contractor': contractor})

    clean_nip = nip.replace("-", "").replace(" ", "")
    status = resp.status_code if resp else None
    return jsonify({
        'exists': False,
        'nip': clean_nip,
        'message': 'Kontrahent nie został znaleziony',
        'status': status
    })

@app.route('/api/contractor/add', methods=['POST'])
@require_api_key
@require_token
def add_contractor(token):
    """Dodaj nowego kontrahenta"""
    data = request.json
    
    if not data:
        return jsonify({'error': 'Brak danych w żądaniu'}), 400
    company_id = wfirma_get_company_id(token)
    contractor, resp = wfirma_add_contractor(token, data, company_id)
    if contractor:
        return jsonify({'success': True, 'contractor': contractor})

    status = resp.status_code if resp else None
    return jsonify({
        'error': 'Błąd podczas dodawania kontrahenta',
        'status': status,
        'details': resp.text if resp else 'Brak odpowiedzi'
    }), status or 500

@app.route('/api/invoice/create', methods=['POST'])
@require_api_key
@require_token
def create_invoice(token):
    """Utwórz fakturę"""
    data = request.json
    
    if not data:
        return jsonify({'error': 'Brak danych w żądaniu'}), 400
    company_id = wfirma_get_company_id(token)
    invoice, resp = wfirma_create_invoice(token, data, company_id)
    if invoice:
        return jsonify({'success': True, 'invoice': invoice})

    status = resp.status_code if resp else None
    return jsonify({
        'error': 'Błąd podczas tworzenia faktury',
        'status': status,
        'details': resp.text if resp else 'Brak odpowiedzi'
    }), status or 500


@app.route('/api/invoice/<invoice_id>/pdf', methods=['GET'])
@require_token
def download_invoice_pdf(token, invoice_id):
    """Pobierz PDF faktury i zwróć jako plik do pobrania"""
    company_id = wfirma_get_company_id(token)
    
    try:
        resp = wfirma_get_invoice_pdf(token, invoice_id, company_id)
        
        if resp.status_code == 200 and 'pdf' in resp.headers.get('Content-Type', '').lower():
            # Zwróć PDF jako response
            return Response(
                resp.content,
                mimetype='application/pdf',
                headers={'Content-Disposition': f'attachment; filename=faktura_{invoice_id}.pdf'}
            )
        else:
            return jsonify({
                'error': 'Nie udało się pobrać PDF',
                'status': resp.status_code,
                'details': resp.text[:300] if resp.text else ''
            }), resp.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/series/list')
@require_api_key
@require_token
def list_series(token):
    """Pobierz listę wszystkich serii faktur"""
    company = (request.args.get('company') or DEFAULT_COMPANY).lower().strip()
    if company not in SUPPORTED_COMPANIES:
        company = DEFAULT_COMPANY
    
    # Załaduj token dla wybranej firmy
    token = load_token(silent=True, company=company)
    if not token:
        return jsonify({
            'error': f'Brak autoryzacji dla firmy {company.upper()}',
            'message': f'Przejdź do /auth?company={company}'
        }), 401
    
    company_id = wfirma_get_company_id(token)
    series_list = wfirma_list_series(token, company_id)
    
    return jsonify({
        'success': True,
        'company': company,
        'series_count': len(series_list),
        'series': series_list
    })


@app.route('/api/invoice/<invoice_id>/send', methods=['POST'])
@require_api_key
@require_token
def send_invoice_email(token, invoice_id):
    """Wyślij fakturę emailem"""
    data = request.json or {}
    email = data.get('email', '').strip()
    
    if not email or '@' not in email:
        return jsonify({'error': 'Brak lub niepoprawny email'}), 400
    
    company_id = wfirma_get_company_id(token)
    
    try:
        resp = wfirma_send_invoice_email(token, invoice_id, email, company_id)
        
        if resp.status_code == 200:
            return jsonify({
                'success': True,
                'message': f'Faktura wysłana na {email}',
                'response': resp.json()
            })
        else:
            return jsonify({
                'error': 'Nie udało się wysłać emaila',
                'status': resp.status_code,
                'details': resp.text[:500] if resp.text else ''
            }), resp.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== ENDPOINT WORKFLOW: NIP -> GUS -> KONTRAHENT -> FAKTURA ====================


def build_invoice_payload(invoice_input: dict, contractor: dict, token: str = None, series_id: int = None, mark_as_paid: bool = False, document_type: str = 'normal', ereceipt_email: str = None) -> tuple[dict | None, str | None]:
    """
    Mapper uproszczonego JSON na strukturę wFirma invoices/add.
    Jeśli token podany - automatycznie tworzy produkty w katalogu wFirma.
    Jeśli series_id podany - faktura będzie w tej serii.
    Jeśli mark_as_paid=True - dodaje alreadypaid_initial z obliczoną kwotą brutto.
    document_type: 'normal' (faktura VAT), 'proforma', 'proforma_bill', 'accounting_note' (nota księgowa), 'receipt_fiscal_normal' (paragon)
    ereceipt_email: email do wysyłki e-paragonu (tylko dla receipt_fiscal_normal)
    """
    if not invoice_input:
        return None, 'Brak sekcji invoice'

    positions = invoice_input.get('positions') or []
    if not isinstance(positions, list) or len(positions) == 0:
        return None, 'Brak pozycji faktury'

    # Daty - domyślnie dzisiaj
    issue_date = invoice_input.get('issue_date') or datetime.date.today().isoformat()
    sale_date = invoice_input.get('sale_date') or issue_date

    payment_due_date = invoice_input.get('payment_due_date')
    if not payment_due_date:
        due_days = invoice_input.get('payment_due_days')
        if due_days is not None:
            try:
                days_int = int(due_days)
                # Oblicz termin płatności od daty wystawienia (issue_date), nie od dzisiaj
                if issue_date:
                    base_date = datetime.date.fromisoformat(issue_date)
                else:
                    base_date = datetime.date.today()
                payment_due_date = (base_date + datetime.timedelta(days=days_int)).isoformat()
                print(f"[WFIRMA DEBUG] payment_due_date obliczony: {base_date} + {days_int} dni = {payment_due_date}")
            except Exception as e:
                print(f"[WFIRMA DEBUG] Błąd obliczania payment_due_date: {e}")
                return None, 'Niepoprawny payment_due_days lub issue_date'

    # Używamy contractor_id (int) zamiast zagnieżdżonego obiektu
    contractor_id_int = _extract_contractor_id(contractor)
    if not contractor_id_int:
        return None, "Brak poprawnego ID kontrahenta"

    payload = {
        "contractor_id": contractor_id_int,
        "date": issue_date,
        "payment_date": payment_due_date,
        "paymenttype": invoice_input.get('payment_method', 'transfer'),
        "type": document_type,  # 'normal', 'proforma', 'proforma_bill'
        "currency": invoice_input.get('currency', 'PLN'),
    }
    
    # Seria faktur (opcjonalnie)
    if series_id:
        payload["series"] = {"id": series_id}
        print(f"[WFIRMA DEBUG] Używam serii ID: {series_id}")
    
    if sale_date:
        payload["sale_date"] = sale_date
    if invoice_input.get('place'):
        payload["issue_place"] = invoice_input.get('place')

    # Mapowanie stawek VAT na ID w wFirma (vat_code.id) oraz stawki procentowe
    vat_code_map = {
        "23": 222,
        "8": 223,
        "5": 224,
        "0": 225,
        "zw": 226,
        "np": 227
    }
    vat_rate_percent = {
        "23": 0.23,
        "8": 0.08,
        "5": 0.05,
        "0": 0.0,
        "zw": 0.0,
        "np": 0.0
    }

    # Pozycje – wFirma wymaga struktury z kluczami numerycznymi: invoicecontents -> "0" -> invoicecontent
    invoice_contents_dict = {}
    total_brutto = 0.0  # Suma brutto wszystkich pozycji
    
    for idx, pos in enumerate(positions):
        name = pos.get('name')
        qty = pos.get('quantity')
        price_net = pos.get('unit_price_net')
        vat_rate = pos.get('vat_rate')
        if name is None or qty is None or price_net is None or vat_rate is None:
            return None, 'Pozycja wymaga pól: name, quantity, unit_price_net, vat_rate'

        # Konwersja na liczby
        try:
            qty_num = float(qty) if isinstance(qty, str) else qty
            price_num = float(price_net) if isinstance(price_net, str) else price_net

            # VAT - pobierz vat_code_id z mapy
            if isinstance(vat_rate, float) and vat_rate.is_integer():
                vat_str = str(int(vat_rate))
            else:
                vat_str = str(vat_rate)

            vat_code_id = vat_code_map.get(vat_str, 222)  # domyślnie 23%
            vat_percent = vat_rate_percent.get(vat_str, 0.23)  # domyślnie 23%
            
            # Oblicz brutto dla tej pozycji
            position_netto = qty_num * price_num
            position_brutto = position_netto * (1 + vat_percent)
            total_brutto += position_brutto

        except (ValueError, TypeError):
            return None, f'Niepoprawne wartości liczbowe w pozycji: {name}'

        # Tworzymy pozycję faktury z pełnymi danymi
        # KLUCZOWE: używamy vat_code: {id: X} zamiast vat: "23"
        # oraz struktury z kluczem numerycznym
        invoice_contents_dict[str(idx)] = {
            "invoicecontent": {
                "name": str(name),
                "count": qty_num,  # jako liczba, nie string
                "unit": pos.get('unit', 'szt.'),
                "price": price_num,  # jako liczba, nie string
                "vat_code": {"id": vat_code_id}
            }
        }
        print(f"[WFIRMA DEBUG] Position: {name}, qty={qty_num}, price={price_num}, vat_code_id={vat_code_id}")

    # Struktura z kluczami numerycznymi (jak wFirma zwraca w odpowiedziach)
    payload["invoicecontents"] = invoice_contents_dict
    
    # Jeśli mark_as_paid - dodaj alreadypaid_initial z obliczoną kwotą brutto
    # To oznacza fakturę jako opłaconą już przy tworzeniu
    if mark_as_paid and total_brutto > 0:
        # Zaokrąglij do 2 miejsc po przecinku
        total_brutto_rounded = round(total_brutto, 2)
        payload["alreadypaid_initial"] = str(total_brutto_rounded)
        print(f"[WFIRMA DEBUG] mark_as_paid=True, alreadypaid_initial={total_brutto_rounded}")
    
    # Debug: loguj typy danych w pierwszej pozycji
    if invoice_contents_dict and "0" in invoice_contents_dict:
        first_pos = invoice_contents_dict["0"]["invoicecontent"]
        try:
            print(f"[WFIRMA DEBUG] invoice first position types: count={type(first_pos['count']).__name__}, price={type(first_pos['price']).__name__}, vat_code_id={first_pos['vat_code']['id']}")
        except Exception:
            pass
    
    # E-paragon: dodaj sekcję ereceipt_integration_receipt jeśli to paragon i podano email
    if document_type == 'receipt_fiscal_normal' and ereceipt_email:
        payload["ereceipt_integration_receipt"] = {
            "email_to_auto_send": ereceipt_email
        }
        print(f"[WFIRMA DEBUG] E-paragon: email={ereceipt_email}")
    
    return payload, None


@app.route('/api/workflow/create-invoice-from-nip', methods=['POST'])
@require_api_key
def workflow_create_invoice():
    """Pełny workflow: NIP -> (GUS) -> kontrahent -> faktura."""
    
    body = request.get_json(silent=True) or {}
    
    # Pobierz parametr company z body (md lub test)
    company = (body.get('company') or DEFAULT_COMPANY).lower().strip()
    if company not in SUPPORTED_COMPANIES:
        return jsonify({
            'error': f'Nieobsługiwana firma: {company}',
            'supported': SUPPORTED_COMPANIES
        }), 400
    
    config = get_company_config(company)
    print(f"[WORKFLOW] Używam konfiguracji dla firmy: {company.upper()} (prefix: {config['prefix']})")
    
    # Załaduj token dla wybranej firmy
    token = load_token(silent=False, company=company)
    if not token:
        return jsonify({
            'error': f'Brak autoryzacji dla firmy {company.upper()}',
            'message': f'Przejdź do /auth?company={company} aby się zalogować',
            'company': company
        }), 401
    
    # Sprawdź ostrzeżenie o wygasającym refresh tokenie
    days_remaining, warning = check_refresh_token_expiry_for_company(company)
    if warning:
        print(f"[WARNING] [{company.upper()}] {warning}")
        # Wyślij powiadomienie jeśli < 7 dni
        if days_remaining is not None and days_remaining <= 7:
            send_token_expiry_notification(days_remaining, warning)
    nip_raw = str(body.get('nip', '')).strip()
    clean_nip = re.sub(r'[^0-9]', '', nip_raw)
    nip_valid = len(clean_nip) == 10  # Flaga czy NIP jest poprawny
    
    # Dane kontrahenta z wywołania (fallback gdy brak/niepoprawny NIP)
    # wFirma wymaga name, street, zip, city - domyślne wartości jeśli puste
    purchaser_name = (body.get('purchaser_name') or '').strip()
    purchaser_address = (body.get('purchaser_address') or '').strip() or '-'  # Domyślnie "-"
    purchaser_zip = (body.get('purchaser_zip') or '').strip() or '00-000'     # Domyślnie "00-000"
    purchaser_city = (body.get('purchaser_city') or '').strip() or '-'        # Domyślnie "-"
    
    invoice_input = body.get('invoice')
    email_address = (body.get('email') or '').strip()
    send_email_requested = bool(body.get('send_email')) or bool(email_address)
    # Seria faktur - dla wydarzeń: FV/EV/nr/miesiąc/rok
    # W wFirma sama "seria" (series_name) musi istnieć i mieć ustawiony format numeracji.
    default_series = 'FV/EV'  # Używana dla obu firm (MD/TEST)
    series_name = (body.get('series_name') or default_series).strip()
    
    # Status płatności faktury - dwa sposoby przekazania:
    # 1. payment_status: "paid" lub "unpaid" (preferowane)
    # 2. mark_as_paid: true/false (kompatybilność wsteczna)
    payment_status_param = body.get('payment_status', '').lower().strip()
    if payment_status_param == 'paid':
        mark_as_paid = True
    elif payment_status_param == 'unpaid':
        mark_as_paid = False
    else:
        # Fallback na mark_as_paid (domyślnie True)
        mark_as_paid = body.get('mark_as_paid', True)
    
    # Top-level parametry dat (nadpisują wartości z invoice jeśli podane)
    # issue_date: data wystawienia faktury (np. "2025-12-13")
    # payment_due_days: ilość dni od daty wystawienia (np. 7, 14, 30)
    # payment_due_date: konkretna data terminu płatności (np. "2025-12-20")
    issue_date_param = body.get('issue_date')
    payment_due_days_param = body.get('payment_due_days')
    payment_due_date_param = body.get('payment_due_date')
    
    # Komentarz/opis na fakturze (np. nazwa wydarzenia)
    description_param = (body.get('description') or '').strip()
    
    # Typ dokumentu: "normal" (faktura VAT), "proforma", "accounting_note" (nota księgowa), "receipt_fiscal_normal" (paragon)
    document_type_param = (body.get('document_type') or 'normal').lower().strip()
    if document_type_param not in ('normal', 'proforma', 'proforma_bill', 'accounting_note', 'receipt_fiscal_normal'):
        document_type_param = 'normal'  # Domyślnie faktura VAT
    
    # E-paragon: email do wysyłki (tylko dla receipt_fiscal_normal)
    ereceipt_email = (body.get('ereceipt_email') or '').strip()
    
    # Nadpisz wartości w invoice_input jeśli podano top-level parametry
    if invoice_input and isinstance(invoice_input, dict):
        if issue_date_param:
            invoice_input['issue_date'] = issue_date_param
        if payment_due_days_param is not None:
            invoice_input['payment_due_days'] = payment_due_days_param
        if payment_due_date_param:
            invoice_input['payment_due_date'] = payment_due_date_param

    # LOG: wejście requestu (bez danych wrażliwych)
    try:
        print("[WFIRMA DEBUG] workflow_create_invoice called")
        print("[WFIRMA DEBUG] raw nip:", nip_raw)
        print("[WFIRMA DEBUG] clean nip:", clean_nip)
        print("[WFIRMA DEBUG] series_name:", series_name, "(case insensitive)")
        print("[WFIRMA DEBUG] payment_status:", payment_status_param if payment_status_param else "default", "-> mark_as_paid:", mark_as_paid)
        print("[WFIRMA DEBUG] issue_date:", issue_date_param, "payment_due_days:", payment_due_days_param, "payment_due_date:", payment_due_date_param)
        print("[WFIRMA DEBUG] invoice keys:", list(invoice_input.keys()) if isinstance(invoice_input, dict) else invoice_input)
        print("[WFIRMA DEBUG] send_email_requested:", send_email_requested, "email:", email_address)
    except Exception:
        pass

    # Walidacja: musi być albo poprawny NIP albo dane purchaser
    if not nip_valid and not purchaser_name:
        return jsonify({
            'error': 'Wymagany poprawny NIP (10 cyfr) lub dane purchaser_name',
            'nip_provided': nip_raw,
            'nip_valid': nip_valid
        }), 400
    if not invoice_input:
        return jsonify({'error': 'Brak sekcji invoice'}), 400

    # 0) Pobierz company_id (ID Twojej firmy) - OPCJONALNE
    # Jeśli masz tylko jedną firmę, API użyje jej automatycznie
    company_id = wfirma_get_company_id(token)
    if company_id:
        print(f"[WFIRMA DEBUG] company_id: {company_id}")
    else:
        print(f"[WFIRMA DEBUG] company_id: brak (użyje domyślnej firmy)")

    # 1) Szukamy kontrahenta lub tworzymy na podstawie danych z wywołania
    contractor = None
    contractor_id = None
    contractor_created = False
    contractor_source = None  # 'wfirma', 'gus', 'purchaser'
    resp_find = None  # Inicjalizacja dla przypadku gdy nie szukamy po NIP
    
    if nip_valid:
        # NIP poprawny - szukamy w wFirma
        contractor, resp_find = wfirma_find_contractor_by_nip(token, clean_nip, company_id)
        contractor_id = _extract_contractor_id(contractor)
        
        try:
            print("[WFIRMA DEBUG] find_contractor_by_nip contractor_id:", contractor_id)
            print("[WFIRMA DEBUG] find_contractor_by_nip raw contractor:", contractor)
            if resp_find is not None:
                print("[WFIRMA DEBUG] find response status:", resp_find.status_code)
                body_txt = resp_find.text or ""
                print("[WFIRMA DEBUG] find response body len:", len(body_txt))
                print("[WFIRMA DEBUG] find response body snippet 2000:", body_txt[:2000])
        except Exception:
            pass
        
        if contractor_id:
            contractor_source = 'wfirma'
    
    # 2) Jeśli brak kontrahenta i NIP poprawny – spróbuj GUS
    if not contractor_id and nip_valid:
        gus_records, gus_err = gus_lookup_nip(clean_nip)
        try:
            print("[WFIRMA DEBUG] gus_lookup_nip records len:", len(gus_records) if gus_records else gus_records, "err:", gus_err)
            if gus_records:
                print("[WFIRMA DEBUG] gus first record:", gus_records[0])
        except Exception:
            pass
        
        # Jeśli GUS znalazł dane - użyj ich do stworzenia kontrahenta
        if gus_records and len(gus_records) > 0:
            gus_first = gus_records[0]
            # Format adresu jak w wFirma
            street_base = gus_first.get('ulica') or ""
            nr_domu = gus_first.get('nrNieruchomosci') or ""
            nr_lokalu = gus_first.get('nrLokalu') or ""
            
            if street_base and nr_domu and nr_lokalu:
                street_full = f"{street_base} {nr_domu}/{nr_lokalu}"
            elif street_base and nr_domu:
                street_full = f"{street_base} {nr_domu}"
            else:
                street_full = street_base

            contractor_payload = {
                "name": gus_first.get('nazwa') or clean_nip,
                "altname": gus_first.get('nazwa') or clean_nip,
                "nip": clean_nip,
                "tax_id_type": "nip",
                "street": street_full,
                "zip": gus_first.get('kodPocztowy') or "",
                "city": gus_first.get('miejscowosc') or "",
                "country": "PL",
            }
            contractor_source = 'gus'
            print(f"[WORKFLOW] Tworzę kontrahenta z danych GUS: {contractor_payload.get('name')}")
        else:
            # GUS nie znalazł - fallback na dane purchaser jeśli dostępne
            if purchaser_name:
                print(f"[WORKFLOW] GUS nie znalazł NIP {clean_nip}, używam danych purchaser")
                contractor_payload = {
                    "name": purchaser_name,
                    "altname": purchaser_name,
                    "nip": clean_nip,  # Zachowaj NIP nawet jeśli GUS go nie zna
                    "tax_id_type": "nip",
                    "street": purchaser_address,
                    "zip": purchaser_zip,
                    "city": purchaser_city,
                    "country": "PL",
                }
                contractor_source = 'purchaser_fallback'
            else:
                return jsonify({'error': 'GUS nie znalazł firmy dla podanego NIP i brak danych purchaser'}), 404
        
        try:
            print("[WFIRMA DEBUG] create contractor payload:", contractor_payload)
        except Exception:
            pass

        new_contractor, resp_add = wfirma_add_contractor(token, contractor_payload, company_id)
        
        # Obsługa wyniku tworzenia kontrahenta
        try:
            print("[WFIRMA DEBUG] add contractor status:", resp_add.status_code if resp_add else None)
            if resp_add is not None:
                body_txt = resp_add.text or ""
                print("[WFIRMA DEBUG] add contractor body len:", len(body_txt))
                print("[WFIRMA DEBUG] add contractor FULL body:", body_txt)
        except Exception:
            pass
        
        if not new_contractor:
            status = resp_add.status_code if resp_add else None
            return jsonify({
                'error': 'Nie udało się dodać kontrahenta w wFirma',
                'status': status,
                'details': resp_add.text if resp_add else 'Brak odpowiedzi',
                'contractor_payload': contractor_payload,
                'contractor_source': contractor_source
            }), status or 502

        contractor = new_contractor
        contractor_id = _extract_contractor_id(contractor)
        contractor_created = True
        
        # FALLBACK: jeśli add nie zwrócił ID, spróbuj re-find po NIP
        if not contractor_id and clean_nip:
            print(f"[WORKFLOW] add_contractor nie zwrócił ID, próbuję re-find po NIP {clean_nip}")
            refind_contractor, _ = wfirma_find_contractor_by_nip(token, clean_nip, company_id)
            if refind_contractor:
                contractor_id = _extract_contractor_id(refind_contractor)
                if contractor_id:
                    contractor = refind_contractor
                    print(f"[WORKFLOW] re-find po NIP znalazł kontrahenta ID={contractor_id}")
    
    # 3) Jeśli NIP niepoprawny - użyj danych purchaser (osoba fizyczna)
    elif not contractor_id and not nip_valid and purchaser_name:
        print(f"[WORKFLOW] NIP niepoprawny/brak, tworzę kontrahenta z danych purchaser: {purchaser_name}")
        contractor_payload = {
            "name": purchaser_name,
            "altname": purchaser_name,
            "tax_id_type": "none",  # Osoba fizyczna bez NIP
            "street": purchaser_address,
            "zip": purchaser_zip,
            "city": purchaser_city,
            "country": "PL",
        }
        contractor_source = 'purchaser'
        
        try:
            print("[WFIRMA DEBUG] create contractor payload (purchaser):", contractor_payload)
        except Exception:
            pass

        new_contractor, resp_add = wfirma_add_contractor(token, contractor_payload, company_id)
        
        # Obsługa wyniku tworzenia kontrahenta
        try:
            print("[WFIRMA DEBUG] add contractor status:", resp_add.status_code if resp_add else None)
            if resp_add is not None:
                body_txt = resp_add.text or ""
                print("[WFIRMA DEBUG] add contractor body len:", len(body_txt))
                print("[WFIRMA DEBUG] add contractor FULL body:", body_txt)
        except Exception:
            pass
        
        if not new_contractor:
            status = resp_add.status_code if resp_add else None
            return jsonify({
                'error': 'Nie udało się dodać kontrahenta w wFirma',
                'status': status,
                'details': resp_add.text if resp_add else 'Brak odpowiedzi',
                'contractor_payload': contractor_payload,
                'contractor_source': contractor_source
            }), status or 502

        contractor = new_contractor
        contractor_id = _extract_contractor_id(contractor)
        contractor_created = True

    if not contractor_id:
        status = resp_find.status_code if resp_find else None
        # Log diagnostyczny z odpowiedzi find (bez wrażliwych danych) – ułatwia debug na Render
        try:
            print("[WFIRMA DEBUG] find response status:", status)
            if resp_find is not None:
                print("[WFIRMA DEBUG] find response body snippet:", (resp_find.text or "")[:500])
            print("[WFIRMA DEBUG] contractor object before failure:", contractor)
        except Exception:
            pass
        return jsonify({
            'error': 'Nie udało się uzyskać ID kontrahenta w wFirma',
            'status': status
        }), status or 502

    # 3) Szukamy serii faktur (opcjonalnie)
    series_id = None
    if series_name:
        series = wfirma_find_series_by_name(token, series_name, company_id)
        if series and series.get('id'):
            series_id = int(series.get('id'))
            print(f"[WORKFLOW] Znaleziono serię '{series_name}' -> ID {series_id}")
        else:
            print(f"[WORKFLOW] UWAGA: Nie znaleziono serii '{series_name}', użyję domyślnej")
            # Loguj dostępne serie żeby ułatwić debugowanie
            available_series = wfirma_list_series(token, company_id)
            if available_series:
                print(f"[WORKFLOW] Dostępne serie ({len(available_series)}):")
                for s in available_series:
                    print(f"[WORKFLOW]   - '{s['name']}' (ID: {s['id']}, szablon: {s['template']})")
    
    # 4) Budujemy payload faktury/proformy/paragonu (z alreadypaid_initial jeśli mark_as_paid=True)
    invoice_payload, map_err = build_invoice_payload(invoice_input, contractor, token, series_id=series_id, mark_as_paid=mark_as_paid, document_type=document_type_param, ereceipt_email=ereceipt_email)
    try:
        print("[WFIRMA DEBUG] invoice payload:", invoice_payload)
        if invoice_payload and 'invoicecontents' in invoice_payload:
            import json as json_lib
            print("[WFIRMA DEBUG] invoicecontents JSON:", json_lib.dumps(invoice_payload['invoicecontents'], ensure_ascii=False))
    except Exception as e:
        print("[WFIRMA DEBUG] log error:", e)
    if map_err:
        return jsonify({'error': map_err}), 400

    # Dodaj description (komentarz/nazwa wydarzenia) do faktury
    if invoice_payload:
        if company in ('test', 'md_test'):
            # Tryb TEST lub MD_TEST: ostrzeżenie + opcjonalnie nazwa wydarzenia
            test_warning = (
                "!!! FAKTURA NIEWAŻNA - TRYB TESTOWY !!!\n"
                "!!! FAKTURA NIEWAŻNA - TRYB TESTOWY !!!\n"
                "!!! FAKTURA NIEWAŻNA - TRYB TESTOWY !!!\n"
                "*** DOKUMENT WYSTAWIONY W CELACH TESTOWYCH ***\n"
                "*** NIE STANOWI PODSTAWY DO ZAPŁATY ***"
            )
            if description_param:
                invoice_payload["description"] = f"{test_warning}\n\n{description_param}"
            else:
                invoice_payload["description"] = test_warning
            print(f"[WORKFLOW] Tryb {company.upper()} - dodano ostrzeżenie na fakturze")
        elif description_param:
            # Tryb PRODUKCJA (md): tylko nazwa wydarzenia (jeśli podana)
            invoice_payload["description"] = description_param
            print(f"[WORKFLOW] Dodano opis na fakturze: {description_param}")

    invoice, resp_inv = wfirma_create_invoice(token, invoice_payload, company_id)
    try:
        print("[WFIRMA DEBUG] invoice create status:", resp_inv.status_code if resp_inv else None)
        if resp_inv is not None:
            body_txt = resp_inv.text or ""
            print("[WFIRMA DEBUG] invoice create body len:", len(body_txt))
            print("[WFIRMA DEBUG] invoice create body snippet 2000:", body_txt[:2000])
        print("[WFIRMA DEBUG] invoice obj:", invoice)
    except Exception:
        pass
    if not invoice:
        status = resp_inv.status_code if resp_inv else None
        error_details = resp_inv.text if resp_inv else 'Brak odpowiedzi'
        
        # Specjalny komunikat dla błędu schematu księgowego
        if 'schematu księgowego' in error_details.lower() or 'schematu ksiegowego' in error_details.lower():
            return jsonify({
                'error': 'Brak konfiguracji schematu księgowego w wFirma',
                'message': 'W panelu wFirma ustaw: Ustawienia → Firma → Księgowość → Schematy księgowe',
                'details': error_details,
                'status': status
            }), 400
        
        return jsonify({
            'error': 'Błąd podczas tworzenia faktury',
            'status': status,
            'details': error_details
        }), status or 502

    # Pobierz ID faktury
    invoice_id = str(invoice.get('id') or invoice.get('invoice_id') or '')
    if not invoice_id:
        return jsonify({
            'error': 'Brak ID faktury w odpowiedzi',
            'invoice': invoice
        }), 502
    
    # Sprawdź status płatności faktury
    # (alreadypaid_initial jest ustawiony przy tworzeniu faktury jeśli mark_as_paid=True)
    payment_result = None
    if mark_as_paid:
        payment_state = invoice.get('paymentstate', 'unknown')
        already_paid = invoice.get('alreadypaid', '0')
        already_paid_initial = invoice.get('alreadypaid_initial', '')
        invoice_total = invoice.get('total', '0')
        
        print(f"[WORKFLOW] Status płatności faktury: paymentstate={payment_state}, alreadypaid={already_paid}, alreadypaid_initial={already_paid_initial}, total={invoice_total}")
        
        if payment_state == 'paid' or already_paid_initial:
            payment_result = {'success': True, 'method': 'alreadypaid_initial', 'paymentstate': payment_state}
            print(f"[WORKFLOW] Faktura oznaczona jako opłacona (alreadypaid_initial przy tworzeniu)")
        else:
            # Fallback: jeśli alreadypaid_initial nie zadziałał, spróbuj payments/add
            print(f"[WORKFLOW] UWAGA: alreadypaid_initial nie zadziałał, próbuję payments/add...")
            invoice_total_float = float(invoice_total) if invoice_total else 0
            if invoice_total_float > 0:
                payment_date = invoice_input.get('issue_date') or invoice.get('date')
                payment_cashbox_id = None
                if invoice.get('payment_cashbox') and invoice['payment_cashbox'].get('id'):
                    payment_cashbox_id = invoice['payment_cashbox']['id']
                payment, resp_payment = wfirma_add_payment(token, invoice_id, invoice_total_float, payment_date, company_id, payment_cashbox_id)
                if payment:
                    payment_result = {'success': True, 'method': 'payments_add', 'payment': payment}
                    print(f"[WORKFLOW] Płatność dodana przez payments/add (kwota: {invoice_total_float})")
                else:
                    payment_result = {'success': False, 'error': 'Nie udało się dodać płatności'}
                    print(f"[WORKFLOW] UWAGA: Nie udało się oznaczyć faktury jako opłaconej")
    
    # ZAWSZE pobierz PDF faktury (niezależnie od emaila)
    pdf_filename = None
    pdf_base64 = None
    pdf_content = None
    try:
        resp_pdf = wfirma_get_invoice_pdf(token, invoice_id, company_id)
        if resp_pdf.status_code == 200 and 'pdf' in resp_pdf.headers.get('Content-Type', '').lower():
            pdf_content = resp_pdf.content
            # Koduj PDF jako base64 dla zwrócenia w odpowiedzi
            pdf_base64 = base64.b64encode(pdf_content).decode('utf-8')
            
            # Zapisz też lokalnie
            os.makedirs('invoices', exist_ok=True)
            pdf_filename = f"invoices/faktura_{invoice_id}.pdf"
            with open(pdf_filename, 'wb') as f:
                f.write(pdf_content)
            print(f"[WFIRMA DEBUG] PDF saved: {pdf_filename} ({len(pdf_content)} bytes)")
        else:
            print(f"[WFIRMA DEBUG] PDF download failed: {resp_pdf.status_code}")
    except Exception as e:
        print(f"[WFIRMA DEBUG] PDF exception: {e}")
    
    # Opcjonalnie wyślij fakturę mailem
    email_result = None
    if send_email_requested:
        if not email_address or '@' not in email_address:
            return jsonify({
                'error': 'Brak lub niepoprawny email do wysyłki faktury',
                'invoice': invoice,
                'pdf_saved': pdf_filename
            }), 400

        resp_email = wfirma_send_invoice_email(token, invoice_id, email_address, company_id)
        try:
            print("[WFIRMA DEBUG] send email status:", resp_email.status_code if resp_email else None)
            if resp_email is not None:
                body_txt = resp_email.text or ""
                print("[WFIRMA DEBUG] send email body len:", len(body_txt))
                print("[WFIRMA DEBUG] send email body snippet:", body_txt[:500])
        except Exception:
            pass
        if resp_email.status_code != 200:
            return jsonify({
                'error': 'Nie udało się wysłać faktury mailem',
                'status': resp_email.status_code,
                'details': resp_email.text[:500] if resp_email.text else '',
                'invoice': invoice,
                'pdf_saved': pdf_filename
            }), resp_email.status_code
        try:
            email_result = resp_email.json()
        except Exception:
            email_result = {}

    # Przygotuj odpowiedź
    # Pobierz status płatności z faktury (dla Make.com)
    invoice_payment_status = invoice.get('paymentstate', 'unknown')  # paid/unpaid/undefined
    
    response = {
        'success': True,
        'company': company,  # Użyta firma (md/test)
        'series_name': series_name,  # Użyta seria faktur (np. "Eventy")
        'series_id': series_id,
        
        # Główne dane faktury (łatwy dostęp dla Make.com)
        'invoice_id': invoice.get('id', ''),
        'invoice_number': invoice.get('fullnumber', ''),  # Pełny numer faktury (np. FV/EV/23/12/2025)
        'invoice_date': invoice.get('date', ''),  # Data wystawienia
        'invoice_sale_date': invoice.get('disposaldate', ''),  # Data sprzedaży
        'invoice_payment_status': invoice_payment_status,  # Status płatności: paid/unpaid/undefined
        'invoice_payment_due_date': invoice.get('paymentdate', ''),  # Termin płatności (gdy unpaid)
        'invoice_total': invoice.get('total', ''),  # Kwota brutto
        'invoice_remaining': invoice.get('remaining', ''),  # Pozostało do zapłaty
        
        'contractor_created': contractor_created,
        'contractor': contractor,
        'invoice': invoice,  # Pełny obiekt faktury (dla zaawansowanych)
        'marked_as_paid': bool(payment_result and payment_result.get('success')),
        'payment_result': payment_result,
        'email_sent': bool(email_result),
        'email_response': email_result,
        'pdf_saved': pdf_filename
    }
    
    # Dodaj PDF jako base64 (dla Make.com - żeby nie robić osobnego HTTP request)
    if pdf_base64:
        response['pdf_base64'] = pdf_base64
        response['pdf_size_bytes'] = len(pdf_content) if pdf_content else 0
    
    # Dodaj URL do pobrania PDF (dla opcjonalnego użycia)
    # Zawsze używamy request.url_root (jesteśmy w kontekście requestu)
    if invoice_id:
        base_url = request.url_root.rstrip('/')
        response['pdf_url'] = f"{base_url}/api/invoice/{invoice_id}/pdf"
    
    # Dodaj ostrzeżenie o refresh tokenie jeśli niedługo wygasa
    days_remaining, warning = check_refresh_token_expiry_for_company(company)
    if warning:
        response['token_warning'] = warning
        response['refresh_token_days_remaining'] = round(days_remaining, 1) if days_remaining else 0
    
    return jsonify(response)


# ==================== ENDPOINTY GUS / REGON ====================

# ==================== ENDPOINTY GUS / REGON ====================

@app.route('/api/gus/name-by-nip', methods=['POST'])
def gus_name_by_nip():
    """
    Prosty port endpointu /api/gus/name-by-nip z backendu Googie_GUS.
    Headers: X-API-Key: <REGON_API_KEY_TOKEN>
    Wejście: JSON { "nip": "1234567890" }
    Wyjście: { "data": [ { regon, nip, nazwa, ... } ] } albo komunikat błędu.
    """
    # Sprawdź osobny token dla endpointów GUS/REGON
    api_key_header = request.headers.get('X-API-Key', '')
    if not REGON_API_KEY_TOKEN:
        return jsonify({'error': 'Brak REGON_API_KEY_TOKEN w konfiguracji serwera'}), 500
    if api_key_header != REGON_API_KEY_TOKEN:
        return jsonify({'error': 'Unauthorized - nieprawidłowy token'}), 401
    
    body = request.get_json(silent=True) or {}

    # Walidacja i oczyszczenie NIP (jak w Node)
    nip_raw = str(body.get('nip', ''))[:20]
    clean_nip = re.sub(r'[^0-9]', '', nip_raw)

    from_header_key = (request.headers.get('x-gus-api-key') or '')[:100]
    api_key = from_header_key or GUS_API_KEY or ''

    if not clean_nip:
        return jsonify({'error': 'Brak NIP'}), 400

    if len(clean_nip) != 10:
        return jsonify({'error': 'NIP musi składać się z dokładnie 10 cyfr'}), 400

    if not api_key:
        return jsonify({
            'error': 'Brak klucza GUS_API_KEY',
            'hint': 'Ustaw zmienną środowiskową GUS_API_KEY / BIR1_medidesk lub przekaż nagłówek x-gus-api-key.'
        }), 400

    # Przełącznik środowiska test/produkcyjne – zgodnie z Googie_GUS
    use_test_env = api_key == 'abcde12345abcde12345' or GUS_USE_TEST
    bir_host = 'wyszukiwarkaregontest.stat.gov.pl' if use_test_env else 'wyszukiwarkaregon.stat.gov.pl'
    bir_url = f'https://{bir_host}/wsBIR/UslugaBIRzewnPubl.svc'

    # Log tylko diagnostyczny (bez pełnego klucza)
    print(f"[GUS] name-by-nip nip={clean_nip} env={'TEST' if use_test_env else 'PROD'} host={bir_host}")

    safe_api_key = escape_xml(api_key)
    login_envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" xmlns:ns="http://CIS/BIR/PUBL/2014/07">'
        '<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">'
        f'<wsa:To>{bir_url}</wsa:To>'
        '<wsa:Action>http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/Zaloguj</wsa:Action>'
        '</soap:Header>'
        '<soap:Body>'
        '<ns:Zaloguj>'
        f'<ns:pKluczUzytkownika>{safe_api_key}</ns:pKluczUzytkownika>'
        '</ns:Zaloguj>'
        '</soap:Body>'
        '</soap:Envelope>'
    )

    try:
        login_resp = post_soap_gus(bir_host, login_envelope, sid=None, timeout=10)
        # Szczegółowe logi z logowania do GUS
        print(f"[GUS] LOGIN status={login_resp.status_code}")
        login_snippet = (login_resp.text or '')[:500]
        print(f"[GUS] LOGIN body snippet={repr(login_snippet)}")
    except Exception as e:
        return jsonify({
            'error': 'Błąd komunikacji z GUS podczas logowania',
            'message': str(e)
        }), 502

    sid_match = re.search(r'<ZalogujResult>([^<]*)</ZalogujResult>', login_resp.text or '')
    sid = sid_match.group(1).strip() if sid_match else ''

    if not sid:
        snippet = (login_resp.text or '')[:300]
        return jsonify({
            'error': 'Logowanie do GUS nie powiodło się (brak SID)',
            'debug': snippet
        }), 502

    safe_nip = escape_xml(clean_nip)
    search_envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:ns="http://CIS/BIR/PUBL/2014/07" '
        'xmlns:q1="http://CIS/BIR/PUBL/2014/07/DataContract" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<soap:Header xmlns:wsa="http://www.w3.org/2005/08/addressing">'
        f'<wsa:To>{bir_url}</wsa:To>'
        '<wsa:Action>http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/DaneSzukajPodmioty</wsa:Action>'
        '</soap:Header>'
        '<soap:Body>'
        '<ns:DaneSzukajPodmioty>'
        '<ns:pParametryWyszukiwania>'
        '<q1:Krs xsi:nil="true"/>'
        '<q1:Krsy xsi:nil="true"/>'
        f'<q1:Nip>{safe_nip}</q1:Nip>'
        '<q1:Nipy xsi:nil="true"/>'
        '<q1:Regon xsi:nil="true"/>'
        '<q1:Regony14zn xsi:nil="true"/>'
        '<q1:Regony9zn xsi:nil="true"/>'
        '</ns:pParametryWyszukiwania>'
        '</ns:DaneSzukajPodmioty>'
        '</soap:Body>'
        '</soap:Envelope>'
    )

    try:
        search_resp = post_soap_gus(bir_host, search_envelope, sid=sid, timeout=10)
        # Szczegółowe logi z wyszukiwania w GUS
        print(f"[GUS] SEARCH status={search_resp.status_code}")
        search_snippet = (search_resp.text or '')[:800]
        print(f"[GUS] SEARCH body snippet={repr(search_snippet)}")
    except Exception as e:
        return jsonify({
            'error': 'Błąd komunikacji z GUS podczas wyszukiwania',
            'message': str(e)
        }), 502

    soap_part = search_resp.text or ''

    # Obsługa odpowiedzi multipart/MTOM – wyciągamy część SOAP, jeśli trzeba
    if 'Content-Type: application/xop+xml' in soap_part:
        match = re.search(
            r'Content-Type: application/xop\+xml[^\r\n]*\r?\n\r?\n([\s\S]*?)\r?\n--uuid:',
            soap_part,
            re.MULTILINE | re.DOTALL,
        )
        if match:
            soap_part = match.group(1)

    # Brak wyniku
    if re.search(r'<DaneSzukajResult\s*/>', soap_part):
        return jsonify({
            'error': 'GUS nie znalazł podmiotu dla podanego NIP'
        }), 404

    result_match = re.search(
        r'<DaneSzukajPodmiotyResult>([\s\S]*?)</DaneSzukajPodmiotyResult>',
        soap_part,
        re.MULTILINE | re.DOTALL,
    )
    inner_xml = result_match.group(1) if result_match else ''

    if not inner_xml:
        print("[GUS] Brak sekcji <DaneSzukajPodmiotyResult> w odpowiedzi GUS")
        return jsonify({
            'error': 'Brak danych w odpowiedzi GUS (DaneSzukajPodmiotyResult pusty)'
        }), 404

    decoded_xml = decode_bir_inner_xml(inner_xml)
    decoded_snippet = decoded_xml[:800]
    print(f"[GUS] DECODED inner XML snippet={repr(decoded_snippet)}")
    if not decoded_xml:
        return jsonify({
            'error': 'Brak danych po dekodowaniu odpowiedzi GUS'
        }), 502

    try:
        root = ET.fromstring(decoded_xml)
    except ET.ParseError as e:
        return jsonify({
            'error': 'Nie udało się sparsować danych GUS',
            'message': str(e)
        }), 502

    data_list: list[dict] = []

    for dane in root.findall('.//dane'):
        def get_text(tag: str) -> str | None:
            el = dane.find(tag)
            return el.text if el is not None else None

        mapped = {
            'regon': get_text('Regon'),
            'nip': get_text('Nip'),
            'nazwa': get_text('Nazwa'),
            'wojewodztwo': get_text('Wojewodztwo'),
            'powiat': get_text('Powiat'),
            'gmina': get_text('Gmina'),
            'miejscowosc': get_text('Miejscowosc'),
            'kodPocztowy': get_text('KodPocztowy'),
            'ulica': get_text('Ulica'),
            'nrNieruchomosci': get_text('NrNieruchomosci'),
            'nrLokalu': get_text('NrLokalu'),
            'typ': get_text('Typ'),
            'silosId': get_text('SilosID'),
            'miejscowoscPoczty': get_text('MiejscowoscPoczty'),
            'krs': get_text('Krs'),
        }
        data_list.append(mapped)

    print(f"[GUS] PARSED records={len(data_list)}")
    if data_list:
        # Dla podglądu logujemy tylko pierwszy rekord
        print(f"[GUS] FIRST record={repr(data_list[0])}")

    return jsonify({'data': data_list}), 200


@app.route('/api/gus/validate-nip', methods=['POST'])
def gus_validate_nip():
    """
    Sprawdź czy NIP jest poprawny i czy istnieje w bazie GUS/REGON.
    Headers: X-API-Key: <REGON_API_KEY_TOKEN>
    Wejście: JSON { "nip": "1234567890" }
    Wyjście: { "nip_status": "brak/niepoprawny/poprawny", "gus_data": {...} lub null }
    """
    # Sprawdź osobny token dla endpointów GUS/REGON
    api_key_header = request.headers.get('X-API-Key', '')
    if not REGON_API_KEY_TOKEN:
        return jsonify({'error': 'Brak REGON_API_KEY_TOKEN w konfiguracji serwera'}), 500
    if api_key_header != REGON_API_KEY_TOKEN:
        return jsonify({'error': 'Unauthorized - nieprawidłowy token'}), 401
    
    body = request.get_json(silent=True) or {}

    nip_raw = str(body.get('nip', '')).strip()
    clean_nip = re.sub(r'[^0-9]', '', nip_raw)

    # Brak NIP
    if not clean_nip:
        print(f"[GUS] validate-nip BRAK nip_raw='{nip_raw}'")
        return jsonify({
            'nip_status': 'brak',
            'nip_provided': nip_raw,
            'gus_data': None
        }), 200

    # Sprawdź w GUS/REGON
    print(f"[GUS] validate-nip START nip={clean_nip}")
    gus_records, gus_err = gus_lookup_nip(clean_nip)
    print(f"[GUS] validate-nip RESULT nip={clean_nip} err={gus_err} records_count={len(gus_records) if gus_records else 0}")

    # Nie znaleziono w GUS lub błąd
    if gus_err or not gus_records or len(gus_records) == 0:
        print(f"[GUS] validate-nip NIEPOPRAWNY nip={clean_nip} (err={gus_err}, records={gus_records})")
        return jsonify({
            'nip_status': 'niepoprawny',
            'nip': clean_nip,
            'gus_data': None
        }), 200

    # NIP znaleziony w GUS
    print(f"[GUS] validate-nip POPRAWNY nip={clean_nip}")
    gus_first = gus_records[0]
    
    # Składamy pełny adres
    street_parts = [gus_first.get('ulica') or '']
    if gus_first.get('nrNieruchomosci'):
        street_parts.append(gus_first.get('nrNieruchomosci'))
    if gus_first.get('nrLokalu'):
        street_parts[1] = f"{street_parts[1]}/{gus_first.get('nrLokalu')}" if len(street_parts) > 1 else gus_first.get('nrLokalu')
    full_street = ' '.join(filter(None, street_parts))
    
    # Województwo na małe litery
    voivodeship = gus_first.get('wojewodztwo') or ''
    voivodeship_lower = voivodeship.lower() if voivodeship else None
    
    return jsonify({
        'nip_status': 'poprawny',
        'nip': clean_nip,
        'gus_data': {
            'name': gus_first.get('nazwa'),
            'regon': gus_first.get('regon'),
            'street': full_street,
            'zip': gus_first.get('kodPocztowy'),
            'city': gus_first.get('miejscowosc'),
            'voivodeship': voivodeship_lower,
            'krs': gus_first.get('krs')
        }
    }), 200


@app.route('/api/invoice/<invoice_id>/send-email', methods=['POST'])
@require_api_key
@require_token
def invoice_send_email(token, invoice_id):
    """Wyślij fakturę mailem przez wFirma."""
    body = request.get_json(silent=True) or {}
    email = (body.get('email') or '').strip()
    if not email or '@' not in email:
        return jsonify({'error': 'Brak lub niepoprawny email'}), 400

    company_id = wfirma_get_company_id(token)
    resp = wfirma_send_invoice_email(token, invoice_id, email, company_id)
    if resp.status_code == 200:
        try:
            data = resp.json()
        except Exception:
            data = {}
        return jsonify({'success': True, 'wfirma_response': data})

    return jsonify({
        'error': 'Nie udało się wysłać faktury mailem',
        'status': resp.status_code,
        'details': resp.text[:500] if resp.text else ''
    }), resp.status_code


# ==================== FAKTURA KORYGUJĄCA ====================


def wfirma_get_invoice(token: str, invoice_id: str, company_id: str = None) -> tuple[dict | None, str | None]:
    """
    Pobierz szczegóły faktury z wFirma (invoices/get).
    Zwraca (invoice_dict, error_message).
    """
    api_url = f"https://api2.wfirma.pl/invoices/get/{invoice_id}?inputFormat=json&outputFormat=json&oauth_version=2"
    if company_id:
        api_url += f"&company_id={company_id}"
    
    headers = get_wfirma_headers(token)
    try:
        resp = requests.get(api_url, headers=headers)
        print(f"[WFIRMA] invoices/get/{invoice_id} status={resp.status_code}")
        
        if resp.status_code == 200:
            result = resp.json()
            invoices = result.get('invoices', {})
            if isinstance(invoices, dict):
                for key, val in invoices.items():
                    if isinstance(val, dict) and 'invoice' in val:
                        return val['invoice'], None
            return None, "Nie znaleziono faktury w odpowiedzi"
        else:
            return None, f"Błąd API: {resp.status_code} - {resp.text[:300]}"
    except Exception as e:
        return None, str(e)


@app.route('/api/workflow/correction', methods=['POST'])
@require_api_key
@require_token
def workflow_create_correction(token):
    """
    Utwórz fakturę korygującą do istniejącej faktury.
    
    Wejście JSON:
    {
        "company": "md",                      # Opcjonalnie (domyślnie md)
        "parent_invoice_id": 12345,           # WYMAGANE - ID faktury oryginalnej
        "correction_reason": "Błąd w cenie",  # Powód korekty (opis)
        "positions": [                        # WYMAGANE - pozycje korekty
            {
                "parent_position_id": 67890,  # WYMAGANE - ID pozycji oryginalnej
                "name": "Nazwa usługi",       # Opcjonalnie (pobierze z oryginału)
                "quantity": 1,                # Nowa ilość (po korekcie)
                "unit_price_net": 100.00,     # Nowa cena netto (po korekcie)
                "vat_rate": "23"              # VAT
            }
        ],
        "issue_date": "2025-12-12",           # Opcjonalnie (domyślnie dziś)
        "series_name": "Korekty"              # Opcjonalnie - seria numeracji
    }
    """
    body = request.get_json(silent=True) or {}
    
    # Parametry
    company = (body.get('company') or DEFAULT_COMPANY).lower().strip()
    parent_invoice_id = body.get('parent_invoice_id')
    correction_reason = (body.get('correction_reason') or 'Korekta faktury').strip()
    positions = body.get('positions') or []
    issue_date = body.get('issue_date') or datetime.date.today().isoformat()
    series_name = (body.get('series_name') or '').strip()
    
    # Walidacja
    if not parent_invoice_id:
        return jsonify({'error': 'Brak parent_invoice_id - ID faktury oryginalnej jest wymagane'}), 400
    
    if not positions or not isinstance(positions, list):
        return jsonify({'error': 'Brak pozycji korekty (positions)'}), 400
    
    # Sprawdź czy wszystkie pozycje mają parent_position_id
    for idx, pos in enumerate(positions):
        if not pos.get('parent_position_id'):
            return jsonify({'error': f'Pozycja {idx+1} nie ma parent_position_id'}), 400
    
    print(f"[CORRECTION] Tworzę korektę dla faktury ID={parent_invoice_id}, company={company}")
    
    # Pobierz company_id (wymagane przez wFirma API)
    wfirma_company_id = wfirma_get_company_id(token)
    
    # 1) Pobierz oryginalną fakturę żeby uzyskać dane kontrahenta i pozycji
    original_invoice, err = wfirma_get_invoice(token, str(parent_invoice_id), wfirma_company_id)
    if err or not original_invoice:
        return jsonify({
            'error': 'Nie udało się pobrać faktury oryginalnej',
            'details': err,
            'parent_invoice_id': parent_invoice_id
        }), 404
    
    print(f"[CORRECTION] Pobrano fakturę oryginalną: {original_invoice.get('fullnumber')}")
    
    # Pobierz contractor_id z oryginalnej faktury
    contractor_data = original_invoice.get('contractor', {})
    contractor_id = contractor_data.get('id') if isinstance(contractor_data, dict) else None
    if not contractor_id:
        return jsonify({'error': 'Nie można odczytać kontrahenta z faktury oryginalnej'}), 400
    
    # 2) Pobierz serię jeśli podano nazwę
    series_id = None
    if series_name:
        series = wfirma_find_series_by_name(token, series_name, wfirma_company_id)
        if series and series.get('id'):
            series_id = int(series.get('id'))
            print(f"[CORRECTION] Znaleziono serię: {series_name} -> ID {series_id}")
        else:
            print(f"[CORRECTION] Nie znaleziono serii: {series_name}")
    
    # 3) Buduj payload faktury korygującej
    # Mapowanie stawek VAT
    vat_code_map = {
        "23": 222, "8": 223, "5": 224, "0": 225, "zw": 226, "np": 227
    }
    vat_rate_percent = {
        "23": 0.23, "8": 0.08, "5": 0.05, "0": 0.0, "zw": 0.0, "np": 0.0
    }
    
    # Pozycje korekty
    invoice_contents_dict = {}
    total_brutto = 0.0
    
    for idx, pos in enumerate(positions):
        parent_pos_id = pos.get('parent_position_id')
        name = pos.get('name', f'Pozycja korekty {idx+1}')
        qty = pos.get('quantity', 1)
        price_net = pos.get('unit_price_net', 0)
        vat_rate = str(pos.get('vat_rate', '23')).lower()
        
        try:
            qty_num = float(qty) if isinstance(qty, str) else qty
            price_num = float(price_net) if isinstance(price_net, str) else price_net
            vat_percent = vat_rate_percent.get(vat_rate, 0.23)
            pos_brutto = qty_num * price_num * (1 + vat_percent)
            total_brutto += pos_brutto
        except Exception:
            pass
        
        vat_code_id = vat_code_map.get(vat_rate, 222)
        
        content = {
            "invoicecontent": {
                "name": name,
                "unit": pos.get('unit', 'szt.'),
                "count": qty,
                "price": price_net,
                "vat_code": {"id": vat_code_id},
                "parent": {"id": int(parent_pos_id)}  # Powiązanie z oryginalną pozycją
            }
        }
        invoice_contents_dict[str(idx)] = content
    
    # Payload faktury korygującej
    correction_payload = {
        "contractor_id": int(contractor_id),
        "date": issue_date,
        "type": "correction",
        "parent": {"id": int(parent_invoice_id)},  # Powiązanie z fakturą oryginalną
        "description": correction_reason,
        "invoicecontents": invoice_contents_dict
    }
    
    # Seria (opcjonalnie)
    if series_id:
        correction_payload["series"] = {"id": series_id}
    
    print(f"[CORRECTION] Payload: contractor_id={contractor_id}, parent_id={parent_invoice_id}, positions={len(positions)}")
    
    # 4) Utwórz fakturę korygującą
    invoice_result, resp = wfirma_create_invoice(token, correction_payload, wfirma_company_id)
    
    if invoice_result and invoice_result.get('id'):
        return jsonify({
            'success': True,
            'message': 'Faktura korygująca utworzona',
            'correction_invoice': {
                'id': invoice_result.get('id'),
                'fullnumber': invoice_result.get('fullnumber'),
                'type': invoice_result.get('type'),
                'parent_invoice_id': parent_invoice_id,
                'netto': invoice_result.get('netto'),
                'brutto': invoice_result.get('brutto'),
                'contractor_id': contractor_id,
                'correction_reason': correction_reason
            },
            'original_invoice': {
                'id': original_invoice.get('id'),
                'fullnumber': original_invoice.get('fullnumber')
            }
        }), 200
    else:
        # Błąd
        error_details = ''
        if resp:
            try:
                error_details = resp.text[:1000]
            except Exception:
                pass
        return jsonify({
            'error': 'Nie udało się utworzyć faktury korygującej',
            'details': error_details,
            'parent_invoice_id': parent_invoice_id
        }), 500


# ==================== ENDPOINT STOPKA EMAIL - UPLOAD ZDJĘĆ ====================

def cors_response(data, status=200):
    """Helper do zwracania odpowiedzi z nagłówkami CORS"""
    response = jsonify(data)
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key'
    return response, status


@app.route('/api/stopka/upload-photo', methods=['POST', 'OPTIONS'])
def upload_stopka_photo():
    """
    Przyjmuje zdjęcie base64, pushuje na GitHub repo Stopka_email,
    zwraca publiczny URL raw.githubusercontent.com
    
    Headers: X-API-Key: <HTML_GENERATOR_API_KEY_TOKEN>
    Body: { "image_base64": "data:image/png;base64,..." }
    Response: { "success": true, "url": "https://raw.githubusercontent.com/...", "filename": "abc123.png" }
    """
    # Obsługa CORS preflight (OPTIONS)
    if request.method == 'OPTIONS':
        return cors_response({'status': 'ok'})
    
    # Sprawdź osobny token dla tego endpointu
    api_key = request.headers.get('X-API-Key', '')
    if not HTML_GENERATOR_API_KEY_TOKEN:
        return cors_response({'success': False, 'error': 'Brak HTML_GENERATOR_API_KEY_TOKEN w konfiguracji serwera'}, 500)
    if api_key != HTML_GENERATOR_API_KEY_TOKEN:
        return cors_response({'success': False, 'error': 'Unauthorized - nieprawidłowy token'}, 401)
    
    print(f"[STOPKA] === START upload-photo ===")
    data = request.get_json(silent=True) or {}
    
    if 'image_base64' not in data:
        print(f"[STOPKA] BŁĄD: Brak image_base64 w request body")
        return cors_response({'success': False, 'error': 'Brak image_base64'}, 400)
    
    if not GITHUB_STOPKA_TOKEN:
        print(f"[STOPKA] BŁĄD: Brak ADMINZOHO_GITHUB_STOPKA_TOKEN w ENV")
        return cors_response({'success': False, 'error': 'Brak ADMINZOHO_GITHUB_STOPKA_TOKEN w konfiguracji'}, 500)
    
    try:
        # Dekoduj base64
        image_data = data['image_base64']
        original_length = len(image_data)
        print(f"[STOPKA] Otrzymano image_base64, długość={original_length}")
        
        if ',' in image_data:
            image_data = image_data.split(',')[1]  # usuń prefix "data:image/png;base64,"
            print(f"[STOPKA] Usunięto prefix data:..., nowa długość={len(image_data)}")
        
        image_bytes = base64.b64decode(image_data)
        print(f"[STOPKA] Zdekodowano base64, rozmiar obrazu={len(image_bytes)} bajtów ({len(image_bytes)/1024:.1f} KB)")
        
        # Generuj losową nazwę (40 znaków)
        random_name = uuid.uuid4().hex + uuid.uuid4().hex[:8]  # 32 + 8 = 40 znaków
        filename = f"{random_name}.png"
        filepath = f"photos/{filename}"
        print(f"[STOPKA] Wygenerowano nazwę pliku: {filename}")
        
        # Push na GitHub via API
        repo = "adminzohomedidesk/Stopka_email"
        branch = "main"
        
        url = f"https://api.github.com/repos/{repo}/contents/{filepath}"
        print(f"[STOPKA] GitHub API URL: {url}")
        
        headers = {
            "Authorization": f"token {GITHUB_STOPKA_TOKEN[:4]}...{GITHUB_STOPKA_TOKEN[-4:]}",  # log tylko fragment tokena
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Przygotuj prawdziwe headery (pełny token)
        real_headers = {
            "Authorization": f"token {GITHUB_STOPKA_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        payload = {
            "message": f"Add photo {filename}",
            "content": base64.b64encode(image_bytes).decode('utf-8'),
            "branch": branch
        }
        
        print(f"[STOPKA] Wysyłam PUT do GitHub API (token: {GITHUB_STOPKA_TOKEN[:4]}...)")
        response = requests.put(url, json=payload, headers=real_headers, timeout=30)
        print(f"[STOPKA] GitHub response status={response.status_code}")
        
        if response.status_code in [200, 201]:
            public_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{filepath}"
            print(f"[STOPKA] Upload OK: {public_url}")
            return cors_response({
                'success': True,
                'url': public_url,
                'filename': filename
            })
        else:
            print(f"[STOPKA] GitHub API error: {response.status_code} - {response.text[:500]}")
            return cors_response({
                'success': False,
                'error': f"GitHub API error: {response.status_code} - {response.text}"
            }, 500)
    
    except Exception as e:
        print(f"[STOPKA] Exception: {e}")
        return cors_response({'success': False, 'error': str(e)}, 500)


# ==================== START SERWERA ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

