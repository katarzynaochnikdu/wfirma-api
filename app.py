""" 
wFirma API - Web Service dla Render
Flask web app z OAuth 2.0 i endpointami API
"""
from flask import Flask, request, redirect, jsonify, Response, send_file, session
import requests
import json
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

# --- Odporność na niedostępność GUS-u (WO-469 / BUG-056, 2026-08-26) -------------------
# Tego dnia rejestr przez ~40 minut odrzucał ruch z Rendera (read timeout / 503).
# Przy timeoucie 10 s i zerowych ponowieniach każda próba padała od razu, co zatrzymało
# sprzedaż B2B w koszyku.
#
# BUDŻET CZASU JEST OGRANICZONY PRZEZ LICZBĘ WORKERÓW, NIE PRZEZ CIERPLIWOŚĆ KLIENTA.
# Procfile daje `gunicorn --workers 2 --timeout 180`, a ten sam proces obsługuje wystawianie
# faktur wFirma i LeadProcessor. Gdyby jedno zapytanie do GUS-u okupowało worker przez 79 s,
# awaria rejestru przewróciłaby przy okazji fakturowanie — czyli naprawa jednego problemu
# wyprodukowałaby gorszy. Stąd podział:
#   * LOGOWANIE — krótki timeout i ponowienia. Gdy GUS działa, loguje się w ~0,4 s
#     (zmierzone), więc 8 s to 20× zapas; ponowienia łapią przejściowe dławienie.
#   * WYSZUKIWANIE — bez ponowień, timeout tylko lekko podniesiony. Skoro logowanie
#     przeszło, sesja żyje i drugi strzał zwykle też przechodzi.
# Najgorszy przypadek: 3×8 s + 3 s przerw + 20 s = ~47 s, z zapasem do gunicornowych 180 s.
GUS_LOGIN_TIMEOUT = int(os.environ.get('GUS_LOGIN_TIMEOUT', '8'))
GUS_SOAP_TIMEOUT = int(os.environ.get('GUS_SOAP_TIMEOUT', '20'))
GUS_LOGIN_ATTEMPTS = int(os.environ.get('GUS_LOGIN_ATTEMPTS', '3'))
GUS_RETRY_BACKOFF_S = (1, 2)

# GitHub token do uploadu zdjęć stopki email
GITHUB_STOPKA_TOKEN = os.environ.get('ADMINZOHO_GITHUB_STOPKA_TOKEN')

# Token dla endpointu stopka/upload-photo (osobny od MAKE_RENDER_API_KEY)
HTML_GENERATOR_API_KEY_TOKEN = os.environ.get('HTML_GENERATOR_API_KEY_TOKEN')

# Token dla endpointów GUS/REGON (osobny od MAKE_RENDER_API_KEY)
REGON_API_KEY_TOKEN = os.environ.get('REGON_API_KEY_TOKEN')

# CORS tylko dla /api/gus/* (oddzielnie od cors_response używanego m.in. przez wFirma).
# Lista dozwolonych Origin rozdzielona przecinkami, np.:
#   https://xxxx.ngrok-free.app,https://twoj-widget.zohobackstage.eu
# Puste = nagłówek Access-Control-Allow-Origin: * (jak wcześniej, kompatybilność wsteczna).
def _parse_gus_cors_origins(raw: str) -> tuple[str, ...]:
    out: list[str] = []
    for part in (raw or '').split(','):
        s = part.strip().rstrip('/')
        if s:
            out.append(s)
    return tuple(out)


GUS_CORS_ALLOWED_ORIGINS = _parse_gus_cors_origins(os.environ.get('GUS_CORS_ORIGINS', ''))


def gus_cors_response(data, status=200):
    """JSON + CORS dla endpointów GUS — whitelist z GUS_CORS_ORIGINS; pusta lista = Allow-Origin *."""
    response = jsonify(data)
    response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key, x-gus-api-key'
    response.headers['Access-Control-Max-Age'] = '86400'
    origin = (request.headers.get('Origin') or '').strip().rstrip('/')
    if GUS_CORS_ALLOWED_ORIGINS:
        if origin and origin in GUS_CORS_ALLOWED_ORIGINS:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Vary'] = 'Origin'
    else:
        response.headers['Access-Control-Allow-Origin'] = '*'
    return response, status


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

# Seria faktur korygujących (używana w wfirma_create_correction)
WFIRMA_SERIES_CORRECTION = os.environ.get("WFIRMA_SERIES_CORRECTION", "Eventy Korekta")
WFIRMA_SERIES_CORRECTION_TEST = os.environ.get("WFIRMA_SERIES_CORRECTION_TEST", "Eventy Korekta TEST")



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
        # DB
        "DATABASE_URL",
    ]
    optional = [
        "MAKE_WEBHOOK_SEND_EMAIL_REQUEST",
    ]

    missing_critical = [k for k in critical if not _present(k)]
    missing_optional = [k for k in optional if not _present(k)]

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

def _refresh_access_token_inner(config, company, company_name, pg_company, prefix, log_prefix, skip_fresh_check, get_wfirma_token_fn=None):
    """Wewnętrzna logika refreshu tokena — wywoływana wewnątrz advisory_lock_ctx."""
    try:
        print(f"{log_prefix} START skip_fresh_check={skip_fresh_check} pg_company={pg_company}")
        now_ts = int(time.time())
        pg_tok = None
        if get_wfirma_token_fn:
            pg_tok = get_wfirma_token_fn(pg_company)
        
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
        if pg_tok and pg_tok.get("refresh_token"):
            refresh_token = _normalize_env_secret(pg_tok.get("refresh_token"))
            refresh_source = "pg"

        if not refresh_token:
            print(f"{log_prefix} Brak refresh tokena w Postgres - wymagana autoryzacja /auth?company={company_name}")
            return None

        old_refresh_fp = _token_fingerprint(refresh_token)
        print(f"{log_prefix} refresh_source={refresh_source} fp={old_refresh_fp}")
        
        token_url = "https://api2.wfirma.pl/oauth2/token"
        payload = {
            'grant_type': 'refresh_token',
            'client_id': config['client_id'],
            'client_secret': config['client_secret'],
            'refresh_token': refresh_token
        }

        response = requests.post(token_url, data=payload)
        print(f"{log_prefix} RESPONSE status_code={response.status_code}")
        
        if response.status_code == 200:
            new_tokens = response.json()
            new_access = new_tokens.get('access_token')
            new_refresh = new_tokens.get('refresh_token')
            expires_in = int(new_tokens.get('expires_in', 3600))
            
            if new_access:
                if new_refresh:
                    print(f"{log_prefix} ROTACJA REFRESH TOKEN old_fp={old_refresh_fp} new_fp={_token_fingerprint(new_refresh)}")
                
                save_token(
                    new_access,
                    expires_in,
                    refresh_token=new_refresh,
                    company=company,
                    send_refresh_email=False,
                    refresh_token_source="refresh_rotation" if new_refresh else None,
                )
                print(f"{log_prefix} SUKCES - Access token odświeżony")
                return new_access

            print(f"{log_prefix} BŁĄD - Brak access_token w odpowiedzi, keys={list(new_tokens.keys())}")
            return None

        print(f"{log_prefix} BŁĄD API status={response.status_code} body={response.text[:500] if response.text else 'PUSTY'}")
        return None
    except Exception as e:
        print(f"{log_prefix} EXCEPTION: {e}")
        traceback.print_exc()
        return None
    finally:
        try:
            print(f"{log_prefix} END")
        except Exception:
            pass


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
    log_prefix = f"[TOKEN REFRESH] [{company_name.upper()}]"

    # Użyj context managera — lock i unlock na TYM SAMYM połączeniu
    try:
        from pg_storage import advisory_lock_ctx, get_wfirma_token as _gwt
    except Exception as e:
        print(f"[LOG] [{company_name.upper()}] Brak pg_storage (fallback bez locka): {e}")
        return _refresh_access_token_inner(config, company, company_name, pg_company, prefix, log_prefix, skip_fresh_check, get_wfirma_token_fn=None)

    with advisory_lock_ctx(lock_id):
        return _refresh_access_token_inner(config, company, company_name, pg_company, prefix, log_prefix, skip_fresh_check, get_wfirma_token_fn=_gwt)

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


