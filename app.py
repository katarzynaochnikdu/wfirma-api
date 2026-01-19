""" 
wFirma API - Web Service dla Render
Flask web app z OAuth 2.0 i endpointami API
"""
from flask import Flask, request, redirect, jsonify, Response
import requests
import json
import os
import time
import re
import datetime
import base64
import uuid
import xml.etree.ElementTree as ET
from urllib.parse import quote
from functools import wraps

app = Flask(__name__)

# Panel admin (konfiguracja eventów w Postgres)
try:
    from admin_panel import admin_bp
    app.register_blueprint(admin_bp, url_prefix="/admin")
except Exception as e:
    # Nie blokuj startu serwera, jeśli zależności panelu nie są gotowe.
    print(f"[ADMIN] Panel admin nieaktywny: {e}")

# Konfiguracja z zmiennych środowiskowych (wFirma OAuth)
# UWAGA: Teraz obsługujemy dwa zestawy danych: WFIRMA_MD_* i WFIRMA_TEST_*
CLIENT_ID = os.environ.get('CLIENT_ID')
CLIENT_SECRET = os.environ.get('CLIENT_SECRET')
REDIRECT_URI = os.environ.get('REDIRECT_URI', 'http://localhost:5000/callback')
TOKEN_FILE = "wfirma_token.json"

# Obsługiwane firmy/zestawy danych
# md = Medidesk produkcja
# test = Konto testowe (osobne tokeny)
# md_test = Medidesk produkcja + ostrzeżenie testowe na fakturach
SUPPORTED_COMPANIES = ['md', 'test', 'md_test']
DEFAULT_COMPANY = 'md'  # Domyślna firma jeśli nie podano