def wfirma_find_contractor_by_name(token: str, name: str, company_id: str = None) -> tuple[dict | None, requests.Response | None]:
    """Znajdź kontrahenta po nazwie; zwraca (contractor_dict|None, response)."""
    api_url = "https://api2.wfirma.pl/contractors/find?inputFormat=json&outputFormat=json&oauth_version=2"
    if company_id:
        api_url += f"&company_id={company_id}"
    print(f"[WFIRMA DEBUG] find_contractor_by_name URL: {api_url}")
    headers = get_wfirma_headers(token)
    search_data = {
        "contractors": {
            "parameters": {
                "conditions": {
                    "condition": {
                        "field": "name",
                        "operator": "like",
                        "value": f"%{name}%"
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


_ZIP_PL_RE = re.compile(r'^\d{2}-\d{3}$')


def _normalize_zip_pl(value) -> str | None:
    """Sprowadza polski kod pocztowy do formatu XX-XXX, którego wymaga wFirma.

    Zwraca None, gdy z wejścia nie da się odczytać dokładnie pięciu cyfr. Wtedy
    jakiekolwiek "naprawianie" byłoby zmyślaniem adresu nabywcy, więc decyzję
    zostawiamy wywołującemu.
    """
    if not value:
        return None
    text = str(value).strip()
    if _ZIP_PL_RE.match(text):
        return text
    digits = re.sub(r'\D', '', text)
    if len(digits) == 5:
        return f"{digits[:2]}-{digits[2:]}"
    return None


def wfirma_add_contractor(token: str, contractor_payload: dict, company_id: str = None) -> tuple[dict | None, requests.Response | None]:
    """Dodaj kontrahenta; zwraca (contractor_dict|None, response)."""
    # 2026-08-09: wFirma przyjmuje polski kod pocztowy WYŁĄCZNIE jako XX-XXX i przy
    # innym zapisie odrzuca całego kontrahenta ("zip: Niepoprawny format kodu
    # pocztowego."), przez co opłacone zamówienie zostaje bez faktury (incydent
    # CART-27847BCD0017 — klientka wpisała kod bez myślnika). Prostujemy tutaj, bo to
    # jedyna brama do wFirmy dla kontrahentów: workflow (GUS i purchaser) oraz ręczne
    # /api/contractor/add. Dzięki temu żadna ścieżka — także dopisana później — nie
    # może tego pominąć.
    #
    # Kodów spoza PL nie ruszamy: XX-XXX ich nie dotyczy, a wymuszenie go zepsułoby
    # poprawny adres (np. brytyjski "SW1A 1AA" czy niemiecki "10115").
    country = str(contractor_payload.get('country') or 'PL').strip().upper()
    raw_zip = contractor_payload.get('zip')
    if raw_zip and country in ('PL', 'POLSKA', 'POLAND'):
        fixed_zip = _normalize_zip_pl(raw_zip)
        if not fixed_zip:
            print(f"[WFIRMA] UWAGA: kod pocztowy '{raw_zip}' nie jest w formacie XX-XXX "
                  f"i nie da się go odtworzyć — wysyłam bez zmian, wFirma prawdopodobnie odmówi")
        elif fixed_zip != str(raw_zip).strip():
            print(f"[WFIRMA] Poprawiono format kodu pocztowego: '{raw_zip}' -> '{fixed_zip}'")
            contractor_payload = {**contractor_payload, 'zip': fixed_zip}

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


def _extract_wfirma_errors(contractor: dict | None) -> list[str]:
    """Wyciąga listę błędów walidacji z odpowiedzi wFirma contractor.
    
    wFirma zwraca errors jako zagnieżdżony dict:
    {"errors": {"0": {"error": {"field": "email", "message": "Nieprawidłowy adres e-mail."}}}}
    """
    if not contractor or not isinstance(contractor, dict):
        return []
    errors_dict = contractor.get('errors')
    if not errors_dict or not isinstance(errors_dict, dict):
        return []
    messages = []
    for key in errors_dict:
        err = errors_dict[key]
        if isinstance(err, dict):
            inner = err.get('error', err)
            field = inner.get('field', '?')
            msg = inner.get('message', str(inner))
            messages.append(f"{field}: {msg}")
    return messages


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


# ==================== ODBIORCA INNY NIZ NABYWCA (WO-471) ====================
#
# Faktura wFirma potrafi miec Odbiorce odrebnego od Nabywcy. Uklad wymagany m.in. przez
# GRUPY VAT: podatnikiem jest grupa (Nabywca), a swiadczenie odbiera jej czlonek (Odbiorca).
#
# ⚠️ WFIRMA GUBI ODBIORCE PO CICHU — najwazniejsza rzecz w tym module.
# Payload z samym `contractor_receiver_id` konczy sie `status: OK`, dokument POWSTAJE,
# a odczyt zwrotny pokazuje `contractor_receiver: {"id": 0}`. Zmierzone 2026-08-26 na
# dokumencie PROF/EV/TEST/4/8/2026. Zeby Odbiorca sie zapisal, musza pojsc OBA klucze:
#   * `contractor_receiver_id`     — wskazanie kontrahenta,
#   * `contractor_detail_receiver` — pelna migawka (rola + nazwa + identyfikator + adres).
# Sama rola bez adresu tez nie wystarcza (sprawdzone).
#
# Dlatego `workflow_create_invoice` po utworzeniu dokumentu SPRAWDZA ODCZYTEM, czy Odbiorca
# tam jest. Bez tej asercji faktura pojechalaby do klienta bez Odbiorcy, a system
# zaraportowalby sukces — czyli najgorszy mozliwy wariant: cichy blad na dokumencie ksiegowym.

#: Rola migawki odbiorcy. Puste pole = wFirma odrzuca CALA fakture
#: ("role: Pole nie moze byc puste.").
RECEIVER_ROLE = "receiver"


def _resolve_tax_id_type(identifier: str | None) -> str:
    """Typ identyfikatora podatkowego dla wFirmy: `nip` | `custom` | `none`.

    wFirma dopuszcza `nip|vat|pesel|regon|custom|none` i WALIDUJE `nip`. Identyfikator
    jednostki wewnetrznej grupy VAT (`5272663852-80408` — NIP grupy + kod czlonka) dostaje
    przy typie `nip` odpowiedz "Nieprawidlowy NIP. Jesli identyfikator nie jest polskim
    numerem NIP nalezy zmienic jego typ". Stad: ksztalt polskiego NIP-u -> `nip`,
    cokolwiek innego niepustego -> `custom` (przechodzi doslownie), pusto -> `none`.
    """
    raw = (identifier or "").strip()
    if not raw:
        return "none"
    compact = re.sub(r"[\s\-]", "", raw)
    if re.fullmatch(r"\d{10}", compact):
        return "nip"
    return "custom"


def build_receiver_snapshot(receiver: dict) -> dict:
    """Migawka odbiorcy do `contractor_detail_receiver`.

    Kod pocztowy prostujemy tym samym `_normalize_zip_pl` co dla nabywcy — wFirma przyjmuje
    polski kod WYLACZNIE jako XX-XXX i przy innym zapisie odrzuca dokument.
    """
    identifier = (receiver.get("nip") or "").strip()
    country = ((receiver.get("country") or "PL").strip().upper()) or "PL"

    zip_raw = (receiver.get("zip") or "").strip()
    zip_value = zip_raw
    if zip_raw and country in ("PL", "POLSKA", "POLAND"):
        fixed = _normalize_zip_pl(zip_raw)
        if fixed:
            if fixed != zip_raw:
                print(f"[RECEIVER] Poprawiono kod pocztowy odbiorcy: '{zip_raw}' -> '{fixed}'")
            zip_value = fixed

    snapshot = {
        "role": RECEIVER_ROLE,
        "name": (receiver.get("name") or "").strip(),
        "tax_id_type": (receiver.get("tax_id_type") or "").strip() or _resolve_tax_id_type(identifier),
        "street": (receiver.get("street") or "").strip(),
        "zip": zip_value,
        "city": (receiver.get("city") or "").strip(),
        "country": country,
    }
    if identifier:
        snapshot["nip"] = identifier
    return snapshot


def receiver_stored_id(stored_invoice: dict | None) -> int:
    """Odczytuje `contractor_receiver.id` z dokumentu pobranego z wFirmy.

    Zwraca 0, gdy odbiorcy nie ma — a to jest wlasnie objaw cichej utraty, ktorego
    szukamy. Brak dokumentu tez daje 0 (nie potrafimy potwierdzic = traktujemy jak brak).
    """
    if not isinstance(stored_invoice, dict):
        return 0
    node = stored_invoice.get('contractor_receiver')
    if not isinstance(node, dict):
        return 0
    try:
        return int(node.get('id') or 0)
    except (TypeError, ValueError):
        return 0


def wfirma_find_contractor_by_tax_id(token: str, identifier: str, company_id: str = None) -> dict | None:
    """Szuka kontrahenta po polu `nip` — DOSLOWNIE, a dopiero potem bez separatorow.

    `wfirma_find_contractor_by_nip` czysci myslniki, wiec NIE znajduje kontrahenta zapisanego
    z identyfikatorem jednostki wewnetrznej (`5272663852-80408` w bazie vs `527266385280408`
    w zapytaniu). Bez tej funkcji kazda kolejna faktura zakladalaby DUPLIKAT odbiorcy.
    """
    raw = (identifier or "").strip()
    if not raw:
        return None

    candidates = [raw]
    compact = raw.replace("-", "").replace(" ", "")
    if compact and compact != raw:
        candidates.append(compact)

    api_url = "https://api2.wfirma.pl/contractors/find?inputFormat=json&outputFormat=json&oauth_version=2"
    if company_id:
        api_url += f"&company_id={company_id}"
    headers = get_wfirma_headers(token)

    for value in candidates:
        body = {"contractors": {"parameters": {"conditions": {"condition": {
            "field": "nip", "operator": "eq", "value": value}}}}}
        try:
            resp = requests.post(api_url, headers=headers, json=body)
            if resp.status_code != 200:
                continue
            contractors = resp.json().get("contractors", {})
            if not isinstance(contractors, dict):
                continue
            for key in contractors:
                if not (key.isdigit() or key == "contractor"):
                    continue
                node = contractors[key]
                found = node.get("contractor") if isinstance(node, dict) else None
                if found and _extract_contractor_id(found):
                    return found
        except Exception as exc:
            print(f"[RECEIVER] Szukanie po identyfikatorze '{value}' nie powiodlo sie: {exc}")
    return None


def wfirma_resolve_receiver_contractor(
    token: str, receiver: dict, company_id: str = None
) -> tuple[dict | None, list[str]]:
    """Znajdz albo zaloz kontrahenta-odbiorce. Zwraca `(contractor|None, bledy)`.

    Kaskada jak dla nabywcy: po identyfikatorze -> po nazwie -> zalozenie. Roznica jest
    jedna i istotna: szukamy `wfirma_find_contractor_by_tax_id`, bo identyfikator odbiorcy
    czesto NIE jest polskim NIP-em i wersja czyszczaca myslniki go nie trafia.
    """
    name = (receiver.get("name") or "").strip()
    identifier = (receiver.get("nip") or "").strip()

    if identifier:
        found = wfirma_find_contractor_by_tax_id(token, identifier, company_id)
        if found:
            print(f"[RECEIVER] Odbiorca znaleziony po identyfikatorze: id={_extract_contractor_id(found)}")
            return found, []

    if name:
        found, _resp = wfirma_find_contractor_by_name(token, name, company_id)
        if found and _extract_contractor_id(found):
            print(f"[RECEIVER] Odbiorca znaleziony po nazwie: id={_extract_contractor_id(found)}")
            return found, []
    else:
        return None, ["name: Odbiorca wymaga nazwy"]

    payload = {k: v for k, v in build_receiver_snapshot(receiver).items() if k != "role"}
    payload["altname"] = payload.get("name")
    created, _resp_add = wfirma_add_contractor(token, payload, company_id)
    if created and _extract_contractor_id(created):
        print(f"[RECEIVER] Odbiorca zalozony: id={_extract_contractor_id(created)}")
        return created, []

    errors = _extract_wfirma_errors(created)
    return None, errors or ["wFirma nie zwrocila ID kontrahenta-odbiorcy"]


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
        print(f"[WFIRMA DEBUG] wfirma_create_invoice response status: {resp.status_code}")
        if resp.status_code == 200:
            result = resp.json()

            # WAŻNE: wFirma.pl zwraca HTTP 200 nawet przy błędach!
            # Sprawdź status.code w JSON
            wfirma_status = result.get('status', {})
            if isinstance(wfirma_status, dict) and wfirma_status.get('code') == 'ERROR':
                print(f"[WFIRMA ERROR] wFirma zwróciło HTTP 200 ale status.code=ERROR!")
                print(f"[WFIRMA ERROR] Response body: {resp.text[:2000]}")
                return None, resp

            # Odpowiedź: invoices.0.invoice
            invoices = result.get('invoices', {})
            if isinstance(invoices, dict):
                for key in invoices:
                    if key.isdigit():
                        invoice = invoices[key].get('invoice', {})
                        if invoice and invoice.get('id'):
                            print(f"[WFIRMA DEBUG] Invoice created successfully: id={invoice.get('id')}, fullnumber={invoice.get('fullnumber')}")
                            return invoice, resp
            print(f"[WFIRMA DEBUG] wfirma_create_invoice: status 200 but no invoice in response. Full response: {resp.text[:2000]}")
            return None, resp
        else:
            # Logowanie błędu z wFirma.pl (ograniczone do 2000 znaków żeby nie jeść RAM)
            print(f"[WFIRMA ERROR] wfirma_create_invoice FAILED! Status: {resp.status_code}")
            print(f"[WFIRMA ERROR] Response body: {resp.text[:2000]}")
            return None, resp
    except Exception as e:
        print(f"[WFIRMA ERROR] wfirma_create_invoice EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return None, resp


def wfirma_create_correction(
    token: str,
    source_invoice_id: str,
    correction_description: str = "Anulowanie zamówienia",
    company_id: str = None,
    series_name_override: str | None = None,
    mark_refund_settled: bool = False,
    send_email: bool = True,
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
        contractor_email = contractor_data.get('email') if isinstance(contractor_data, dict) else None
        

        
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
        # Wg Postman: wysyłamy parent_id, name (oryginalne), count, price
        invoice_contents_dict = {}
        for idx, pos in enumerate(positions):
            content = {
                "invoicecontent": {
                    "parent_id": int(pos.get('id')),
                    "name": pos.get('name', ''),
                    "count": 0,
                    "price": 0
                }
            }
            invoice_contents_dict[str(idx)] = content
            print(f"[WFIRMA DEBUG] Correction pos {idx}: parent_id={pos.get('id')}, name={pos.get('name')}, zerowanie")
        
        # 3.5) Pobierz serię korekty (jeśli skonfigurowana)
        # Brak żądanej serii = TWARDY BŁĄD - korekta bez serii dostałaby domyślną
        # numerację, co maskuje wystawianie dokumentu w niewłaściwej firmie
        series_id = None
        series_to_use = series_name_override or WFIRMA_SERIES_CORRECTION
        if series_to_use:
            series = wfirma_find_series_by_name(token, series_to_use, company_id)
            if series and series.get('id'):
                series_id = int(series.get('id'))
                print(f"[WFIRMA DEBUG] Znaleziono serię korekty: {series_to_use} -> ID {series_id}")
            else:
                print(f"[WFIRMA ERROR] Nie znaleziono serii korekty '{series_to_use}' (company_id={company_id}) - przerywam, korekta NIE zostanie wystawiona")
                return None, None
        
        # 4) Payload faktury korygującej
        import datetime
        correction_payload = {
            "contractor_id": int(contractor_id),
            "date": datetime.date.today().isoformat(),
            "type": "correction",
            "parent_id": int(source_invoice_id),  # FLAT parent_id (nie obiekt parent.id!)
            "description": correction_description,
            "invoicecontents": invoice_contents_dict,
            "send": send_email,
        }
        
        # Dodaj serię korekty jeśli znaleziono
        if series_id:
            correction_payload["series_id"] = series_id
        
        # Dodaj email kontrahenta jeśli dostępny
        if contractor_email:
            correction_payload["email"] = contractor_email
            print(f"[WFIRMA DEBUG] Correction will be sent to: {contractor_email}")
        else:
            print(f"[WFIRMA DEBUG] Warning: No contractor email, correction may not be sent")
        
        print(f"[WFIRMA DEBUG] Correction payload: contractor_id={contractor_id}, parent_id={source_invoice_id}, positions={len(positions)}, send=True, email={contractor_email or 'BRAK'}")
        
        # 5) Utwórz fakturę korygującą
        invoice_result, resp = wfirma_create_invoice(token, correction_payload, company_id)
        
        if invoice_result and invoice_result.get('id'):
            correction_id = invoice_result.get('id')
            correction_number = invoice_result.get('fullnumber')
            print(f"[WFIRMA DEBUG] Correction created: id={correction_id}, number={correction_number}")

            # Oznacz korektę jako rozliczoną (odhacz przepływ gotówki) jeśli mark_refund_settled
            if mark_refund_settled:
                try:
                    brutto_raw = invoice_result.get('brutto') or invoice_result.get('total') or '0'
                    try:
                        brutto_val = float(str(brutto_raw).replace(',', '.'))
                    except (ValueError, TypeError):
                        brutto_val = 0.0
                    amount_to_settle = abs(brutto_val)
                    if amount_to_settle > 0:
                        ok, _ = wfirma_mark_invoice_paid(token, str(correction_id), amount_to_settle, company_id)
                        if ok:
                            print(f"[WFIRMA DEBUG] Korekta {correction_number} oznaczona jako rozliczona (alreadypaid_initial={amount_to_settle})")
                        else:
                            print(f"[WFIRMA DEBUG] Nie udało się oznaczyć korekty jako rozliczonej")
                    else:
                        print(f"[WFIRMA DEBUG] Korekta ma brutto=0, pomijam mark_refund_settled")
                except Exception as ex:
                    print(f"[WFIRMA DEBUG] Wyjątek przy mark_refund_settled: {ex}")
            
            # Wyślij korektę emailem jeśli kontrahent ma email
            if send_email and contractor_email and '@' in contractor_email:
                try:
                    print(f"[WFIRMA DEBUG] Sending correction email to: {contractor_email}")
                    resp_email = wfirma_send_invoice_email(token, str(correction_id), contractor_email, company_id)
                    print(f"[WFIRMA DEBUG] send correction email status: {resp_email.status_code}")
                    if resp_email.status_code == 200:
                        print(f"[WFIRMA DEBUG] Correction email sent successfully to {contractor_email}")
                    else:
                        print(f"[WFIRMA DEBUG] Correction email failed: {resp_email.text[:300] if resp_email.text else 'no body'}")
                except Exception as email_ex:
                    print(f"[WFIRMA DEBUG] Exception sending correction email: {email_ex}")
            else:
                print(f"[WFIRMA DEBUG] Skipping correction email - no valid contractor email")
            
            return invoice_result, resp
        else:
            print(f"[WFIRMA ERROR] Nie udało się utworzyć korekty!")
            if resp:
                print(f"[WFIRMA ERROR] Status: {resp.status_code}, Body: {resp.text[:2000]}")
            else:
                print(f"[WFIRMA ERROR] No response object (resp is None)")
            return None, resp

    except Exception as e:
        print(f"[WFIRMA ERROR] Correction exception: {e}")
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


# Przypięte ID firm w wFirma per zestaw (md/test).
# INCYDENT 2026-07-09: konto integracyjne widzi 2 firmy (Medidesk 130706 i Vetidesk 545419),
# a companies/find zwraca je w NIEGWARANTOWANEJ kolejności (podąża za firmą wybraną w panelu).
# Branie "pierwszej z listy" wystawiło proformę w księgach Vetidesk. Dlatego ID firmy
# NIGDY nie może być zgadywane - musi być przypięte tutaj lub w ENV WFIRMA_<COMPANY>_COMPANY_ID.
WFIRMA_KNOWN_COMPANY_IDS = {
    'md': '130706',  # Medidesk Sp. z o.o.
}


def wfirma_get_company_id(token: str, company: str = None) -> str | None:
    """
    Zwraca ID firmy wFirma dla zestawu md/test/md_test.

    Kolejność źródeł:
    1. ENV WFIRMA_<COMPANY>_COMPANY_ID (np. WFIRMA_MD_COMPANY_ID) - jawne przypięcie.
    2. WFIRMA_KNOWN_COMPANY_IDS (wbudowane, md -> Medidesk 130706).
    3. companies/find - TYLKO gdy konto widzi dokładnie jedną firmę.
       Przy >1 firmach zwraca None (fail-loud) zamiast zgadywać.
    """
    config = get_company_config(company)
    pinned = (os.environ.get(f"{config['prefix']}COMPANY_ID") or '').strip()
    if pinned:
        return pinned
    known = WFIRMA_KNOWN_COMPANY_IDS.get(config['pg_company'])
    if known:
        return known

    api_url = "https://api2.wfirma.pl/companies/find?inputFormat=json&outputFormat=json&oauth_version=2"
    headers = get_wfirma_headers(token)
    body = {"companies": {"parameters": {"limit": "20"}}}

    try:
        resp = requests.post(api_url, headers=headers, json=body)
        print(f"[WFIRMA DEBUG] get_company_id status: {resp.status_code}")
        print(f"[WFIRMA DEBUG] get_company_id response: {resp.text[:500]}")

        if resp.status_code == 200:
            data = resp.json()
            companies = data.get('companies', {})
            print(f"[WFIRMA DEBUG] companies keys: {list(companies.keys()) if companies else None}")

            found = []
            if isinstance(companies, dict):
                for key in companies:
                    if key.isdigit() or key == '0':
                        comp = companies[key].get('company', {})
                        if comp.get('id'):
                            found.append(comp)

            if len(found) == 1:
                company_id = str(found[0].get('id'))
                print(f"[WFIRMA DEBUG] Found company_id: {company_id}")
                return company_id
            if len(found) > 1:
                print(f"[WFIRMA ERROR] Konto widzi {len(found)} firm - odmawiam zgadywania, ustaw {config['prefix']}COMPANY_ID:")
                for comp in found:
                    print(f"[WFIRMA ERROR]   - id={comp.get('id')}, name={comp.get('name')}, nip={comp.get('nip')}")
                return None
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
        login_resp = post_soap_gus_retry(bir_host, login_envelope, sid=None)
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
        search_resp = post_soap_gus(bir_host, search_envelope, sid=sid)
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
    UWAGA: NIE dekodujemy &amp; na & - xml.etree.ElementTree sam to robi poprawnie!
    """
    if not isinstance(encoded, str):
        return ""

    return (
        encoded.lstrip("\ufeff")
        .replace("&amp;amp;", "&amp;")  # podwójne kodowanie → pojedyncze (dla parsera XML)
        .replace("&#xD;", "\r")
        .replace("&#xA;", "\n")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        # NIE dekodujemy &amp; → & tutaj - parser XML robi to automatycznie
        .strip()
    )


def post_soap_gus(bir_host: str, envelope: str, sid: str | None, timeout: int = GUS_SOAP_TIMEOUT) -> requests.Response:
    """
    Minimalna wersja postSoap z Googie_GUS – wysyła envelope SOAP do GUS/BIR.
    Timeout domyślnie GUS_SOAP_TIMEOUT (WO-469). Nagłówek 'sid' ustawiany jeśli podano.
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


def post_soap_gus_retry(bir_host: str, envelope: str, sid: str | None = None,
                        timeout: int = GUS_LOGIN_TIMEOUT,
                        attempts: int = GUS_LOGIN_ATTEMPTS) -> requests.Response:
    """
    post_soap_gus z ponowieniami — WO-469 (BUG-056).

    2026-08-26 GUS przez ~40 minut odrzucał ruch z naszego serwera (read timeout / 503),
    a pojedynczy strzał bez ponowienia zamieniał to w zatrzymanie sprzedaży B2B.

    Ponawiamy WYŁĄCZNIE to, co rokuje: wyjątek transportowy (timeout, zerwane połączenie)
    oraz 5xx, czyli „spróbuj później" po stronie GUS-u. Kod 4xx (m.in. 401 przy złym kluczu)
    NIE jest ponawiany — powtórka nic nie zmieni, a tylko wydłuży oczekiwanie użytkownika.

    Rzuca ostatni wyjątek, jeśli żadna próba nie dała odpowiedzi. Ostatnią odpowiedź 5xx
    zwraca normalnie — rozpoznanie i tak należy do wywołującego (brak SID => błąd).
    """
    last_exc: Exception | None = None
    last_resp: requests.Response | None = None

    for attempt in range(1, max(1, attempts) + 1):
        try:
            resp = post_soap_gus(bir_host, envelope, sid=sid, timeout=timeout)
            if resp.status_code < 500:
                return resp
            last_resp = resp
            print(f"[GUS-RETRY] proba {attempt}/{attempts}: HTTP {resp.status_code} od GUS")
        except Exception as e:
            last_exc = e
            print(f"[GUS-RETRY] proba {attempt}/{attempts}: {type(e).__name__}: {e}")

        if attempt < attempts:
            time.sleep(GUS_RETRY_BACKOFF_S[min(attempt - 1, len(GUS_RETRY_BACKOFF_S) - 1)])

    if last_resp is not None:
        return last_resp
    raise last_exc if last_exc else RuntimeError("GUS: brak odpowiedzi i brak wyjątku")


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


@app.route('/api/token/health', methods=['GET'])
def token_health():
    """
    Publiczny status tokena wFirma (dla domyślnej firmy: md).
    Zwraca czytelny stan: ważny, wygasa, lub wygasł.
    Otwarty endpoint np. dla uptime monitoring.
    """
    company = request.args.get('company', DEFAULT_COMPANY)
    from pg_storage import get_wfirma_token
    token_data = get_wfirma_token(_pg_company_name(company))
    
    if not token_data:
        return jsonify({
            "status": "expired",
            "message": "❌ Token nie istnieje! Wymagana ponowna autoryzacja.",
            "access_token_valid": False,
            "refresh_token_days_remaining": 0,
            "auth_url": f"/auth?company={company}"
        }), 200

    now_ts = time.time()
    # access token: sprawdź Unix timestamp z Postgres (klucz: access_token_expires_at)
    is_access_valid = False
    access_expires_at_ts = token_data.get('access_token_expires_at')
    if access_expires_at_ts:
        try:
            if now_ts < float(access_expires_at_ts):
                is_access_valid = True
        except Exception:
            pass

    # refresh token: sprawdź Unix timestamp (klucz: refresh_token_expires_at)
    refresh_expires_at_ts = token_data.get('refresh_token_expires_at')
    
    days_remaining = 0
    if refresh_expires_at_ts:
        try:
            delta_s = float(refresh_expires_at_ts) - now_ts
            days_remaining = round(delta_s / 86400.0, 1)
        except Exception:
            days_remaining = 0
            
    if days_remaining <= 0:
        return jsonify({
            "status": "expired",
            "message": "❌ Token wygasł! Wymagana ponowna autoryzacja.",
            "access_token_valid": is_access_valid,
            "refresh_token_days_remaining": days_remaining,
            "auth_url": f"/auth?company={company}"
        }), 200
    elif days_remaining < 7:
        return jsonify({
            "status": "warning",
            "message": f"⚠️ Token wygasa za {days_remaining} dni! Odnów autoryzację.",
            "access_token_valid": is_access_valid,
            "refresh_token_days_remaining": days_remaining,
            "auth_url": f"/auth?company={company}"
        }), 200
    else:
        return jsonify({
            "status": "ok",
            "message": f"Token ważny, wygasa za {days_remaining} dni",
            "access_token_valid": is_access_valid,
            "refresh_token_days_remaining": days_remaining,
            "refresh_token_expires_at_unix": refresh_expires_at_ts,
            "company": company
        }), 200


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
    wfirma_company_id = wfirma_get_company_id(token, company)
    if not wfirma_company_id:
        for _ in range(2):
            time.sleep(0.4)
            wfirma_company_id = wfirma_get_company_id(token, company)
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
    # WO-471: wFirma odrzuca kontrahenta przez HTTP **200** z `status.code: ERROR` i echem
    # payloadu wzbogaconym o `errors`. Do WO-471 ta trasa raportowala wtedy `success: True`
    # dla kontrahenta, ktory NIE powstal (brak `id`). Sciezka workflow byla odporna, ta nie.
    if contractor and _extract_contractor_id(contractor):
        return jsonify({'success': True, 'contractor': contractor})

    wf_errors = _extract_wfirma_errors(contractor)
    if wf_errors:
        return jsonify({
            'error': f"wFirma odrzuciła dane kontrahenta: {'; '.join(wf_errors)}",
            'wfirma_validation_errors': wf_errors,
            'contractor': contractor,
        }), 400

    status = resp.status_code if resp else None
    return jsonify({
        'error': 'Błąd podczas dodawania kontrahenta',
        'status': status,
        'details': resp.text if resp else 'Brak odpowiedzi'
    }), status or 500

@app.route('/api/invoice/find-by-number', methods=['POST', 'OPTIONS'])
@require_api_key
@require_token
def api_find_invoice_by_number(token):
    """Wyszukaj fakturę po numerze (fullnumber)."""
    if request.method == 'OPTIONS':
        return cors_response({'status': 'ok'})

    body = request.get_json(silent=True) or {}
    fullnumber = (body.get('fullnumber') or body.get('number') or '').strip()

    print(f"[API] POST /api/invoice/find-by-number -> fullnumber='{fullnumber}'")

    if not fullnumber:
        return cors_response({'error': 'Brak parametru fullnumber/number'}, 400)

    company_id = wfirma_get_company_id(token)
    invoice, err = wfirma_find_invoice_by_fullnumber(token, fullnumber, company_id)

    if invoice:
        print(f"[API] Znaleziono fakturę: id={invoice.get('id')}, fullnumber={invoice.get('fullnumber')}")
        return cors_response({'success': True, 'invoice': invoice})
    else:
        print(f"[API] Nie znaleziono faktury o numerze '{fullnumber}': {err}")
        return cors_response({'error': f'Nie znaleziono faktury: {fullnumber}', 'details': err}, 404)


@app.route('/api/invoice/<invoice_id>', methods=['GET'])
@require_api_key
@require_token
def api_get_invoice(token, invoice_id):
    """Pobierz szczegóły faktury po ID."""
    print(f"[API] GET /api/invoice/{invoice_id}")

    if not invoice_id or invoice_id == 'None':
        print(f"[API] Invalid invoice_id: {invoice_id}")
        return cors_response({'error': 'Nieprawidłowe ID faktury', 'invoice_id': invoice_id}, 400)

    company_id = wfirma_get_company_id(token)
    invoice, err = wfirma_get_invoice(token, str(invoice_id), company_id)

    if invoice:
        print(f"[API] Pobrano fakturę: id={invoice.get('id')}, fullnumber={invoice.get('fullnumber')}")
        return cors_response({'success': True, 'invoice': invoice})
    else:
        print(f"[API] Nie znaleziono faktury ID={invoice_id}: {err}")
        return cors_response({'error': f'Nie znaleziono faktury o ID {invoice_id}', 'details': err}, 404)


@app.route('/api/invoice/create', methods=['POST', 'OPTIONS'])
@require_api_key
@require_token
def create_invoice(token):
    """Utwórz fakturę"""
    # Obsługa CORS preflight (OPTIONS)
    if request.method == 'OPTIONS':
        return cors_response({'status': 'ok'})
    
    data = request.json
    
    if not data:
        return cors_response({'error': 'Brak danych w żądaniu'}, 400)
    company_id = wfirma_get_company_id(token)
    invoice, resp = wfirma_create_invoice(token, data, company_id)
    if invoice:
        return cors_response({'success': True, 'invoice': invoice})

    status = resp.status_code if resp else None
    return cors_response({
        'error': 'Błąd podczas tworzenia faktury',
        'status': status,
        'details': resp.text if resp else 'Brak odpowiedzi'
    }, status or 500)


@app.route('/api/invoice/<invoice_id>/pdf', methods=['GET'])
@require_api_key
@require_token
def download_invoice_pdf(token, invoice_id):
    """Pobierz PDF faktury i zwróć jako plik do pobrania"""
    company_id = wfirma_get_company_id(token)
    
    try:
        resp = wfirma_get_invoice_pdf(token, invoice_id, company_id)
        
        if resp.status_code == 200 and 'pdf' in resp.headers.get('Content-Type', '').lower():
            # Walidacja: sprawdź magic bytes PDF (%PDF-)
            if not _is_valid_pdf(resp.content):
                print(f"[WFIRMA WARN] PDF response is not a valid PDF! Size={len(resp.content)}, magic={resp.content[:10]}")
                return jsonify({
                    'error': 'Odpowiedź wFirma nie zawiera prawidłowego PDF',
                    'content_size': len(resp.content),
                    'hint': 'wFirma mogła zwrócić stronę błędu zamiast PDF'
                }), 502
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
    
    company_id = wfirma_get_company_id(token, company)
    series_list = wfirma_list_series(token, company_id)
    
    return jsonify({
        'success': True,
        'company': company,
        'series_count': len(series_list),
        'series': series_list
    })


@app.route('/api/invoice/<invoice_id>/send', methods=['POST', 'OPTIONS'])
@require_api_key
@require_token
def send_invoice_email(token, invoice_id):
    """Wyślij fakturę emailem"""
    # Obsługa CORS preflight (OPTIONS)
    if request.method == 'OPTIONS':
        return cors_response({'status': 'ok'})
    
    data = request.json or {}
    email = data.get('email', '').strip()
    
    if not email or '@' not in email:
        return cors_response({'error': 'Brak lub niepoprawny email'}, 400)
    
    company_id = wfirma_get_company_id(token)
    
    try:
        resp = wfirma_send_invoice_email(token, invoice_id, email, company_id)
        
        if resp.status_code == 200:
            return cors_response({
                'success': True,
                'message': f'Faktura wysłana na {email}',
                'response': resp.json()
            })
        else:
            return cors_response({
                'error': 'Nie udało się wysłać emaila',
                'status': resp.status_code,
                'details': resp.text[:500] if resp.text else ''
            }, resp.status_code)
    except Exception as e:
        return cors_response({'error': str(e)}, 500)


# ==================== ENDPOINT WORKFLOW: NIP -> GUS -> KONTRAHENT -> FAKTURA ====================


def build_invoice_payload(invoice_input: dict, contractor: dict, token: str = None, series_id: int = None, mark_as_paid: bool = False, document_type: str = 'normal', ereceipt_email: str = None, parent_invoice_id: int = None, receiver_contractor_id: int = None, receiver_snapshot: dict = None) -> tuple[dict | None, str | None]:
    """
    Mapper uproszczonego JSON na strukturę wFirma invoices/add.
    Jeśli token podany - automatycznie tworzy produkty w katalogu wFirma.
    Jeśli series_id podany - faktura będzie w tej serii.
    Jeśli mark_as_paid=True - dodaje alreadypaid_initial z obliczoną kwotą brutto.
    document_type: 'normal' (faktura VAT), 'proforma', 'proforma_bill', 'accounting_note' (nota księgowa), 'receipt_fiscal_normal' (paragon)
    ereceipt_email: email do wysyłki e-paragonu (tylko dla receipt_fiscal_normal)
    parent_invoice_id: ID faktury nadrzędnej (np. proformy) - do systemowego powiązania
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

    # Odbiorca inny niz Nabywca (WO-471). OBA klucze sa wymagane — sam
    # `contractor_receiver_id` wFirma przyjmuje i po cichu gubi (patrz RECEIVER_ROLE).
    if receiver_contractor_id and receiver_snapshot:
        payload["contractor_receiver_id"] = int(receiver_contractor_id)
        payload["contractor_detail_receiver"] = receiver_snapshot
        print(f"[WFIRMA DEBUG] Odbiorca: contractor_receiver_id={receiver_contractor_id}, "
              f"nazwa='{receiver_snapshot.get('name')}', typ_id={receiver_snapshot.get('tax_id_type')}")
    elif receiver_contractor_id or receiver_snapshot:
        # Polowiczne dane = pewna cicha utrata odbiorcy. Lepiej nie wystawiac dokumentu.
        return None, 'Odbiorca wymaga jednoczesnie ID kontrahenta i migawki danych'

    # Seria faktur (opcjonalnie)
    if series_id:
        payload["series"] = {"id": series_id}
        print(f"[WFIRMA DEBUG] Używam serii ID: {series_id}")
    
    # Powiązanie faktury końcowej z proformą/zamówieniem
    # UWAGA: "parent" w wFirma = powiązanie z korektą, "order" = powiązanie z proformą
    if parent_invoice_id and document_type == 'normal':
        payload["order"] = {"id": int(parent_invoice_id)}
        print(f"[WFIRMA DEBUG] Powiązanie z order (proforma) ID: {parent_invoice_id}")
    
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


@app.route('/api/workflow/create-invoice-from-nip', methods=['POST', 'OPTIONS'])
@require_api_key
def workflow_create_invoice():
    """Pełny workflow: NIP -> (GUS) -> kontrahent -> faktura."""
    
    # Obsługa CORS preflight (OPTIONS)
    if request.method == 'OPTIONS':
        return cors_response({'status': 'ok'})
    
    body = request.get_json(silent=True) or {}
    
    # Pobierz parametr company z body (md lub test)
    company = (body.get('company') or DEFAULT_COMPANY).lower().strip()
    if company not in SUPPORTED_COMPANIES:
        return cors_response({
            'error': f'Nieobsługiwana firma: {company}',
            'supported': SUPPORTED_COMPANIES
        }, 400)
    
    config = get_company_config(company)
    print(f"[WORKFLOW] Używam konfiguracji dla firmy: {company.upper()} (prefix: {config['prefix']})")
    
    # Załaduj token dla wybranej firmy
    token = load_token(silent=False, company=company)
    if not token:
        return cors_response({
            'error': f'Brak autoryzacji dla firmy {company.upper()}',
            'message': f'Przejdź do /auth?company={company} aby się zalogować',
            'company': company
        }, 401)
    
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
    
    # Istniejący contractor_id z wFirma (np. z proformy - żeby użyć tego samego kontrahenta)
    existing_contractor_id = body.get('existing_contractor_id')
    if existing_contractor_id:
        print(f"[WORKFLOW] Przekazano existing_contractor_id: {existing_contractor_id}")
    
    # Dane kontrahenta z wywołania (fallback gdy brak/niepoprawny NIP)
    # wFirma wymaga name, street, zip, city - domyślne wartości jeśli puste
    purchaser_name = (body.get('purchaser_name') or '').strip()
    purchaser_address = (body.get('purchaser_address') or '').strip() or '-'  # Domyślnie "-"
    # Kod pocztowy prostujemy już przy parsowaniu, żeby ta sama, poprawna wartość
    # trafiła do wszystkich trzech ścieżek tworzenia kontrahenta (purchaser, GUS
    # z uzupełnieniem, purchaser_fallback). Gdy zapisu nie da się odczytać, zostaje
    # '00-000' — tak samo jak dla pustego pola. Dokument dla OPŁACONEGO zamówienia
    # jest ważniejszy niż idealny adres: fakturę bez kodu da się skorygować, brakiem
    # faktury zajmuje się już księgowość i klient.
    purchaser_zip_raw = (body.get('purchaser_zip') or '').strip()
    purchaser_zip = _normalize_zip_pl(purchaser_zip_raw)
    if not purchaser_zip:
        if purchaser_zip_raw:
            print(f"[WORKFLOW] UWAGA: kod pocztowy '{purchaser_zip_raw}' jest nieczytelny — "
                  f"podstawiam 00-000, adres na fakturze wymaga ręcznej poprawki")
        purchaser_zip = '00-000'                                              # Domyślnie "00-000"
    elif purchaser_zip != purchaser_zip_raw:
        print(f"[WORKFLOW] Poprawiono kod pocztowy purchaser: '{purchaser_zip_raw}' -> '{purchaser_zip}'")
    purchaser_city = (body.get('purchaser_city') or '').strip() or '-'        # Domyślnie "-"
    
    invoice_input = body.get('invoice')
    email_address = (body.get('email') or '').strip()
    send_email_requested = bool(body.get('send_email')) or bool(email_address)
    
    # Typ dokumentu: "normal" (faktura VAT), "proforma", "accounting_note" (nota księgowa), "receipt_fiscal_normal" (paragon)
    # UWAGA: Musi być przed wyborem serii (series_name zależy od document_type)
    document_type_param = (body.get('document_type') or 'normal').lower().strip()
    if document_type_param not in ('normal', 'proforma', 'proforma_bill', 'accounting_note', 'receipt_fiscal_normal'):
        document_type_param = 'normal'  # Domyślnie faktura VAT
    
    # Seria faktur - dla wydarzeń: FV/EV/nr/miesiąc/rok
    # W wFirma sama "seria" (series_name) musi istnieć i mieć ustawiony format numeracji.
    # Dla trybu testowego (test, md_test) automatycznie wybieramy serie testowe
    if company in ('test', 'md_test'):
        # Serie testowe (z obrazka wFirma)
        if document_type_param == 'proforma':
            default_series = 'Eventy Pro forma TEST'
        else:
            default_series = 'Eventy Faktura VAT TEST'
    else:
        # Serie produkcyjne
        if document_type_param == 'proforma':
            default_series = 'Eventy Pro forma'
        else:
            default_series = 'Eventy Faktura VAT'
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
    
    # Parent invoice ID - do powiązania faktury końcowej z proformą
    parent_invoice_id_param = body.get('parent_invoice_id')
    if parent_invoice_id_param:
        print(f"[WORKFLOW] parent_invoice_id (proforma): {parent_invoice_id_param}")
    
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
        return cors_response({
            'error': 'Wymagany poprawny NIP (10 cyfr) lub dane purchaser_name',
            'nip_provided': nip_raw,
            'nip_valid': nip_valid
        }, 400)
    if not invoice_input:
        return cors_response({'error': 'Brak sekcji invoice'}, 400)

    # 0) Pobierz company_id (ID Twojej firmy) - WYMAGANE
    # Bez jednoznacznego company_id NIE wystawiamy dokumentu - wFirma użyłaby
    # "domyślnej" firmy konta, która może być inna niż Medidesk (incydent Vetidesk 2026-07-09).
    company_id = wfirma_get_company_id(token, company)
    if company_id:
        print(f"[WFIRMA DEBUG] company_id: {company_id}")
    else:
        print(f"[WFIRMA ERROR] Nie udało się jednoznacznie ustalić company_id dla '{company}' - przerywam")
        return cors_response({
            'error': 'Nie udało się jednoznacznie ustalić firmy w wFirma - dokument NIE został wystawiony',
            'company': company,
            'hint': f"Ustaw ENV {get_company_config(company)['prefix']}COMPANY_ID na ID właściwej firmy w wFirma"
        }, 502)

    # 1) Szukamy kontrahenta lub tworzymy na podstawie danych z wywołania
    contractor = None
    contractor_id = None
    contractor_created = False
    contractor_source = None  # 'wfirma', 'gus', 'purchaser', 'existing'
    resp_find = None  # Inicjalizacja dla przypadku gdy nie szukamy po NIP
    
    # Jeśli mamy existing_contractor_id (np. z proformy) - użyj go bezpośrednio
    if existing_contractor_id:
        try:
            contractor_id = int(existing_contractor_id)
            contractor = {"id": contractor_id}  # Minimalny obiekt kontrahenta
            contractor_source = 'existing'
            print(f"[WORKFLOW] Używam istniejącego kontrahenta ID={contractor_id} (z proformy)")
        except (ValueError, TypeError) as e:
            print(f"[WORKFLOW] Błąd parsowania existing_contractor_id: {e}")
            existing_contractor_id = None  # Fallback do normalnego szukania
    
    if not contractor_id and nip_valid:
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

            # 2026-08-09: GUS potrafi zwrócić rekord BEZ adresu — dotyczy zwłaszcza
            # jednoosobowych działalności (`typ: 'F'`), dla których wyszukiwarka REGON
            # nie oddaje adresu w podstawowym zapytaniu (spółki, `typ: 'P'`, mają komplet).
            # Wcześniej adres brany był z GUS BEZWARUNKOWO, więc puste kod/miasto szły do
            # wFirmy, ta odrzucała kontrahenta ("zip: Pole nie może być puste.; city: ..."),
            # a opłacone zamówienie zostawało bez faktury (incydent CART-533B018855D1,
            # 08.08.2026). Paradoks: gdy GUS nie znał NIP-u W OGÓLE, fallback niżej ratował
            # sytuację — szkodziła dopiero odpowiedź CZĘŚCIOWA.
            #
            # Fallback jest teraz POLOWY, nie całościowy: każde puste pole adresu bierzemy
            # z danych wywołującego (`purchaser_*` mają domyślniki '-' / '00-000' ustawione
            # przy parsowaniu body, więc nigdy nie są puste). Nazwa zostaje z GUS — to
            # oficjalna nazwa z rejestru i na fakturze jest właściwsza niż wpis klienta.
            gus_zip = gus_first.get('kodPocztowy') or ""
            gus_city = gus_first.get('miejscowosc') or ""
            _addr_gaps = [
                label
                for label, gus_value in (("street", street_full), ("zip", gus_zip), ("city", gus_city))
                if not gus_value
            ]

            contractor_payload = {
                "name": gus_first.get('nazwa') or clean_nip,
                "altname": gus_first.get('nazwa') or clean_nip,
                "nip": clean_nip,
                "tax_id_type": "nip",
                "street": street_full or purchaser_address,
                "zip": gus_zip or purchaser_zip,
                "city": gus_city or purchaser_city,
                "country": "PL",
                "email": email_address or "",
            }
            contractor_source = 'gus+purchaser' if _addr_gaps else 'gus'
            print(f"[WORKFLOW] Tworzę kontrahenta z danych GUS: {contractor_payload.get('name')}")
            if _addr_gaps:
                print(
                    f"[WORKFLOW] GUS nie podał adresu ({', '.join(_addr_gaps)}) dla NIP {clean_nip} "
                    f"(typ={gus_first.get('typ')}) — uzupełniam z danych purchaser"
                )
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
                    "email": email_address or "",
                }
                contractor_source = 'purchaser_fallback'
            else:
                return cors_response({'error': 'GUS nie znalazł firmy dla podanego NIP i brak danych purchaser'}, 404)
        
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
            
            # FALLBACK: Zanim zwrócimy błąd, spróbuj re-find po NIP i Nazwie
            print(f"[WORKFLOW] add_contractor failed, próbuję re-find po NIP {clean_nip}")
            refind_contractor, _ = wfirma_find_contractor_by_nip(token, clean_nip, company_id)
            if not refind_contractor and contractor_payload.get('name'):
                print(f"[WORKFLOW] re-find po NIP nieudany, próbuję re-find po nazwie: {contractor_payload['name']}")
                refind_contractor, _ = wfirma_find_contractor_by_name(token, contractor_payload['name'], company_id)
            
            if refind_contractor:
                contractor_id = _extract_contractor_id(refind_contractor)
                if contractor_id:
                    contractor = refind_contractor
                    contractor_created = False
                    print(f"[WORKFLOW] re-find znalazł kontrahenta ID={contractor_id}")
            
            if not contractor:
                return cors_response({
                    'error': 'Nie udało się dodać kontrahenta w wFirma',
                    'status': status,
                    'details': resp_add.text if resp_add else 'Brak odpowiedzi',
                    'contractor_payload': contractor_payload,
                    'contractor_source': contractor_source
                }, status or 502)
        else:
            contractor = new_contractor
            contractor_id = _extract_contractor_id(contractor)
            contractor_created = True
            # Wykryj sytuację: wFirma zwróciła obiekt z errors ale BEZ id
            if not contractor_id and new_contractor:
                wf_errors = _extract_wfirma_errors(new_contractor)
                if wf_errors:
                    print(f"[WORKFLOW] UWAGA: wFirma zwróciła kontrahenta BEZ ID z błędami walidacji: {wf_errors}")
                    print(f"[WORKFLOW] Payload który wywołał błąd: NIP={clean_nip}, email={contractor_payload.get('email')}, name={contractor_payload.get('name')}")
                else:
                    print(f"[WORKFLOW] UWAGA: wFirma zwróciła kontrahenta BEZ ID (brak errors w odpowiedzi)")
                    print(f"[WORKFLOW] Contractor object: {new_contractor}")
    
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
            "email": email_address or "",
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
            
            # FALLBACK: Zanim zwrócimy błąd, spróbuj re-find po Nazwie (bo tu nie ma NIP)
            print(f"[WORKFLOW] add_contractor failed, próbuję re-find po nazwie: {purchaser_name}")
            refind_contractor, _ = wfirma_find_contractor_by_name(token, purchaser_name, company_id)
            if refind_contractor:
                contractor_id = _extract_contractor_id(refind_contractor)
                if contractor_id:
                    contractor = refind_contractor
                    contractor_created = False
                    print(f"[WORKFLOW] re-find znalazł kontrahenta ID={contractor_id}")
            
            if not contractor:
                return cors_response({
                    'error': 'Nie udało się dodać kontrahenta w wFirma',
                    'status': status,
                    'details': resp_add.text if resp_add else 'Brak odpowiedzi',
                    'contractor_payload': contractor_payload,
                    'contractor_source': contractor_source
                }, status or 502)
        else:
            contractor = new_contractor
            contractor_id = _extract_contractor_id(contractor)
            contractor_created = True
            # Wykryj sytuację: wFirma zwróciła obiekt z errors ale BEZ id
            if not contractor_id and new_contractor:
                wf_errors = _extract_wfirma_errors(new_contractor)
                if wf_errors:
                    print(f"[WORKFLOW] UWAGA: wFirma zwróciła kontrahenta BEZ ID z błędami walidacji: {wf_errors}")
                    print(f"[WORKFLOW] Payload który wywołał błąd: email={contractor_payload.get('email')}, name={contractor_payload.get('name')}")
                else:
                    print(f"[WORKFLOW] UWAGA: wFirma zwróciła kontrahenta BEZ ID (brak errors w odpowiedzi)")
                    print(f"[WORKFLOW] Contractor object: {new_contractor}")

    if not contractor_id:
        status = resp_find.status_code if resp_find else None
        # Wyciągnij szczegółowe błędy walidacji z wFirma (jeśli są)
        wf_validation_errors = _extract_wfirma_errors(contractor) if contractor else []
        # Log diagnostyczny
        try:
            print("[WFIRMA DEBUG] find response status:", status)
            if resp_find is not None:
                print("[WFIRMA DEBUG] find response body snippet:", (resp_find.text or "")[:500])
            print("[WFIRMA DEBUG] contractor object before failure:", contractor)
            if wf_validation_errors:
                print(f"[WFIRMA ERROR] Błędy walidacji wFirma które zablokowały utworzenie kontrahenta: {wf_validation_errors}")
        except Exception:
            pass
        
        # Zbuduj czytelny komunikat błędu
        if wf_validation_errors:
            error_msg = f"wFirma odrzuciła dane kontrahenta: {'; '.join(wf_validation_errors)}"
        else:
            error_msg = 'Nie udało się uzyskać ID kontrahenta w wFirma'
        
        return cors_response({
            'error': error_msg,
            'wfirma_validation_errors': wf_validation_errors or None,
            'status': status,
            'nip': clean_nip if nip_valid else None,
            'email_used': email_address or None,
            'contractor_source': contractor_source,
        }, status or 502)

    # 2b) Odbiorca inny niz Nabywca (WO-471) — opcjonalny blok `receiver`.
    # Rozwiazujemy PRZED wystawieniem: dokumentu bez wymaganego Odbiorcy lepiej nie tworzyc
    # wcale, niz tworzyc i korygowac. Brak bloku = zachowanie identyczne jak dotychczas.
    receiver_contractor_id = None
    receiver_snapshot = None
    receiver_input = body.get('receiver')
    if receiver_input:
        if not isinstance(receiver_input, dict):
            return cors_response({'error': 'Pole "receiver" musi byc obiektem'}, 400)
        if not (receiver_input.get('name') or '').strip():
            return cors_response({'error': 'Odbiorca wymaga pola "name"'}, 400)

        receiver_contractor, receiver_errors = wfirma_resolve_receiver_contractor(
            token, receiver_input, company_id
        )
        if not receiver_contractor:
            print(f"[WORKFLOW] BLAD: nie udalo sie ustalic odbiorcy: {receiver_errors}")
            return cors_response({
                'error': (
                    f"wFirma odrzucila dane Odbiorcy: {'; '.join(receiver_errors)}"
                    if receiver_errors else 'Nie udalo sie ustalic kontrahenta-odbiorcy'
                ),
                'wfirma_validation_errors': receiver_errors or None,
                'receiver_name': (receiver_input.get('name') or '').strip(),
                'hint': 'Dokument NIE zostal wystawiony — popraw dane Odbiorcy i ponow.',
            }, 502)

        receiver_contractor_id = _extract_contractor_id(receiver_contractor)
        receiver_snapshot = build_receiver_snapshot(receiver_input)
        print(f"[WORKFLOW] Odbiorca ustalony: id={receiver_contractor_id} "
              f"nazwa='{receiver_snapshot.get('name')}'")

    # 3) Szukamy serii faktur
    # Brak żądanej serii = TWARDY BŁĄD. Fallback na serię domyślną maskował wystawienie
    # dokumentu w księgach niewłaściwej firmy (incydent Vetidesk 2026-07-09: seria
    # "Eventy Pro forma" nie istniała w Vetidesk, więc proforma dostała domyślny numer).
    series_id = None
    if series_name:
        series = wfirma_find_series_by_name(token, series_name, company_id)
        if series and series.get('id'):
            series_id = int(series.get('id'))
            print(f"[WORKFLOW] Znaleziono serię '{series_name}' -> ID {series_id}")
        else:
            print(f"[WORKFLOW] BŁĄD: Nie znaleziono serii '{series_name}' (company_id={company_id}) - przerywam, dokument NIE zostanie wystawiony")
            # Loguj dostępne serie żeby ułatwić debugowanie
            available_series = wfirma_list_series(token, company_id)
            if available_series:
                print(f"[WORKFLOW] Dostępne serie ({len(available_series)}):")
                for s in available_series:
                    print(f"[WORKFLOW]   - '{s['name']}' (ID: {s['id']}, szablon: {s['template']})")
            return cors_response({
                'error': f"Nie znaleziono serii '{series_name}' w wFirma - dokument NIE został wystawiony",
                'series_name': series_name,
                'company': company,
                'wfirma_company_id': company_id,
                'available_series': [s.get('name') for s in (available_series or [])],
                'hint': 'Sprawdź nazwę serii w wFirma (Ustawienia -> Serie numeracji) lub czy company_id wskazuje właściwą firmę'
            }, 422)
    
    # 4) Budujemy payload faktury/proformy/paragonu (z alreadypaid_initial jeśli mark_as_paid=True)
    # parent_invoice_id - powiązanie z proformą (jeśli faktura końcowa)
    invoice_payload, map_err = build_invoice_payload(invoice_input, contractor, token, series_id=series_id, mark_as_paid=mark_as_paid, document_type=document_type_param, ereceipt_email=ereceipt_email, parent_invoice_id=parent_invoice_id_param, receiver_contractor_id=receiver_contractor_id, receiver_snapshot=receiver_snapshot)
    try:
        print("[WFIRMA DEBUG] invoice payload:", invoice_payload)
        if invoice_payload and 'invoicecontents' in invoice_payload:
            import json as json_lib
            print("[WFIRMA DEBUG] invoicecontents JSON:", json_lib.dumps(invoice_payload['invoicecontents'], ensure_ascii=False))
    except Exception as e:
        print("[WFIRMA DEBUG] log error:", e)
    if map_err:
        return cors_response({'error': map_err}, 400)

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
            return cors_response({
                'error': 'Brak konfiguracji schematu księgowego w wFirma',
                'message': 'W panelu wFirma ustaw: Ustawienia → Firma → Księgowość → Schematy księgowe',
                'details': error_details,
                'status': status
            }, 400)
        
        return cors_response({
            'error': 'Błąd podczas tworzenia faktury',
            'status': status,
            'details': error_details
        }, status or 502)

    # Pobierz ID faktury
    invoice_id = str(invoice.get('id') or invoice.get('invoice_id') or '')
    if not invoice_id:
        return cors_response({
            'error': 'Brak ID faktury w odpowiedzi',
            'invoice': invoice
        }, 502)

    # WO-471: ASERCJA ODBIORCY. wFirma potrafi przyjac dokument ze `status: OK` i ZGUBIC
    # odbiorce (odczyt pokazuje wtedy `contractor_receiver: {"id": 0}`). Bez tego sprawdzenia
    # faktura pojechalaby do klienta bez Odbiorcy, a system zaraportowalby sukces.
    #
    # UWAGA na ksztalt bledu: dokument JUZ ISTNIEJE. Komunikat musi to powiedziec wprost,
    # zeby nikt — czlowiek ani automat — nie ponowil wystawienia i nie zrobil duplikatu.
    if receiver_contractor_id:
        stored_invoice, stored_err = wfirma_get_invoice(token, invoice_id, company_id)
        stored_receiver_id = receiver_stored_id(stored_invoice)
        if stored_receiver_id != int(receiver_contractor_id):
            invoice_number = invoice.get('fullnumber', '')
            print(f"[WORKFLOW] BLAD KRYTYCZNY: dokument {invoice_number} (id={invoice_id}) powstal "
                  f"BEZ Odbiorcy — oczekiwano id={receiver_contractor_id}, w wFirmie id={stored_receiver_id}")
            return cors_response({
                'error': 'Dokument zostal wystawiony, ale wFirma nie zapisala Odbiorcy',
                'message': (
                    f"Dokument {invoice_number} ISTNIEJE w wFirmie (id={invoice_id}), lecz bez Odbiorcy. "
                    "NIE wystawiaj ponownie — powstalby duplikat. Popraw dokument w wFirmie "
                    "albo go anuluj i wystaw na nowo."
                ),
                'receiver_verification_failed': True,
                'invoice_id': invoice_id,
                'invoice_number': invoice_number,
                'expected_receiver_id': int(receiver_contractor_id),
                'stored_receiver_id': stored_receiver_id,
                'read_back_error': stored_err,
            }, 502)
        print(f"[WORKFLOW] Odbiorca potwierdzony odczytem: contractor_receiver.id={stored_receiver_id}")

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
            # Walidacja: sprawdź magic bytes PDF (%PDF-)
            if not _is_valid_pdf(pdf_content):
                print(f"[WFIRMA WARN] PDF response is NOT a valid PDF! Size={len(pdf_content)}, first_bytes={pdf_content[:20]}")
                pdf_content = None  # Nie zapisuj garbage jako PDF
            else:
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
            return cors_response({
                'error': 'Brak lub niepoprawny email do wysyłki faktury',
                'invoice': invoice,
                'pdf_saved': pdf_filename
            }, 400)

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
            return cors_response({
                'error': 'Nie udało się wysłać faktury mailem',
                'status': resp_email.status_code,
                'details': resp_email.text[:500] if resp_email.text else '',
                'invoice': invoice,
                'pdf_saved': pdf_filename
            }, resp_email.status_code)
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
        # WO-471: pusty gdy zamowienie nie ma Odbiorcy. Wartosc = potwierdzona ODCZYTEM,
        # nie samym payloadem — patrz asercja odbiorcy wyzej.
        'receiver_contractor_id': receiver_contractor_id,
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
    
    return cors_response(response)


# ==================== ENDPOINTY GUS / REGON ====================

# ==================== ENDPOINTY GUS / REGON ====================

@app.route('/api/gus/name-by-nip', methods=['POST', 'OPTIONS'])
def gus_name_by_nip():
    """
    Prosty port endpointu /api/gus/name-by-nip z backendu Googie_GUS.
    Headers: X-API-Key: <REGON_API_KEY_TOKEN>
    Wejście: JSON { "nip": "1234567890" }
    Wyjście: { "data": [ { regon, nip, nazwa, ... } ] } albo komunikat błędu.
    """
    # Obsługa CORS preflight (OPTIONS)
    if request.method == 'OPTIONS':
        return gus_cors_response({'status': 'ok'})
    
    # Sprawdź osobny token dla endpointów GUS/REGON
    api_key_header = request.headers.get('X-API-Key', '')
    if not REGON_API_KEY_TOKEN:
        return gus_cors_response({'error': 'Brak REGON_API_KEY_TOKEN w konfiguracji serwera'}, 500)
    if api_key_header != REGON_API_KEY_TOKEN:
        return gus_cors_response({'error': 'Unauthorized - nieprawidłowy token'}, 401)
    
    body = request.get_json(silent=True) or {}

    # Walidacja i oczyszczenie NIP (jak w Node)
    nip_raw = str(body.get('nip', ''))[:20]
    clean_nip = re.sub(r'[^0-9]', '', nip_raw)

    from_header_key = (request.headers.get('x-gus-api-key') or '')[:100]
    api_key = from_header_key or GUS_API_KEY or ''

    if not clean_nip:
        return gus_cors_response({'error': 'Brak NIP'}, 400)

    if len(clean_nip) != 10:
        return gus_cors_response({'error': 'NIP musi składać się z dokładnie 10 cyfr'}, 400)

    if not api_key:
        return gus_cors_response({
            'error': 'Brak klucza GUS_API_KEY',
            'hint': 'Ustaw zmienną środowiskową GUS_API_KEY / BIR1_medidesk lub przekaż nagłówek x-gus-api-key.'
        }, 400)

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
        login_resp = post_soap_gus_retry(bir_host, login_envelope, sid=None)
        # Szczegółowe logi z logowania do GUS
        print(f"[GUS] LOGIN status={login_resp.status_code}")
        login_snippet = (login_resp.text or '')[:500]
        print(f"[GUS] LOGIN body snippet={repr(login_snippet)}")
    except Exception as e:
        return gus_cors_response({
            'error': 'Błąd komunikacji z GUS podczas logowania',
            'message': str(e)
        }, 502)

    sid_match = re.search(r'<ZalogujResult>([^<]*)</ZalogujResult>', login_resp.text or '')
    sid = sid_match.group(1).strip() if sid_match else ''

    if not sid:
        snippet = (login_resp.text or '')[:300]
        return gus_cors_response({
            'error': 'Logowanie do GUS nie powiodło się (brak SID)',
            'debug': snippet
        }, 502)

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
        search_resp = post_soap_gus(bir_host, search_envelope, sid=sid)
        # Szczegółowe logi z wyszukiwania w GUS
        print(f"[GUS] SEARCH status={search_resp.status_code}")
        search_snippet = (search_resp.text or '')[:800]
        print(f"[GUS] SEARCH body snippet={repr(search_snippet)}")
    except Exception as e:
        return gus_cors_response({
            'error': 'Błąd komunikacji z GUS podczas wyszukiwania',
            'message': str(e)
        }, 502)

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
        return gus_cors_response({
            'error': 'GUS nie znalazł podmiotu dla podanego NIP'
        }, 404)

    result_match = re.search(
        r'<DaneSzukajPodmiotyResult>([\s\S]*?)</DaneSzukajPodmiotyResult>',
        soap_part,
        re.MULTILINE | re.DOTALL,
    )
    inner_xml = result_match.group(1) if result_match else ''

    if not inner_xml:
        print("[GUS] Brak sekcji <DaneSzukajPodmiotyResult> w odpowiedzi GUS")
        return gus_cors_response({
            'error': 'Brak danych w odpowiedzi GUS (DaneSzukajPodmiotyResult pusty)'
        }, 404)

    decoded_xml = decode_bir_inner_xml(inner_xml)
    decoded_snippet = decoded_xml[:800]
    print(f"[GUS] DECODED inner XML snippet={repr(decoded_snippet)}")
    if not decoded_xml:
        return gus_cors_response({
            'error': 'Brak danych po dekodowaniu odpowiedzi GUS'
        }, 502)

    try:
        root = ET.fromstring(decoded_xml)
    except ET.ParseError as e:
        return gus_cors_response({
            'error': 'Nie udało się sparsować danych GUS',
            'message': str(e)
        }, 502)

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

    return gus_cors_response({'data': data_list})


@app.route('/api/gus/validate-nip', methods=['POST', 'OPTIONS'])
def gus_validate_nip():
    """
    Sprawdź czy NIP jest poprawny i czy istnieje w bazie GUS/REGON.
    Headers: X-API-Key: <REGON_API_KEY_TOKEN>
    Wejście: JSON { "nip": "1234567890" }
    Wyjście: { "nip_status": "brak/niepoprawny/poprawny", "gus_data": {...} lub null }
    """
    # Obsługa CORS preflight (OPTIONS)
    if request.method == 'OPTIONS':
        return gus_cors_response({'status': 'ok'})
    
    # Sprawdź osobny token dla endpointów GUS/REGON
    api_key_header = request.headers.get('X-API-Key', '')
    if not REGON_API_KEY_TOKEN:
        return gus_cors_response({'error': 'Brak REGON_API_KEY_TOKEN w konfiguracji serwera'}, 500)
    if api_key_header != REGON_API_KEY_TOKEN:
        return gus_cors_response({'error': 'Unauthorized - nieprawidłowy token'}, 401)
    
    body = request.get_json(silent=True) or {}

    nip_raw = str(body.get('nip', '')).strip()
    clean_nip = re.sub(r'[^0-9]', '', nip_raw)

    # Brak NIP
    if not clean_nip:
        print(f"[GUS] validate-nip BRAK nip_raw='{nip_raw}'")
        return gus_cors_response({
            'nip_status': 'brak',
            'nip_provided': nip_raw,
            'gus_data': None
        })

    # Sprawdź w GUS/REGON
    print(f"[GUS] validate-nip START nip={clean_nip}")
    gus_records, gus_err = gus_lookup_nip(clean_nip)
    print(f"[GUS] validate-nip RESULT nip={clean_nip} err={gus_err} records_count={len(gus_records) if gus_records else 0}")

    # WO-469 (BUG-056): awaria łączności to NIE to samo, co "nie ma takiej firmy".
    # Do 2026-08-26 oba przypadki wracały jako HTTP 200 `niepoprawny`, więc koszyk nie miał
    # czym ich odróżnić i pokazywał klientowi z poprawnym NIP-em, że firmy nie znaleziono.
    # Awaria dostaje własny status i własny kod HTTP — dopiero to pozwala konsumentowi
    # zaproponować ręczne uzupełnienie danych zamiast zatrzymać zamówienie.
    if gus_err:
        print(f"[GUS] validate-nip NIEDOSTEPNY nip={clean_nip} (err={gus_err})")
        return gus_cors_response({
            'nip_status': 'niedostepny',
            'nip': clean_nip,
            'gus_data': None,
            # Treść błędu jest diagnostyczna (host, timeout) i NIE zawiera klucza API —
            # `gus_err` powstaje z wyjątku transportowego, klucz siedzi w ciele SOAP.
            'error': 'Rejestr GUS chwilowo nie odpowiada',
            'detail': str(gus_err)[:200]
        }, 503)

    # Rejestr odpowiedział i nie zna tego NIP-u
    if not gus_records or len(gus_records) == 0:
        print(f"[GUS] validate-nip NIEPOPRAWNY nip={clean_nip} (brak rekordow w GUS)")
        return gus_cors_response({
            'nip_status': 'niepoprawny',
            'nip': clean_nip,
            'gus_data': None
        })

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
    
    return gus_cors_response({
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
        },
        'data': gus_first
    })


@app.route('/api/invoice/<invoice_id>/send-email', methods=['POST', 'OPTIONS'])
@require_api_key
@require_token
def invoice_send_email(token, invoice_id):
    """Wyślij fakturę mailem przez wFirma."""
    # Obsługa CORS preflight (OPTIONS)
    if request.method == 'OPTIONS':
        return cors_response({'status': 'ok'})
    
    body = request.get_json(silent=True) or {}
    email = (body.get('email') or '').strip()
    if not email or '@' not in email:
        return cors_response({'error': 'Brak lub niepoprawny email'}, 400)

    company_id = wfirma_get_company_id(token)
    resp = wfirma_send_invoice_email(token, invoice_id, email, company_id)
    if resp.status_code == 200:
        try:
            data = resp.json()
        except Exception:
            data = {}
        return cors_response({'success': True, 'wfirma_response': data})

    return cors_response({
        'error': 'Nie udało się wysłać faktury mailem',
        'status': resp.status_code,
        'details': resp.text[:500] if resp.text else ''
    }, resp.status_code)


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


def wfirma_find_invoice_by_fullnumber(token: str, fullnumber: str, company_id: str = None) -> tuple[dict | None, str | None]:
    """
    Wyszukaj fakturę w wFirma po pełnym numerze (fullnumber), np. "PROF 4/2026".
    Zwraca (invoice_dict, error_message).
    """
    fullnumber = (fullnumber or "").strip()
    if not fullnumber:
        return None, "Brak fullnumber"

    api_url = "https://api2.wfirma.pl/invoices/find?inputFormat=json&outputFormat=json&oauth_version=2"
    if company_id:
        api_url += f"&company_id={company_id}"

    headers = get_wfirma_headers(token)

    # Szukamy po polu fullnumber (eq) – zgodnie z konwencją find w wFirma (jak companies/find, goods/find)
    body = {
        "invoices": {
            "parameters": {
                "conditions": {
                    "condition": {
                        "field": "fullnumber",
                        "operator": "eq",
                        "value": fullnumber,
                    }
                },
                "limit": "10",
            }
        }
    }

    try:
        resp = requests.post(api_url, headers=headers, json=body)
        print(f"[WFIRMA] invoices/find fullnumber='{fullnumber}' status={resp.status_code}")

        if resp.status_code != 200:
            return None, f"Błąd API: {resp.status_code} - {resp.text[:300]}"

        data = resp.json()
        invoices = data.get("invoices", {})
        if not isinstance(invoices, dict):
            return None, "Nieprawidłowa odpowiedź invoices/find"

        # W odpowiedzi są klucze liczbowe: {"0": {"invoice": {...}}}
        found = []
        for k, v in invoices.items():
            if not (isinstance(k, str) and k.isdigit()):
                continue
            if isinstance(v, dict) and isinstance(v.get("invoice"), dict):
                found.append(v["invoice"])

        if not found:
            return None, "Nie znaleziono faktury po fullnumber"

        # Jeśli jest kilka, wybierz dokładny match fullnumber, w przeciwnym razie pierwszy
        exact = next((inv for inv in found if str(inv.get("fullnumber") or "").strip() == fullnumber), None)
        return exact or found[0], None
    except Exception as e:
        return None, str(e)


@app.route('/api/workflow/correction', methods=['POST', 'OPTIONS'])
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
    # Obsługa CORS preflight (OPTIONS)
    if request.method == 'OPTIONS':
        return cors_response({'status': 'ok'})
    
    body = request.get_json(silent=True) or {}
    
    # Parametry
    company = (body.get('company') or DEFAULT_COMPANY).lower().strip()
    parent_invoice_id = body.get('parent_invoice_id')
    correction_reason = (body.get('correction_reason') or 'Korekta faktury').strip()
    positions = body.get('positions') or []
    issue_date = body.get('issue_date') or datetime.date.today().isoformat()
    series_name = (body.get('series_name') or '').strip() or WFIRMA_SERIES_CORRECTION  # Fallback na domyślną serię korekt
    full_correction = body.get('full_correction', False)  # Tryb pełnej korekty (zerowanie wszystkich pozycji)

    # Walidacja
    if not parent_invoice_id:
        return cors_response({'error': 'Brak parent_invoice_id - ID faktury oryginalnej jest wymagane'}, 400)

    # positions nie są wymagane jeśli full_correction=True
    if not full_correction and (not positions or not isinstance(positions, list)):
        return cors_response({'error': 'Brak pozycji korekty (positions). Użyj full_correction=true dla pełnej korekty (zerowanie wszystkich pozycji).'}, 400)

    print(f"[CORRECTION] Tworzę korektę dla faktury ID={parent_invoice_id}, company={company}, full_correction={full_correction}")

    # Pobierz company_id (wymagane przez wFirma API)
    wfirma_company_id = wfirma_get_company_id(token, company)
    if not wfirma_company_id:
        return cors_response({
            'error': 'Nie udało się jednoznacznie ustalić firmy w wFirma - korekta NIE została wystawiona',
            'company': company,
            'hint': f"Ustaw ENV {get_company_config(company)['prefix']}COMPANY_ID na ID właściwej firmy w wFirma"
        }, 502)

    # 1) Pobierz oryginalną fakturę żeby uzyskać dane kontrahenta i pozycji
    original_invoice, err = wfirma_get_invoice(token, str(parent_invoice_id), wfirma_company_id)
    if err or not original_invoice:
        return cors_response({
            'error': 'Nie udało się pobrać faktury oryginalnej',
            'details': err,
            'parent_invoice_id': parent_invoice_id
        }, 404)

    print(f"[CORRECTION] Pobrano fakturę oryginalną: {original_invoice.get('fullnumber')}")

    # Pobierz contractor_id z oryginalnej faktury
    contractor_data = original_invoice.get('contractor', {})
    contractor_id = contractor_data.get('id') if isinstance(contractor_data, dict) else None
    if not contractor_id:
        return cors_response({'error': 'Nie można odczytać kontrahenta z faktury oryginalnej'}, 400)

    # 1.5) Pobierz PRAWDZIWE pozycje z oryginalnej faktury
    original_contents = original_invoice.get('invoicecontents', {})
    original_positions = []  # Lista dict: {id, name, count, price, unit, vat_code_id}
    if isinstance(original_contents, dict):
        for key, val in original_contents.items():
            if isinstance(val, dict) and 'invoicecontent' in val:
                content = val['invoicecontent']
                orig_pos = {
                    'id': content.get('id'),
                    'name': content.get('name'),
                    'count': content.get('count'),
                    'price': content.get('price'),
                    'unit': content.get('unit', 'szt.'),
                    'vat_code_id': content.get('vat_code', {}).get('id') if isinstance(content.get('vat_code'), dict) else 222,
                }
                original_positions.append(orig_pos)

    print(f"[CORRECTION] Oryginalna faktura ma {len(original_positions)} pozycji: {[{'id': p['id'], 'name': p['name']} for p in original_positions]}")

    if not original_positions:
        return cors_response({'error': 'Faktura oryginalna nie ma pozycji (invoicecontents)'}, 400)

    # Buduj mapę ID pozycji oryginalnej (do walidacji)
    original_pos_ids = {str(p['id']) for p in original_positions}

    # 2) Pobierz serię jeśli podano nazwę
    # Brak żądanej serii = TWARDY BŁĄD (żadnych cichych fallbacków na serię domyślną)
    series_id = None
    if series_name:
        series = wfirma_find_series_by_name(token, series_name, wfirma_company_id)
        if series and series.get('id'):
            series_id = int(series.get('id'))
            print(f"[CORRECTION] Znaleziono serię: {series_name} -> ID {series_id}")
        else:
            print(f"[CORRECTION] BŁĄD: Nie znaleziono serii '{series_name}' (company_id={wfirma_company_id}) - przerywam")
            return cors_response({
                'error': f"Nie znaleziono serii '{series_name}' w wFirma - korekta NIE została wystawiona",
                'series_name': series_name,
                'company': company,
                'wfirma_company_id': wfirma_company_id,
                'hint': 'Sprawdź nazwę serii w wFirma (Ustawienia -> Serie numeracji) lub czy company_id wskazuje właściwą firmę'
            }, 422)

    # 3) Buduj pozycje korekty
    invoice_contents_dict = {}

    if full_correction or not positions:
        # TRYB PEŁNEJ KOREKTY: zeruj wszystkie pozycje z oryginalnej faktury
        print(f"[CORRECTION] Tryb pełnej korekty - zeruję {len(original_positions)} pozycji")
        for idx, orig_pos in enumerate(original_positions):
            # Wg Postman: wysyłamy parent_id, name (oryginalne), count=0, price=0
            content = {
                "invoicecontent": {
                    "parent_id": int(orig_pos['id']),
                    "name": orig_pos.get('name', ''),
                    "count": 0,
                    "price": 0
                }
            }
            invoice_contents_dict[str(idx)] = content
            print(f"[CORRECTION] Pozycja {idx}: parent_id={orig_pos['id']}, name={orig_pos.get('name')}, zerowanie")
    else:
        # TRYB RĘCZNY: użyj pozycji z requestu, ale WALIDUJ parent_position_id
        for idx, pos in enumerate(positions):
            parent_pos_id = pos.get('parent_position_id')

            # Walidacja: sprawdź czy parent_position_id należy do oryginalnej faktury
            if parent_pos_id and str(parent_pos_id) not in original_pos_ids:
                print(f"[CORRECTION] UWAGA: parent_position_id={parent_pos_id} NIE należy do faktury {parent_invoice_id}!")
                print(f"[CORRECTION] Dostępne ID pozycji oryginalnej: {original_pos_ids}")

                # Auto-fix: jeśli jest tylko 1 pozycja na oryginale i 1 w requescie, użyj oryginalnej
                if len(original_positions) == 1 and len(positions) == 1:
                    parent_pos_id = original_positions[0]['id']
                    print(f"[CORRECTION] Auto-fix: użyto ID pozycji z oryginału: {parent_pos_id}")
                else:
                    return cors_response({
                        'error': f'Pozycja {idx+1}: parent_position_id={pos.get("parent_position_id")} nie należy do faktury {parent_invoice_id}',
                        'available_position_ids': list(original_pos_ids),
                        'hint': 'Użyj full_correction=true dla pełnej korekty lub podaj prawidłowe parent_position_id'
                    }, 400)

            if not parent_pos_id:
                # Brak parent_position_id - spróbuj dopasować po indeksie
                if idx < len(original_positions):
                    parent_pos_id = original_positions[idx]['id']
                    print(f"[CORRECTION] Auto-assign: pozycja {idx} -> parent_position_id={parent_pos_id}")
                else:
                    return cors_response({'error': f'Pozycja {idx+1} nie ma parent_position_id i nie można dopasować automatycznie'}, 400)

            qty = pos.get('quantity', 0)
            price_net = pos.get('unit_price_net', 0)

            # Wg Postman: wysyłamy parent_id, name (oryginalne z faktury), count, price
            # Znajdź oryginalną pozycję żeby pobrać name
            orig_name = ''
            for op in original_positions:
                if str(op['id']) == str(parent_pos_id):
                    orig_name = op.get('name', '')
                    break

            content = {
                "invoicecontent": {
                    "parent_id": int(parent_pos_id),
                    "name": pos.get('name') or orig_name,
                    "count": qty,
                    "price": price_net
                }
            }
            invoice_contents_dict[str(idx)] = content
            print(f"[CORRECTION] Pozycja {idx}: parent_id={parent_pos_id}, name={pos.get('name') or orig_name}, count={qty}, price={price_net}")

    # Payload faktury korygującej
    correction_payload = {
        "contractor_id": int(contractor_id),
        "date": issue_date,
        "type": "correction",
        "parent_id": int(parent_invoice_id),  # FLAT parent_id wg dokumentacji wFirma
        "description": correction_reason,
        "invoicecontents": invoice_contents_dict
    }

    # Seria (opcjonalnie)
    if series_id:
        correction_payload["series_id"] = series_id

    print(f"[CORRECTION] Payload: contractor_id={contractor_id}, parent_id={parent_invoice_id}, positions={len(invoice_contents_dict)}")

    # LOG: pełny payload korekty
    try:
        import json as json_lib
        print(f"[CORRECTION] Full correction_payload: {json_lib.dumps(correction_payload, ensure_ascii=False, indent=2)}")
    except Exception:
        print(f"[CORRECTION] correction_payload (raw): {correction_payload}")

    # 4) Utwórz fakturę korygującą
    invoice_result, resp = wfirma_create_invoice(token, correction_payload, wfirma_company_id)

    if invoice_result and invoice_result.get('id'):
        correction_id = invoice_result.get('id')
        print(f"[CORRECTION] SUCCESS! Korekta utworzona: id={correction_id}, fullnumber={invoice_result.get('fullnumber')}")

        # Pobierz PDF korekty
        pdf_base64 = None
        pdf_filename = None
        try:
            resp_pdf = wfirma_get_invoice_pdf(token, str(correction_id), wfirma_company_id)
            if resp_pdf.status_code == 200 and 'pdf' in resp_pdf.headers.get('Content-Type', '').lower():
                pdf_content = resp_pdf.content
                pdf_base64 = base64.b64encode(pdf_content).decode('utf-8')
                os.makedirs('invoices', exist_ok=True)
                pdf_filename = f"invoices/korekta_{correction_id}.pdf"
                with open(pdf_filename, 'wb') as f:
                    f.write(pdf_content)
                print(f"[CORRECTION] PDF saved: {pdf_filename} ({len(pdf_content)} bytes)")
            else:
                print(f"[CORRECTION] PDF download failed: {resp_pdf.status_code}")
        except Exception as e:
            print(f"[CORRECTION] PDF exception: {e}")

        # Buduj URL do PDF
        base_url = request.url_root.rstrip('/')
        pdf_url = f"{base_url}/api/invoice/{correction_id}/pdf"

        response_data = {
            'success': True,
            'message': 'Faktura korygująca utworzona',
            'correction_invoice': {
                'id': correction_id,
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
            },
            # Pola top-level dla kompatybilności z różnymi klientami
            'invoice_id': correction_id,
            'correction_invoice_id': correction_id,
            'wfirma_invoice_id': correction_id,
            'invoice_number': invoice_result.get('fullnumber'),
            'correction_number': invoice_result.get('fullnumber'),
            'fullnumber': invoice_result.get('fullnumber'),
            'pdf_url': pdf_url,
            'pdf_saved': pdf_filename
        }

        if pdf_base64:
            response_data['pdf_base64'] = pdf_base64

        return cors_response(response_data)
    else:
        # PEŁNE LOGOWANIE BŁĘDU
        error_details = ''
        resp_status = None
        resp_headers = None
        if resp:
            try:
                resp_status = resp.status_code
                error_details = resp.text
                print(f"[CORRECTION ERROR] wFirma API zwróciło błąd! Status: {resp_status}")
                print(f"[CORRECTION ERROR] Response body: {error_details[:2000]}")
            except Exception as log_ex:
                print(f"[CORRECTION ERROR] Error reading response: {log_ex}")
        else:
            print(f"[CORRECTION ERROR] No response object (resp is None)")

        return cors_response({
            'error': 'Nie udało się utworzyć faktury korygującej',
            'details': error_details[:2000] if error_details else 'brak odpowiedzi',
            'wfirma_status': resp_status,
            'parent_invoice_id': parent_invoice_id
        }, 500)


@app.route('/api/test/correction-debug', methods=['POST', 'OPTIONS'])
@require_api_key
def test_correction_debug():
    """
    Endpoint diagnostyczny do testowania korekt.
    Pobiera fakturę, loguje jej strukturę, buduje payload korekty i wysyła do wFirma.

    JSON body:
    {
        "invoice_id": 12345,         # WYMAGANE - ID faktury do skorygowania
        "company": "md",             # Opcjonalnie
        "dry_run": true              # Opcjonalnie - jeśli true, tylko pokaże payload bez wysyłania
    }
    """
    if request.method == 'OPTIONS':
        return cors_response({'status': 'ok'})

    body = request.get_json(silent=True) or {}
    invoice_id = body.get('invoice_id')
    company = (body.get('company') or DEFAULT_COMPANY).lower().strip()
    dry_run = body.get('dry_run', False)

    if not invoice_id:
        return cors_response({'error': 'Brak invoice_id'}, 400)

    token = load_token(company=company)
    if not token:
        return cors_response({'error': f'Brak tokena OAuth dla firmy: {company}'}, 401)

    wfirma_company_id = wfirma_get_company_id(token, company)

    # 1) Pobierz fakturę
    invoice, err = wfirma_get_invoice(token, str(invoice_id), wfirma_company_id)
    if err or not invoice:
        return cors_response({'error': 'Nie udało się pobrać faktury', 'details': err}, 404)

    # 2) Analiza struktury faktury
    invoice_info = {
        'id': invoice.get('id'),
        'fullnumber': invoice.get('fullnumber'),
        'type': invoice.get('type'),
        'netto': invoice.get('netto'),
        'brutto': invoice.get('brutto'),
        'parent': invoice.get('parent'),
        'order': invoice.get('order'),
    }

    # 3) Analiza pozycji
    positions_info = []
    original_contents = invoice.get('invoicecontents', {})
    if isinstance(original_contents, dict):
        for key, val in original_contents.items():
            if isinstance(val, dict) and 'invoicecontent' in val:
                content = val['invoicecontent']
                positions_info.append({
                    'id': content.get('id'),
                    'name': content.get('name'),
                    'count': content.get('count'),
                    'price': content.get('price'),
                    'unit': content.get('unit'),
                    'parent': content.get('parent'),
                    'invoice_id_from_content': content.get('invoice', {}).get('id') if isinstance(content.get('invoice'), dict) else None,
                })

    # Contractor
    contractor_data = invoice.get('contractor', {})
    contractor_id = contractor_data.get('id') if isinstance(contractor_data, dict) else None

    # 4) Buduj payload korekty (wg Postman)
    import datetime
    invoice_contents_dict = {}
    for idx, pos in enumerate(positions_info):
        invoice_contents_dict[str(idx)] = {
            "invoicecontent": {
                "parent_id": int(pos['id']),
                "name": pos.get('name', ''),
                "count": 0,
                "price": 0
            }
        }

    correction_payload = {
        "contractor_id": int(contractor_id) if contractor_id else None,
        "date": datetime.date.today().isoformat(),
        "type": "correction",
        "parent_id": int(invoice_id),
        "description": "Test korekty (debug endpoint)",
        "invoicecontents": invoice_contents_dict
    }

    result = {
        'invoice_info': invoice_info,
        'positions': positions_info,
        'contractor_id': contractor_id,
        'correction_payload': correction_payload,
        'dry_run': dry_run
    }

    if not dry_run:
        # Wyślij do wFirma
        print(f"[CORRECTION-DEBUG] Wysyłam payload korekty dla faktury {invoice_id}")
        import json as json_lib
        print(f"[CORRECTION-DEBUG] Payload: {json_lib.dumps(correction_payload, ensure_ascii=False)[:2000]}")

        invoice_result, resp = wfirma_create_invoice(token, correction_payload, wfirma_company_id)

        if invoice_result and invoice_result.get('id'):
            result['correction_result'] = {
                'success': True,
                'id': invoice_result.get('id'),
                'fullnumber': invoice_result.get('fullnumber')
            }
        else:
            resp_text = ''
            if resp:
                try:
                    resp_text = resp.text[:2000]
                except:
                    resp_text = str(resp.status_code)
            result['correction_result'] = {
                'success': False,
                'status_code': resp.status_code if resp else None,
                'response': resp_text
            }

    return cors_response(result)


@app.route('/api/test/correction-payment-flow', methods=['POST', 'OPTIONS'])
@require_api_key
@require_token
def test_correction_payment_flow(token):
    """
    Endpoint TESTOWY: pełna korekta (zerowanie) + opcjonalne oznaczenie korekty jako rozliczonej.
    Używa serii TEST (Eventy Korekta TEST). Do testów na fakturach z serii Eventy Faktura VAT TEST.
    
    Body JSON:
    {
        "parent_invoice_id": 12345,           # WYMAGANE - ID faktury VAT do skorygowania
        "mark_correction_settled": true       # Opcjonalnie (domyślnie false) - czy oznaczyć korektę jako rozliczoną (alreadypaid_initial na FK)
    }
    """
    if request.method == 'OPTIONS':
        return cors_response({'status': 'ok'})
    
    body = request.get_json(silent=True) or {}
    parent_invoice_id = body.get('parent_invoice_id')
    mark_correction_settled = body.get('mark_correction_settled', False) in (True, 'true', '1', 1)
    
    if not parent_invoice_id:
        return cors_response({'error': 'Brak parent_invoice_id - ID faktury do skorygowania jest wymagane'}, 400)
    
    print(f"[TEST CORRECTION] parent_invoice_id={parent_invoice_id}, mark_correction_settled={mark_correction_settled}")
    
    try:
        company_id = wfirma_get_company_id(token)
        correction, resp = wfirma_create_correction(
            token=token,
            source_invoice_id=str(parent_invoice_id),
            correction_description="Test korekty - odhaczanie płatności",
            company_id=company_id,
            series_name_override=WFIRMA_SERIES_CORRECTION_TEST,
            mark_refund_settled=mark_correction_settled,
            send_email=False,
        )
        
        if correction and correction.get('id'):
            return cors_response({
                'success': True,
                'message': 'Korekta testowa utworzona',
                'correction': {
                    'id': correction.get('id'),
                    'fullnumber': correction.get('fullnumber'),
                    'brutto': correction.get('brutto'),
                    'mark_refund_settled': mark_correction_settled,
                },
                'parent_invoice_id': parent_invoice_id,
            })
        else:
            err = (resp.text[:500] if resp and resp.text else 'brak odpowiedzi') if resp else 'brak odpowiedzi'
            return cors_response({
                'error': 'Nie udało się utworzyć korekty testowej',
                'details': err,
                'parent_invoice_id': parent_invoice_id,
            }, 500)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return cors_response({'error': str(e), 'parent_invoice_id': parent_invoice_id}, 500)


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


# ==================== HELPERY WALIDACJI ====================

def _is_valid_pdf(content: bytes) -> bool:
    """Sprawdź czy content to rzeczywisty PDF (magic bytes + min size)."""
    if not content or len(content) < 100:
        return False
    return content[:5] == b'%PDF-'


# ==================== START SERWERA ====================

# Auto-start: inicjalizacja schematu DB i monitora tokenów
try:
    from pg_storage import ensure_schema
    ensure_schema()
    print("[STARTUP] Schemat DB zainicjalizowany")
except Exception as e:
    print(f"[STARTUP] Schema init error (non-fatal): {e}")

try:
    start_wfirma_token_monitor()
except Exception as e:
    print(f"[STARTUP] Token monitor start error (non-fatal): {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