def get_company_config(company: str = None) -> dict:
    """
    Pobierz konfigurację dla danej firmy (md, test, md_test).
    Zwraca dict z client_id, client_secret, access_token, refresh_token, token_expires.
    
    md_test używa danych MD (te same tokeny co produkcja) ale z ostrzeżeniem testowym.
    """
    company = (company or DEFAULT_COMPANY).lower().strip()
    if company not in SUPPORTED_COMPANIES:
        company = DEFAULT_COMPANY
    
    # md_test używa tych samych danych co md (prefix WFIRMA_MD_)
    if company == 'md_test':
        prefix = "WFIRMA_MD_"
    else:
        prefix = f"WFIRMA_{company.upper()}_"
    
    return {
        'company': company,
        'prefix': prefix,
        'client_id': os.environ.get(f'{prefix}CLIENT_ID') or CLIENT_ID,
        'client_secret': os.environ.get(f'{prefix}CLIENT_SECRET') or CLIENT_SECRET,
        'access_token': os.environ.get(f'{prefix}ACCESS_TOKEN'),
        'refresh_token': os.environ.get(f'{prefix}REFRESH_TOKEN'),
        'token_expires': os.environ.get(f'{prefix}TOKEN_EXPIRES'),
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

# ==================== FUNKCJE POMOCNICZE ====================

def update_render_env_var(key, value):
    """
    Bezpiecznie aktualizuje JEDNĄ zmienną środowiskową w usłudze Render.
    Pobiera najpierw wszystkie zmienne, modyfikuje jedną, zapisuje całość.
    WAŻNE: Również aktualizuje os.environ żeby zmiany były widoczne natychmiast!
    """
    # ZAWSZE aktualizuj pamięć procesu - nawet jeśli Render API nie jest skonfigurowane
    os.environ[key] = value
    print(f"[LOG] update_render_env_var: zaktualizowano os.environ[{key}]")
    
    if not RENDER_API_KEY or not RENDER_SERVICE_ID:
        print(f"[LOG] update_render_env_var: brak RENDER_API_KEY lub RENDER_SERVICE_ID - tylko pamięć lokalna")
        return True  # Zwracamy True bo os.environ zostało zaktualizowane
    
    url = f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/env-vars"
    headers = {
        "Authorization": f"Bearer {RENDER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        # 1) POBIERZ wszystkie aktualne zmienne
        get_resp = requests.get(url, headers=headers)
        if get_resp.status_code != 200:
            print(f"[LOG] update_render_env_var: błąd GET {get_resp.status_code} {get_resp.text[:200]}")
            return False
        
        current_vars = get_resp.json()  # Lista obiektów [{"envVar": {"key": "X", "value": "Y"}}, ...]
        print(f"[LOG] update_render_env_var: pobrano {len(current_vars)} zmiennych")
        
        # 2) Przekształć na prostą listę do PUT
        env_list = []
        key_found = False
        for item in current_vars:
            env_var = item.get('envVar', {})
            existing_key = env_var.get('key')
            existing_value = env_var.get('value')
            
            if existing_key == key:
                # Aktualizuj tę zmienną
                env_list.append({"key": key, "value": value})
                key_found = True
                print(f"[LOG] update_render_env_var: aktualizuję {key} w Render")
            else:
                # Zachowaj bez zmian
                env_list.append({"key": existing_key, "value": existing_value})
        
        # 3) Jeśli zmienna nie istniała - dodaj ją
        if not key_found:
            env_list.append({"key": key, "value": value})
            print(f"[LOG] update_render_env_var: dodaję nową zmienną {key} w Render")
        
        # 4) ZAPISZ całą listę (PUT)
        put_resp = requests.put(url, headers=headers, json=env_list)
        if put_resp.status_code == 200:
            print(f"[LOG] update_render_env_var: sukces - zaktualizowano {key} w Render")
            return True
        else:
            print(f"[LOG] update_render_env_var: błąd PUT {put_resp.status_code} {put_resp.text[:200]}")
            return False
            
    except Exception as e:
        print(f"[LOG] update_render_env_var: wyjątek {e}")
        return False

def save_token(access_token, expires_in, refresh_token=None, company=None):
    """
    Zapisz token do ENV (główne źródło) i pliku (backup).
    ENV jest JEDYNYM trwałym storage po redeployu!
    
    Args:
        access_token: Token dostępu
        expires_in: Czas ważności w sekundach
        refresh_token: Refresh token (opcjonalny)
        company: Firma/zestaw danych ('md' lub 'test')
    """
    config = get_company_config(company)
    prefix = config['prefix']
    
    expires_at = int(time.time() + expires_in - 60)  # 60 sek margines, jako int
    
    # Pobierz istniejący refresh_token jeśli nowy nie podany
    final_refresh_token = refresh_token
    if not final_refresh_token:
        # Priorytet: plik > ENV (tylko dla domyślnej firmy)
        if company is None and os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, 'r') as f:
                    old_data = json.load(f)
                    final_refresh_token = old_data.get('refresh_token')
            except:
                pass
        if not final_refresh_token:
            final_refresh_token = config['refresh_token']
    
    print(f"[LOG] [{config['company'].upper()}] save_token: access={access_token[:20]}..., refresh={bool(final_refresh_token)}, expires_at={expires_at}")
    
    # 1. Zapisz do PLIKU (lokalny cache - tylko dla domyślnej firmy, backward compatibility)
    if company is None:
        token_data = {
            'access_token': access_token,
            'expires_at': expires_at,
            'refresh_token': final_refresh_token
        }
        try:
            with open(TOKEN_FILE, 'w') as f:
                json.dump(token_data, f)
            print(f"[LOG] Token zapisany do pliku")
        except Exception as e:
            print(f"[ERROR] Nie można zapisać tokenu do pliku: {e}")
    
    # 2. Zapisz do ENV (trwałe po redeployu) - z odpowiednim prefixem dla firmy!
    if final_refresh_token:
        update_render_env_var(f"{prefix}REFRESH_TOKEN", final_refresh_token)
    update_render_env_var(f"{prefix}ACCESS_TOKEN", access_token)
    update_render_env_var(f"{prefix}TOKEN_EXPIRES", str(expires_at))
    
    # 3. Jeśli to NOWY refresh_token (z /auth), zapisz też jego termin ważności (30 dni)
    if refresh_token:  # Nowy refresh token = nowe 30 dni
        refresh_expires_at = int(time.time() + 30 * 24 * 60 * 60)  # 30 dni od teraz
        update_render_env_var(f"{prefix}REFRESH_TOKEN_EXPIRES", str(refresh_expires_at))
        print(f"[LOG] [{config['company'].upper()}] Nowy refresh_token ważny do: {datetime.datetime.fromtimestamp(refresh_expires_at).strftime('%Y-%m-%d %H:%M')}")

def refresh_access_token(forced_refresh_token=None, company=None):
    """
    Odśwież token używając refresh_token (z pliku lub argumentu).
    
    WAŻNE: Zawiera blokadę na równoczesne odświeżanie - zapobiega race condition
    gdy wiele requestów próbuje odświeżyć token jednocześnie.
    
    Args:
        forced_refresh_token: Wymuszony refresh token
        company: Firma/zestaw danych ('md' lub 'test')
    """
    config = get_company_config(company)
    prefix = config['prefix']
    
    # BLOKADA: Sprawdź czy ktoś inny właśnie odświeża token
    # Jeśli ostatni refresh był < 30 sekund temu, poczekaj i sprawdź czy token jest już ważny
    last_refresh_key = f"{prefix}LAST_REFRESH"
    last_refresh_str = os.environ.get(last_refresh_key, '0')
    try:
        last_refresh_time = int(last_refresh_str)
    except:
        last_refresh_time = 0
    
    current_time = int(time.time())
    time_since_refresh = current_time - last_refresh_time
    
    if time_since_refresh < 30:
        # Ktoś inny mógł właśnie odświeżyć - poczekaj i sprawdź
        print(f"[LOG] [{config['company'].upper()}] Ostatni refresh był {time_since_refresh}s temu - czekam na zakończenie...")
        import time as time_module
        time_module.sleep(3)  # Poczekaj 3 sekundy
        
        # Odśwież ENV z Render (pobierz najnowsze wartości)
        if RENDER_API_KEY and RENDER_SERVICE_ID:
            try:
                url = f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/env-vars"
                headers = {"Authorization": f"Bearer {RENDER_API_KEY}"}
                resp = requests.get(url, headers=headers)
                if resp.status_code == 200:
                    for item in resp.json():
                        env_var = item.get('envVar', {})
                        key = env_var.get('key')
                        value = env_var.get('value')
                        if key and key.startswith(prefix):
                            os.environ[key] = value
                    print(f"[LOG] [{config['company'].upper()}] Odświeżono ENV z Render")
            except Exception as e:
                print(f"[LOG] [{config['company'].upper()}] Błąd pobierania ENV z Render: {e}")
        
        # Sprawdź czy token jest już ważny (odświeżony przez inny proces)
        token_expires_str = os.environ.get(f"{prefix}TOKEN_EXPIRES", '0')
        try:
            token_expires = int(token_expires_str)
            if token_expires > current_time + 60:  # Ważny jeszcze co najmniej 60s
                access_token = os.environ.get(f"{prefix}ACCESS_TOKEN")
                if access_token:
                    print(f"[LOG] [{config['company'].upper()}] Token został odświeżony przez inny proces - używam go")
                    return access_token
        except:
            pass
    
    # Oznacz że zaczynamy refresh (blokada dla innych procesów)
    os.environ[last_refresh_key] = str(current_time)
    update_render_env_var(last_refresh_key, str(current_time))
    
    refresh_token = forced_refresh_token
    if not refresh_token and company is None and os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                data = json.load(f)
                refresh_token = data.get('refresh_token')
        except:
            pass
            
    # Fallback: sprawdź zmienną środowiskową dla danej firmy
    if not refresh_token:
        refresh_token = config['refresh_token']
        
    if not refresh_token:
        print(f"[LOG] [{config['company'].upper()}] Brak refresh tokena, nie można odświeżyć sesji")
        return None
        
    print(f"[LOG] [{config['company'].upper()}] Próba odświeżenia tokenu...")
    token_url = "https://api2.wfirma.pl/oauth2/token"
    payload = {
        'grant_type': 'refresh_token',
        'client_id': config['client_id'],
        'client_secret': config['client_secret'],
        'refresh_token': refresh_token
    }
    
    try:
        print(f"[LOG] [{config['company'].upper()}] Refresh payload keys: {list(payload.keys())}")
        response = requests.post(token_url, data=payload)
        print(f"[LOG] [{config['company'].upper()}] Refresh response status: {response.status_code}")
        
        if response.status_code == 200:
            new_tokens = response.json()
            new_access = new_tokens.get('access_token')
            new_refresh = new_tokens.get('refresh_token')
            expires_in = int(new_tokens.get('expires_in', 3600))
            
            # LOG: sprawdź czy wFirma zwraca nowy refresh_token
            print(f"[LOG] [{config['company'].upper()}] Refresh response: access={bool(new_access)}, refresh={bool(new_refresh)}, expires={expires_in}")
            
            if new_access:
                # WAŻNE: Zapisujemy nowe tokeny NATYCHMIAST (przed jakimkolwiek returnem)
                save_token(new_access, expires_in, new_refresh, company=company)
                print(f"[LOG] [{config['company'].upper()}] Token odświeżony pomyślnie i zapisany do ENV")
                return new_access
            else:
                print(f"[LOG] [{config['company'].upper()}] Brak access_token w odpowiedzi: {new_tokens}")
        else:
            print(f"[LOG] [{config['company'].upper()}] Błąd API refresh token: {response.status_code} {response.text}")
    except Exception as e:
        print(f"[LOG] [{config['company'].upper()}] Błąd podczas odświeżania tokenu: {e}")
        
    return None

def is_token_valid():
    """Sprawdź czy zapisany token jest ważny dla domyślnej firmy"""
    return is_token_valid_for_company(None)


def is_token_valid_for_company(company=None):
    """Sprawdź czy zapisany token jest ważny dla danej firmy (ENV > plik)"""
    config = get_company_config(company)
    
    # 1. Sprawdź ENV dla danej firmy (priorytet - trwałe po redeployu)
    env_expires = config['token_expires']
    env_access = config['access_token']
    if env_expires and env_access:
        try:
            return time.time() < float(env_expires)
        except:
            pass
    
    # 2. Fallback: sprawdź plik (tylko dla domyślnej firmy - backward compatibility)
    if company is None and os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                token_data = json.load(f)
            return time.time() < token_data.get('expires_at', 0)
        except:
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
    """
    config = get_company_config(company)
    prefix = config['prefix']
    
    refresh_expires = os.environ.get(f'{prefix}REFRESH_TOKEN_EXPIRES')
    if not refresh_expires:
        # Fallback na starą zmienną (backward compatibility)
        refresh_expires = os.environ.get('WFIRMA_REFRESH_TOKEN_EXPIRES')
    if not refresh_expires:
        return None, None
    
    try:
        expires_at = float(refresh_expires)
        now = time.time()
        seconds_remaining = expires_at - now
        days_remaining = seconds_remaining / (24 * 60 * 60)
        
        company_label = config['company'].upper()
        
        if days_remaining <= 0:
            return 0, f"🚨 [{company_label}] REFRESH TOKEN WYGASŁ! Przejdź przez /auth?company={config['company']} NATYCHMIAST!"
        elif days_remaining <= 3:
            return days_remaining, f"🔴 [{company_label}] PILNE! Refresh token wygasa za {days_remaining:.1f} dni! Przejdź przez /auth?company={config['company']}!"
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
    """Zwraca pełny status tokenów dla danej firmy (do endpointu /api/token/status)"""
    config = get_company_config(company)
    prefix = config['prefix']
    
    status = {
        'company': config['company'],
        'access_token_valid': is_token_valid_for_company(company),
        'refresh_token_exists': bool(config['refresh_token']),
    }
    
    # Access token
    env_expires = config['token_expires']
    if env_expires:
        try:
            expires_at = float(env_expires)
            status['access_token_expires_at'] = expires_at
            status['access_token_remaining_seconds'] = max(0, int(expires_at - time.time()))
        except:
            pass
    
    # Refresh token
    days_remaining, warning = check_refresh_token_expiry_for_company(company)
    if days_remaining is not None:
        status['refresh_token_days_remaining'] = round(days_remaining, 1)
        status['refresh_token_expires_at'] = os.environ.get(f'{prefix}REFRESH_TOKEN_EXPIRES')
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
    
    notification_data = {
        "type": "refresh_token_expiry_warning",
        "days_remaining": round(days_remaining, 1) if days_remaining else 0,
        "warning": warning_message,
        "email": email,
        "service_url": os.environ.get('REDIRECT_URI', 'https://wfirma-api.onrender.com').replace('/callback', ''),
        "action_required": "Przejdź na /auth aby odnowić token",
        "timestamp": datetime.datetime.now().isoformat()
    }
    
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

def load_token(silent=False, company=None):
    """
    Wczytaj token (ENV > plik) - automatycznie odświeża jeśli wygasł.
    Po redeployu plik nie istnieje, więc ENV jest GŁÓWNYM źródłem!
    
    Args:
        silent: Czy ukrywać logi
        company: Firma/zestaw danych ('md' lub 'test'). Jeśli None - używa domyślnego.
    """
    config = get_company_config(company)
    prefix = config['prefix']
    
    access_token = None
    expires_at = 0
    refresh_token = None
    
    # 1. NAJPIERW sprawdź ENV dla danej firmy (trwałe po redeployu!)
    env_access = config['access_token']
    env_expires = config['token_expires']
    env_refresh = config['refresh_token']
    
    if env_access and env_expires:
        try:
            access_token = env_access
            expires_at = float(env_expires)
            refresh_token = env_refresh
            if not silent:
                print(f"[LOG] [{config['company'].upper()}] Tokeny wczytane z ENV ({prefix}*)")
        except:
            pass
    
    # 2. Jeśli brak w ENV, sprawdź plik (tylko dla domyślnej firmy - backward compatibility)
    if not access_token and company is None and os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                token_data = json.load(f)
            access_token = token_data.get('access_token')
            expires_at = token_data.get('expires_at', 0)
            refresh_token = token_data.get('refresh_token') or env_refresh
            if not silent:
                print(f"[LOG] Tokeny wczytane z pliku")
        except Exception as e:
            if not silent:
                print(f"[LOG] Błąd wczytywania z pliku: {e}")
    
    # 3. Jeśli token ważny - zwróć
    if access_token and time.time() < expires_at:
        remaining = int(expires_at - time.time())
        if not silent:
            print(f"[LOG] [{config['company'].upper()}] ✓ Token ważny jeszcze {remaining} sekund")
        return access_token
    
    # 4. Token wygasł lub brak - spróbuj odświeżyć
    if not refresh_token:
        refresh_token = env_refresh  # Ostatnia szansa - ENV
    
    if refresh_token:
        if not silent:
            print(f"[LOG] [{config['company'].upper()}] Token wygasł/brak, próba odświeżenia...")
        new_token = refresh_access_token(forced_refresh_token=refresh_token, company=company)
        if new_token:
            return new_token
    
    if not silent:
        print(f"[LOG] [{config['company'].upper()}] Brak tokenu i refresh_token - wymagana autoryzacja /auth")
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


def require_api_key(f):
    """Decorator wymagający API Key w headerze X-API-Key (ochrona przed nieuprawnionymi wywołaniami)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Jeśli MAKE_RENDER_API_KEY nie jest ustawiony w ENV - pomijamy weryfikację (dev mode)
        if not MAKE_RENDER_API_KEY:
            print("[WARNING] MAKE_RENDER_API_KEY nie jest ustawiony - brak ochrony API!")
            return f(*args, **kwargs)
        
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
        
        # Weryfikuj podpis
        is_valid, error = verify_webhook_signature(payload, signature)
        if not is_valid:
            return jsonify({
                'status': 'error',
                'error': error or 'Invalid signature'
            }), 400
        
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
        
        # Przetwórz event
        result = process_webhook_event(event_type, event_data)
        
        # Stripe wymaga 200 OK nawet dla zignorowanych eventów
        return jsonify(result), 200
        
    except Exception as e:
        # Loguj błąd ale zwróć 200 żeby Stripe nie ponawiał
        print(f"[STRIPE WEBHOOK ERROR] {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 200


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
            return jsonify({
                'status': 'error',
                'error': error or 'Invalid signature'
            }), 400
        
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return jsonify({
                'status': 'error',
                'error': 'Invalid JSON payload'
            }), 400
        
        event_type = event.get('type', '')
        event_data = event.get('data', {}).get('object', {})
        
        result = process_webhook_event(event_type, event_data)
        result['mode'] = 'sandbox'
        
        return jsonify(result), 200
        
    except Exception as e:
        print(f"[STRIPE SANDBOX WEBHOOK ERROR] {str(e)}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 200


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
    
    if not client_id:
        return jsonify({
            'error': f'CLIENT_ID nie jest ustawiony dla firmy {company.upper()}',
            'expected_env': f'{config["prefix"]}CLIENT_ID'
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
        f"redirect_uri={quote(REDIRECT_URI, safe='')}&"
        f"state={company}"  # state jest zwracany bez zmian w callbacku
    )
    
    print(f"[AUTH] Rozpoczynam autoryzację dla firmy: {company.upper()}")
    print(f"[AUTH] Client ID: {client_id[:10]}...")
    print(f"[AUTH] Redirect URI: {REDIRECT_URI}")
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
    # WAŻNE: company jest przekazywane przez parametr 'state' (nie query param!)
    state = request.args.get('state', '')
    company = (state or DEFAULT_COMPANY).lower().strip()
    
    if company not in SUPPORTED_COMPANIES:
        company = DEFAULT_COMPANY
    
    config = get_company_config(company)
    
    print(f"[CALLBACK] Otrzymano callback, state={state}, company={company.upper()}")
    
    if error:
        return jsonify({
            'error': 'Błąd autoryzacji',
            'details': error,
            'company': company
        }), 400
    
    if not code:
        return jsonify({'error': 'Brak kodu autoryzacyjnego', 'company': company}), 400
    
    # WAŻNE: redirect_uri musi być DOKŁADNIE taki jak w /auth (bez query params!)
    # Wymień kod na token używając credentials dla danej firmy
    token_url = "https://api2.wfirma.pl/oauth2/token?oauth_version=2"
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': config['client_id'],
        'client_secret': config['client_secret'],
        'redirect_uri': REDIRECT_URI  # Musi być identyczny jak zarejestrowany!
    }
    
    print(f"[CALLBACK] [{company.upper()}] Wymiana kodu na token...")
    print(f"[CALLBACK] [{company.upper()}] Client ID: {config['client_id'][:10] if config['client_id'] else 'BRAK'}...")
    print(f"[CALLBACK] [{company.upper()}] Redirect URI: {REDIRECT_URI}")
    
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
        save_token(access_token, expires_in, refresh_token, company=company)
        
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
    Parametr ?company=md lub ?company=test
    """
    company = (request.args.get('company') or DEFAULT_COMPANY).lower().strip()
    if company not in SUPPORTED_COMPANIES:
        company = DEFAULT_COMPANY
    
    config = get_company_config(company)
    
    print(f"[TOKEN REFRESH] Próba odświeżenia tokenu dla firmy: {company.upper()}")
    print(f"[TOKEN REFRESH] Client ID exists: {bool(config['client_id'])}")
    print(f"[TOKEN REFRESH] Client Secret exists: {bool(config['client_secret'])}")
    print(f"[TOKEN REFRESH] Refresh Token exists: {bool(config['refresh_token'])}")
    
    if not config['client_id'] or not config['client_secret']:
        return jsonify({
            'error': f'Brak CLIENT_ID lub CLIENT_SECRET dla firmy {company.upper()}',
            'expected_vars': [f'{config["prefix"]}CLIENT_ID', f'{config["prefix"]}CLIENT_SECRET'],
            'company': company
        }), 400
    
    if not config['refresh_token']:
        return jsonify({
            'error': f'Brak REFRESH_TOKEN dla firmy {company.upper()}',
            'expected_var': f'{config["prefix"]}REFRESH_TOKEN',
            'message': f'Przejdź do /auth?company={company} żeby uzyskać nowy token',
            'company': company
        }), 400
    
    # Próba odświeżenia
    new_token = refresh_access_token(forced_refresh_token=config['refresh_token'], company=company)
    
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

@app.route('/api/contractor/<nip>')
@require_api_key
@require_token
def check_contractor(token, nip):
    """Sprawdź czy kontrahent istnieje po NIP"""
    contractor, resp = wfirma_find_contractor_by_nip(token, nip)
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
    contractor, resp = wfirma_add_contractor(token, data)
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
    invoice, resp = wfirma_create_invoice(token, data)
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
    try:
        contractor_id_int = int(contractor.get('id'))
    except (ValueError, TypeError):
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
    # Seria faktur - domyślna dla TEST i MD to "Eventy"
    default_series = 'Eventy'  # Używana dla obu firm
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
        contractor_id = contractor.get('id') if contractor else None
        
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
        contractor_id = contractor.get('id')
        contractor_created = True
    
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
        contractor_id = contractor.get('id')
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
    if invoice_id:
        base_url = request.url_root.rstrip('/') if hasattr(request, 'url_root') else REDIRECT_URI.replace('/callback', '')
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

    resp = wfirma_send_invoice_email(token, invoice_id, email)
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
    
    # 1) Pobierz oryginalną fakturę żeby uzyskać dane kontrahenta i pozycji
    original_invoice, err = wfirma_get_invoice(token, str(parent_invoice_id))
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
        resp_series = wfirma_find_series(token, series_name)
        if resp_series.status_code == 200:
            try:
                series_list = resp_series.json().get('series', [])
                if isinstance(series_list, dict):
                    for key, val in series_list.items():
                        if isinstance(val, dict) and 'serie' in val:
                            s = val['serie']
                            if s.get('name', '').lower() == series_name.lower():
                                series_id = int(s.get('id'))
                                print(f"[CORRECTION] Znaleziono serię: {series_name} -> ID {series_id}")
                                break
            except Exception as e:
                print(f"[CORRECTION] Błąd parsowania serii: {e}")
    
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
    invoice_result, resp = wfirma_create_invoice(token, correction_payload)
    
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

