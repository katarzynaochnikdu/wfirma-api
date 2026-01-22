import json
import os
import csv
import io
import string
import secrets
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, Response, abort, flash, redirect, render_template_string, request, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash

from pg_storage import (
    delete_event,
    get_event,
    get_ticket_classes,
    list_events,
    parse_kv_lines,
    replace_ticket_classes,
    upsert_event,
    # Payment rules
    list_payment_rules,
    get_payment_rule,
    upsert_payment_rule,
    delete_payment_rule,
    match_payment_rule,
    # Orders
    list_orders,
    get_order,
    update_order_status,
    delete_order,
    get_wfirma_documents,
    count_participants_by_status,
    # Event tickets/participants stats
    get_participants_for_event,
    get_participants_for_order,
    get_event_ticket_stats,
    # Mails
    mail_log_exists,
    save_mail_log,
    # Admin users
    admin_user_count,
    get_admin_user_by_email,
    get_admin_user_by_id,
    list_admin_users,
    create_admin_user,
    update_admin_user_password,
    update_admin_user_active,
    update_admin_user_last_login,
    increment_admin_user_failed_login,
    delete_admin_user,
    update_admin_user_access,
    insert_admin_audit_log,
    list_admin_audit_log,
)


admin_bp = Blueprint("admin_bp", __name__)


ADMIN_PANEL_TOKEN = os.environ.get("ADMIN_PANEL_TOKEN")  # ustaw w Render ENV (LEGACY - docelowo usunąć)
ADMIN_BOOTSTRAP_TOKEN = os.environ.get("ADMIN_BOOTSTRAP_TOKEN")  # tymczasowy token do utworzenia pierwszego admina

# Uprawnienia kart w panelu
ADMIN_PAGE_OPTIONS = [
    ("events", "Wydarzenia"),
    ("orders", "Zamówienia"),
    ("import", "Import"),
    ("users", "Konta i uprawnienia"),
    ("audit", "Log audytu"),
]


# ---------------------------------------------------------------------------
# SESSION-BASED AUTHENTICATION (nowe logowanie email+hasło)
# ---------------------------------------------------------------------------

def _get_current_admin_user() -> Optional[Dict[str, Any]]:
    """Zwraca aktualnie zalogowanego admina z sesji (lub None)."""
    user_id = session.get("admin_user_id")
    if not user_id:
        return None
    user = get_admin_user_by_id(user_id)
    if not user or not user.get("is_active"):
        # Wyczyść nieważną sesję
        session.pop("admin_user_id", None)
        return None
    return user


def _normalize_allowed_pages(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed if v]
        except Exception:
            return [v.strip() for v in value.split(",") if v.strip()]
    return []


def _user_has_permission(user: Optional[Dict[str, Any]], permission_key: str) -> bool:
    # Legacy token lub brak usera -> pełny dostęp
    if not user:
        return True
    role_raw = (user.get("role") or "").strip().lower()
    role = role_raw or "admin"
    if role == "admin":
        return True
    allowed = _normalize_allowed_pages(user.get("allowed_pages"))
    return permission_key in allowed


def _is_viewer(user: Optional[Dict[str, Any]]) -> bool:
    """Czy user ma rolę viewer (read-only)."""
    if not user:
        return False
    return (user.get("role") or "").strip().lower() == "viewer"


def _is_admin_user(user: Optional[Dict[str, Any]]) -> bool:
    """Czy user ma rolę admin (pełny dostęp)."""
    if not user:
        return True  # legacy token / brak usera
    return (user.get("role") or "").strip().lower() == "admin"


def _normalize_allowed_events(value: Any) -> List[str]:
    """Normalizuje listę dozwolonych wydarzeń."""
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed if v]
        except Exception:
            return [v.strip() for v in value.split(",") if v.strip()]
    return []


def _user_can_access_event(user: Optional[Dict[str, Any]], event_id: str) -> bool:
    """Sprawdza czy user ma dostęp do wydarzenia."""
    if not user:
        return True  # Legacy token
    role = (user.get("role") or "").strip().lower() or "admin"
    if role == "admin":
        return True  # Admin widzi wszystko
    # Viewer/limited - sprawdź allowed_events
    allowed = _normalize_allowed_events(user.get("allowed_events"))
    if not allowed:
        return False  # Brak przypisanych wydarzeń
    return event_id in allowed


def _first_allowed_page(user: Optional[Dict[str, Any]]) -> str:
    for key, _label in ADMIN_PAGE_OPTIONS:
        if _user_has_permission(user, key):
            return key
    return "orders"


def _landing_url_for_user(user: Optional[Dict[str, Any]], token: Optional[str] = None) -> str:
    key = _first_allowed_page(user)
    if key == "events":
        return url_for("admin_bp.events_list", token=token) if token else url_for("admin_bp.events_list")
    if key == "orders":
        return url_for("admin_bp.orders_list", token=token) if token else url_for("admin_bp.orders_list")
    if key == "import":
        return url_for("admin_bp.import_page", token=token) if token else url_for("admin_bp.import_page")
    if key == "users":
        return url_for("admin_bp.users_list", token=token) if token else url_for("admin_bp.users_list")
    if key == "audit":
        return url_for("admin_bp.audit_log", token=token) if token else url_for("admin_bp.audit_log")
    return url_for("admin_bp.orders_list")


def _require_admin_login():
    """
    Dekorator wymagający zalogowania przez sesję.
    Jeśli użytkownik nie jest zalogowany, przekierowuje do /admin/login.
    
    TYMCZASOWO: akceptuje też stary ADMIN_PANEL_TOKEN (dla migracji).
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 1. Sprawdź sesję (nowe logowanie)
            user = _get_current_admin_user()
            if user:
                # Dodaj user do kontekstu (request.admin_user)
                request.admin_user = user
                return f(*args, **kwargs)
            
            # 2. LEGACY: sprawdź stary token (do usunięcia po migracji)
            if ADMIN_PANEL_TOKEN:
                token = (
                    (request.args.get("token") or "").strip()
                    or (request.form.get("token") or "").strip()
                    or (request.headers.get("X-Admin-Token") or "").strip()
                )
                if token and token == ADMIN_PANEL_TOKEN:
                    # Legacy token - nie ma user, ale przepuszczamy
                    request.admin_user = None
                    return f(*args, **kwargs)
            
            # 3. Niezalogowany - redirect do logowania
            return redirect(url_for("admin_bp.login"))
        return decorated_function
    return decorator


def _get_admin_token_for_legacy() -> Optional[str]:
    """Zwraca token dla legacy URL-i (jeśli jest w sesji lub request)."""
    # Jeśli zalogowany przez sesję, nie potrzeba tokenu
    if _get_current_admin_user():
        return None
    # Legacy: token z request
    return (
        (request.args.get("token") or "").strip()
        or (request.form.get("token") or "").strip()
    ) or None


def _generate_csrf_token() -> str:
    """Generuje lub zwraca istniejący CSRF token z sesji."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def _verify_csrf_token() -> bool:
    """Weryfikuje CSRF token z formularza."""
    form_token = request.form.get("csrf_token", "").strip()
    session_token = session.get("csrf_token", "")
    return form_token and session_token and secrets.compare_digest(form_token, session_token)


def _get_client_ip() -> str:
    """Pobiera IP klienta (uwzględnia proxy)."""
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()


def _generate_temp_password(length: int = 12) -> str:
    """Generuje tymczasowe hasło (bez znaków niejednoznacznych)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(max(10, int(length))))


def _send_admin_credentials_email(to_email: str, full_name: str, temp_password: str, is_reset: bool) -> bool:
    """Wysyła email z hasłem tymczasowym i linkiem do logowania."""
    try:
        from backstage_engine import _send_email_via_make
    except Exception:
        return False

    login_url = url_for("admin_bp.login", _external=True)
    change_url = url_for("admin_bp.change_password", _external=True)
    subject = "Dostęp do panelu administracyjnego płatności"
    headline = "Reset hasła do panelu" if is_reset else "Twoje konto w panelu administracyjnym"

    body_html = f"""
    <div style="background:#f8fafc; padding:24px 12px; font-family: 'EuclidCircularB', Arial, sans-serif; color:#1e293b;">
      <table width="100%" cellpadding="0" cellspacing="0" style="max-width:640px; margin:0 auto; background:#fff; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden;">
        <tr>
          <td style="background:#0065D7; padding:22px 24px;">
            <div style="color:#fff; font-size:18px; font-weight:700; letter-spacing:0.3px;">HALO MEDIDESK</div>
            <div style="color:#e0f2fe; font-size:13px; margin-top:4px;">Dostęp do portalu</div>
          </td>
        </tr>
        <tr>
          <td style="padding:22px 24px;">
            <h2 style="margin:0 0 10px 0; font-size:18px; font-weight:700; color:#0f172a;">{headline}</h2>
            <p style="margin:0 0 10px 0; font-size:14px;">Witaj {full_name or ""}</p>
            <p style="margin:0 0 14px 0; font-size:14px; color:#334155;">Poniżej masz tymczasowe hasło. Po pierwszym logowaniu system wymusi jego zmianę.</p>
            <div style="padding:12px 14px; background:#f1f5f9; border:1px solid #e2e8f0; border-radius:8px; margin:12px 0;">
              <div style="font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:16px; letter-spacing:0.6px;">{temp_password}</div>
            </div>
            <div style="margin:16px 0;">
              <a href="{login_url}" style="display:inline-block; background:#0065D7; color:#fff; text-decoration:none; padding:10px 16px; border-radius:8px; font-weight:600;">Przejdź do logowania</a>
            </div>
            <p style="margin:0 0 10px 0; font-size:13px;">Po zalogowaniu: <a href="{change_url}" style="color:#0065D7; text-decoration:none; font-weight:600;">Zmień hasło</a></p>
            <p style="color:#64748b; font-size:12px; margin:16px 0 0 0;">Jeśli to nie Ty inicjujesz dostęp, zignoruj tę wiadomość.</p>
          </td>
        </tr>
        <tr>
          <td style="padding:0 24px 18px 24px;">
            <hr style="border:none; border-top:1px solid #e2e8f0; margin:0 0 16px 0;">
            <div style="font-size:12px; color:#475569; font-weight:600;">Serdecznie pozdrawiam,</div>
          </td>
        </tr>
      </table>
      
      <!-- Stopka -->
      <table width="100%" cellpadding="0" cellspacing="0" style="max-width:640px; margin:12px auto 0 auto; background:transparent;">
        <tr>
          <td style="padding:0 8px;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#fff; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden;">
              <tr>
                <td style="padding:16px;">
                  <table width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="width:110px;" valign="top">
                        <img style="border:1px #0074d7 solid; border-radius:50%; width:90px; height:90px; object-fit:cover;" alt="HALO MEDIDESK" src="https://raw.githubusercontent.com/adminzohomedidesk/Stopka_email/main/photos/55dfa5e8a1974e8db504ede103d9b17caa5b4c5f.png">
                      </td>
                      <td style="padding-left:10px;" valign="top">
                        <div style="font-size:14px; font-weight:700; color:#0074d7;">HALO MEDIDESK</div>
                        <div style="height:6px;"></div>
                        <div style="width:90px; height:3px; background:#0074d7;"></div>
                        <div style="height:8px;"></div>
                        <a style="text-decoration:none; color:#333333; font-size:12px; font-weight:500;" href="mailto:halo@medidesk.com">
                          <img style="max-width:18px; margin-right:5px; vertical-align:middle;" alt="halo@medidesk.com" src="https://raw.githubusercontent.com/adminzohomedidesk/Stopka_email/main/mail_mini.png">
                          <span>halo@medidesk.com</span>
                        </a>
                      </td>
                    </tr>
                  </table>
                  <div style="height:12px;"></div>
                  <div style="font-size:11px; color:#333333;">
                    Medidesk Sp. z o.o. <span style="color:#0074d7; font-weight:700;">|</span>
                    ul. W. Niegolewskiego 17/2 <span style="color:#0074d7; font-weight:700;">|</span>
                    01-570 Warszawa
                  </div>
                </td>
              </tr>
              <tr>
                <td style="padding:0 16px 14px 16px;">
                  <a target="_blank" href="https://adminzohomedidesk.github.io/Stopka_email/banner_akcja.html" rel="noopener noreferrer">
                    <img style="border:0; max-width:100%; width:100%; height:auto;" alt="Medidesk" src="https://raw.githubusercontent.com/adminzohomedidesk/Stopka_email/main/banner_akcja_1.png">
                  </a>
                </td>
              </tr>
              <tr>
                <td style="padding:0 16px 16px 16px; font-size:11px; color:#00cca3;">
                  Obserwuj nas: <a style="text-decoration:none; color:#00cca3;" href="https://medidesk.pl/">medidesk.com</a> <span>|</span>
                  <a style="text-decoration:none; color:#00cca3;" href="https://www.facebook.com/medideskpl/">Facebook</a> <span>|</span>
                  <a style="text-decoration:none; color:#00cca3;" href="https://www.linkedin.com/company/18386183/">Linkedin</a>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </div>
    """
    res = _send_email_via_make(
        to_email=to_email,
        subject=subject,
        body_html=body_html,
        event_order_id="ADMIN-USER",
        template_type="admin_credentials",
    )
    return bool(res.get("success"))


# ---------------------------------------------------------------------------
# IFRAME LAUNCHER (for Zoho CRM integration)
# ---------------------------------------------------------------------------

@admin_bp.route("/launch", methods=["GET"])
def launch():
    """
    Strona nakładki dla iframe (np. Zoho CRM).
    
    Ze względu na ograniczenia cookies (SameSite) sesje nie działają w iframe.
    Ta strona wyświetla przycisk otwierający panel admin w nowej karcie.
    """
    # Build the login URL (absolute)
    login_url = url_for("admin_bp.login", _external=True)
    
    # Full standalone HTML (no BASE_HTML to avoid any session issues)
    html = f"""
<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Medidesk Admin</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
      padding: 20px;
      overflow: auto;
    }}
    
    .launch-card {{
      width: 100%;
      max-width: 520px;
      background: #fff;
      border-radius: 16px;
      box-shadow: 0 10px 40px rgba(0, 101, 215, 0.1), 0 2px 10px rgba(0, 0, 0, 0.05);
      overflow: hidden;
      text-align: center;
    }}
    
    .launch-header {{
      background: linear-gradient(90deg, #00E09F 0%, #00A1D7 50%, #0065D7 100%);
      padding: 36px 28px;
    }}
    
    .launch-header svg {{
      height: 36px;
      margin-bottom: 8px;
    }}
    
    .launch-header p {{
      color: rgba(255,255,255,0.9);
      font-size: 14px;
      font-weight: 500;
    }}
    
    .launch-body {{
      padding: 36px 32px 40px;
    }}
    
    .launch-icon {{
      width: 64px;
      height: 64px;
      margin: 0 auto 20px;
      background: linear-gradient(135deg, #e0f2fe 0%, #dbeafe 100%);
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    
    .launch-icon svg {{
      width: 32px;
      height: 32px;
      color: #0065D7;
    }}
    
    .launch-title {{
      font-size: 22px;
      font-weight: 600;
      color: #1e293b;
      margin-bottom: 12px;
    }}
    
    .launch-desc {{
      font-size: 15px;
      color: #64748b;
      line-height: 1.6;
      margin-bottom: 28px;
    }}
    
    .launch-btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      width: 100%;
      padding: 16px 24px;
      background: #0065D7;
      color: #fff;
      border: none;
      border-radius: 10px;
      font-size: 16px;
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
      transition: background 0.15s ease, transform 0.1s ease;
    }}
    
    .launch-btn:hover {{
      background: #0052b3;
      transform: translateY(-1px);
    }}
    
    .launch-btn:active {{
      transform: translateY(0);
    }}
    
    .launch-btn svg {{
      width: 20px;
      height: 20px;
    }}

    .launch-btn .btn-logo {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: rgba(255, 255, 255, 0.15);
      border: 1px solid rgba(255, 255, 255, 0.35);
      flex: 0 0 auto;
    }}

    .launch-btn .btn-logo svg {{
      width: 18px;
      height: 18px;
    }}
    
    .launch-hint {{
      margin-top: 20px;
      font-size: 12px;
      color: #94a3b8;
    }}
    
    /* Iframe detection message */
    .iframe-notice {{
      display: none;
      background: #fef3c7;
      color: #92400e;
      padding: 12px 16px;
      font-size: 13px;
      border-bottom: 1px solid #fcd34d;
    }}
    
    body.in-iframe .iframe-notice {{
      display: block;
    }}

    /* In iframe we keep content at the top to avoid clipping */
    body.in-iframe {{
      align-items: center;
      justify-content: center;
      padding-top: 20px;
      padding-bottom: 20px;
    }}

    /* Subtle compact tweaks for iframe without squeezing */
    body.in-iframe .launch-header {{
      padding: 28px 24px;
    }}

    body.in-iframe .launch-body {{
      padding: 28px 24px 32px;
    }}
  </style>
</head>
<body>
  <div class="launch-card">
    <div class="iframe-notice">
      Panel wymaga otwarcia w osobnej karcie przeglądarki
    </div>
    
    <div class="launch-header">
      <svg viewBox="0 0 145 29" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path fill="#fff" d="M33.85 27.74c2-.0 4.1-.8 5.16-1.68.58-.46.86-.98.86-1.5 0-.8-.67-1.53-1.55-1.53-.33 0-.67.09-1.03.28-.67.37-1.4 1.07-3.62 1.07-2.1 0-4.1-1.35-4.62-3.85h10.03c.97 0 1.8-.67 1.85-1.65 0-4.4-3.59-8.1-7.69-8.1-4.01 0-7.81 3.24-7.81 8.71 0 4.71 3.22 8.26 8.42 8.26zm-.48-13.6c1.88 0 3.65 1.37 3.8 3.12v.21h-7.96c.49-2.54 2.13-3.33 4.16-3.33zM56.49 4.81c-1.06 0-1.82.8-1.82 1.87v5.99c-1.07-.98-2.8-1.9-4.9-1.9-4.1 0-7.36 3.49-7.36 8.5 0 4.98 3.25 8.47 7.48 8.47 2.07 0 3.86-1.1 4.77-2.14 0 1.04.76 1.83 1.82 1.83 1.07 0 1.83-.8 1.83-1.87V6.68c0-1.1-.76-1.87-1.82-1.87zm-6.14 19.57c-2.64 0-4.44-2.2-4.44-5.1 0-2.91 1.8-5.14 4.44-5.14 2.68 0 4.47 2.23 4.47 5.14 0 2.9-1.79 5.1-4.47 5.1zM65.07 12.94c0-1.07-.76-1.86-1.82-1.86-1.07 0-1.83.79-1.83 1.86v12.63c0 1.07.76 1.86 1.83 1.86 1.06 0 1.82-.79 1.82-1.86V12.94zm-1.73-4.44c1.06 0 1.92-.86 1.92-1.93 0-1.07-.86-1.93-1.92-1.93-1.06 0-1.92.86-1.92 1.93 0 1.07.86 1.93 1.92 1.93zM81.33 4.81c-1.07 0-1.83.8-1.83 1.87v5.99c-1.06-.98-2.79-1.9-4.89-1.9-4.1 0-7.36 3.49-7.36 8.5 0 4.98 3.25 8.47 7.48 8.47 2.07 0 3.86-1.1 4.77-2.14 0 1.04.76 1.83 1.83 1.83 1.06 0 1.82-.8 1.82-1.87V6.68c0-1.1-.76-1.87-1.82-1.87zm-6.14 19.57c-2.65 0-4.44-2.2-4.44-5.1 0-2.91 1.79-5.14 4.44-5.14 2.67 0 4.47 2.23 4.47 5.14 0 2.9-1.8 5.1-4.47 5.1zM93.97 27.74c2.01 0 4.1-.8 5.17-1.68.58-.46.85-.98.85-1.5 0-.8-.67-1.53-1.55-1.53-.33 0-.67.09-1.03.28-.67.37-1.4 1.07-3.62 1.07-2.1 0-4.1-1.35-4.61-3.85h10.03c.97 0 1.79-.67 1.85-1.65 0-4.4-3.59-8.1-7.7-8.1-4.01 0-7.81 3.24-7.81 8.71 0 4.71 3.22 8.26 8.42 8.26zm-.49-13.6c1.89 0 3.65 1.37 3.8 3.12v.21h-7.96c.49-2.54 2.13-3.33 4.16-3.33zM102.51 24.9c1.58 2.14 4.17 2.84 6.57 2.84 2.83 0 5.99-1.74 5.99-4.89 0-3.58-2.89-4.43-5.35-5.1-1.79-.49-3.34-.89-3.34-2.3 0-1.53 1.4-1.68 2.31-1.68 1.49 0 2.68.58 3.37 1.47.52.49 1.46.58 2.07.09.85-.7.64-1.65.18-2.26-1.28-1.62-3.68-2.29-5.54-2.29-2.98 0-5.9 1.8-5.9 4.83 0 3.61 3.07 4.44 5.59 5.14 1.8.49 3.31.95 3.31 2.26 0 1.59-1.49 1.77-2.37 1.8-1.95 0-3.13-.67-4.29-1.86-.7-.7-1.46-.7-2.1-.31-1.03.67-.91 1.68-.5 2.26zM119.6 27.43c1.06 0 1.82-.79 1.82-1.86v-3.21l1.49-1.38 5.47 5.81c.37.4.85.61 1.34.61.82 0 1.85-.73 1.85-1.8 0-.46-.18-.95-.58-1.38l-5.32-5.81 4.59-4.25c.49-.43.73-.92.73-1.38 0-.73-.79-1.71-1.73-1.71-.46 0-.94.18-1.34.58l-6.5 6.33V6.68c0-1.07-.76-1.87-1.82-1.87-1.07 0-1.83.8-1.83 1.87v18.89c0 1.07.76 1.86 1.83 1.86zM1.76 10.94c.77 0 1.43.5 1.67 1.2.95-.69 2.08-1.09 3.39-1.09 2.27 0 4.01.76 5.16 2.18 1.15-1.37 2.81-2.18 4.92-2.18 4.26 0 6.66 2.69 6.79 7.36v7.44c0 .98-.79 1.77-1.76 1.77-.97 0-1.76-.79-1.76-1.77v-7.36c-.09-2.76-1.03-3.82-3.21-3.84-2.18 0-3.14 1.27-3.28 3.84v7.36c0 .98-.79 1.77-1.76 1.77-.97 0-1.76-.79-1.76-1.77v-6.71c-.01-.07-.01-.14 0-.22v-.42c-.1-2.76-1.04-3.82-3.21-3.84-2.26 0-3.2 1.35-3.29 4.09v7.1c0 .98-.79 1.77-1.76 1.77C.79 27.59 0 26.8 0 25.82V12.71c0-.98.79-1.77 1.76-1.77zM142.59 0c1.3-.01 2.12 1.42 1.45 2.52l-4.64 7.72c-.47.79-1.5 1.04-2.28.57-.79-.47-1.05-1.5-.57-2.28l3.1-5.16-6.18.07c-.89.01-1.62-.68-1.69-1.55l-.0-.1c-.01-.92.73-1.67 1.65-1.68l9.16-.1z"/>
      </svg>
      <p>Panel Administracyjny</p>
    </div>
    
    <div class="launch-body">
      <div class="launch-icon">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
        </svg>
      </div>
      
      <h1 class="launch-title">Otwórz Panel Admin</h1>
      
      <p class="launch-desc">
        Panel administracyjny wymaga otwarcia w osobnej karcie przeglądarki, 
        aby zapewnić pełną funkcjonalność i bezpieczeństwo sesji.
      </p>
      
      <a href="{login_url}" target="_blank" rel="noopener" class="launch-btn">
        <span class="btn-logo" aria-hidden="true">
          <svg viewBox="0 0 145 29" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path fill="#fff" d="M33.85 27.74c2-.0 4.1-.8 5.16-1.68.58-.46.86-.98.86-1.5 0-.8-.67-1.53-1.55-1.53-.33 0-.67.09-1.03.28-.67.37-1.4 1.07-3.62 1.07-2.1 0-4.1-1.35-4.62-3.85h10.03c.97 0 1.8-.67 1.85-1.65 0-4.4-3.59-8.1-7.69-8.1-4.01 0-7.81 3.24-7.81 8.71 0 4.71 3.22 8.26 8.42 8.26zm-.48-13.6c1.88 0 3.65 1.37 3.8 3.12v.21h-7.96c.49-2.54 2.13-3.33 4.16-3.33zM56.49 4.81c-1.06 0-1.82.8-1.82 1.87v5.99c-1.07-.98-2.8-1.9-4.9-1.9-4.1 0-7.36 3.49-7.36 8.5 0 4.98 3.25 8.47 7.48 8.47 2.07 0 3.86-1.1 4.77-2.14 0 1.04.76 1.83 1.82 1.83 1.07 0 1.83-.8 1.83-1.87V6.68c0-1.1-.76-1.87-1.82-1.87zm-6.14 19.57c-2.64 0-4.44-2.2-4.44-5.1 0-2.91 1.8-5.14 4.44-5.14 2.68 0 4.47 2.23 4.47 5.14 0 2.9-1.79 5.1-4.47 5.1zM65.07 12.94c0-1.07-.76-1.86-1.82-1.86-1.07 0-1.83.79-1.83 1.86v12.63c0 1.07.76 1.86 1.83 1.86 1.06 0 1.82-.79 1.82-1.86V12.94zm-1.73-4.44c1.06 0 1.92-.86 1.92-1.93 0-1.07-.86-1.93-1.92-1.93-1.06 0-1.92.86-1.92 1.93 0 1.07.86 1.93 1.92 1.93zM81.33 4.81c-1.07 0-1.83.8-1.83 1.87v5.99c-1.06-.98-2.79-1.9-4.89-1.9-4.1 0-7.36 3.49-7.36 8.5 0 4.98 3.25 8.47 7.48 8.47 2.07 0 3.86-1.1 4.77-2.14 0 1.04.76 1.83 1.83 1.83 1.06 0 1.82-.8 1.82-1.87V6.68c0-1.1-.76-1.87-1.82-1.87zm-6.14 19.57c-2.65 0-4.44-2.2-4.44-5.1 0-2.91 1.79-5.14 4.44-5.14 2.67 0 4.47 2.23 4.47 5.14 0 2.9-1.8 5.1-4.47 5.1zM93.97 27.74c2.01 0 4.1-.8 5.17-1.68.58-.46.85-.98.85-1.5 0-.8-.67-1.53-1.55-1.53-.33 0-.67.09-1.03.28-.67.37-1.4 1.07-3.62 1.07-2.1 0-4.1-1.35-4.61-3.85h10.03c.97 0 1.79-.67 1.85-1.65 0-4.4-3.59-8.1-7.7-8.1-4.01 0-7.81 3.24-7.81 8.71 0 4.71 3.22 8.26 8.42 8.26zm-.49-13.6c1.89 0 3.65 1.37 3.8 3.12v.21h-7.96c.49-2.54 2.13-3.33 4.16-3.33zM102.51 24.9c1.58 2.14 4.17 2.84 6.57 2.84 2.83 0 5.99-1.74 5.99-4.89 0-3.58-2.89-4.43-5.35-5.1-1.79-.49-3.34-.89-3.34-2.3 0-1.53 1.4-1.68 2.31-1.68 1.49 0 2.68.58 3.37 1.47.52.49 1.46.58 2.07.09.85-.7.64-1.65.18-2.26-1.28-1.62-3.68-2.29-5.54-2.29-2.98 0-5.9 1.8-5.9 4.83 0 3.61 3.07 4.44 5.59 5.14 1.8.49 3.31.95 3.31 2.26 0 1.59-1.49 1.77-2.37 1.8-1.95 0-3.13-.67-4.29-1.86-.7-.7-1.46-.7-2.1-.31-1.03.67-.91 1.68-.5 2.26zM119.6 27.43c1.06 0 1.82-.79 1.82-1.86v-3.21l1.49-1.38 5.47 5.81c.37.4.85.61 1.34.61.82 0 1.85-.73 1.85-1.8 0-.46-.18-.95-.58-1.38l-5.32-5.81 4.59-4.25c.49-.43.73-.92.73-1.38 0-.73-.79-1.71-1.73-1.71-.46 0-.94.18-1.34.58l-6.5 6.33V6.68c0-1.07-.76-1.87-1.82-1.87-1.07 0-1.83.8-1.83 1.87v18.89c0 1.07.76 1.86 1.83 1.86zM1.76 10.94c.77 0 1.43.5 1.67 1.2.95-.69 2.08-1.09 3.39-1.09 2.27 0 4.01.76 5.16 2.18 1.15-1.37 2.81-2.18 4.92-2.18 4.26 0 6.66 2.69 6.79 7.36v7.44c0 .98-.79 1.77-1.76 1.77-.97 0-1.76-.79-1.76-1.77v-7.36c-.09-2.76-1.03-3.82-3.21-3.84-2.18 0-3.14 1.27-3.28 3.84v7.36c0 .98-.79 1.77-1.76 1.77-.97 0-1.76-.79-1.76-1.77v-6.71c-.01-.07-.01-.14 0-.22v-.42c-.1-2.76-1.04-3.82-3.21-3.84-2.26 0-3.2 1.35-3.29 4.09v7.1c0 .98-.79 1.77-1.76 1.77C.79 27.59 0 26.8 0 25.82V12.71c0-.98.79-1.77 1.76-1.77zM142.59 0c1.3-.01 2.12 1.42 1.45 2.52l-4.64 7.72c-.47.79-1.5 1.04-2.28.57-.79-.47-1.05-1.5-.57-2.28l3.1-5.16-6.18.07c-.89.01-1.62-.68-1.69-1.55l-.0-.1c-.01-.92.73-1.67 1.65-1.68l9.16-.1z"/>
          </svg>
        </span>
        <span>Przejdź do panelu administracyjnego płatności</span>
      </a>
      
      <p class="launch-hint">
        Kliknij przycisk powyżej, aby otworzyć panel w nowym oknie
      </p>
    </div>
  </div>
  
  <script>
    // Detect if page is in iframe; auto-redirect when not embedded.
    var isInIframe = false;
    try {{
      isInIframe = window.self !== window.top;
    }} catch (e) {{
      isInIframe = true;
    }}
    if (isInIframe) {{
      document.body.classList.add('in-iframe');
    }} else {{
      window.location.replace("{login_url}");
    }}
  </script>
</body>
</html>
"""
    return html


# ---------------------------------------------------------------------------
# LOGIN / LOGOUT ROUTES
# ---------------------------------------------------------------------------

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    """Strona logowania do panelu admin."""
    error = None
    
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = (request.form.get("password") or "").strip()
        
        if not email or not password:
            error = "Podaj email i hasło"
        else:
            user = get_admin_user_by_email(email)
            if not user:
                error = "Nieprawidłowy email lub hasło"
                insert_admin_audit_log(
                    action="login_failed_unknown_user",
                    target_email=email,
                    ip=_get_client_ip(),
                    user_agent=request.headers.get("User-Agent", "")[:500],
                )
            elif not user.get("is_active"):
                error = "Konto jest nieaktywne"
                insert_admin_audit_log(
                    action="login_failed_inactive",
                    admin_user_id=user["id"],
                    target_email=email,
                    ip=_get_client_ip(),
                    user_agent=request.headers.get("User-Agent", "")[:500],
                )
            elif user.get("locked_until"):
                import datetime
                locked = user["locked_until"]
                now = datetime.datetime.now(datetime.timezone.utc)
                if isinstance(locked, datetime.datetime) and locked > now:
                    error = f"Konto zablokowane do {locked.strftime('%H:%M:%S')}"
                    insert_admin_audit_log(
                        action="login_failed_locked",
                        admin_user_id=user["id"],
                        target_email=email,
                        ip=_get_client_ip(),
                        user_agent=request.headers.get("User-Agent", "")[:500],
                    )
                else:
                    # Lock wygasł, kontynuuj sprawdzanie hasła
                    pass
            
            if not error:
                # Sprawdź hasło
                if check_password_hash(user["password_hash"], password):
                    # Sukces - zaloguj
                    session["admin_user_id"] = user["id"]
                    session.permanent = True  # Sesja trwa dłużej niż przeglądarka
                    update_admin_user_last_login(user["id"])
                    insert_admin_audit_log(
                        action="login_success",
                        admin_user_id=user["id"],
                        target_email=email,
                        ip=_get_client_ip(),
                        user_agent=request.headers.get("User-Agent", "")[:500],
                    )
                    if user.get("must_change_password"):
                        return redirect(url_for("admin_bp.change_password"))
                    return redirect(_landing_url_for_user(user))
                else:
                    # Błędne hasło
                    failed_count = increment_admin_user_failed_login(user["id"])
                    if failed_count >= 5:
                        error = "Zbyt wiele nieudanych prób. Konto zablokowane na 15 minut."
                    else:
                        error = "Nieprawidłowy email lub hasło"
                    insert_admin_audit_log(
                        action="login_failed_wrong_password",
                        admin_user_id=user["id"],
                        target_email=email,
                        ip=_get_client_ip(),
                        user_agent=request.headers.get("User-Agent", "")[:500],
                        data={"failed_count": failed_count},
                    )
    
    # Formularz logowania - stylizowany z kolorami Medidesk
    can_audit = _user_has_permission(_get_current_admin_user(), "audit")
    body = f"""
    <style>
      .login-wrapper {{
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
        padding: 20px;
      }}
      .login-card {{
        width: 100%;
        max-width: 420px;
        background: #fff;
        border-radius: 16px;
        box-shadow: 0 10px 40px rgba(0, 101, 215, 0.1), 0 2px 10px rgba(0, 0, 0, 0.05);
        overflow: hidden;
      }}
      .login-header {{
        background: linear-gradient(90deg, #00E09F 0%, #00A1D7 50%, #0065D7 100%);
        padding: 32px 32px 28px;
        text-align: center;
      }}
      .login-header svg {{
        height: 32px;
        margin-bottom: 8px;
      }}
      .login-header h1 {{
        margin: 0;
        font-size: 14px;
        font-weight: 500;
        color: rgba(255,255,255,0.9);
        letter-spacing: 0.5px;
      }}
      .login-body {{
        padding: 32px;
      }}
      .login-title {{
        font-size: 22px;
        font-weight: 600;
        color: #1e293b;
        margin: 0 0 24px 0;
        text-align: center;
      }}
      .login-field {{
        margin-bottom: 20px;
      }}
      .login-field label {{
        display: block;
        font-size: 13px;
        font-weight: 500;
        color: #64748b;
        margin-bottom: 6px;
      }}
      .login-field input {{
        width: 100%;
        padding: 12px 16px;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        font-size: 15px;
        transition: all 0.15s ease;
      }}
      .login-field input:focus {{
        outline: none;
        border-color: #0065D7;
        box-shadow: 0 0 0 3px rgba(0, 101, 215, 0.1);
      }}
      .login-btn {{
        width: 100%;
        padding: 14px 20px;
        background: #0065D7;
        color: #fff;
        border: none;
        border-radius: 8px;
        font-size: 15px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s ease;
      }}
      .login-btn:hover {{
        background: #0052b3;
      }}
      .login-error {{
        background: #fee2e2;
        color: #991b1b;
        padding: 12px 16px;
        border-radius: 8px;
        margin-bottom: 20px;
        font-size: 14px;
      }}
      .login-footer {{
        text-align: center;
        margin-top: 20px;
        padding-top: 20px;
        border-top: 1px solid #f1f5f9;
        font-size: 12px;
        color: #94a3b8;
      }}
    </style>
    
    <div class="login-wrapper">
      <div class="login-card">
        <div class="login-header">
          <svg viewBox="0 0 145 29" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path fill="#fff" d="M33.85 27.74c2-.0 4.1-.8 5.16-1.68.58-.46.86-.98.86-1.5 0-.8-.67-1.53-1.55-1.53-.33 0-.67.09-1.03.28-.67.37-1.4 1.07-3.62 1.07-2.1 0-4.1-1.35-4.62-3.85h10.03c.97 0 1.8-.67 1.85-1.65 0-4.4-3.59-8.1-7.69-8.1-4.01 0-7.81 3.24-7.81 8.71 0 4.71 3.22 8.26 8.42 8.26zm-.48-13.6c1.88 0 3.65 1.37 3.8 3.12v.21h-7.96c.49-2.54 2.13-3.33 4.16-3.33zM56.49 4.81c-1.06 0-1.82.8-1.82 1.87v5.99c-1.07-.98-2.8-1.9-4.9-1.9-4.1 0-7.36 3.49-7.36 8.5 0 4.98 3.25 8.47 7.48 8.47 2.07 0 3.86-1.1 4.77-2.14 0 1.04.76 1.83 1.82 1.83 1.07 0 1.83-.8 1.83-1.87V6.68c0-1.1-.76-1.87-1.82-1.87zm-6.14 19.57c-2.64 0-4.44-2.2-4.44-5.1 0-2.91 1.8-5.14 4.44-5.14 2.68 0 4.47 2.23 4.47 5.14 0 2.9-1.79 5.1-4.47 5.1zM65.07 12.94c0-1.07-.76-1.86-1.82-1.86-1.07 0-1.83.79-1.83 1.86v12.63c0 1.07.76 1.86 1.83 1.86 1.06 0 1.82-.79 1.82-1.86V12.94zm-1.73-4.44c1.06 0 1.92-.86 1.92-1.93 0-1.07-.86-1.93-1.92-1.93-1.06 0-1.92.86-1.92 1.93 0 1.07.86 1.93 1.92 1.93zM81.33 4.81c-1.07 0-1.83.8-1.83 1.87v5.99c-1.06-.98-2.79-1.9-4.89-1.9-4.1 0-7.36 3.49-7.36 8.5 0 4.98 3.25 8.47 7.48 8.47 2.07 0 3.86-1.1 4.77-2.14 0 1.04.76 1.83 1.83 1.83 1.06 0 1.82-.8 1.82-1.87V6.68c0-1.1-.76-1.87-1.82-1.87zm-6.14 19.57c-2.65 0-4.44-2.2-4.44-5.1 0-2.91 1.79-5.14 4.44-5.14 2.67 0 4.47 2.23 4.47 5.14 0 2.9-1.8 5.1-4.47 5.1zM93.97 27.74c2.01 0 4.1-.8 5.17-1.68.58-.46.85-.98.85-1.5 0-.8-.67-1.53-1.55-1.53-.33 0-.67.09-1.03.28-.67.37-1.4 1.07-3.62 1.07-2.1 0-4.1-1.35-4.61-3.85h10.03c.97 0 1.79-.67 1.85-1.65 0-4.4-3.59-8.1-7.7-8.1-4.01 0-7.81 3.24-7.81 8.71 0 4.71 3.22 8.26 8.42 8.26zm-.49-13.6c1.89 0 3.65 1.37 3.8 3.12v.21h-7.96c.49-2.54 2.13-3.33 4.16-3.33zM102.51 24.9c1.58 2.14 4.17 2.84 6.57 2.84 2.83 0 5.99-1.74 5.99-4.89 0-3.58-2.89-4.43-5.35-5.1-1.79-.49-3.34-.89-3.34-2.3 0-1.53 1.4-1.68 2.31-1.68 1.49 0 2.68.58 3.37 1.47.52.49 1.46.58 2.07.09.85-.7.64-1.65.18-2.26-1.28-1.62-3.68-2.29-5.54-2.29-2.98 0-5.9 1.8-5.9 4.83 0 3.61 3.07 4.44 5.59 5.14 1.8.49 3.31.95 3.31 2.26 0 1.59-1.49 1.77-2.37 1.8-1.95 0-3.13-.67-4.29-1.86-.7-.7-1.46-.7-2.1-.31-1.03.67-.91 1.68-.5 2.26zM119.6 27.43c1.06 0 1.82-.79 1.82-1.86v-3.21l1.49-1.38 5.47 5.81c.37.4.85.61 1.34.61.82 0 1.85-.73 1.85-1.8 0-.46-.18-.95-.58-1.38l-5.32-5.81 4.59-4.25c.49-.43.73-.92.73-1.38 0-.73-.79-1.71-1.73-1.71-.46 0-.94.18-1.34.58l-6.5 6.33V6.68c0-1.07-.76-1.87-1.82-1.87-1.07 0-1.83.8-1.83 1.87v18.89c0 1.07.76 1.86 1.83 1.86zM1.76 10.94c.77 0 1.43.5 1.67 1.2.95-.69 2.08-1.09 3.39-1.09 2.27 0 4.01.76 5.16 2.18 1.15-1.37 2.81-2.18 4.92-2.18 4.26 0 6.66 2.69 6.79 7.36v7.44c0 .98-.79 1.77-1.76 1.77-.97 0-1.76-.79-1.76-1.77v-7.36c-.09-2.76-1.03-3.82-3.21-3.84-2.18 0-3.14 1.27-3.28 3.84v7.36c0 .98-.79 1.77-1.76 1.77-.97 0-1.76-.79-1.76-1.77v-6.71c-.01-.07-.01-.14 0-.22v-.42c-.1-2.76-1.04-3.82-3.21-3.84-2.26 0-3.2 1.35-3.29 4.09v7.1c0 .98-.79 1.77-1.76 1.77C.79 27.59 0 26.8 0 25.82V12.71c0-.98.79-1.77 1.76-1.77zM142.59 0c1.3-.01 2.12 1.42 1.45 2.52l-4.64 7.72c-.47.79-1.5 1.04-2.28.57-.79-.47-1.05-1.5-.57-2.28l3.1-5.16-6.18.07c-.89.01-1.62-.68-1.69-1.55l-.0-.1c-.01-.92.73-1.67 1.65-1.68l9.16-.1z"/>
          </svg>
          <h1>Panel Administracyjny</h1>
        </div>
        <div class="login-body">
          <h2 class="login-title">Zaloguj się</h2>
          
          {f'<div class="login-error">{error}</div>' if error else ''}
          
          <form method="post" action="{url_for('admin_bp.login')}">
            <div class="login-field">
              <label for="email">Adres email</label>
              <input type="email" id="email" name="email" required autofocus placeholder="twoj@email.com" />
            </div>
            
            <div class="login-field">
              <label for="password">Hasło</label>
              <input type="password" id="password" name="password" required placeholder="Wprowadź hasło" />
            </div>
            
            <button type="submit" class="login-btn">Zaloguj się</button>
          </form>
          
          <div class="login-footer">
            Medidesk Admin Panel
          </div>
        </div>
      </div>
    </div>
    """
    return _page("Logowanie", body, show_nav=False)


@admin_bp.route("/change-password", methods=["GET", "POST"])
def change_password():
    """Wymuszana zmiana hasła po utworzeniu/resetcie."""
    _require_admin_token()
    user = _get_current_admin_user()
    if not user:
        return redirect(url_for("admin_bp.login"))

    error = None
    if request.method == "POST":
        current_password = (request.form.get("current_password") or "").strip()
        password = (request.form.get("password") or "").strip()
        password2 = (request.form.get("password2") or "").strip()

        if not current_password:
            error = "Podaj aktualne hasło"
        elif not check_password_hash(user["password_hash"], current_password):
            error = "Aktualne hasło jest nieprawidłowe"
        elif not password or len(password) < 8:
            error = "Nowe hasło musi mieć min. 8 znaków"
        elif password != password2:
            error = "Hasła nie są identyczne"
        else:
            password_hash = generate_password_hash(password)
            if update_admin_user_password(user["id"], password_hash, must_change_password=False):
                insert_admin_audit_log(
                    action="change_password",
                    admin_user_id=user["id"],
                    target_email=user.get("email"),
                    ip=_get_client_ip(),
                    user_agent=request.headers.get("User-Agent", "")[:500],
                )
                return redirect(_landing_url_for_user(user))
            error = "Nie udało się zapisać nowego hasła"

    body = f"""
    <style>
      .change-card {{
        max-width: 520px;
        margin: 0 auto;
        background: #fff;
        border: 1px solid var(--md-border);
        border-radius: 12px;
        padding: 24px;
      }}
      .change-card h3 {{
        margin: 0 0 12px 0;
      }}
      .change-card p {{
        color: #475569;
        font-size: 14px;
        margin: 0 0 16px 0;
      }}
    </style>
    <div class="change-card">
      <h3>Ustaw nowe hasło</h3>
      <p>To wymagane po utworzeniu konta lub resecie hasła.</p>
      {'<div class="error">' + error + '</div>' if error else ''}
      <form method="post" action="{url_for('admin_bp.change_password')}">
        <div class="form-row">
          <label for="current_password">Aktualne hasło</label>
          <input type="password" id="current_password" name="current_password" required placeholder="Wpisz aktualne hasło" />
        </div>
        <div class="form-row">
          <label for="password">Nowe hasło (min. 8 znaków)</label>
          <input type="password" id="password" name="password" required minlength="8" placeholder="Wpisz nowe hasło" />
        </div>
        <div class="form-row">
          <label for="password2">Powtórz nowe hasło</label>
          <input type="password" id="password2" name="password2" required minlength="8" placeholder="Powtórz nowe hasło" />
        </div>
        <div style="display:flex; gap:10px; margin-top:16px;">
          <button class="btn btnPrimary" type="submit">Zapisz nowe hasło</button>
          <a class="btn" href="{url_for('admin_bp.logout')}">Wyloguj</a>
        </div>
      </form>
    </div>
    """
    return _page("Zmień hasło", body)


@admin_bp.route("/logout", methods=["GET", "POST"])
def logout():
    """Wylogowanie z panelu admin."""
    user = _get_current_admin_user()
    if user:
        insert_admin_audit_log(
            action="logout",
            admin_user_id=user["id"],
            target_email=user["email"],
            ip=_get_client_ip(),
            user_agent=request.headers.get("User-Agent", "")[:500],
        )
    session.pop("admin_user_id", None)
    session.pop("csrf_token", None)
    return redirect(url_for("admin_bp.login"))


# ---------------------------------------------------------------------------
# BOOTSTRAP - tworzenie pierwszego konta admina
# ---------------------------------------------------------------------------

@admin_bp.route("/bootstrap", methods=["GET", "POST"])
def bootstrap():
    """
    Tworzenie pierwszego konta admina.
    
    WARUNKI:
    - Działa TYLKO gdy tabela admin_users jest pusta.
    - Wymaga ADMIN_BOOTSTRAP_TOKEN (osobny od ADMIN_PANEL_TOKEN).
    - Po utworzeniu pierwszego admina endpoint przestaje działać.
    """
    # Sprawdź czy są już admini
    count = admin_user_count()
    if count > 0:
        return _page(
            "Bootstrap niedostępny",
            """
            <div class="warn">
              <b>Bootstrap jest niedostępny.</b><br/>
              W systemie istnieje już co najmniej jedno konto admina.<br/>
              <a href="/admin/login">Przejdź do logowania</a>
            </div>
            """,
            show_nav=False,
        )
    
    # Sprawdź token bootstrap
    if not ADMIN_BOOTSTRAP_TOKEN:
        return _page(
            "Bootstrap niezskonfigurowany",
            """
            <div class="error">
              <b>Brak ADMIN_BOOTSTRAP_TOKEN w ENV.</b><br/>
              Ustaw tę zmienną w Render Dashboard, aby utworzyć pierwsze konto admina.
            </div>
            """,
            show_nav=False,
        )
    
    provided_token = (
        (request.args.get("token") or "").strip()
        or (request.form.get("bootstrap_token") or "").strip()
    )
    
    # Jeśli nie podano tokenu, pokaż formularz z pytaniem o token
    if not provided_token:
        body = """
        <style>
          .login-wrapper { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%); padding: 20px; }
          .login-card { width: 100%; max-width: 420px; background: #fff; border-radius: 16px; box-shadow: 0 10px 40px rgba(0, 101, 215, 0.1), 0 2px 10px rgba(0, 0, 0, 0.05); overflow: hidden; }
          .login-header { background: linear-gradient(90deg, #00E09F 0%, #00A1D7 50%, #0065D7 100%); padding: 32px 32px 28px; text-align: center; }
          .login-header svg { height: 32px; margin-bottom: 8px; }
          .login-header h1 { margin: 0; font-size: 14px; font-weight: 500; color: rgba(255,255,255,0.9); letter-spacing: 0.5px; }
          .login-body { padding: 32px; }
          .login-title { font-size: 20px; font-weight: 600; color: #1e293b; margin: 0 0 8px 0; text-align: center; }
          .login-subtitle { font-size: 13px; color: #64748b; text-align: center; margin-bottom: 24px; }
          .login-field { margin-bottom: 20px; }
          .login-field label { display: block; font-size: 13px; font-weight: 500; color: #64748b; margin-bottom: 6px; }
          .login-field input { width: 100%; padding: 12px 16px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 15px; transition: all 0.15s ease; }
          .login-field input:focus { outline: none; border-color: #0065D7; box-shadow: 0 0 0 3px rgba(0, 101, 215, 0.1); }
          .login-btn { width: 100%; padding: 14px 20px; background: #0065D7; color: #fff; border: none; border-radius: 8px; font-size: 15px; font-weight: 600; cursor: pointer; transition: background 0.15s ease; }
          .login-btn:hover { background: #0052b3; }
        </style>
        
        <div class="login-wrapper">
          <div class="login-card">
            <div class="login-header">
              <svg viewBox="0 0 145 29" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path fill="#fff" d="M33.85 27.74c2-.0 4.1-.8 5.16-1.68.58-.46.86-.98.86-1.5 0-.8-.67-1.53-1.55-1.53-.33 0-.67.09-1.03.28-.67.37-1.4 1.07-3.62 1.07-2.1 0-4.1-1.35-4.62-3.85h10.03c.97 0 1.8-.67 1.85-1.65 0-4.4-3.59-8.1-7.69-8.1-4.01 0-7.81 3.24-7.81 8.71 0 4.71 3.22 8.26 8.42 8.26zm-.48-13.6c1.88 0 3.65 1.37 3.8 3.12v.21h-7.96c.49-2.54 2.13-3.33 4.16-3.33zM56.49 4.81c-1.06 0-1.82.8-1.82 1.87v5.99c-1.07-.98-2.8-1.9-4.9-1.9-4.1 0-7.36 3.49-7.36 8.5 0 4.98 3.25 8.47 7.48 8.47 2.07 0 3.86-1.1 4.77-2.14 0 1.04.76 1.83 1.82 1.83 1.07 0 1.83-.8 1.83-1.87V6.68c0-1.1-.76-1.87-1.82-1.87zm-6.14 19.57c-2.64 0-4.44-2.2-4.44-5.1 0-2.91 1.8-5.14 4.44-5.14 2.68 0 4.47 2.23 4.47 5.14 0 2.9-1.79 5.1-4.47 5.1zM65.07 12.94c0-1.07-.76-1.86-1.82-1.86-1.07 0-1.83.79-1.83 1.86v12.63c0 1.07.76 1.86 1.83 1.86 1.06 0 1.82-.79 1.82-1.86V12.94zm-1.73-4.44c1.06 0 1.92-.86 1.92-1.93 0-1.07-.86-1.93-1.92-1.93-1.06 0-1.92.86-1.92 1.93 0 1.07.86 1.93 1.92 1.93zM81.33 4.81c-1.07 0-1.83.8-1.83 1.87v5.99c-1.06-.98-2.79-1.9-4.89-1.9-4.1 0-7.36 3.49-7.36 8.5 0 4.98 3.25 8.47 7.48 8.47 2.07 0 3.86-1.1 4.77-2.14 0 1.04.76 1.83 1.83 1.83 1.06 0 1.82-.8 1.82-1.87V6.68c0-1.1-.76-1.87-1.82-1.87zm-6.14 19.57c-2.65 0-4.44-2.2-4.44-5.1 0-2.91 1.79-5.14 4.44-5.14 2.67 0 4.47 2.23 4.47 5.14 0 2.9-1.8 5.1-4.47 5.1zM93.97 27.74c2.01 0 4.1-.8 5.17-1.68.58-.46.85-.98.85-1.5 0-.8-.67-1.53-1.55-1.53-.33 0-.67.09-1.03.28-.67.37-1.4 1.07-3.62 1.07-2.1 0-4.1-1.35-4.61-3.85h10.03c.97 0 1.79-.67 1.85-1.65 0-4.4-3.59-8.1-7.7-8.1-4.01 0-7.81 3.24-7.81 8.71 0 4.71 3.22 8.26 8.42 8.26zm-.49-13.6c1.89 0 3.65 1.37 3.8 3.12v.21h-7.96c.49-2.54 2.13-3.33 4.16-3.33zM102.51 24.9c1.58 2.14 4.17 2.84 6.57 2.84 2.83 0 5.99-1.74 5.99-4.89 0-3.58-2.89-4.43-5.35-5.1-1.79-.49-3.34-.89-3.34-2.3 0-1.53 1.4-1.68 2.31-1.68 1.49 0 2.68.58 3.37 1.47.52.49 1.46.58 2.07.09.85-.7.64-1.65.18-2.26-1.28-1.62-3.68-2.29-5.54-2.29-2.98 0-5.9 1.8-5.9 4.83 0 3.61 3.07 4.44 5.59 5.14 1.8.49 3.31.95 3.31 2.26 0 1.59-1.49 1.77-2.37 1.8-1.95 0-3.13-.67-4.29-1.86-.7-.7-1.46-.7-2.1-.31-1.03.67-.91 1.68-.5 2.26zM119.6 27.43c1.06 0 1.82-.79 1.82-1.86v-3.21l1.49-1.38 5.47 5.81c.37.4.85.61 1.34.61.82 0 1.85-.73 1.85-1.8 0-.46-.18-.95-.58-1.38l-5.32-5.81 4.59-4.25c.49-.43.73-.92.73-1.38 0-.73-.79-1.71-1.73-1.71-.46 0-.94.18-1.34.58l-6.5 6.33V6.68c0-1.07-.76-1.87-1.82-1.87-1.07 0-1.83.8-1.83 1.87v18.89c0 1.07.76 1.86 1.83 1.86zM1.76 10.94c.77 0 1.43.5 1.67 1.2.95-.69 2.08-1.09 3.39-1.09 2.27 0 4.01.76 5.16 2.18 1.15-1.37 2.81-2.18 4.92-2.18 4.26 0 6.66 2.69 6.79 7.36v7.44c0 .98-.79 1.77-1.76 1.77-.97 0-1.76-.79-1.76-1.77v-7.36c-.09-2.76-1.03-3.82-3.21-3.84-2.18 0-3.14 1.27-3.28 3.84v7.36c0 .98-.79 1.77-1.76 1.77-.97 0-1.76-.79-1.76-1.77v-6.71c-.01-.07-.01-.14 0-.22v-.42c-.1-2.76-1.04-3.82-3.21-3.84-2.26 0-3.2 1.35-3.29 4.09v7.1c0 .98-.79 1.77-1.76 1.77C.79 27.59 0 26.8 0 25.82V12.71c0-.98.79-1.77 1.76-1.77zM142.59 0c1.3-.01 2.12 1.42 1.45 2.52l-4.64 7.72c-.47.79-1.5 1.04-2.28.57-.79-.47-1.05-1.5-.57-2.28l3.1-5.16-6.18.07c-.89.01-1.62-.68-1.69-1.55l-.0-.1c-.01-.92.73-1.67 1.65-1.68l9.16-.1z"/>
              </svg>
              <h1>Panel Administracyjny</h1>
            </div>
            <div class="login-body">
              <h2 class="login-title">Bootstrap</h2>
              <p class="login-subtitle">Podaj token bootstrap (ADMIN_BOOTSTRAP_TOKEN z Render ENV).</p>
              
              <form method="get" action="">
                <div class="login-field">
                  <label for="token">Token bootstrap</label>
                  <input type="password" id="token" name="token" required autofocus placeholder="Wprowadź token" />
                </div>
                
                <button type="submit" class="login-btn">Dalej</button>
              </form>
            </div>
          </div>
        </div>
        """
        return _page("Bootstrap", body, show_nav=False)
    
    # Weryfikuj token
    if provided_token != ADMIN_BOOTSTRAP_TOKEN:
        return _page(
            "Nieprawidłowy token",
            """
            <div class="error">
              <b>Nieprawidłowy token bootstrap.</b><br/>
              Sprawdź czy podałeś poprawną wartość ADMIN_BOOTSTRAP_TOKEN.
            </div>
            <div style="margin-top:16px;">
              <a href="/admin/bootstrap" class="btn">Spróbuj ponownie</a>
            </div>
            """,
            show_nav=False,
        )
    
    error = None
    success = None
    
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = (request.form.get("password") or "").strip()
        password2 = (request.form.get("password2") or "").strip()
        
        # Walidacja
        if not email or "@" not in email:
            error = "Podaj prawidłowy adres email"
        elif not password or len(password) < 8:
            error = "Hasło musi mieć co najmniej 8 znaków"
        elif password != password2:
            error = "Hasła nie są identyczne"
        else:
            # Utwórz konto
            password_hash = generate_password_hash(password)
            user = create_admin_user(email, password_hash)
            
            if user:
                insert_admin_audit_log(
                    action="bootstrap_create_admin",
                    admin_user_id=user["id"],
                    target_email=email,
                    ip=_get_client_ip(),
                    user_agent=request.headers.get("User-Agent", "")[:500],
                )
                success = f"Konto admina {email} zostało utworzone!"
            else:
                error = "Błąd podczas tworzenia konta (może już istnieje taki email?)"
    
    # Formularz tworzenia konta - stylizowany jak login
    body = f"""
    <style>
      .login-wrapper {{ min-height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%); padding: 20px; }}
      .login-card {{ width: 100%; max-width: 420px; background: #fff; border-radius: 16px; box-shadow: 0 10px 40px rgba(0, 101, 215, 0.1), 0 2px 10px rgba(0, 0, 0, 0.05); overflow: hidden; }}
      .login-header {{ background: linear-gradient(90deg, #00E09F 0%, #00A1D7 50%, #0065D7 100%); padding: 32px 32px 28px; text-align: center; }}
      .login-header svg {{ height: 32px; margin-bottom: 8px; }}
      .login-header h1 {{ margin: 0; font-size: 14px; font-weight: 500; color: rgba(255,255,255,0.9); letter-spacing: 0.5px; }}
      .login-body {{ padding: 32px; }}
      .login-title {{ font-size: 20px; font-weight: 600; color: #1e293b; margin: 0 0 24px 0; text-align: center; }}
      .login-field {{ margin-bottom: 20px; }}
      .login-field label {{ display: block; font-size: 13px; font-weight: 500; color: #64748b; margin-bottom: 6px; }}
      .login-field input {{ width: 100%; padding: 12px 16px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 15px; transition: all 0.15s ease; }}
      .login-field input:focus {{ outline: none; border-color: #0065D7; box-shadow: 0 0 0 3px rgba(0, 101, 215, 0.1); }}
      .login-btn {{ width: 100%; padding: 14px 20px; background: #0065D7; color: #fff; border: none; border-radius: 8px; font-size: 15px; font-weight: 600; cursor: pointer; transition: background 0.15s ease; }}
      .login-btn:hover {{ background: #0052b3; }}
      .login-success {{ background: #d1fae5; color: #065f46; padding: 16px; border-radius: 8px; margin-bottom: 20px; text-align: center; }}
      .login-success a {{ color: #0065D7; font-weight: 600; }}
      .login-error {{ background: #fee2e2; color: #991b1b; padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; font-size: 14px; }}
      .login-hint {{ text-align: center; margin-top: 20px; padding-top: 20px; border-top: 1px solid #f1f5f9; font-size: 12px; color: #94a3b8; }}
    </style>
    
    <div class="login-wrapper">
      <div class="login-card">
        <div class="login-header">
          <svg viewBox="0 0 145 29" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path fill="#fff" d="M33.85 27.74c2-.0 4.1-.8 5.16-1.68.58-.46.86-.98.86-1.5 0-.8-.67-1.53-1.55-1.53-.33 0-.67.09-1.03.28-.67.37-1.4 1.07-3.62 1.07-2.1 0-4.1-1.35-4.62-3.85h10.03c.97 0 1.8-.67 1.85-1.65 0-4.4-3.59-8.1-7.69-8.1-4.01 0-7.81 3.24-7.81 8.71 0 4.71 3.22 8.26 8.42 8.26zm-.48-13.6c1.88 0 3.65 1.37 3.8 3.12v.21h-7.96c.49-2.54 2.13-3.33 4.16-3.33zM56.49 4.81c-1.06 0-1.82.8-1.82 1.87v5.99c-1.07-.98-2.8-1.9-4.9-1.9-4.1 0-7.36 3.49-7.36 8.5 0 4.98 3.25 8.47 7.48 8.47 2.07 0 3.86-1.1 4.77-2.14 0 1.04.76 1.83 1.82 1.83 1.07 0 1.83-.8 1.83-1.87V6.68c0-1.1-.76-1.87-1.82-1.87zm-6.14 19.57c-2.64 0-4.44-2.2-4.44-5.1 0-2.91 1.8-5.14 4.44-5.14 2.68 0 4.47 2.23 4.47 5.14 0 2.9-1.79 5.1-4.47 5.1zM65.07 12.94c0-1.07-.76-1.86-1.82-1.86-1.07 0-1.83.79-1.83 1.86v12.63c0 1.07.76 1.86 1.83 1.86 1.06 0 1.82-.79 1.82-1.86V12.94zm-1.73-4.44c1.06 0 1.92-.86 1.92-1.93 0-1.07-.86-1.93-1.92-1.93-1.06 0-1.92.86-1.92 1.93 0 1.07.86 1.93 1.92 1.93zM81.33 4.81c-1.07 0-1.83.8-1.83 1.87v5.99c-1.06-.98-2.79-1.9-4.89-1.9-4.1 0-7.36 3.49-7.36 8.5 0 4.98 3.25 8.47 7.48 8.47 2.07 0 3.86-1.1 4.77-2.14 0 1.04.76 1.83 1.83 1.83 1.06 0 1.82-.8 1.82-1.87V6.68c0-1.1-.76-1.87-1.82-1.87zm-6.14 19.57c-2.65 0-4.44-2.2-4.44-5.1 0-2.91 1.79-5.14 4.44-5.14 2.67 0 4.47 2.23 4.47 5.14 0 2.9-1.8 5.1-4.47 5.1zM93.97 27.74c2.01 0 4.1-.8 5.17-1.68.58-.46.85-.98.85-1.5 0-.8-.67-1.53-1.55-1.53-.33 0-.67.09-1.03.28-.67.37-1.4 1.07-3.62 1.07-2.1 0-4.1-1.35-4.61-3.85h10.03c.97 0 1.79-.67 1.85-1.65 0-4.4-3.59-8.1-7.7-8.1-4.01 0-7.81 3.24-7.81 8.71 0 4.71 3.22 8.26 8.42 8.26zm-.49-13.6c1.89 0 3.65 1.37 3.8 3.12v.21h-7.96c.49-2.54 2.13-3.33 4.16-3.33zM102.51 24.9c1.58 2.14 4.17 2.84 6.57 2.84 2.83 0 5.99-1.74 5.99-4.89 0-3.58-2.89-4.43-5.35-5.1-1.79-.49-3.34-.89-3.34-2.3 0-1.53 1.4-1.68 2.31-1.68 1.49 0 2.68.58 3.37 1.47.52.49 1.46.58 2.07.09.85-.7.64-1.65.18-2.26-1.28-1.62-3.68-2.29-5.54-2.29-2.98 0-5.9 1.8-5.9 4.83 0 3.61 3.07 4.44 5.59 5.14 1.8.49 3.31.95 3.31 2.26 0 1.59-1.49 1.77-2.37 1.8-1.95 0-3.13-.67-4.29-1.86-.7-.7-1.46-.7-2.1-.31-1.03.67-.91 1.68-.5 2.26zM119.6 27.43c1.06 0 1.82-.79 1.82-1.86v-3.21l1.49-1.38 5.47 5.81c.37.4.85.61 1.34.61.82 0 1.85-.73 1.85-1.8 0-.46-.18-.95-.58-1.38l-5.32-5.81 4.59-4.25c.49-.43.73-.92.73-1.38 0-.73-.79-1.71-1.73-1.71-.46 0-.94.18-1.34.58l-6.5 6.33V6.68c0-1.07-.76-1.87-1.82-1.87-1.07 0-1.83.8-1.83 1.87v18.89c0 1.07.76 1.86 1.83 1.86zM1.76 10.94c.77 0 1.43.5 1.67 1.2.95-.69 2.08-1.09 3.39-1.09 2.27 0 4.01.76 5.16 2.18 1.15-1.37 2.81-2.18 4.92-2.18 4.26 0 6.66 2.69 6.79 7.36v7.44c0 .98-.79 1.77-1.76 1.77-.97 0-1.76-.79-1.76-1.77v-7.36c-.09-2.76-1.03-3.82-3.21-3.84-2.18 0-3.14 1.27-3.28 3.84v7.36c0 .98-.79 1.77-1.76 1.77-.97 0-1.76-.79-1.76-1.77v-6.71c-.01-.07-.01-.14 0-.22v-.42c-.1-2.76-1.04-3.82-3.21-3.84-2.26 0-3.2 1.35-3.29 4.09v7.1c0 .98-.79 1.77-1.76 1.77C.79 27.59 0 26.8 0 25.82V12.71c0-.98.79-1.77 1.76-1.77zM142.59 0c1.3-.01 2.12 1.42 1.45 2.52l-4.64 7.72c-.47.79-1.5 1.04-2.28.57-.79-.47-1.05-1.5-.57-2.28l3.1-5.16-6.18.07c-.89.01-1.62-.68-1.69-1.55l-.0-.1c-.01-.92.73-1.67 1.65-1.68l9.16-.1z"/>
          </svg>
          <h1>Panel Administracyjny</h1>
        </div>
        <div class="login-body">
          <h2 class="login-title">Utwórz pierwsze konto admina</h2>
          
          {f'<div class="login-success">{success}<br/><a href="/admin/login">Przejdź do logowania</a></div>' if success else ''}
          {f'<div class="login-error">{error}</div>' if error else ''}
          
          {'' if success else f'''
          <form method="post" action="{url_for('admin_bp.bootstrap', token=provided_token)}">
            <input type="hidden" name="bootstrap_token" value="{provided_token}" />
            
            <div class="login-field">
              <label for="email">Adres email</label>
              <input type="email" id="email" name="email" required autofocus placeholder="twoj@email.com" />
            </div>
            
            <div class="login-field">
              <label for="password">Hasło (min. 8 znaków)</label>
              <input type="password" id="password" name="password" required minlength="8" placeholder="Wprowadź hasło" />
            </div>
            
            <div class="login-field">
              <label for="password2">Powtórz hasło</label>
              <input type="password" id="password2" name="password2" required minlength="8" placeholder="Powtórz hasło" />
            </div>
            
            <button type="submit" class="login-btn">Utwórz konto</button>
          </form>
          
          <div class="login-hint">
            Po utworzeniu konta usuń ADMIN_BOOTSTRAP_TOKEN z Render ENV.
          </div>
          '''}
        </div>
      </div>
    </div>
    """
    return _page("Bootstrap", body, show_nav=False)


# Definicje pól dla marketingu (label, opis, placeholder).
# Te klucze trafiają do events.data (JSONB). Panel ma być prosty i przewidywalny.
FIELD_DEFS: List[Dict[str, str]] = [
    {"key": "eventName", "label": "Nazwa wydarzenia", "hint": "np. Dental Practice Academy", "kind": "text"},
    {"key": "eventId", "label": "Event ID (Backstage)", "hint": "np. 24311000000651079", "kind": "text"},
    {"key": "md_email_kontakt", "label": "Email kontaktowy", "hint": "np. eventy@medidesk.com", "kind": "email"},
    {"key": "md_mobile_kontakt", "label": "Telefon kontaktowy", "hint": "np. +48 123 456 789", "kind": "phone"},
    {"key": "md_email_techniczny", "label": "Email techniczny", "hint": "np. adminzoho@medidesk.com", "kind": "email"},
    {"key": "md_mobile_techniczny", "label": "Telefon techniczny", "hint": "np. +48 123 456 789", "kind": "phone"},

    {"key": "event_location_google_link", "label": "Link Google Maps", "hint": "https://maps.app.goo.gl/…", "kind": "url"},
    {"key": "event_location_place", "label": "Miejsce", "hint": "np. Regent Warsaw Hotel", "kind": "text"},
    {"key": "event_location_address", "label": "Adres", "hint": "np. ul. Belwederska 23", "kind": "text"},
    {"key": "event_location_zip", "label": "Kod pocztowy", "hint": "np. 00-761", "kind": "text"},
    {"key": "event_location_city", "label": "Miasto", "hint": "np. Warszawa", "kind": "text"},
    {"key": "event_country", "label": "Kraj", "hint": "np. Polska", "kind": "text"},

    {"key": "event_date_time", "label": "Data i czas START (ISO)", "hint": "np. 2026-02-05T09:00:00.000Z", "kind": "text"},
    {"key": "event_end_date_time", "label": "Data i czas KONIEC (ISO)", "hint": "np. 2026-02-06T17:00:00.000Z", "kind": "text"},
    {"key": "event_days_count", "label": "Liczba dni (auto lub ręcznie)", "hint": "auto z dat lub wpisz ręcznie", "kind": "text"},
    {"key": "event_day", "label": "Dzień (liczba)", "hint": "np. 6", "kind": "text"},
    {"key": "event_month_number", "label": "Miesiąc (liczba)", "hint": "np. 2", "kind": "text"},
    {"key": "event_month_text", "label": "Miesiąc (tekst)", "hint": "np. luty", "kind": "text"},
    {"key": "event_month_text_odmiana", "label": "Miesiąc (odmiana)", "hint": "np. lutego", "kind": "text"},
    {"key": "event_year", "label": "Rok", "hint": "np. 2026", "kind": "text"},
    {"key": "event_time_text", "label": "Godzina (tekst)", "hint": "np. 10:00", "kind": "text"},
    {"key": "event_day_text_1", "label": "Data (tekst 1)", "hint": "np. 6 lutego 2026", "kind": "text"},
    {"key": "event_day_text_2", "label": "Data (tekst 2)", "hint": "opcjonalnie", "kind": "text"},

    {"key": "color_gradient_1", "label": "Kolor 1 (hex)", "hint": "np. #269571", "kind": "color"},
    {"key": "color_gradient_2", "label": "Kolor 2 (hex)", "hint": "np. #47005f", "kind": "color"},
    {"key": "color_gradient_angle", "label": "Kąt gradientu", "hint": "np. 90", "kind": "text"},

    {"key": "event_mapa_hotel_link", "label": "Link mapa hotel (grafika)", "hint": "https://…", "kind": "url"},
    {"key": "event_logo_link", "label": "Logo (link)", "hint": "https://…", "kind": "url"},
    {"key": "event_logo_link_white", "label": "Logo (białe) link", "hint": "https://…", "kind": "url"},
    {"key": "event_logo_link_color", "label": "Logo (kolor) link", "hint": "https://…", "kind": "url"},
    {"key": "event_picture_1_link", "label": "Zdjęcie 1 (link)", "hint": "https://…", "kind": "url"},
    {"key": "event_mail_link_top_banner", "label": "Baner mail (góra) link", "hint": "https://…", "kind": "url"},
    {"key": "event_mail_link_bottom_banner", "label": "Baner mail (dół) link", "hint": "https://…", "kind": "url"},

    {"key": "url_event", "label": "URL wydarzenia (public)", "hint": "https://…", "kind": "url"},
    {"key": "url_success", "label": "URL success", "hint": "https://…", "kind": "url"},
    {"key": "url_cancel", "label": "URL cancel", "hint": "https://…", "kind": "url"},
    {"key": "event_config_link", "label": "Link konfiguracji (Backstage)", "hint": "https://…", "kind": "url"},
    {"key": "event_orders_link", "label": "Link orders (Backstage)", "hint": "https://…", "kind": "url"},
    {"key": "event_attendees_link", "label": "Link attendees (Backstage)", "hint": "https://…", "kind": "url"},
]


def _require_admin_token() -> str:
    """
    Wymaga autoryzacji do panelu admin.
    
    MIGRACJA: obsługuje zarówno sesję (nowe) jak i token (legacy).
    - Jeśli użytkownik jest zalogowany przez sesję: zwraca pusty string (URLs bez tokenu).
    - Jeśli token jest poprawny: zwraca token (legacy URLs).
    - Jeśli żadne: przekierowuje do /admin/login.
    """
    # 1. Sprawdź sesję (nowe logowanie)
    user = _get_current_admin_user()
    if user:
        request.admin_user = user
        # Wymuś zmianę hasła po utworzeniu/resetcie
        if user.get("must_change_password"):
            endpoint = (request.endpoint or "")
            if endpoint not in ("admin_bp.change_password", "admin_bp.logout"):
                from flask import make_response
                resp = make_response(redirect(url_for("admin_bp.change_password")))
                abort(resp)
        return ""  # Zalogowany przez sesję - token nie jest potrzebny
    
    # 2. Sprawdź legacy token
    if ADMIN_PANEL_TOKEN:
        token = (
            (request.args.get("token") or "").strip()
            or (request.form.get("token") or "").strip()
            or (request.headers.get("X-Admin-Token") or "").strip()
        )
        if token and token == ADMIN_PANEL_TOKEN:
            request.admin_user = None  # Legacy - brak user
            return token
    
    # 3. Niezalogowany - redirect do logowania (zamiast abort)
    # Używamy abort z redirect response, żeby Flask to obsłużył
    from flask import make_response
    resp = make_response(redirect(url_for("admin_bp.login")))
    abort(resp)


def _require_permission(permission_key: str):
    """Dekorator wymagający uprawnienia do danej sekcji panelu."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            token = _require_admin_token()
            user = _get_current_admin_user()
            if user and not _user_has_permission(user, permission_key):
                return _err(403, "Brak dostępu", "Nie masz uprawnień do tej sekcji.")
            request.admin_token = token
            return f(*args, **kwargs)
        return wrapped
    return decorator


def _safe_json_loads(s: str) -> Tuple[Optional[Any], Optional[str]]:
    try:
        return json.loads(s), None
    except Exception as e:
        return None, str(e)


def _field_name(key: str) -> str:
    return f"field__{key}"


def _is_http_url(value: str) -> bool:
    v = (value or "").strip().lower()
    return v.startswith("http://") or v.startswith("https://")


def _is_hex_color(value: str) -> bool:
    v = (value or "").strip()
    if not v.startswith("#"):
        return False
    if len(v) not in (4, 7):
        return False
    allowed = "0123456789abcdefABCDEF"
    return all(ch in allowed for ch in v[1:])


def _detect_delimiter(sample: str) -> str:
    # Prosty heurystyczny wybór dla CSV z Make (często ';')
    if sample.count(";") >= sample.count(","):
        return ";"
    return ","


def _is_pivot_format(headers: List[str]) -> bool:
    """
    Wykrywa czy CSV jest w formacie pivot (klucze w pierwszej kolumnie).
    Format pivot: pierwsza kolumna to nazwy pól (np. "eventName", "eventId"),
                  kolejne kolumny to "Rekord 1", "Rekord 2", etc.
    Format klasyczny: nagłówki to nazwy pól (eventName,eventId,...)
    """
    if not headers or len(headers) < 2:
        return False
    
    # Jeśli pierwsza kolumna to coś typu "key", "pole", "field" - to pivot
    first = headers[0].lower().strip()
    if first in ("key", "pole", "field", "klucz", ""):
        return True
    
    # Jeśli druga kolumna zawiera "rekord", "record", lub jest numerem - to pivot
    second = headers[1].lower().strip()
    if "rekord" in second or "record" in second or second.isdigit():
        return True
    
    # Jeśli pierwsza kolumna to znana nazwa pola (eventName, eventId) - to klasyczny
    known_fields = {"eventname", "eventid", "event_id", "event_name", "id", "name"}
    if first in known_fields:
        return False
    
    # Domyślnie: jeśli dużo kolumn (>10) - prawdopodobnie klasyczny
    return len(headers) < 10


def _parse_classic_csv(content: bytes) -> List[Dict[str, str]]:
    """
    Parser dla klasycznego formatu CSV:
      - pierwszy wiersz to nagłówki: eventName,eventId,md_email_kontakt,...
      - kolejne wiersze to dane: Archiwum Amoz,24311000000429100,...
    Zwraca listę rekordów (dict header->value).
    """
    text = content.decode("utf-8-sig", errors="replace")
    first_line = (text.splitlines() or [""])[0]
    delim = _detect_delimiter(first_line)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(reader)
    if not rows or len(rows) < 2:
        return []

    headers = [h.strip() for h in rows[0]]
    records: List[Dict[str, str]] = []

    for r in rows[1:]:
        if not r or not any(cell.strip() for cell in r):
            continue
        rec: Dict[str, str] = {}
        for i, h in enumerate(headers):
            if not h:
                continue
            val = r[i] if i < len(r) else ""
            rec[h] = (val or "").strip()
        if any(v for v in rec.values()):
            records.append(rec)

    return records


def _parse_pivot_csv(content: bytes) -> List[Dict[str, str]]:
    """
    Parser dla formatu 'pivot' jak Twoje CSV z Make:
      - pierwszy wiersz to nagłówki: key;Rekord 1;Rekord 2;...
      - kolejne wiersze: pole;v1;v2;...
    Zwraca listę rekordów (dict key->value) o długości N (liczba kolumn rekordów).
    """
    text = content.decode("utf-8-sig", errors="replace")
    first_line = (text.splitlines() or [""])[0]
    delim = _detect_delimiter(first_line)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(reader)
    if not rows or len(rows[0]) < 2:
        return []

    # liczba rekordów = liczba kolumn - 1 (kolumna 0 to nazwa pola)
    record_count = max(0, len(rows[0]) - 1)
    records: List[Dict[str, str]] = [dict() for _ in range(record_count)]

    for r in rows[1:]:
        if not r:
            continue
        key = (r[0] or "").strip()
        if not key:
            continue
        for i in range(record_count):
            val = r[i + 1] if (i + 1) < len(r) else ""
            records[i][key] = (val or "").strip()

    # usuń rekordy całkiem puste
    records = [rec for rec in records if any(v for v in rec.values())]
    return records


def _parse_events_csv(content: bytes) -> Tuple[List[Dict[str, str]], str]:
    """
    Automatycznie wykrywa format CSV (pivot vs klasyczny) i parsuje.
    Zwraca (lista_rekordów, wykryty_format).
    """
    text = content.decode("utf-8-sig", errors="replace")
    first_line = (text.splitlines() or [""])[0]
    delim = _detect_delimiter(first_line)
    
    # Parsuj nagłówki
    reader = csv.reader(io.StringIO(first_line), delimiter=delim)
    headers = list(reader)[0] if first_line else []
    
    if _is_pivot_format(headers):
        return _parse_pivot_csv(content), "pivot"
    else:
        return _parse_classic_csv(content), "classic"


def _parse_bilety_csv(content: bytes) -> List[Dict[str, str]]:
    """
    Parser dla Bilety.csv (pivot) – zwraca listę rekordów:
      {eventId, ticketClassId, ticketName, eventName}
    """
    records = _parse_pivot_csv(content)
    out: List[Dict[str, str]] = []
    for rec in records:
        event_id = (rec.get("eventId") or "").strip()
        ticket_class_id = (rec.get("ticketClassId") or "").strip()
        if not event_id or not ticket_class_id:
            continue
        out.append(
            {
                "eventId": event_id,
                "eventName": (rec.get("eventName") or "").strip(),
                "ticketClassId": ticket_class_id,
                "ticketName": (rec.get("ticketName") or "").strip(),
            }
        )
    return out


BASE_HTML = """
<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{{ title }} | Medidesk Admin</title>
  <style>
    /* ========== MEDIDESK COLORS ========== */
    :root {
      --md-primary: #0065D7;
      --md-secondary: #00A1D7;
      --md-accent: #00E09F;
      --md-gradient: linear-gradient(90deg, #00E09F 0%, #00A1D7 50%, #0065D7 100%);
      --md-bg: #f8fafc;
      --md-card-bg: #ffffff;
      --md-border: #e2e8f0;
      --md-text: #111111;
      --md-text-muted: #333333;
    }
    
    /* ========== BASE STYLES ========== */
    * { box-sizing: border-box; }
    body { 
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      margin: 0; 
      padding: 0;
      color: var(--md-text); 
      background: var(--md-bg);
      min-height: 100vh;
    }
    
    /* ========== LINKS ========== */
    a { color: var(--md-primary); text-decoration: none; }
    a:hover { text-decoration: underline; }
    
    /* ========== LAYOUT ========== */
    .row { display: flex; gap: 16px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .grid-edit { display: grid; grid-template-columns: 80% 20%; gap: 16px; }

    /* ========== SECTIONS (ACCORDION STYLE) ========== */
    details.styled-section {
      background: #fff;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      margin-bottom: 16px;
      overflow: hidden;
      box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    details.styled-section > summary {
      background: #f8fafc;
      padding: 12px 16px;
      font-weight: 600;
      font-size: 14px;
      color: #334155;
      cursor: pointer;
      border-bottom: 1px solid #e2e8f0;
      display: flex;
      align-items: center;
      list-style: none;
    }
    details.styled-section > summary::-webkit-details-marker { display: none; }
    details.styled-section > summary::before {
      content: '▶';
      font-size: 10px;
      margin-right: 8px;
      transition: transform 0.2s;
      color: #64748b;
    }
    details.styled-section[open] > summary::before { transform: rotate(90deg); }
    details.styled-section > .section-content { padding: 20px; }
    
    /* Tabela biletów w sekcji */
    .tickets-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .tickets-table th {
      background: #f1f5f9; padding: 10px 12px; text-align: left;
      font-weight: 600; color: #475569; border-bottom: 2px solid #e2e8f0;
    }
    .tickets-table td { padding: 10px 12px; border-bottom: 1px solid #e2e8f0; vertical-align: middle; }
    .tickets-table input[type="text"] {
      width: 100%; border: 1px solid #cbd5e1; padding: 6px 8px; border-radius: 4px; font-size: 13px;
    }
    .tickets-table input[type="text"]:focus {
      border-color: var(--md-primary); outline: none; box-shadow: 0 0 0 2px rgba(3, 105, 161, 0.1);
    }
    .content-wrapper { padding: 16px 24px; max-width: 1200px; margin: 0 auto; }
    
    /* ========== NAVIGATION ========== */
    .topbar {
      background: var(--md-card-bg);
      border-bottom: 1px solid var(--md-border);
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .topbar-gradient {
      height: 4px;
      background: var(--md-gradient);
    }
    .topbar-content {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 32px;
      max-width: 1400px;
      margin: 0 auto;
    }
    .topbar-brand {
      display: flex;
      align-items: center;
      gap: 12px;
      font-weight: 700;
      font-size: 18px;
      color: var(--md-primary);
    }
    .topbar-brand svg { height: 28px; width: auto; }
    .topbar-nav {
      display: flex;
      gap: 4px;
    }
    .topbar-nav a {
      padding: 8px 16px;
      border-radius: 6px;
      font-size: 14px;
      font-weight: 500;
      color: var(--md-text-muted);
      transition: all 0.15s ease;
    }
    .topbar-nav a:hover {
      background: #f1f5f9;
      color: var(--md-primary);
      text-decoration: none;
    }
    .topbar-nav a.active {
      background: #e0f2fe;
      color: var(--md-primary);
    }
    .topbar-user {
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 13px;
      color: var(--md-text-muted);
    }
    .topbar-user .btn { padding: 6px 14px; font-size: 13px; }
    
    /* ========== PAGE HEADER ========== */
    .page-header {
      margin-bottom: 16px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--md-border);
    }
    .page-header h1 {
      margin: 0 0 4px 0;
      font-size: 24px;
      font-weight: 600;
      color: var(--md-text);
    }
    .page-header .subtitle {
      color: var(--md-text-muted);
      font-size: 14px;
    }
    
    /* ========== CARDS ========== */
    .card { 
      border: 1px solid var(--md-primary); 
      border-radius: 10px; 
      padding: 16px; 
      background: var(--md-card-bg);
      box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    .card-header {
      font-weight: 600;
      font-size: 15px;
      margin-bottom: 10px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--md-border);
      color: var(--md-text);
    }
    
    /* ========== SECTION ========== */
    .section { margin-bottom: 16px; }
    .section-title {
      font-size: 13px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--md-text-muted);
      margin-bottom: 8px;
    }
    
    /* ========== TYPOGRAPHY ========== */
    .muted { color: var(--md-text-muted); font-size: 13px; }
    code { 
      background: #f1f5f9; 
      padding: 2px 8px; 
      border-radius: 6px; 
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
    }
    
    /* ========== BADGES / PILLS ========== */
    .pill { 
      display: inline-block; 
      padding: 4px 12px; 
      border-radius: 999px; 
      font-size: 12px;
      font-weight: 500;
      background: #e0f2fe;
      color: var(--md-primary);
    }
    .pill-success { background: #d1fae5; color: #059669; }
    .pill-warning { background: #fef3c7; color: #d97706; }
    .pill-error { background: #fee2e2; color: #dc2626; }
    .pill-neutral { background: #f1f5f9; color: #64748b; }
    
    /* ========== BUTTONS ========== */
    .btn { 
      display: inline-block; 
      padding: 10px 18px; 
      border-radius: 8px; 
      border: 1px solid var(--md-border); 
      background: var(--md-card-bg); 
      color: var(--md-text); 
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      transition: all 0.15s ease;
      text-decoration: none;
    }
    .btn:hover { 
      background: #f8fafc; 
      border-color: var(--md-secondary);
      text-decoration: none;
    }
    .btnPrimary { 
      border-color: var(--md-primary); 
      background: var(--md-primary); 
      color: #fff; 
    }
    .btnPrimary:hover { 
      background: #0052b3;
      border-color: #0052b3;
    }
    .btnDanger { 
      border-color: #dc2626; 
      background: #dc2626; 
      color: #fff; 
    }
    .btnDanger:hover {
      background: #b91c1c;
      border-color: #b91c1c;
    }
    .btnSecondary {
      border-color: var(--md-secondary);
      background: var(--md-secondary);
      color: #fff;
    }
    
    /* ========== FORMS ========== */
    input[type=text], input[type=email], input[type=password], textarea, select { 
      width: 100%; 
      padding: 10px 14px; 
      border-radius: 8px; 
      border: 1px solid var(--md-border);
      font-family: inherit;
      font-size: 14px;
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    input[type=text]:focus, input[type=email]:focus, input[type=password]:focus, textarea:focus, select:focus {
      outline: none;
      border-color: var(--md-primary);
      box-shadow: 0 0 0 3px rgba(0, 101, 215, 0.1);
    }
    textarea { min-height: 200px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .formGrid { display: grid; grid-template-columns: 200px 1fr; gap: 10px 14px; align-items: start; }
    .formLabel { font-size: 13px; color: var(--md-text); padding-top: 10px; font-weight: 500; word-break: break-word; white-space: normal; }
    .formHint { display: none; }
    .grid-edit { display: grid; grid-template-columns: 80% 20%; gap: 16px; }
    input[type="text"] { word-break: break-all; }
    
    /* ========== TABLES ========== */
    table { width: 100%; max-width: 1100px; margin: 0 auto; border-collapse: collapse; }
    th { 
      text-align: left; 
      padding: 8px 12px; 
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--md-text-muted);
      border-bottom: 2px solid var(--md-border);
    }
    td { 
      padding: 8px 12px; 
      border-bottom: 1px solid var(--md-border);
      font-size: 14px;
    }
    tr:hover { background: #f8fafc; }
    
    /* ========== KEY-VALUE GRID ========== */
    .kv { display: grid; grid-template-columns: 180px 1fr; gap: 8px 16px; font-size: 14px; }
    .kv > div { padding: 6px 0; border-bottom: 1px solid #f1f5f9; }
    .kv > div:nth-child(odd) { color: var(--md-text-muted); font-weight: 500; }
    
    /* ========== ALERTS ========== */
    .warn { 
      background: #fef3c7; 
      border: 1px solid #fcd34d; 
      padding: 14px 16px; 
      border-radius: 8px;
      color: #92400e;
    }
    .error { 
      background: #fee2e2; 
      border: 1px solid #fca5a5; 
      padding: 14px 16px; 
      border-radius: 8px;
      color: #991b1b;
    }
    .ok { 
      background: #d1fae5; 
      border: 1px solid #6ee7b7; 
      padding: 14px 16px; 
      border-radius: 8px;
      color: #065f46;
    }
    .info {
      background: #e0f2fe;
      border: 1px solid #7dd3fc;
      padding: 14px 16px;
      border-radius: 8px;
      color: #075985;
    }
    
    /* ========== MISC ========== */
    .banner { width: 100%; max-width: 900px; border: 1px solid var(--md-border); border-radius: 10px; overflow: hidden; }
    img { max-width: 100%; height: auto; display: block; }
    .swatch { width: 28px; height: 18px; border: 1px solid var(--md-border); border-radius: 5px; display: inline-block; vertical-align: middle; margin-left: 10px; }
    details { border: 1px solid var(--md-border); border-radius: 8px; padding: 12px 16px; background: #fafafa; }
    summary { cursor: pointer; font-weight: 600; color: var(--md-text); }
    hr { border: none; border-top: 1px solid var(--md-border); margin: 20px 0; }
    
    /* ========== MEDIDESK LOGO SVG ========== */
    .md-logo {
      display: inline-block;
      height: 24px;
    }
  </style>
</head>
<body>
  {% if show_nav %}
  <!-- Top Navigation Bar -->
  <div class="topbar">
    <div class="topbar-gradient"></div>
    <div class="topbar-content">
      <div class="topbar-brand">
        <svg class="md-logo" viewBox="0 0 145 29" fill="none" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <linearGradient id="mdGrad" x1="-4.73%" y1="50%" x2="100%" y2="50%">
              <stop offset="0%" stop-color="#00E09F"/>
              <stop offset="49.55%" stop-color="#00A1D7"/>
              <stop offset="100%" stop-color="#0065D7"/>
            </linearGradient>
          </defs>
          <path fill="url(#mdGrad)" d="M33.85 27.74c2-.0 4.1-.8 5.16-1.68.58-.46.86-.98.86-1.5 0-.8-.67-1.53-1.55-1.53-.33 0-.67.09-1.03.28-.67.37-1.4 1.07-3.62 1.07-2.1 0-4.1-1.35-4.62-3.85h10.03c.97 0 1.8-.67 1.85-1.65 0-4.4-3.59-8.1-7.69-8.1-4.01 0-7.81 3.24-7.81 8.71 0 4.71 3.22 8.26 8.42 8.26zm-.48-13.6c1.88 0 3.65 1.37 3.8 3.12v.21h-7.96c.49-2.54 2.13-3.33 4.16-3.33zM56.49 4.81c-1.06 0-1.82.8-1.82 1.87v5.99c-1.07-.98-2.8-1.9-4.9-1.9-4.1 0-7.36 3.49-7.36 8.5 0 4.98 3.25 8.47 7.48 8.47 2.07 0 3.86-1.1 4.77-2.14 0 1.04.76 1.83 1.82 1.83 1.07 0 1.83-.8 1.83-1.87V6.68c0-1.1-.76-1.87-1.82-1.87zm-6.14 19.57c-2.64 0-4.44-2.2-4.44-5.1 0-2.91 1.8-5.14 4.44-5.14 2.68 0 4.47 2.23 4.47 5.14 0 2.9-1.79 5.1-4.47 5.1zM65.07 12.94c0-1.07-.76-1.86-1.82-1.86-1.07 0-1.83.79-1.83 1.86v12.63c0 1.07.76 1.86 1.83 1.86 1.06 0 1.82-.79 1.82-1.86V12.94zm-1.73-4.44c1.06 0 1.92-.86 1.92-1.93 0-1.07-.86-1.93-1.92-1.93-1.06 0-1.92.86-1.92 1.93 0 1.07.86 1.93 1.92 1.93zM81.33 4.81c-1.07 0-1.83.8-1.83 1.87v5.99c-1.06-.98-2.79-1.9-4.89-1.9-4.1 0-7.36 3.49-7.36 8.5 0 4.98 3.25 8.47 7.48 8.47 2.07 0 3.86-1.1 4.77-2.14 0 1.04.76 1.83 1.83 1.83 1.06 0 1.82-.8 1.82-1.87V6.68c0-1.1-.76-1.87-1.82-1.87zm-6.14 19.57c-2.65 0-4.44-2.2-4.44-5.1 0-2.91 1.79-5.14 4.44-5.14 2.67 0 4.47 2.23 4.47 5.14 0 2.9-1.8 5.1-4.47 5.1zM93.97 27.74c2.01 0 4.1-.8 5.17-1.68.58-.46.85-.98.85-1.5 0-.8-.67-1.53-1.55-1.53-.33 0-.67.09-1.03.28-.67.37-1.4 1.07-3.62 1.07-2.1 0-4.1-1.35-4.61-3.85h10.03c.97 0 1.79-.67 1.85-1.65 0-4.4-3.59-8.1-7.7-8.1-4.01 0-7.81 3.24-7.81 8.71 0 4.71 3.22 8.26 8.42 8.26zm-.49-13.6c1.89 0 3.65 1.37 3.8 3.12v.21h-7.96c.49-2.54 2.13-3.33 4.16-3.33zM102.51 24.9c1.58 2.14 4.17 2.84 6.57 2.84 2.83 0 5.99-1.74 5.99-4.89 0-3.58-2.89-4.43-5.35-5.1-1.79-.49-3.34-.89-3.34-2.3 0-1.53 1.4-1.68 2.31-1.68 1.49 0 2.68.58 3.37 1.47.52.49 1.46.58 2.07.09.85-.7.64-1.65.18-2.26-1.28-1.62-3.68-2.29-5.54-2.29-2.98 0-5.9 1.8-5.9 4.83 0 3.61 3.07 4.44 5.59 5.14 1.8.49 3.31.95 3.31 2.26 0 1.59-1.49 1.77-2.37 1.8-1.95 0-3.13-.67-4.29-1.86-.7-.7-1.46-.7-2.1-.31-1.03.67-.91 1.68-.5 2.26zM119.6 27.43c1.06 0 1.82-.79 1.82-1.86v-3.21l1.49-1.38 5.47 5.81c.37.4.85.61 1.34.61.82 0 1.85-.73 1.85-1.8 0-.46-.18-.95-.58-1.38l-5.32-5.81 4.59-4.25c.49-.43.73-.92.73-1.38 0-.73-.79-1.71-1.73-1.71-.46 0-.94.18-1.34.58l-6.5 6.33V6.68c0-1.07-.76-1.87-1.82-1.87-1.07 0-1.83.8-1.83 1.87v18.89c0 1.07.76 1.86 1.83 1.86zM1.76 10.94c.77 0 1.43.5 1.67 1.2.95-.69 2.08-1.09 3.39-1.09 2.27 0 4.01.76 5.16 2.18 1.15-1.37 2.81-2.18 4.92-2.18 4.26 0 6.66 2.69 6.79 7.36v7.44c0 .98-.79 1.77-1.76 1.77-.97 0-1.76-.79-1.76-1.77v-7.36c-.09-2.76-1.03-3.82-3.21-3.84-2.18 0-3.14 1.27-3.28 3.84v7.36c0 .98-.79 1.77-1.76 1.77-.97 0-1.76-.79-1.76-1.77v-6.71c-.01-.07-.01-.14 0-.22v-.42c-.1-2.76-1.04-3.82-3.21-3.84-2.26 0-3.2 1.35-3.29 4.09v7.1c0 .98-.79 1.77-1.76 1.77C.79 27.59 0 26.8 0 25.82V12.71c0-.98.79-1.77 1.76-1.77zM142.59 0c1.3-.01 2.12 1.42 1.45 2.52l-4.64 7.72c-.47.79-1.5 1.04-2.28.57-.79-.47-1.05-1.5-.57-2.28l3.1-5.16-6.18.07c-.89.01-1.62-.68-1.69-1.55l-.0-.1c-.01-.92.73-1.67 1.65-1.68l9.16-.1z"/>
        </svg>
    </div>
      <nav class="topbar-nav">
        {% if can_events %}
        <a href="{{ events_url }}">Wydarzenia</a>
        {% endif %}
        {% if can_orders %}
        <a href="{{ orders_url }}">Zamówienia</a>
        {% endif %}
        {% if can_import %}
        <a href="{{ import_url }}">Import</a>
        {% endif %}
        {% if can_users %}
        <a href="{{ users_url }}">Konta i uprawnienia</a>
        {% endif %}
        {% if can_audit %}
        <a href="{{ audit_url }}">Log audytu</a>
        {% endif %}
      </nav>
      <div class="topbar-user">
        {% if user_email %}
        <span>{{ user_email }}</span>
        <a href="{{ logout_url }}" class="btn">Wyloguj</a>
        {% else %}
        <span>token: <code>***</code></span>
        {% endif %}
  </div>
    </div>
  </div>
  
  <!-- Main Content -->
  <div class="content-wrapper">
    <div class="page-header">
      <h1>{{ title }}</h1>
    </div>
  {{ body|safe }}
  </div>
  {% else %}
  <!-- No nav (login page etc.) -->
  {{ body|safe }}
  {% endif %}
</body>
</html>
"""


def _page(title: str, body: str, show_nav: bool = True) -> str:
    """Renderuje stronę panelu admin."""
    user = _get_current_admin_user()
    user_email = user.get("email") if user else None
    can_events = _user_has_permission(user, "events")
    can_orders = _user_has_permission(user, "orders")
    can_import = _user_has_permission(user, "import")
    can_users = _user_has_permission(user, "users")
    can_audit = _user_has_permission(user, "audit")
    
    # Get token for legacy URL generation
    token = _get_admin_token_for_legacy()
    
    return render_template_string(
        BASE_HTML,
        title=title,
        body=body,
        show_nav=show_nav,
        user_email=user_email,
        logout_url=url_for("admin_bp.logout") if user else None,
        can_events=can_events,
        can_orders=can_orders,
        can_import=can_import,
        can_users=can_users,
        can_audit=can_audit,
        events_url=url_for("admin_bp.events_list", token=token) if token else url_for("admin_bp.events_list"),
        orders_url=url_for("admin_bp.orders_list", token=token) if token else url_for("admin_bp.orders_list"),
        import_url=url_for("admin_bp.import_page", token=token) if token else url_for("admin_bp.import_page"),
        users_url=url_for("admin_bp.users_list", token=token) if token else url_for("admin_bp.users_list"),
        audit_url=url_for("admin_bp.audit_log", token=token) if token else url_for("admin_bp.audit_log"),
    )


@admin_bp.route("/", methods=["GET"])
def admin_root():
    token = _require_admin_token()
    user = _get_current_admin_user()
    return redirect(_landing_url_for_user(user, token=token or None))


@admin_bp.route("/import", methods=["GET"])
@_require_permission("import")
def import_page():
    token = _require_admin_token()
    body = f"""
    <style>
      .import-card {{
        max-width: 700px;
        background: #fff;
        border: 1px solid var(--md-border);
        border-radius: 12px;
        overflow: hidden;
      }}
      .import-card-header {{
        padding: 20px 24px;
        background: #f8fafc;
        border-bottom: 1px solid var(--md-border);
      }}
      .import-card-header h3 {{
        margin: 0;
        font-size: 18px;
        font-weight: 600;
      }}
      .import-card-body {{
        padding: 24px;
      }}
      .import-info {{
        font-size: 14px;
        color: var(--md-text);
        line-height: 1.6;
      }}
      .import-info ul {{
        margin: 12px 0;
        padding-left: 20px;
      }}
      .import-info li {{
        margin-bottom: 6px;
      }}
      .import-form {{
        margin-top: 24px;
        padding-top: 24px;
        border-top: 1px solid var(--md-border);
      }}
      .file-group {{
        margin-bottom: 20px;
      }}
      .file-group label {{
        display: block;
        font-size: 13px;
        font-weight: 600;
        color: var(--md-text);
        margin-bottom: 8px;
      }}
      .file-group input[type="file"] {{
        width: 100%;
        padding: 12px;
        border: 2px dashed var(--md-border);
        border-radius: 8px;
        background: #f8fafc;
        cursor: pointer;
        transition: all 0.15s ease;
      }}
      .file-group input[type="file"]:hover {{
        border-color: var(--md-primary);
        background: #f1f5f9;
      }}
      .confirm-group {{
        margin: 24px 0;
        padding: 16px;
        background: #fef3c7;
        border-radius: 8px;
      }}
      .confirm-group label {{
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 13px;
        color: #92400e;
        cursor: pointer;
      }}
      .confirm-group input[type="checkbox"] {{
        width: 18px;
        height: 18px;
      }}
    </style>

    <div style="margin-bottom:20px;">
      <a class="btn" href="{url_for('admin_bp.events_list', token=token)}">← Lista wydarzeń</a>
    </div>
    
    <div class="import-card">
      <div class="import-card-header">
        <h3>Import konfiguracji z CSV</h3>
      </div>
      <div class="import-card-body">
        <div class="import-info">
          <p>Wgraj pliki <code>Wydarzenia.csv</code> i <code>Bilety.csv</code>. Import wykona:</p>
          <ul>
            <li>Upsert eventów (po <code>eventId</code>)</li>
            <li>Nadpisanie klas biletów dla eventów z pliku</li>
        </ul>
          
          <div class="info" style="margin:16px 0;">
            <strong>Obsługiwane formaty CSV:</strong><br/>
          • <b>Klasyczny</b> – nagłówki w pierwszym wierszu (np. <code>eventName,eventId,...</code>)<br/>
          • <b>Pivot</b> – klucze w pierwszej kolumnie (np. <code>key;Rekord 1;Rekord 2</code>)<br/>
            <span class="muted">Format jest wykrywany automatycznie.</span>
        </div>
          
        <div class="warn">
            <strong>Uwaga:</strong> bilety zostaną zaimportowane tylko dla eventów, które istnieją w <code>Wydarzenia.csv</code>.
        </div>
      </div>
        
        <form method="post" action="{url_for('admin_bp.import_run')}" enctype="multipart/form-data" class="import-form">
        <input type="hidden" name="token" value="{token}" />
          
          <div class="file-group">
            <label>Wydarzenia.csv</label>
        <input type="file" name="wydarzenia" accept=".csv" />
          </div>
          
          <div class="file-group">
            <label>Bilety.csv (opcjonalnie)</label>
        <input type="file" name="bilety" accept=".csv" />
          </div>
          
          <div class="confirm-group">
            <label>
              <input type="checkbox" name="confirm" value="yes" />
              Potwierdzam import (nadpisze klasy biletów dla eventów z pliku)
            </label>
          </div>
          
          <button class="btn btnPrimary" type="submit" style="width:100%;">Importuj pliki</button>
      </form>
      </div>
    </div>
    """
    return _page("Import CSV", body)


@admin_bp.route("/import", methods=["POST"])
@_require_permission("import")
def import_run():
    token = _require_admin_token()
    confirm = (request.form.get("confirm") or "").strip().lower() == "yes"
    if not confirm:
        body = f"<div class='error'>Zaznacz potwierdzenie importu.</div><p><a class='btn' href='{url_for('admin_bp.import_page', token=token)}'>Wróć</a></p>"
        return _page("Błąd importu", body), 400

    wydarzenia_file = request.files.get("wydarzenia")
    bilety_file = request.files.get("bilety")

    if not wydarzenia_file or not wydarzenia_file.filename:
        body = f"<div class='error'>Brak pliku Wydarzenia.csv</div><p><a class='btn' href='{url_for('admin_bp.import_page', token=token)}'>Wróć</a></p>"
        return _page("Błąd importu", body), 400

    # Automatyczne wykrywanie formatu CSV (pivot vs klasyczny)
    wydarzenia_records, detected_format = _parse_events_csv(wydarzenia_file.read())
    bilety_records: List[Dict[str, str]] = []
    if bilety_file and bilety_file.filename:
        bilety_records = _parse_bilety_csv(bilety_file.read())

    # Import events
    imported_events = 0
    event_ids: List[str] = []
    for rec in wydarzenia_records:
        event_id = (rec.get("eventId") or rec.get("eventID") or rec.get("event_id") or "").strip()
        event_name = (rec.get("eventName") or "").strip()
        status = (rec.get("Status wprowadzenia do MAKE") or rec.get("Status") or "").strip()
        notes = (rec.get("UWAGI") or "").strip()
        if not event_id or not event_name:
            continue

        # dane w JSONB: wszystkie pola poza metadanymi
        data: Dict[str, Any] = {}
        for k, v in rec.items():
            if k in ("Status wprowadzenia do MAKE", "UWAGI"):
                continue
            data[k] = v
        # fallback
        data.setdefault("eventId", event_id)
        data.setdefault("eventName", event_name)

        upsert_event(event_id=event_id, event_name=event_name, status=status, notes=notes, data=data)
        imported_events += 1
        event_ids.append(event_id)

    # Import ticket classes grouped by event
    imported_ticket_classes = 0
    skipped_ticket_events: List[str] = []
    if bilety_records:
        event_id_set = set(event_ids)
        by_event: Dict[str, List[Dict[str, Any]]] = {}
        for r in bilety_records:
            eid = (r.get("eventId") or "").strip()
            if not eid:
                continue
            # Importuj bilety tylko dla eventów, które istnieją w Wydarzenia.csv
            if eid not in event_id_set:
                skipped_ticket_events.append(eid)
                continue
            by_event.setdefault(eid, []).append(
                {
                    "ticket_class_id": (r.get("ticketClassId") or "").strip(),
                    "ticket_name": (r.get("ticketName") or "").strip(),
                    "data": {},
                }
            )

        for eid, classes in by_event.items():
            replace_ticket_classes(eid, classes)
            imported_ticket_classes += len(classes)

    skipped_html = ""
    if skipped_ticket_events:
        uniq = sorted(set(skipped_ticket_events))
        skipped_html = (
            "<div class='warn' style='margin-top:12px;'>"
            "<b>Pominięte bilety dla eventów (brak w Wydarzenia.csv):</b><br/>"
            + " ".join(f"<code>{x}</code>" for x in uniq[:50])
            + ("<div class='muted' style='margin-top:6px;'>… (ucięto listę)</div>" if len(uniq) > 50 else "")
            + "</div>"
        )

    format_label = "klasyczny (nagłówki w pierwszym wierszu)" if detected_format == "classic" else "pivot (klucze w pierwszej kolumnie)"
    
    body = f"""
    <div class="ok"><b>Import zakończony.</b></div>
    <div style="height:10px;"></div>
    <div class="card">
      <div class="kv">
        <div class="muted">Wykryty format CSV</div><div><code>{detected_format}</code> – {format_label}</div>
        <div class="muted">Zaimportowane eventy</div><div><b>{imported_events}</b></div>
        <div class="muted">Zaimportowane klasy biletów</div><div><b>{imported_ticket_classes}</b></div>
      </div>
    </div>
    {skipped_html}
    <div style="height:12px;"></div>
    <a class="btn btnPrimary" href="{url_for('admin_bp.events_list', token=token)}">Przejdź do listy wydarzeń</a>
    """
    return _page("Import OK", body)


@admin_bp.route("/events", methods=["GET"])
@_require_permission("events")
def events_list():
    token = _require_admin_token()
    current_user = _get_current_admin_user()
    is_viewer = _is_viewer(current_user)
    is_admin = _is_admin_user(current_user)
    
    events = list_events(limit=500)
    
    # Filtruj wydarzenia dla viewera
    if is_viewer:
        allowed_events = _normalize_allowed_events(current_user.get("allowed_events") if current_user else [])
        # Jeśli viewer nie ma przypisanych wydarzeń - pokaż pustą listę
        if not allowed_events:
            events = []
        else:
            events = [e for e in events if e.get("event_id") in allowed_events]

    def _status_pill(status: str) -> str:
        """Return styled pill for event status."""
        s = (status or "").lower()
        if s == "active" or s == "aktywne":
            return '<span class="pill pill-success">Aktywne</span>'
        elif s == "draft" or s == "szkic":
            return '<span class="pill pill-warning">Szkic</span>'
        elif s == "ended" or s == "zakończone":
            return '<span class="pill pill-neutral">Zakończone</span>'
        else:
            return f'<span class="pill">{status or "—"}</span>'

    rows = []
    for e in events:
        status = e.get('status') or ''
        status_class = "active" if status.lower() in ("active", "aktywne") else "draft" if status.lower() in ("draft", "szkic") else "ended"
        
        # Get banner and color from event data
        event_data = e.get('data') or {}
        banner_url = event_data.get('event_mail_link_top_banner') or event_data.get('event_mail_link_bottom_banner') or ''
        event_color = event_data.get('color_gradient_1') or ''
        
        # Border style based on event color
        border_style = f"border-color: {event_color};" if event_color else ""
        
        # Linki do Backstage
        backstage_config_link = event_data.get('event_config_link') or ''
        backstage_orders_link = event_data.get('event_orders_link') or ''
        backstage_attendees_link = event_data.get('event_attendees_link') or ''
        
        # Banner HTML - show image or gradient placeholder
        if banner_url:
            banner_html = f'<div class="event-card-banner"><img src="{banner_url}" alt="" loading="lazy" /></div>'
        else:
            # Use event color for placeholder gradient if available
            if event_color:
                banner_html = f'<div class="event-card-banner event-card-banner-placeholder" style="background: linear-gradient(135deg, {event_color}22 0%, {event_color}11 100%);"></div>'
            else:
                banner_html = '<div class="event-card-banner event-card-banner-placeholder"></div>'
        
        # Backstage buttons - 3 przyciski (jeśli istnieją linki)
        backstage_btns = []
        if backstage_config_link:
            backstage_btns.append(f'<a href="{backstage_config_link}" target="_blank" rel="noopener" class="btn backstage-btn" style="font-size:12px; padding:6px 10px;" title="Konfiguracja w Backstage"><img src="/backstage-logo.jpg" alt="BS" style="width:14px; height:14px; border-radius:2px; vertical-align:middle; margin-right:3px;" />Konfiguracja ↗</a>')
        if backstage_orders_link:
            backstage_btns.append(f'<a href="{backstage_orders_link}" target="_blank" rel="noopener" class="btn backstage-btn" style="font-size:12px; padding:6px 10px;" title="Zamówienia w Backstage"><img src="/backstage-logo.jpg" alt="BS" style="width:14px; height:14px; border-radius:2px; vertical-align:middle; margin-right:3px;" />Zamówienia ↗</a>')
        if backstage_attendees_link:
            backstage_btns.append(f'<a href="{backstage_attendees_link}" target="_blank" rel="noopener" class="btn backstage-btn" style="font-size:12px; padding:6px 10px;" title="Uczestnicy w Backstage"><img src="/backstage-logo.jpg" alt="BS" style="width:14px; height:14px; border-radius:2px; vertical-align:middle; margin-right:3px;" />Uczestnicy ↗</a>')
        backstage_btn = ''.join(backstage_btns)
        
        rows.append(
            f"""
            <div class="event-card" data-status="{status_class}" style="{border_style}">
              {banner_html}
              <div class="event-card-content">
                <div class="event-card-header">
                  <div class="event-card-info">
                    <div class="event-card-title">{e.get('event_name','')}</div>
                </div>
                  <div class="event-card-status">
                    {_status_pill(status)}
                </div>
              </div>
                <div class="event-card-actions">
                {'<a class="btn" href="' + url_for('admin_bp.event_edit', event_id=e.get('event_id',''), token=token) + '">Edytuj</a>' if is_admin else ''}
                <a class="btn" href="{url_for('admin_bp.event_preview', event_id=e.get('event_id',''), token=token)}">Podgląd</a>
                {backstage_btn if is_admin else ''}
                </div>
              </div>
            </div>
            """
        )

    body = f"""
    <style>
      .events-toolbar {{
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
        margin-bottom: 24px;
      }}
      .events-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
        gap: 20px;
      }}
      .event-card {{
        background: #fff;
        border: 3px solid var(--md-border);
        border-radius: 12px;
        overflow: hidden;
        transition: box-shadow 0.2s ease, transform 0.2s ease;
      }}
      .event-card:hover {{
        box-shadow: 0 4px 12px rgba(0, 101, 215, 0.15);
        transform: translateY(-2px);
      }}
      .event-card-banner {{
        width: 100%;
        height: 120px;
        overflow: hidden;
        background: #f8fafc;
        position: relative;
        display: flex;
        align-items: center;
        justify-content: center;
      }}
      .event-card-banner img {{
        width: 100%;
        height: 100%;
        object-fit: contain;
        object-position: center;
        background: #fff;
      }}
      .event-card-banner-placeholder {{
        width: 100%;
        height: 100%;
        background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%);
      }}
      .event-card[data-status="active"] .event-card-banner-placeholder {{
        background: linear-gradient(135deg, rgba(0, 224, 159, 0.15) 0%, rgba(0, 161, 215, 0.15) 100%);
      }}
      .event-card[data-status="draft"] .event-card-banner-placeholder {{
        background: linear-gradient(135deg, rgba(252, 211, 77, 0.2) 0%, rgba(251, 191, 36, 0.1) 100%);
      }}
      .event-card[data-status="ended"] .event-card-banner-placeholder {{
        background: linear-gradient(135deg, rgba(148, 163, 184, 0.2) 0%, rgba(100, 116, 139, 0.1) 100%);
      }}
      .event-card-content {{
        padding: 16px;
      }}
      .event-card-header {{
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 12px;
        margin-bottom: 12px;
      }}
      .event-card-title {{
        font-weight: 600;
        font-size: 15px;
        color: var(--md-text);
        margin-bottom: 4px;
        line-height: 1.3;
      }}
      .event-card-id {{
        font-size: 11px;
        color: var(--md-text-muted);
      }}
      .event-card-id code {{
        font-size: 10px;
        background: #f1f5f9;
        padding: 2px 5px;
        border-radius: 4px;
      }}
      .event-card-actions {{
        display: flex;
        flex-direction: column;
        gap: 8px;
      }}
      .event-card-actions .btn {{
        padding: 10px 16px;
        font-size: 13px;
        text-align: center;
        width: 100%;
      }}
      .event-card-actions .backstage-btn {{
        background: #f0f9ff;
        border: 1px solid #bae6fd;
        color: #0369a1;
      }}
      .event-card-actions .backstage-btn:hover {{
        background: #e0f2fe;
      }}
      .empty-state {{
        text-align: center;
        padding: 60px 20px;
        color: var(--md-text-muted);
      }}
      .empty-state-icon {{
        font-size: 48px;
        margin-bottom: 16px;
        opacity: 0.5;
      }}
    </style>
    
    <div class="events-toolbar">
      {'<a class="btn btnPrimary" href="' + url_for('admin_bp.event_new', token=token) + '">+ Nowe wydarzenie</a>' if is_admin else ''}
      {'<a class="btn" href="' + url_for('admin_bp.import_page', token=token) + '">Import CSV</a>' if is_admin else ''}
      {'<span class="pill" style="background:#e0f2fe; color:#0369a1;">Tryb podglądu</span>' if is_viewer else ''}
    </div>
    
    {f'''
    <div class="events-grid">
      {''.join(rows)}
    </div>
    ''' if rows else '''
    <div class="empty-state">
      <div class="empty-state-icon">📅</div>
      <p>Brak wydarzeń</p>
      <p class="muted">Dodaj pierwsze wydarzenie klikając "Nowe wydarzenie"</p>
    </div>
    '''}
    """
    return _page("Wydarzenia", body)


@admin_bp.route("/events/new", methods=["GET"])
@_require_permission("events")
def event_new():
    token = _require_admin_token()
    
    # Blokuj tworzenie dla nie-adminów
    if not _is_admin_user(_get_current_admin_user()):
        abort(403, description="Brak uprawnień do tworzenia wydarzeń")
    
    return _event_form_page(token=token, event=None, tickets=[])


@admin_bp.route("/events/<event_id>/edit", methods=["GET"])
@_require_permission("events")
def event_edit(event_id: str):
    token = _require_admin_token()
    
    # Nie-admin nie może edytować - przekieruj do podglądu
    if not _is_admin_user(_get_current_admin_user()):
        return redirect(url_for("admin_bp.event_preview", event_id=event_id, token=token))
    
    ev = get_event(event_id)
    if not ev:
        abort(404, description="Nie znaleziono eventu")
    tickets = get_ticket_classes(event_id)
    return _event_form_page(token=token, event=ev, tickets=tickets)


@admin_bp.route("/events/save", methods=["POST"])
@_require_permission("events")
def event_save():
    token = _require_admin_token()
    
    # Blokuj edycję dla nie-adminów
    if not _is_admin_user(_get_current_admin_user()):
        abort(403, description="Brak uprawnień do edycji")

    event_id = (request.form.get("event_id") or "").strip()
    event_name = (request.form.get("event_name") or "").strip()
    status = (request.form.get("status") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    data_json = (request.form.get("data_json") or "").strip()
    kv_paste = (request.form.get("kv_paste") or "").strip()
    ticket_classes_json = (request.form.get("ticket_classes_json") or "").strip()

    if not event_id or not event_name:
        body = f'<div class="error">Wymagane: event_id i event_name</div><p><a class="btn" href="{url_for("admin_bp.event_new", token=token)}">Wróć</a></p>'
        return _page("Błąd", body), 400

    data: Dict[str, Any] = {}

    if data_json:
        parsed, err = _safe_json_loads(data_json)
        if err or not isinstance(parsed, dict):
            body = f'<div class="error">Niepoprawny JSON w data_json: {err}</div><p><a class="btn" href="{url_for("admin_bp.event_edit", event_id=event_id, token=token)}">Wróć</a></p>'
            return _page("Błąd", body), 400
        data = parsed

    if kv_paste:
        data.update(parse_kv_lines(kv_paste))

    # Pola formularza (marketing) – zawsze bierzemy wartości z inputów.
    # Dla istniejących eventów pola są prefill, więc zapisuje "cały formularz".
    for fd in FIELD_DEFS:
        k = fd["key"]
        data[k] = (request.form.get(_field_name(k)) or "").strip()

    # Fallback: jeśli ktoś nie wypełni eventId/eventName w data, uzupełnij.
    if not data.get("eventId"):
        data["eventId"] = event_id
    if not data.get("eventName"):
        data["eventName"] = event_name

    # Ticket classes
    ticket_classes: List[Dict[str, Any]] = []
    if ticket_classes_json:
        parsed, err = _safe_json_loads(ticket_classes_json)
        if err or not isinstance(parsed, list):
            body = f'<div class="error">Niepoprawny JSON w ticket_classes_json: {err}</div><p><a class="btn" href="{url_for("admin_bp.event_edit", event_id=event_id, token=token)}">Wróć</a></p>'
            return _page("Błąd", body), 400
        for item in parsed:
            if not isinstance(item, dict):
                continue
            ticket_classes.append(
                {
                    "ticket_class_id": item.get("ticket_class_id"),
                    "ticket_name": item.get("ticket_name"),
                    "data": item.get("data") or {},
                }
            )

    upsert_event(event_id=event_id, event_name=event_name, status=status, notes=notes, data=data)
    if ticket_classes_json:
        replace_ticket_classes(event_id, ticket_classes)

    return redirect(url_for("admin_bp.event_edit", event_id=event_id, token=token))


@admin_bp.route("/events/<event_id>/delete", methods=["POST"])
@_require_permission("events")
def event_delete(event_id: str):
    token = _require_admin_token()
    
    # Blokuj usuwanie dla nie-adminów
    if not _is_admin_user(_get_current_admin_user()):
        abort(403, description="Brak uprawnień do usuwania")
    
    delete_event(event_id)
    return redirect(url_for("admin_bp.events_list", token=token))


def _render_event_preview(token: str, event_id: str, event_name: str, data: Dict[str, Any], is_viewer: bool = False) -> str:
    def _val(k: str) -> str:
        v = data.get(k)
        return (str(v).strip() if v is not None else "")

    banner = _val("event_mail_link_top_banner") or _val("event_mail_link_bottom_banner")
    logo = _val("event_logo_link") or _val("event_logo_link_white") or _val("event_logo_link_color")
    color1 = _val("color_gradient_1")
    color2 = _val("color_gradient_2")
    header_bg = f"linear-gradient(135deg, {color1} 0%, {color2} 100%)" if (color1 and color2) else (color1 or "#0065D7")
    
    # Linki do Backstage
    backstage_config_link = _val("event_config_link")
    backstage_orders_link = _val("event_orders_link")
    backstage_attendees_link = _val("event_attendees_link")

    # Nie alarmujemy o brakujących polach - można edytować w razie potrzeby

    # Grupuj pola w sekcje logiczne
    field_sections = {
        "Podstawowe dane": ["eventId", "eventName", "md_email_kontakt", "md_mobile_kontakt", "md_email_techniczny", "md_phone_techniczny"],
        "Szczegóły wydarzenia": ["event_date_time", "event_end_date_time", "event_days_count", "event_day_text_1", "event_day_text_2", "event_address_text_street", "event_address_text_postcode", "event_address_text_city"],
        "Kolory i branding": ["color_gradient_1", "color_gradient_2"],
        "Obrazy i media": ["event_mail_link_top_banner", "event_mail_link_bottom_banner", "event_logo_link", "event_logo_link_white", "event_logo_link_color"],
        "Linki Backstage": ["event_config_link", "event_orders_link", "event_attendees_link"],
    }

    # W trybie viewera nie pokazujemy sekcji Backstage
    if is_viewer:
        field_sections.pop("Linki Backstage", None)
    
    def _render_field(fd: Dict[str, str]) -> str:
        k = fd["key"]
        v = _val(k)
        label = fd["label"]
        kind = fd.get("kind", "text")
        
        if not v:
            return f'''
            <div class="field-row">
              <div class="field-label">
                {label}
                <span class="field-key" style="display:none;">{k}</span>
              </div>
              <div class="field-value muted">—</div>
            </div>
            '''
        
        # Format value based on type
        if kind == "url" and _is_http_url(v):
            preview_html = f'<div style="margin-top:12px;"><img src="{v}" style="max-width:100%; height:auto; max-height:400px; border-radius:12px; border:2px solid #e5e7eb; box-shadow:0 2px 8px rgba(0,0,0,0.08);" onerror="this.style.display=\'none\'" /></div>' if any(ext in v.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']) else ''
            value_html = f'<a href="{v}" target="_blank" rel="noopener" style="color:#0065D7; text-decoration:none; font-weight:500;">Otwórz link ↗</a>{preview_html}'
        elif kind == "color" and _is_hex_color(v):
            value_html = f'<div style="display:flex; align-items:center; gap:16px;"><div style="width:80px; height:50px; border-radius:10px; background:{v}; border:2px solid #e5e7eb; box-shadow:0 2px 4px rgba(0,0,0,0.1);"></div><code style="font-size:14px; font-weight:600;">{v}</code></div>'
        else:
            value_html = v
        
        return f'''
        <div class="field-row">
          <div class="field-label">
            {label}
            <span class="field-key" style="display:none;">{k}</span>
          </div>
          <div class="field-value">{value_html}</div>
        </div>
        '''
    
    sections_html = ""
    for section_name, field_keys in field_sections.items():
        fields_in_section = [fd for fd in FIELD_DEFS if fd["key"] in field_keys]
        if not fields_in_section:
            continue
        
        fields_html = "".join(_render_field(fd) for fd in fields_in_section)
        sections_html += f'''
        <div class="preview-section">
          <div class="preview-section-header">{section_name}</div>
          <div class="preview-section-body">{fields_html}</div>
        </div>
        '''

    # Sekcja Backstage (linki zewnętrzne) - format tabelkowy
    backstage_html = ""
    if is_viewer:
        backstage_html = ""
    elif backstage_config_link or backstage_orders_link or backstage_attendees_link:
        ext_icon = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-left:4px; vertical-align:middle;"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>'
        
        backstage_rows = ""
        if backstage_config_link:
            backstage_rows += f'<tr><td style="padding:12px 16px; border-bottom:1px solid #e2e8f0;">Link konfiguracji (Backstage)</td><td style="padding:12px 16px; border-bottom:1px solid #e2e8f0;"><a href="{backstage_config_link}" target="_blank" rel="noopener" style="color:#0065D7; text-decoration:none; font-weight:500;">Otwórz link {ext_icon}</a></td></tr>'
        if backstage_orders_link:
            backstage_rows += f'<tr><td style="padding:12px 16px; border-bottom:1px solid #e2e8f0;">Link orders (Backstage)</td><td style="padding:12px 16px; border-bottom:1px solid #e2e8f0;"><a href="{backstage_orders_link}" target="_blank" rel="noopener" style="color:#0065D7; text-decoration:none; font-weight:500;">Otwórz link {ext_icon}</a></td></tr>'
        if backstage_attendees_link:
            backstage_rows += f'<tr><td style="padding:12px 16px;">Link attendees (Backstage)</td><td style="padding:12px 16px;"><a href="{backstage_attendees_link}" target="_blank" rel="noopener" style="color:#0065D7; text-decoration:none; font-weight:500;">Otwórz link {ext_icon}</a></td></tr>'
        
        backstage_html = f'''
        <div class="preview-section" style="margin-top:20px;">
          <div class="preview-section-header" style="background:linear-gradient(135deg, #0369a1 0%, #0ea5e9 100%); color:white; display:flex; align-items:center; gap:8px;">
            <img src="/backstage-logo.jpg" alt="Backstage" style="width:20px; height:20px; border-radius:4px;" />
            ZOHO BACKSTAGE
          </div>
          <div class="preview-section-body" style="padding:0;">
            <table style="width:100%; border-collapse:collapse;">
              {backstage_rows}
            </table>
          </div>
        </div>
        '''
    
    # Sekcja Typy biletów (konfiguracja z naszej bazy)
    ticket_classes = get_ticket_classes(event_id)
    ticket_classes_html = ""
    if ticket_classes:
        tc_rows = ""
        for tc in ticket_classes:
            tc_id = tc.get("ticket_class_id", "")
            tc_name = tc.get("ticket_name", "")
            tc_data = tc.get("data") or {}
            tc_price = tc_data.get("ticket_price") or tc_data.get("price") or "—"
            tc_vat = tc_data.get("vat_rate") or tc_data.get("vat") or "—"
            tc_rows += f'''
            <tr>
              <td style="padding:12px 16px; border-bottom:1px solid #e2e8f0;"><code style="font-size:11px; background:#f1f5f9; padding:2px 6px; border-radius:4px;">{tc_id[:20]}...</code></td>
              <td style="padding:12px 16px; border-bottom:1px solid #e2e8f0; font-weight:500;">{tc_name}</td>
              <td style="padding:12px 16px; border-bottom:1px solid #e2e8f0; text-align:right;">{tc_price} PLN</td>
              <td style="padding:12px 16px; border-bottom:1px solid #e2e8f0; text-align:right;">{tc_vat}%</td>
            </tr>
            '''
        ticket_classes_html = f'''
        <div class="preview-section" style="margin-top:20px;">
          <div class="preview-section-header" style="background:linear-gradient(135deg, #7c3aed 0%, #a855f7 100%); color:white;">TYPY BILETÓW ({len(ticket_classes)})</div>
          <div class="preview-section-body" style="padding:0;">
            <table style="width:100%; border-collapse:collapse; font-size:14px;">
              <tr style="background:#f8fafc;">
                <th style="padding:10px 16px; text-align:left; font-weight:600; font-size:12px; color:#64748b; text-transform:uppercase;">ID</th>
                <th style="padding:10px 16px; text-align:left; font-weight:600; font-size:12px; color:#64748b; text-transform:uppercase;">Nazwa</th>
                <th style="padding:10px 16px; text-align:right; font-weight:600; font-size:12px; color:#64748b; text-transform:uppercase;">Cena netto</th>
                <th style="padding:10px 16px; text-align:right; font-weight:600; font-size:12px; color:#64748b; text-transform:uppercase;">VAT</th>
              </tr>
              {tc_rows}
            </table>
          </div>
        </div>
        '''
    else:
        ticket_classes_html = '''
        <div class="preview-section" style="margin-top:20px;">
          <div class="preview-section-header" style="background:linear-gradient(135deg, #7c3aed 0%, #a855f7 100%); color:white;">TYPY BILETÓW</div>
          <div class="preview-section-body">
            <div style="color:#94a3b8; text-align:center; padding:20px;">Brak skonfigurowanych typów biletów</div>
          </div>
        </div>
        '''

    # Statystyki wydarzeń (używane w nagłówku)
    stats = get_event_ticket_stats(event_id)
    orders_paid = stats["orders_by_status"].get("paid", {}).get("count", 0)
    orders_pending = stats["orders_by_status"].get("pending_payment", {}).get("count", 0)
    participants_emailed = stats["participants_by_status"].get("emailed", 0)
    participants_registered = stats["participants_by_status"].get("registered", 0)
    
    # Link do kalendarza (.ics) - tymczasowo ukryty
    calendar_html = ""

    body = f"""
    <style>
      .preview-container {{
        max-width: 980px;
        margin: 0 auto;
      }}
      .preview-section {{
        background: #fff;
        border: 2px solid #e2e8f0;
        border-radius: 16px;
        margin-bottom: 24px;
        overflow: hidden;
        box-shadow: 0 4px 12px rgba(0,0,0,0.06);
      }}
      .preview-section-header {{
        padding: 16px 20px;
        background: linear-gradient(135deg, #0065D7, #00A1D7);
        font-weight: 700;
        font-size: 17px;
        color: #ffffff;
        letter-spacing: 0.3px;
        text-transform: uppercase;
      }}
      .preview-section-body {{
        padding: 6px 0;
      }}
      .field-row {{
        display: grid;
        grid-template-columns: 240px 1fr;
        gap: 28px;
        padding: 16px 20px;
        border-bottom: 1px solid #f1f5f9;
        transition: background 0.2s;
      }}
      .field-row:hover {{
        background: #fafbfc;
      }}
      .field-row:last-child {{
        border-bottom: none;
      }}
      .field-label {{
        font-weight: 600;
        color: #334155;
        font-size: 15px;
        line-height: 1.4;
      }}
      .field-key {{
        display: block;
        font-size: 11px;
        color: #94a3b8;
        font-family: monospace;
        margin-top: 4px;
      }}
      .field-value {{
        color: #0f172a;
        font-size: 15px;
        word-break: break-word;
        line-height: 1.5;
      }}
      .toggle-tech-names {{
        display: inline-block;
        margin-left: 12px;
        padding: 4px 10px;
        font-size: 12px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        cursor: pointer;
        color: #64748b;
        transition: all 0.2s;
      }}
      .toggle-tech-names:hover {{
        background: #e2e8f0;
        color: #334155;
      }}
      @media (max-width: 900px) {{
        .field-row {{
          grid-template-columns: 1fr;
          gap: 8px;
        }}
      }}
    </style>
    
    <script>
      function toggleTechNames() {{
        const keys = document.querySelectorAll('.field-key');
        const btn = document.getElementById('toggleBtn');
        const isHidden = keys[0].style.display === 'none' || keys[0].style.display === '';
        
        keys.forEach(key => {{
          key.style.display = isHidden ? 'block' : 'none';
        }});
        
        btn.textContent = isHidden ? '🔒 Ukryj nazwy API' : '🔓 Pokaż nazwy API';
      }}
    </script>
    
    <div style="margin-bottom:20px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
      <div style="display:flex; gap:10px;">
        {'<a class="btn" href="' + url_for('admin_bp.event_edit', event_id=event_id, token=token) + '">← Wróć do edycji</a>' if not is_viewer else ''}
        <a class="btn" href="{url_for('admin_bp.events_list', token=token)}">← Lista wydarzeń</a>
        {'<span class="pill" style="background:#e0f2fe; color:#0369a1;">Tryb podglądu</span>' if is_viewer else ''}
      </div>
      {'<button id="toggleBtn" onclick="toggleTechNames()" class="toggle-tech-names">🔓 Pokaż nazwy API</button>' if not is_viewer else ''}
    </div>
    
    <div class="preview-container">
      <div class="card" style="margin-top:20px; border:2px solid {color1 or '#0065D7'}; overflow:hidden;">
        <div style="text-align:center; padding:20px 24px 16px; background:{header_bg};">
          <div style="font-weight:700; font-size:22px; color:#ffffff; text-shadow:0 1px 2px rgba(0,0,0,0.15);">{event_name}</div>
          {'<div style="margin-top:6px; color:#e2e8f0;"><code style="font-size:12px; background:rgba(255,255,255,0.15); color:#ffffff; border:1px solid rgba(255,255,255,0.25); padding:2px 6px; border-radius:6px;">' + event_id + '</code></div>' if not is_viewer else ''}
        </div>
        <div style="display:grid; grid-template-columns: repeat(3, 1fr); border-top:1px solid #e2e8f0;">
          <div style="padding:20px; text-align:center; border-right:1px solid #e2e8f0;">
            <div style="font-size:32px; font-weight:700; color:{color1 or '#0065D7'};">{stats['orders_total']}</div>
            <div style="font-size:13px; color:#64748b; font-weight:500;">Zamówień</div>
            <div style="font-size:11px; color:#94a3b8; margin-top:2px;">{orders_paid} opłaconych</div>
          </div>
          <div style="padding:20px; text-align:center; border-right:1px solid #e2e8f0;">
            <div style="font-size:32px; font-weight:700; color:#16a34a;">{stats['participants_total']}</div>
            <div style="font-size:13px; color:#64748b; font-weight:500;">Uczestników</div>
            <div style="font-size:11px; color:#94a3b8; margin-top:2px;">{participants_emailed} powiadomionych</div>
          </div>
          <div style="padding:20px; text-align:center;">
            <div style="font-size:32px; font-weight:700; color:#059669;">{stats['revenue_paid']:.0f}<span style="font-size:16px; font-weight:500;"> PLN</span></div>
            <div style="font-size:13px; color:#64748b; font-weight:500;">Przychód</div>
            <div style="font-size:11px; color:#94a3b8; margin-top:2px;">z opłaconych</div>
          </div>
        </div>
        <div style="padding:12px 20px; background:#f8fafc; border-top:1px solid #e2e8f0; text-align:center;">
          <a href="{url_for('admin_bp.event_tickets', event_id=event_id, token=token)}" class="btn btnPrimary" style="font-size:13px;">Zobacz szczegóły biletów →</a>
        </div>
      </div>
      
      {backstage_html if not is_viewer else ''}
      
      {ticket_classes_html}
      
      {calendar_html}
      
      {sections_html}
    </div>
    """
    return _page("Podgląd wydarzenia", body)


@admin_bp.route("/events/<event_id>/preview", methods=["GET"])
@_require_permission("events")
def event_preview(event_id: str):
    token = _require_admin_token()
    current_user = _get_current_admin_user()
    
    # Sprawdź dostęp viewera do tego wydarzenia
    if _is_viewer(current_user) and not _user_can_access_event(current_user, event_id):
        abort(403, description="Brak dostępu do tego wydarzenia")
    
    ev = get_event(event_id)
    if not ev:
        abort(404, description="Nie znaleziono eventu")

    data = ev.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    is_viewer = _is_viewer(current_user)
    return _render_event_preview(
        token=token,
        event_id=str(ev.get("event_id") or event_id),
        event_name=str(ev.get("event_name") or ""),
        data=data,
        is_viewer=is_viewer,
    )


@admin_bp.route("/events/preview-draft", methods=["POST"])
@_require_permission("events")
def preview_draft():
    """Podgląd bez zapisu – przydatne dla marketingu."""
    token = _require_admin_token()

    event_id = (request.form.get("event_id") or "").strip()
    event_name = (request.form.get("event_name") or "").strip()
    if not event_id or not event_name:
        abort(400, description="Wymagane: event_id i event_name")

    data: Dict[str, Any] = {}
    data_json = (request.form.get("data_json") or "").strip()
    kv_paste = (request.form.get("kv_paste") or "").strip()
    if data_json:
        parsed, err = _safe_json_loads(data_json)
        if not err and isinstance(parsed, dict):
            data = parsed
    if kv_paste:
        data.update(parse_kv_lines(kv_paste))
    for fd in FIELD_DEFS:
        k = fd["key"]
        data[k] = (request.form.get(_field_name(k)) or "").strip()

    if not data.get("eventId"):
        data["eventId"] = event_id
    if not data.get("eventName"):
        data["eventName"] = event_name

    return _render_event_preview(token=token, event_id=event_id, event_name=event_name, data=data)


def _render_ticket_classes_section(tickets: List[Dict[str, Any]]) -> str:
    """Renderuje sekcję z typami biletów (do podglądu/edycji)."""
    if not tickets:
        return '''
        <div class="card" style="margin-top:20px;">
          <div style="font-weight:700; margin-bottom:10px; color:#7c3aed;">🎫 Typy biletów</div>
          <div class="muted">Brak skonfigurowanych typów biletów</div>
        </div>
        '''
    
    tc_rows = ""
    for tc in tickets:
        tc_id = tc.get("ticket_class_id", "")
        tc_name = tc.get("ticket_name", "")
        tc_data = tc.get("data") or {}
        tc_price = tc_data.get("ticket_price") or tc_data.get("price") or "—"
        tc_vat = tc_data.get("vat_rate") or tc_data.get("vat") or "—"
        tc_rows += f'''
        <tr>
          <td style="padding:10px 12px; border-bottom:1px solid #e2e8f0; font-size:11px;"><code style="background:#f1f5f9; padding:2px 6px; border-radius:4px;">{tc_id}</code></td>
          <td style="padding:10px 12px; border-bottom:1px solid #e2e8f0; font-weight:500;">{tc_name}</td>
          <td style="padding:10px 12px; border-bottom:1px solid #e2e8f0; text-align:right;">{tc_price} PLN</td>
          <td style="padding:10px 12px; border-bottom:1px solid #e2e8f0; text-align:right;">{tc_vat}%</td>
        </tr>
        '''
    
    return f'''
    <div class="card" style="margin-top:20px; border:2px solid #a855f7;">
      <div style="font-weight:700; margin-bottom:12px; color:#7c3aed; display:flex; justify-content:space-between; align-items:center;">
        <span>🎫 Typy biletów ({len(tickets)})</span>
        <span style="font-size:12px; color:#94a3b8; font-weight:400;">Edycja poniżej w sekcji "Typy biletów"</span>
      </div>
      <table style="width:100%; border-collapse:collapse; font-size:14px;">
        <tr style="background:#f8fafc;">
          <th style="padding:8px 12px; text-align:left; font-weight:600; font-size:11px; color:#64748b; text-transform:uppercase;">ticket_class_id</th>
          <th style="padding:8px 12px; text-align:left; font-weight:600; font-size:11px; color:#64748b; text-transform:uppercase;">Nazwa</th>
          <th style="padding:8px 12px; text-align:right; font-weight:600; font-size:11px; color:#64748b; text-transform:uppercase;">Cena netto</th>
          <th style="padding:8px 12px; text-align:right; font-weight:600; font-size:11px; color:#64748b; text-transform:uppercase;">VAT</th>
        </tr>
        {tc_rows}
      </table>
    </div>
    '''


def _event_form_page(token: str, event: Optional[Dict[str, Any]], tickets: List[Dict[str, Any]]) -> str:
    is_new = event is None
    event_id = "" if is_new else (event.get("event_id") or "")
    event_name = "" if is_new else (event.get("event_name") or "")
    status = "" if is_new else (event.get("status") or "")
    notes = "" if is_new else (event.get("notes") or "")
    data = {} if is_new else (event.get("data") or {})
    if not isinstance(data, dict):
        data = {}

    # Ticket classes -> JSON array (proste do wklejenia)
    ticket_classes_payload: List[Dict[str, Any]] = []
    for t in tickets or []:
        ticket_classes_payload.append(
            {
                "ticket_class_id": t.get("ticket_class_id"),
                "ticket_name": t.get("ticket_name"),
                "data": t.get("data") or {},
            }
        )
    ticket_classes_json = json.dumps(ticket_classes_payload, ensure_ascii=False, indent=2)

    data_json = json.dumps(data, ensure_ascii=False, indent=2)

    # Prefill wartości pól
    field_values: Dict[str, str] = {}
    for fd in FIELD_DEFS:
        k = fd["key"]
        v = data.get(k)
        field_values[k] = (str(v) if v is not None else "")

    fields_html = []
    for fd in FIELD_DEFS:
        k = fd["key"]
        # eventId jest edytowany wyłącznie w polu głównym (na górze)
        if k == "eventId":
            continue
        label = fd["label"]
        hint = fd.get("hint", "")
        kind = fd.get("kind", "text")
        raw_val = field_values.get(k) or ""
        safe_val = raw_val.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        
        # Podgląd dla kolorów
        color_preview = ""
        if kind == "color":
            color_preview = f'<div id="preview_{k}" class="color-preview" style="width:60px; height:36px; border-radius:8px; border:1px solid #e5e7eb; margin-top:8px; background:{raw_val if _is_hex_color(raw_val) else "#fff"};"></div>'
        
        # Podgląd dla obrazów (URL)
        image_preview = ""
        if kind == "url" and raw_val and any(ext in raw_val.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']):
            image_preview = f'<div id="preview_{k}" class="image-preview" style="margin-top:8px;"><img src="{raw_val}" style="max-width:100%; height:auto; max-height:120px; border-radius:8px; border:1px solid #e5e7eb;" onerror="this.parentElement.style.display=\'none\'" /></div>'
        elif kind == "url":
            image_preview = f'<div id="preview_{k}" class="image-preview" style="margin-top:8px; display:none;"></div>'
        
        fields_html.append(
            f"""
            <div class="formLabel">{label}<div class="formHint"><code>{k}</code></div></div>
            <div>
              <input type="text" name="{_field_name(k)}" value="{safe_val}" placeholder="{hint}" data-field-key="{k}" data-field-kind="{kind}" oninput="updatePreview(this)" />
              {color_preview}
              {image_preview}
            </div>
            """
        )

    # Edytor typów biletów (tabela)
    ticket_editor_rows = ""
    for t in tickets or []:
        tc_id = str(t.get("ticket_class_id") or "")
        tc_name = str(t.get("ticket_name") or "")
        tc_data = t.get("data") or {}
        tc_price = tc_data.get("ticket_price")
        if tc_price is None:
            tc_price = tc_data.get("price")
        if tc_price is None:
            tc_price = ""
        tc_vat = tc_data.get("vat_rate")
        if tc_vat is None:
            tc_vat = tc_data.get("vat")
        if tc_vat is None:
            tc_vat = ""
        tc_data_json = json.dumps(tc_data, ensure_ascii=False)

        safe_tc_id = tc_id.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        safe_tc_name = tc_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        safe_tc_price = str(tc_price).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        safe_tc_vat = str(tc_vat).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        safe_tc_data_json = tc_data_json.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

        ticket_editor_rows += f"""
        <tr class="ticket-class-row">
          <td style="padding:8px; border-bottom:1px solid #e2e8f0;">
            <input type="text" name="ticket_class_id" value="{safe_tc_id}" placeholder="ID z Backstage" style="width:100%; font-family:monospace; font-size:12px;" />
          </td>
          <td style="padding:8px; border-bottom:1px solid #e2e8f0;">
            <input type="text" name="ticket_class_name" value="{safe_tc_name}" placeholder="Nazwa biletu" style="width:100%;" />
          </td>
          <td style="padding:8px; border-bottom:1px solid #e2e8f0; text-align:right;">
            <input type="text" name="ticket_class_price" value="{safe_tc_price}" placeholder="np. 399.00" style="width:100%; text-align:right;" />
          </td>
          <td style="padding:8px; border-bottom:1px solid #e2e8f0; text-align:right;">
            <input type="text" name="ticket_class_vat" value="{safe_tc_vat}" placeholder="np. 23" style="width:100%; text-align:right;" />
            <input type="hidden" name="ticket_class_data_json" value="{safe_tc_data_json}" />
          </td>
          <td style="padding:8px; border-bottom:1px solid #e2e8f0; text-align:right; width:90px;">
            <button type="button" class="btn btnDanger" style="padding:4px 8px; font-size:11px;" onclick="removeTicketRow(this)">Usuń</button>
          </td>
        </tr>
        """

    if not ticket_editor_rows:
        ticket_editor_rows = """
        <tr class="ticket-class-row">
          <td style="padding:8px; border-bottom:1px solid #e2e8f0;">
            <input type="text" name="ticket_class_id" value="" placeholder="ID z Backstage" style="width:100%; font-family:monospace; font-size:12px;" />
          </td>
          <td style="padding:8px; border-bottom:1px solid #e2e8f0;">
            <input type="text" name="ticket_class_name" value="" placeholder="Nazwa biletu" style="width:100%;" />
          </td>
          <td style="padding:8px; border-bottom:1px solid #e2e8f0; text-align:right;">
            <input type="text" name="ticket_class_price" value="" placeholder="np. 399.00" style="width:100%; text-align:right;" />
          </td>
          <td style="padding:8px; border-bottom:1px solid #e2e8f0; text-align:right;">
            <input type="text" name="ticket_class_vat" value="" placeholder="np. 23" style="width:100%; text-align:right;" />
            <input type="hidden" name="ticket_class_data_json" value="{}" />
          </td>
          <td style="padding:8px; border-bottom:1px solid #e2e8f0; text-align:right; width:90px;">
            <button type="button" class="btn btnDanger" style="padding:4px 8px; font-size:11px;" onclick="removeTicketRow(this)">Usuń</button>
          </td>
        </tr>
        """

    preview_link = ""
    rules_link = ""
    tickets_link = ""
    if event_id:
        preview_link = f'<a class="btn" href="{url_for("admin_bp.event_preview", event_id=event_id, token=token)}">Podgląd</a>'
        rules_link = f'<a class="btn" style="background:#e3f2fd;" href="{url_for("admin_bp.payment_rules_list", event_id=event_id, token=token)}">Reguły płatności</a>'
        tickets_link = f'<a class="btn" style="background:#d1fae5;" href="{url_for("admin_bp.event_tickets", event_id=event_id, token=token)}">Bilety</a>'

    delete_form = ""
    if event_id:
        delete_form = f"""
        <form method="post" action="{url_for('admin_bp.event_delete', event_id=event_id)}" onsubmit="return confirm('Usunąć wydarzenie {event_id}?');" style="display:inline;">
          <input type="hidden" name="token" value="{token}" />
          <button class="btn btnDanger" type="submit">Usuń</button>
        </form>
        """

    body = f"""
    <div style="margin-bottom:12px;">
      <a class="btn" href="{url_for('admin_bp.events_list', token=token)}">← Lista wydarzeń</a>
      {preview_link}
      {rules_link}
      {tickets_link}
      {delete_form}
    </div>

    <div class="grid-edit">
      
      <!-- LEWA KOLUMNA: FORMULARZ -->
      <div>
        <form id="event-form" method="post" action="{url_for('admin_bp.event_save')}">
          <input type="hidden" name="token" value="{token}" />
          
          <!-- SEKCJA 1: DANE WYDARZENIA -->
          <details class="styled-section" open>
            <summary>1. Dane wydarzenia i konfiguracja</summary>
            <div class="section-content">
              
              <div class="formGrid">
                <div class="formLabel">ID wydarzenia (Backstage)</div>
                <div>
                  <input type="text" name="event_id" value="{event_id}" placeholder="np. 24311000000651079" {'readonly' if (not is_new) else ''} style="font-family:monospace; background:{'#f1f5f9' if not is_new else '#fff'};" />
                </div>

                <div class="formLabel">Nazwa wydarzenia</div>
                <div>
                  <input type="text" name="event_name" value="{event_name}" placeholder="np. Dental Practice Academy" style="font-weight:600;" />
                </div>

                <div class="formLabel">Status (opcjonalnie)</div>
                <div>
                  <input type="text" name="status" value="{status}" placeholder="np. w systemie" />
                </div>

                <div class="formLabel">Notatki (opcjonalnie)</div>
                <div>
                  <input type="text" name="notes" value="{notes}" placeholder="np. DPA" />
                </div>
              </div>
              
              <div style="margin: 24px 0 16px 0; border-bottom:1px solid #e2e8f0;"></div>
              <div style="font-size:12px; font-weight:700; color:#64748b; margin-bottom:12px; text-transform:uppercase;">Pola marketingowe</div>

              <div class="formGrid">
                {''.join(fields_html)}
              </div>
            </div>
          </details>

          <!-- SEKCJA 2: BILETY -->
          <details class="styled-section" open>
            <summary>2. Konfiguracja biletów</summary>
            <div class="section-content" style="padding:0;">
              <div style="padding:16px; background:#f8fafc; border-bottom:1px solid #e2e8f0; font-size:13px; color:#64748b;">
                Zdefiniuj typy biletów, które mają być obsługiwane. ID musi zgadzać się z tym w Backstage.
              </div>
              
              <table id="ticket-classes-table" class="tickets-table">
                <thead>
                  <tr>
                    <th style="width:25%;">ID biletu (Backstage)</th>
                    <th style="width:35%;">Nazwa (dla klienta)</th>
                    <th style="width:15%; text-align:right;">Cena netto</th>
                    <th style="width:10%; text-align:right;">VAT %</th>
                    <th style="width:15%; text-align:center;">Akcje</th>
                  </tr>
                </thead>
                <tbody>
                  {ticket_editor_rows}
                </tbody>
              </table>
              
              <div style="padding:16px; background:#f8fafc; border-top:1px solid #e2e8f0; display:flex; gap:12px;">
                <button class="btn" type="button" onclick="addTicketRow()">+ Dodaj nowy bilet</button>
                <button class="btn" type="button" onclick="syncTicketClassesJson()" style="margin-left:auto; font-size:12px; opacity:0.7;">⟳ Aktualizuj JSON</button>
              </div>
            </div>
          </details>

          <!-- SEKCJA 3: ZAAWANSOWANE -->
          <details class="styled-section">
            <summary>3. Zaawansowane (JSON)</summary>
            <div class="section-content">
              <div class="muted">Pełny obiekt JSON (edycja ręczna tylko dla technicznych):</div>
              <textarea name="data_json" style="font-family:monospace; font-size:12px; height:150px;">{data_json}</textarea>
              
              <div style="height:16px;"></div>
              
              <div class="muted">Szybkie wklejanie (key TAB value):</div>
              <textarea name="kv_paste" placeholder="event_location_place<TAB>Regent Warsaw Hotel" style="height:80px;"></textarea>
              
              <div style="height:16px;"></div>
              
              <div class="muted">JSON biletów (generowany automatycznie z tabeli powyżej):</div>
              <textarea id="ticket_classes_json" name="ticket_classes_json" style="font-family:monospace; font-size:12px; height:100px; background:#f1f5f9;" readonly>{ticket_classes_json}</textarea>
            </div>
          </details>

          <!-- AKCJE -->
          <div style="display:flex; gap:16px; align-items:center; margin-top:24px; padding: 20px; background:#fff; border:1px solid #e2e8f0; border-radius:8px; box-shadow:0 2px 4px rgba(0,0,0,0.05); position:sticky; bottom:20px; z-index:10;">
            <button class="btn btnPrimary" type="submit" style="padding:10px 24px; font-size:14px;">Zapisz zmiany</button>
            <button class="btn" type="submit" formaction="{url_for('admin_bp.preview_draft')}" formmethod="post">Podgląd (bez zapisu)</button>
            <div style="margin-left:auto; font-size:12px; color:#64748b;">
              Ostatnia zmiana zapisuje wszystkie sekcje.
            </div>
          </div>

        </form>
      </div>

      <!-- PRAWA KOLUMNA: INSTRUKCJA -->
      <div class="card" style="height:fit-content; position:sticky; top:20px;">
        <div style="font-weight:700; margin-bottom:10px; color:#334155;">Instrukcja</div>
        <div class="muted" style="line-height:1.5;">
          <ol style="padding-left:16px; margin:0;">
            <li style="margin-bottom:6px;">Wypełnij <b>Dane wydarzenia</b>.</li>
            <li style="margin-bottom:6px;">Skonfiguruj <b>Bilety</b> w tabeli.</li>
            <li style="margin-bottom:6px;">Linki zawsze zaczynaj od <code>https://</code>.</li>
            <li style="margin-bottom:6px;">Kolory jako hex, np. <code>#269571</code>.</li>
          </ol>
          <div style="margin-top:12px; padding-top:12px; border-top:1px solid #e2e8f0;">
            Użyj przycisku <b>Podgląd</b>, aby sprawdzić banery i linki przed zapisaniem.
          </div>
        </div>
      </div>
    
    </div>
    
    <script>
      let ticketJsonManualEdit = false;
      let ticketTableEdited = false;

      // Synchronizacja event_id ↔ eventId oraz event_name ↔ eventName
      (function() {{
        const eventIdMain = document.querySelector('input[name="event_id"]');
        const eventIdField = document.querySelector('input[name="field__eventId"]');
        const eventNameMain = document.querySelector('input[name="event_name"]');
        const eventNameField = document.querySelector('input[name="field__eventName"]');
        
        // Synchronizacja event_id → eventId (główne → marketingowe)
        if (eventIdMain && eventIdField) {{
          eventIdMain.addEventListener('input', function() {{
            eventIdField.value = this.value;
          }});
          // Synchronizacja eventId → event_id (marketingowe → główne) - tylko jeśli główne jest edytowalne
          if (!eventIdMain.hasAttribute('readonly')) {{
            eventIdField.addEventListener('input', function() {{
              eventIdMain.value = this.value;
            }});
          }}
        }}
        
        // Synchronizacja event_name → eventName
        if (eventNameMain && eventNameField) {{
          eventNameMain.addEventListener('input', function() {{
            eventNameField.value = this.value;
          }});
          eventNameField.addEventListener('input', function() {{
            eventNameMain.value = this.value;
          }});
        }}
      }})();

      function updatePreview(input) {{
        const key = input.getAttribute('data-field-key');
        const kind = input.getAttribute('data-field-kind');
        const value = input.value.trim();
        const previewEl = document.getElementById('preview_' + key);
        
        if (!previewEl) return;
        
        if (kind === 'color') {{
          // Walidacja koloru hex
          const isValidColor = /^#[0-9A-Fa-f]{{6}}$/.test(value);
          if (isValidColor) {{
            previewEl.style.background = value;
            previewEl.style.display = 'block';
          }} else {{
            previewEl.style.background = '#fff';
          }}
        }} else if (kind === 'url') {{
          // Sprawdź czy to link do obrazka
          const isImageUrl = value && /\\.(jpg|jpeg|png|gif|webp|svg)(\\?.*)?$/i.test(value);
          if (isImageUrl && value.startsWith('http')) {{
            previewEl.innerHTML = '<img src="' + value + '" style="max-width:100%; height:auto; max-height:120px; border-radius:8px; border:1px solid #e5e7eb;" onerror="this.parentElement.style.display=\\'none\\'" />';
            previewEl.style.display = 'block';
          }} else {{
            previewEl.style.display = 'none';
          }}
        }}
      }}

      function parseNumberValue(value) {{
        const raw = (value || '').trim();
        if (!raw) return null;
        const normalized = raw.replace(',', '.');
        const num = Number(normalized);
        return Number.isFinite(num) ? num : raw;
      }}

      function syncTicketClassesJson() {{
        const rows = document.querySelectorAll('#ticket-classes-table tbody .ticket-class-row');
        const list = [];
        rows.forEach((row) => {{
          const idEl = row.querySelector('input[name="ticket_class_id"]');
          const nameEl = row.querySelector('input[name="ticket_class_name"]');
          const priceEl = row.querySelector('input[name="ticket_class_price"]');
          const vatEl = row.querySelector('input[name="ticket_class_vat"]');
          const dataEl = row.querySelector('input[name="ticket_class_data_json"]');

          const ticketClassId = (idEl ? idEl.value.trim() : '');
          const ticketName = (nameEl ? nameEl.value.trim() : '');
          const priceRaw = (priceEl ? priceEl.value.trim() : '');
          const vatRaw = (vatEl ? vatEl.value.trim() : '');
          const dataRaw = (dataEl ? dataEl.value.trim() : '');

          if (!ticketClassId && !ticketName && !priceRaw && !vatRaw) {{
            return;
          }}

          let data = {{}};
          if (dataRaw) {{
            try {{
              data = JSON.parse(dataRaw);
            }} catch (e) {{
              data = {{}};
            }}
          }}

          if (priceRaw) {{
            data['ticket_price'] = parseNumberValue(priceRaw);
            if ('price' in data) delete data['price'];
          }} else {{
            if ('ticket_price' in data) delete data['ticket_price'];
            if ('price' in data) delete data['price'];
          }}

          if (vatRaw) {{
            data['vat_rate'] = parseNumberValue(vatRaw);
            if ('vat' in data) delete data['vat'];
          }} else {{
            if ('vat_rate' in data) delete data['vat_rate'];
            if ('vat' in data) delete data['vat'];
          }}

          list.push({{
            ticket_class_id: ticketClassId,
            ticket_name: ticketName,
            data: data
          }});
        }});

        const textarea = document.getElementById('ticket_classes_json');
        if (textarea) {{
          textarea.value = JSON.stringify(list, null, 2);
          ticketJsonManualEdit = false;
          ticketTableEdited = true;
        }}
      }}

      function addTicketRow() {{
        const tbody = document.querySelector('#ticket-classes-table tbody');
        if (!tbody) return;
        const row = document.createElement('tr');
        row.className = 'ticket-class-row';
        row.innerHTML = `
          <td style="padding:8px; border-bottom:1px solid #e2e8f0;">
            <input type="text" name="ticket_class_id" value="" placeholder="ID z Backstage" style="width:100%; font-family:monospace; font-size:12px;" />
          </td>
          <td style="padding:8px; border-bottom:1px solid #e2e8f0;">
            <input type="text" name="ticket_class_name" value="" placeholder="Nazwa biletu" style="width:100%;" />
          </td>
          <td style="padding:8px; border-bottom:1px solid #e2e8f0; text-align:right;">
            <input type="text" name="ticket_class_price" value="" placeholder="np. 399.00" style="width:100%; text-align:right;" />
          </td>
          <td style="padding:8px; border-bottom:1px solid #e2e8f0; text-align:right;">
            <input type="text" name="ticket_class_vat" value="" placeholder="np. 23" style="width:100%; text-align:right;" />
            <input type="hidden" name="ticket_class_data_json" value="{{}}" />
          </td>
          <td style="padding:8px; border-bottom:1px solid #e2e8f0; text-align:right; width:90px;">
            <button type="button" class="btn btnDanger" style="padding:4px 8px; font-size:11px;" onclick="removeTicketRow(this)">Usuń</button>
          </td>
        `;
        tbody.appendChild(row);
        ticketTableEdited = true;
      }}

      function removeTicketRow(btn) {{
        const row = btn && btn.closest ? btn.closest('tr') : null;
        if (row && row.parentElement) {{
          row.parentElement.removeChild(row);
        }}
        ticketTableEdited = true;
      }}

      const ticketJsonTextarea = document.getElementById('ticket_classes_json');
      if (ticketJsonTextarea) {{
        ticketJsonTextarea.addEventListener('input', function() {{
          ticketJsonManualEdit = true;
          ticketTableEdited = false;
        }});
      }}

      const ticketTable = document.getElementById('ticket-classes-table');
      if (ticketTable) {{
        ticketTable.addEventListener('input', function() {{
          ticketJsonManualEdit = false;
          ticketTableEdited = true;
        }});
      }}

      const eventForm = document.getElementById('event-form');
      if (eventForm) {{
        eventForm.addEventListener('submit', function() {{
          if (!ticketJsonManualEdit || ticketTableEdited) {{
            syncTicketClassesJson();
          }}
        }});
      }}
    </script>
    """
    return _page("Edytuj wydarzenie" if not is_new else "Nowe wydarzenie", body)


# ---------------------------------------------------------------------------
# EVENT TICKETS / PARTICIPANTS VIEW
# ---------------------------------------------------------------------------


@admin_bp.route("/events/<event_id>/tickets", methods=["GET"])
@_require_permission("events")
def event_tickets(event_id: str):
    """Widok biletów i uczestników dla wydarzenia."""
    token = _require_admin_token()
    current_user = _get_current_admin_user()
    is_viewer = _is_viewer(current_user)
    
    # Sprawdź dostęp viewera do tego wydarzenia
    if is_viewer and not _user_can_access_event(current_user, event_id):
        abort(403, description="Brak dostępu do tego wydarzenia")
    
    ev = get_event(event_id)
    if not ev:
        abort(404, description="Nie znaleziono eventu")

    event_data = ev.get("data") or {}
    color1 = event_data.get("color_gradient_1") or "#0065D7"
    color2 = event_data.get("color_gradient_2") or ""
    header_bg = f"linear-gradient(135deg, {color1} 0%, {color2} 100%)" if color2 else color1

    # Pobierz dane
    ticket_classes = get_ticket_classes(event_id)
    stats = get_event_ticket_stats(event_id)
    participants = get_participants_for_event(event_id)

    # Status pill colors
    STATUS_COLORS = {
        "paid": ("Opłacone", "#dcfce7", "#166534"),
        "pending_payment": ("Oczekuje", "#fef9c3", "#854d0e"),
        "received": ("Otrzymane", "#e0f2fe", "#0369a1"),
        "failed": ("Błąd", "#fee2e2", "#991b1b"),
        "cancelled": ("Anulowane", "#f3f4f6", "#6b7280"),
        "registered": ("Zarejestrowany", "#e0f2fe", "#0369a1"),
        "emailed": ("Powiadomiony", "#dcfce7", "#166534"),
        "pending": ("Oczekuje", "#fef9c3", "#854d0e"),
    }

    def status_pill(status: str) -> str:
        label, bg, color = STATUS_COLORS.get(status, (status, "#f3f4f6", "#6b7280"))
        return f'<span class="pill" style="background:{bg}; color:{color};">{label}</span>'

    # Sekcja 1: Statystyki
    orders_paid = stats["orders_by_status"].get("paid", {}).get("count", 0)
    orders_pending = stats["orders_by_status"].get("pending_payment", {}).get("count", 0)
    orders_received = stats["orders_by_status"].get("received", {}).get("count", 0)
    orders_failed = stats["orders_by_status"].get("failed", {}).get("count", 0)
    
    participants_emailed = stats["participants_by_status"].get("emailed", 0)
    participants_registered = stats["participants_by_status"].get("registered", 0)
    participants_pending = stats["participants_by_status"].get("pending", 0)

    stats_html = f"""
    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:16px; margin-bottom:24px;">
      <div class="card" style="text-align:center;">
        <div style="font-size:32px; font-weight:700; color:#0369a1;">{stats['orders_total']}</div>
        <div class="muted">Zamówień łącznie</div>
        <div style="font-size:12px; margin-top:8px;">
          {status_pill('paid')} {orders_paid} |
          {status_pill('pending_payment')} {orders_pending} |
          {status_pill('received')} {orders_received}
        </div>
      </div>
      <div class="card" style="text-align:center;">
        <div style="font-size:32px; font-weight:700; color:#166534;">{stats['participants_total']}</div>
        <div class="muted">Uczestników łącznie</div>
        <div style="font-size:12px; margin-top:8px;">
          {status_pill('emailed')} {participants_emailed} |
          {status_pill('registered')} {participants_registered} |
          {status_pill('pending')} {participants_pending}
        </div>
      </div>
      <div class="card" style="text-align:center;">
        <div style="font-size:32px; font-weight:700; color:#059669;">{stats['revenue_paid']:.2f} PLN</div>
        <div class="muted">Przychód (opłacone)</div>
      </div>
    </div>
    """

    # Sekcja 2: Klasy biletów (bez danych technicznych)
    ticket_rows = []
    for tc in ticket_classes:
        tc_id = tc.get("ticket_class_id", "")
        tc_name = tc.get("ticket_name", "") or tc.get("data", {}).get("name", "") or "—"
        ticket_rows.append(f"""
            <tr>
              <td><code>{tc_id}</code></td>
              <td>{tc_name}</td>
            </tr>
        """)

    tickets_html = f"""
    <div class="card" style="margin-bottom:24px;">
      <div style="font-weight:700; margin-bottom:12px;">Klasy biletów ({len(ticket_classes)})</div>
      <table style="width:100%; border-collapse:collapse; font-size:14px;">
        <thead>
          <tr style="background:#f8fafc;">
            <th style="padding:8px; text-align:left; border-bottom:1px solid #e5e7eb;">ID klasy</th>
            <th style="padding:8px; text-align:left; border-bottom:1px solid #e5e7eb;">Nazwa</th>
          </tr>
        </thead>
        <tbody>
          {''.join(ticket_rows) if ticket_rows else '<tr><td colspan="2" class="muted" style="padding:16px; text-align:center;">Brak klas biletów</td></tr>'}
        </tbody>
      </table>
    </div>
    """

    # Sekcja 3: Lista uczestników
    participant_rows = []
    for p in participants[:200]:  # Limit do 200 dla wydajności
        p_email = p.get("email") or p.get("purchaser_email") or "—"
        p_name = f"{p.get('first_name') or ''} {p.get('last_name') or ''}".strip() or "—"
        p_phone = p.get("phone") or "—"
        p_ticket_class = p.get("ticket_class_id") or "—"
        p_status = p.get("status") or "—"
        p_order = p.get("event_order_id") or "—"
        order_url = url_for('admin_bp.order_detail', order_id=p_order, token=token)
        
        participant_rows.append(f"""
            <tr>
              <td style="padding:8px; border-bottom:1px solid #f1f5f9;">{p_email}</td>
              <td style="padding:8px; border-bottom:1px solid #f1f5f9;">{p_name}</td>
              <td style="padding:8px; border-bottom:1px solid #f1f5f9;">{p_phone}</td>
              <td style="padding:8px; border-bottom:1px solid #f1f5f9;"><code>{p_ticket_class}</code></td>
              <td style="padding:8px; border-bottom:1px solid #f1f5f9;">{status_pill(p_status)}</td>
              <td style="padding:8px; border-bottom:1px solid #f1f5f9;"><a href="{order_url}" style="color:#0369a1;">{p_order[:12]}...</a></td>
            </tr>
        """)

    participants_html = f"""
    <div class="card">
      <div style="font-weight:700; margin-bottom:12px;">Uczestnicy ({len(participants)}{' — pokazano 200' if len(participants) > 200 else ''})</div>
      <div style="overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse; font-size:14px; min-width:700px;">
          <thead>
            <tr style="background:#f8fafc;">
              <th style="padding:8px; text-align:left; border-bottom:2px solid #e5e7eb;">Email</th>
              <th style="padding:8px; text-align:left; border-bottom:2px solid #e5e7eb;">Imię Nazwisko</th>
              <th style="padding:8px; text-align:left; border-bottom:2px solid #e5e7eb;">Telefon</th>
              <th style="padding:8px; text-align:left; border-bottom:2px solid #e5e7eb;">Klasa biletu</th>
              <th style="padding:8px; text-align:left; border-bottom:2px solid #e5e7eb;">Status</th>
              <th style="padding:8px; text-align:left; border-bottom:2px solid #e5e7eb;">Zamówienie</th>
            </tr>
          </thead>
          <tbody>
            {''.join(participant_rows) if participant_rows else '<tr><td colspan="6" class="muted" style="padding:16px; text-align:center;">Brak uczestników</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>
    """

    body = f"""
    <div style="margin-bottom:12px;">
      <a class="btn" href="{url_for('admin_bp.event_preview' if is_viewer else 'admin_bp.event_edit', event_id=event_id, token=token)}">← Wróć do eventu</a>
      <a class="btn" href="{url_for('admin_bp.events_list', token=token)}">Lista wydarzeń</a>
      {'<span class="pill" style="background:#e0f2fe; color:#0369a1; margin-left:auto;">Tryb podglądu</span>' if is_viewer else ''}
    </div>

    <div class="card" style="margin-bottom:16px; border:2px solid {color1}; overflow:hidden;">
      <div style="padding:16px 20px; background:{header_bg};">
        <div style="font-weight:700; font-size:18px; color:#ffffff;">{ev.get('event_name', '')}</div>
        <div style="margin-top:6px; color:#e2e8f0;">
          <code style="font-size:12px; background:rgba(255,255,255,0.15); color:#ffffff; border:1px solid rgba(255,255,255,0.25); padding:2px 6px; border-radius:6px;">{event_id}</code>
        </div>
      </div>
    </div>

    {stats_html}
    {tickets_html}
    {participants_html}
    """
    return _page(f"Bilety – {ev.get('event_name', '')}", body)


# ---------------------------------------------------------------------------
# PAYMENT RULES MANAGEMENT
# ---------------------------------------------------------------------------

FLOW_OPTIONS = ["FOC", "PROFORMA", "STRIPE"]
WFIRMA_DOC_TYPES = ["proforma", "normal", "proforma_bill"]


@admin_bp.route("/events/<event_id>/rules", methods=["GET"])
@_require_permission("events")
def payment_rules_list(event_id: str):
    """Lista reguł płatności dla eventu."""
    token = _require_admin_token()
    current_user = _get_current_admin_user()
    is_viewer = _is_viewer(current_user)
    
    # Sprawdź dostęp viewera do tego wydarzenia
    if is_viewer and not _user_can_access_event(current_user, event_id):
        abort(403, description="Brak dostępu do tego wydarzenia")
    
    ev = get_event(event_id)
    if not ev:
        abort(404, description="Nie znaleziono eventu")

    rules = list_payment_rules(event_id)

    rows = []
    for r in rules:
        flow = r.get("flow", "")
        flow_class = {
            "FOC": "background:#ecfdf3;",
            "PROFORMA": "background:#fff8e1;",
            "STRIPE": "background:#e3f2fd;",
        }.get(flow, "")

        pattern = r.get("payment_option_name_pattern") or ""
        ptype = r.get("payment_type")
        is_default = r.get("is_default")

        match_desc = []
        if pattern:
            match_desc.append(f'nazwa zawiera: <code>{pattern}</code>')
        if ptype is not None:
            match_desc.append(f'payment_type = <code>{ptype}</code>')
        if is_default:
            match_desc.append('<span class="pill" style="background:#fef3c7;">DOMYŚLNA</span>')
        if not match_desc:
            match_desc.append('<span class="muted">brak warunków</span>')

        rows.append(f"""
            <div class="card" style="margin-bottom:10px;">
              <div style="display:flex; justify-content:space-between; align-items:start; gap:10px;">
                <div>
                  <div style="font-weight:700;">
                    <span class="pill" style="{flow_class}">{flow}</span>
                  </div>
                  <div class="muted" style="margin-top:6px;">
                    Dopasowanie: {' | '.join(match_desc)}
                  </div>
                  <div class="muted" style="margin-top:4px;">
                    wFirma: {r.get('wfirma_document_type') or '—'} / seria: {r.get('wfirma_series_name') or '—'}
                  </div>
                </div>
                {'<div style="display:flex; gap:8px;"><a class="btn" href="' + url_for('admin_bp.payment_rule_edit', event_id=event_id, rule_id=r.get('id'), token=token) + '">Edytuj</a><form method="post" action="' + url_for('admin_bp.payment_rule_delete', event_id=event_id, rule_id=r.get('id')) + '" onsubmit="return confirm(\'Usunąć regułę?\');" style="display:inline;"><input type="hidden" name="token" value="' + token + '" /><button class="btn btnDanger" type="submit">Usuń</button></form></div>' if not is_viewer else ''}
              </div>
            </div>
        """)

    body = f"""
    <div style="margin-bottom:12px;">
      <a class="btn" href="{url_for('admin_bp.event_preview' if is_viewer else 'admin_bp.event_edit', event_id=event_id, token=token)}">← Wróć do eventu</a>
      <a class="btn" href="{url_for('admin_bp.events_list', token=token)}">Lista wydarzeń</a>
    </div>

    <div class="card" style="margin-bottom:16px;">
      <div style="font-weight:700;">{ev.get('event_name', '')}</div>
      <div class="muted"><code>{event_id}</code></div>
    </div>

    <div style="margin-bottom:14px;">
      {'<a class="btn btnPrimary" href="' + url_for('admin_bp.payment_rule_new', event_id=event_id, token=token) + '">+ Nowa reguła płatności</a>' if not is_viewer else '<span class="pill" style="background:#e0f2fe; color:#0369a1;">Tryb podglądu</span>'}
    </div>

    <div class="muted" style="margin-bottom:10px;">
      <b>Jak działa routing?</b><br/>
      1. Jeśli <code>total = 0</code> → zawsze <b>FOC</b> (Free of Charge)<br/>
      2. Inaczej: dopasuj regułę po <code>payment_option_name</code> (zawiera) lub <code>payment_type</code><br/>
      3. Jeśli brak dopasowania → użyj reguły domyślnej
    </div>

    {''.join(rows) if rows else '<div class="muted">Brak reguł. Dodaj pierwszą regułę płatności.</div>'}
    """
    return _page(f"Reguły płatności – {ev.get('event_name', '')}", body)


@admin_bp.route("/events/<event_id>/rules/new", methods=["GET"])
@_require_permission("events")
def payment_rule_new(event_id: str):
    """Formularz nowej reguły płatności."""
    token = _require_admin_token()
    
    # Blokuj dla viewera
    if _is_viewer(_get_current_admin_user()):
        abort(403, description="Brak uprawnień do tworzenia reguł")
    
    ev = get_event(event_id)
    if not ev:
        abort(404, description="Nie znaleziono eventu")
    return _payment_rule_form(token, ev, rule=None)


@admin_bp.route("/events/<event_id>/rules/<int:rule_id>/edit", methods=["GET"])
@_require_permission("events")
def payment_rule_edit(event_id: str, rule_id: int):
    """Formularz edycji reguły płatności."""
    token = _require_admin_token()
    
    # Blokuj dla viewera
    if _is_viewer(_get_current_admin_user()):
        return redirect(url_for("admin_bp.payment_rules_list", event_id=event_id, token=token))
    
    ev = get_event(event_id)
    if not ev:
        abort(404, description="Nie znaleziono eventu")
    rule = get_payment_rule(rule_id)
    if not rule or rule.get("event_id") != event_id:
        abort(404, description="Nie znaleziono reguły")
    return _payment_rule_form(token, ev, rule=rule)


@admin_bp.route("/events/<event_id>/rules/save", methods=["POST"])
@_require_permission("events")
def payment_rule_save(event_id: str):
    """Zapisuje regułę płatności."""
    token = _require_admin_token()
    
    # Blokuj dla viewera
    if _is_viewer(_get_current_admin_user()):
        abort(403, description="Brak uprawnień do edycji reguł")
    
    ev = get_event(event_id)
    if not ev:
        abort(404, description="Nie znaleziono eventu")

    rule_id_str = (request.form.get("rule_id") or "").strip()
    rule_id = int(rule_id_str) if rule_id_str else None

    flow = (request.form.get("flow") or "").strip().upper()
    if flow not in FLOW_OPTIONS:
        body = f'<div class="error">Nieprawidłowy flow: {flow}</div><p><a class="btn" href="{url_for("admin_bp.payment_rules_list", event_id=event_id, token=token)}">Wróć</a></p>'
        return _page("Błąd", body), 400

    payment_option_name_pattern = (request.form.get("payment_option_name_pattern") or "").strip() or None
    payment_type_str = (request.form.get("payment_type") or "").strip()
    payment_type = int(payment_type_str) if payment_type_str else None
    is_default = (request.form.get("is_default") or "").lower() == "on"

    wfirma_company = (request.form.get("wfirma_company") or "").strip() or None
    wfirma_series_name = (request.form.get("wfirma_series_name") or "").strip() or None
    wfirma_document_type = (request.form.get("wfirma_document_type") or "").strip() or None
    wfirma_payment_due_days_str = (request.form.get("wfirma_payment_due_days") or "").strip()
    wfirma_payment_due_days = int(wfirma_payment_due_days_str) if wfirma_payment_due_days_str else None

    upsert_payment_rule(
        event_id=event_id,
        flow=flow,
        rule_id=rule_id,
        payment_option_id=None,
        payment_type=payment_type,
        payment_option_name_pattern=payment_option_name_pattern,
        is_default=is_default,
        wfirma_company=wfirma_company,
        wfirma_series_name=wfirma_series_name,
        wfirma_document_type=wfirma_document_type,
        wfirma_payment_due_days=wfirma_payment_due_days,
    )

    return redirect(url_for("admin_bp.payment_rules_list", event_id=event_id, token=token))


@admin_bp.route("/events/<event_id>/rules/<int:rule_id>/delete", methods=["POST"])
@_require_permission("events")
def payment_rule_delete(event_id: str, rule_id: int):
    """Usuwa regułę płatności."""
    token = _require_admin_token()
    
    # Blokuj dla viewera
    if _is_viewer(_get_current_admin_user()):
        abort(403, description="Brak uprawnień do usuwania reguł")
    
    delete_payment_rule(rule_id)
    return redirect(url_for("admin_bp.payment_rules_list", event_id=event_id, token=token))


def _payment_rule_form(token: str, event: Dict[str, Any], rule: Optional[Dict[str, Any]]) -> str:
    """Renderuje formularz reguły płatności."""
    is_new = rule is None
    event_id = event.get("event_id", "")
    event_name = event.get("event_name", "")

    rule_id = "" if is_new else (rule.get("id") or "")
    flow = "" if is_new else (rule.get("flow") or "")
    payment_option_name_pattern = "" if is_new else (rule.get("payment_option_name_pattern") or "")
    payment_type = "" if is_new else (rule.get("payment_type") if rule.get("payment_type") is not None else "")
    is_default = False if is_new else bool(rule.get("is_default"))
    wfirma_company = "" if is_new else (rule.get("wfirma_company") or "")
    wfirma_series_name = "" if is_new else (rule.get("wfirma_series_name") or "")
    wfirma_document_type = "" if is_new else (rule.get("wfirma_document_type") or "")
    wfirma_payment_due_days = "" if is_new else (rule.get("wfirma_payment_due_days") if rule.get("wfirma_payment_due_days") is not None else "")

    flow_options_html = "".join(
        f'<option value="{f}" {"selected" if f == flow else ""}>{f}</option>'
        for f in FLOW_OPTIONS
    )

    doc_type_options_html = '<option value="">— (domyślny)</option>' + "".join(
        f'<option value="{d}" {"selected" if d == wfirma_document_type else ""}>{d}</option>'
        for d in WFIRMA_DOC_TYPES
    )

    body = f"""
    <div style="margin-bottom:12px;">
      <a class="btn" href="{url_for('admin_bp.payment_rules_list', event_id=event_id, token=token)}">← Wróć do listy reguł</a>
    </div>

    <div class="card" style="margin-bottom:16px;">
      <div style="font-weight:700;">{event_name}</div>
      <div class="muted"><code>{event_id}</code></div>
    </div>

    <div class="grid">
      <div class="card">
        <div style="font-weight:700; margin-bottom:10px;">{'Nowa reguła' if is_new else 'Edytuj regułę'}</div>
        <form method="post" action="{url_for('admin_bp.payment_rule_save', event_id=event_id)}">
          <input type="hidden" name="token" value="{token}" />
          <input type="hidden" name="rule_id" value="{rule_id}" />

          <div class="muted">Flow (typ przepływu) *</div>
          <select name="flow" style="width:100%; padding:10px; border-radius:8px; border:1px solid #ccc;">
            <option value="">— wybierz —</option>
            {flow_options_html}
          </select>
          <div class="formHint">
            <b>FOC</b> = Free of Charge (darmowe, tylko mail)<br/>
            <b>PROFORMA</b> = wystawiamy proformę w wFirma, czekamy na przelew<br/>
            <b>STRIPE</b> = generujemy link do płatności online
          </div>
          <div style="height:14px;"></div>

          <div class="muted">Dopasowanie: payment_option_name zawiera</div>
          <input type="text" name="payment_option_name_pattern" value="{payment_option_name_pattern}" placeholder="np. Pro-forma lub online" />
          <div class="formHint">Jeśli nazwa opcji płatności (z Backstage) zawiera ten tekst → reguła pasuje.</div>
          <div style="height:10px;"></div>

          <div class="muted">Dopasowanie: payment_type (opcjonalnie)</div>
          <input type="text" name="payment_type" value="{payment_type}" placeholder="np. 4" />
          <div class="formHint">Dokładna wartość payment_type z Backstage (liczbowa).</div>
          <div style="height:10px;"></div>

          <div>
            <label>
              <input type="checkbox" name="is_default" {"checked" if is_default else ""} />
              Reguła domyślna (fallback)
            </label>
          </div>
          <div class="formHint">Użyta gdy żadna inna reguła nie pasuje.</div>
          <div style="height:14px;"></div>

          <div style="border-top:1px solid #eee; padding-top:14px; margin-top:10px;">
            <div class="muted" style="font-weight:700;">Ustawienia wFirma (dla PROFORMA / STRIPE)</div>
          </div>
          <div style="height:10px;"></div>

          <div class="muted">wfirma_company</div>
          <input type="text" name="wfirma_company" value="{wfirma_company}" placeholder="np. md lub test" />
          <div class="formHint">Który zestaw tokenów wFirma (md/test/md_test).</div>
          <div style="height:10px;"></div>

          <div class="muted">wfirma_series_name</div>
          <input type="text" name="wfirma_series_name" value="{wfirma_series_name}" placeholder="np. FV/2026" />
          <div class="formHint">Seria numeracji faktury/proformy.</div>
          <div style="height:10px;"></div>

          <div class="muted">wfirma_document_type</div>
          <select name="wfirma_document_type" style="width:100%; padding:10px; border-radius:8px; border:1px solid #ccc;">
            {doc_type_options_html}
          </select>
          <div class="formHint">Typ dokumentu: proforma / normal / proforma_bill.</div>
          <div style="height:10px;"></div>

          <div class="muted">wfirma_payment_due_days</div>
          <input type="text" name="wfirma_payment_due_days" value="{wfirma_payment_due_days}" placeholder="np. 14" />
          <div class="formHint">Termin płatności w dniach.</div>
          <div style="height:14px;"></div>

          <button class="btn btnPrimary" type="submit">Zapisz</button>
        </form>
      </div>

      <div class="card">
        <div style="font-weight:700; margin-bottom:10px;">Instrukcja</div>
        <div class="muted">
          <b>Jak działa routing płatności?</b><br/><br/>
          1. Jeśli <code>total = 0</code> → zawsze <b>FOC</b><br/>
          2. Dopasuj regułę:<br/>
          &nbsp;&nbsp;• najpierw po <code>payment_option_name</code><br/>
          &nbsp;&nbsp;• potem po <code>payment_type</code><br/>
          3. Jeśli brak dopasowania → reguła domyślna<br/><br/>
          <b>Typowa konfiguracja:</b><br/>
          • Reguła 1: pattern = <code>Pro-forma</code> → flow = <code>PROFORMA</code><br/>
          • Reguła 2: pattern = <code>online</code> → flow = <code>STRIPE</code><br/>
          • Reguła 3: domyślna → flow = <code>STRIPE</code> (fallback)
        </div>
      </div>
    </div>
    """
    return _page("Reguła płatności", body)


# ---------------------------------------------------------------------------
# ORDERS MANAGEMENT
# ---------------------------------------------------------------------------

ORDER_STATUS_LABELS = {
    "received": ("Otrzymane", "background:#f3f4f6;"),
    "pending_payment": ("Oczekuje na płatność", "background:#fff8e1;"),
    "paid": ("Opłacone", "background:#ecfdf3;"),
    "failed": ("Błąd", "background:#fff5f5;"),
    "cancelled": ("Anulowane", "background:#f3f4f6;"),
}


@admin_bp.route("/orders", methods=["GET"])
@_require_permission("orders")
def orders_list():
    """Lista zamówień z filtrowaniem."""
    token = _require_admin_token()
    current_user = _get_current_admin_user()
    is_viewer = _is_viewer(current_user)
    allowed_events = _normalize_allowed_events(current_user.get("allowed_events") if current_user else []) if is_viewer else []

    # Filtrowanie
    status_filter = (request.args.get("status") or "").strip()
    event_filter = (request.args.get("event_id") or "").strip()

    orders = list_orders(
        event_id=event_filter or None,
        status=status_filter or None,
        limit=200,
    )
    
    # Filtruj zamówienia dla viewera - tylko z dozwolonych wydarzeń
    if is_viewer:
        if not allowed_events:
            # Brak przypisanych wydarzeń - pusta lista
            orders = []
        else:
            orders = [o for o in orders if o.get("event_id") in allowed_events]

    # Pobierz listę eventów do filtrowania
    events = list_events(limit=100)
    
    # Dla viewera - tylko dozwolone wydarzenia w filtrze
    if is_viewer:
        if not allowed_events:
            events = []
        else:
            events = [e for e in events if e.get("event_id") in allowed_events]
    
    event_meta_by_id: Dict[str, Dict[str, str]] = {}
    for e in (events or []):
        eid = str(e.get("event_id") or "")
        if not eid:
            continue
        data = e.get("data") or {}
        event_meta_by_id[eid] = {
            "name": e.get("event_name") or "",
            "color": data.get("color_gradient_1") or "",
            "city": data.get("event_location_city") or data.get("event_address_text_city") or "",
        }
    event_name_by_id = {eid: meta.get("name", "") for eid, meta in event_meta_by_id.items()}
    event_options = "".join(
        f'<option value="{e.get("event_id", "")}" {"selected" if e.get("event_id") == event_filter else ""}>{e.get("event_name", "")}</option>'
        for e in events
    )

    status_options = "".join(
        f'<option value="{s}" {"selected" if s == status_filter else ""}>{label}</option>'
        for s, (label, _) in ORDER_STATUS_LABELS.items()
    )

    # Cache reguł płatności per event (żeby nie robić N zapytań na 200 wierszy)
    rules_by_event_id: Dict[str, List[Dict[str, Any]]] = {}
    for o in orders:
        eid = str(o.get("event_id") or "")
        if eid and eid not in rules_by_event_id:
            rules_by_event_id[eid] = list_payment_rules(eid) or []

    def _flow_from_rules(event_id: str, payment_type: Optional[int]) -> Optional[str]:
        """Zwraca flow (FOC/PROFORMA/STRIPE) bez heurystyk po nazwie."""
        rules = rules_by_event_id.get(str(event_id) or "", [])
        # 1) dopasowanie po payment_type
        for r in rules:
            rpt = r.get("payment_type")
            if rpt is not None and rpt == payment_type:
                return r.get("flow")
        # 2) reguła domyślna
        for r in rules:
            if r.get("is_default"):
                return r.get("flow")
        return None

    payment_pill_styles = {
        "FOC": "background:#ecfdf3; color:#166534; border:1px solid #bbf7d0;",
        "Pro forma": "background:#fff7ed; color:#9a3412; border:1px solid #fed7aa;",
        "Online (Stripe)": "background:#e0f2fe; color:#0369a1; border:1px solid #bae6fd;",
    }

    def _payment_pill(form: str) -> str:
        style = payment_pill_styles.get(form, "background:#f1f5f9; color:#64748b; border:1px solid #e2e8f0;")
        return f'<span class="pill pill-payment" style="{style}">{form}</span>'

    rows = []
    for o in orders:
        status = o.get("status", "received")
        label, style = ORDER_STATUS_LABELS.get(status, ("?", ""))
        total = o.get("total") or 0
        currency = o.get("currency", "PLN")
        order_id = o.get("event_order_id", "") or ""
        event_id = o.get("event_id", "") or ""
        payment_type = o.get("payment_type")

        # Wydarzenie (bez danych osobowych) + kolor + miasto
        event_meta = event_meta_by_id.get(str(event_id), {})
        event_name = event_meta.get("name") or (str(event_id)[:8] + "…") if event_id else "—"
        event_color = (event_meta.get("color") or "").strip()
        event_city = (event_meta.get("city") or "").strip() or "—"
        event_color_style = f' style="color:{event_color};"' if event_color else ""
        event_cell_html = f'<div class="order-event-name"{event_color_style}>{event_name}</div><div class="order-event-city">{event_city}</div>'

        # Liczba osób: suma statusów uczestników (jeśli brak – 0)
        participants_count = 0
        try:
            from pg_storage import count_participants_by_status
            pc = count_participants_by_status(str(order_id))
            participants_count = int(sum((pc or {}).values()))
        except Exception:
            participants_count = 0

        # Nr proformy / faktury + netto z dokumentu (jeśli jest)
        proforma_number = "—"
        invoice_number = "—"
        netto_value = None
        has_proforma = False
        has_invoice = False
        try:
            wfirma_docs = get_wfirma_documents(str(order_id))
            # weź najnowszą proformę jeśli istnieje
            proforma_doc = next((d for d in (wfirma_docs or []) if (d.get("document_type") == "proforma")), None)
            if proforma_doc:
                has_proforma = True
                proforma_number = proforma_doc.get("wfirma_number") or "—"
            # weź najnowszą fakturę końcową (normal) jeśli istnieje
            invoice_doc = next((d for d in (wfirma_docs or []) if (d.get("document_type") == "normal")), None)
            if invoice_doc:
                has_invoice = True
                invoice_number = invoice_doc.get("wfirma_number") or "—"
            doc_for_netto = proforma_doc or invoice_doc
            raw = (doc_for_netto.get("raw") if doc_for_netto else {}) or {}
            if isinstance(raw, dict):
                inv = raw.get("invoice") or {}
                if isinstance(inv, dict) and inv.get("netto") is not None:
                    try:
                        netto_value = float(inv.get("netto"))
                    except Exception:
                        netto_value = None
        except Exception:
            pass

        # Forma płatności
        payment_option_name = (o.get("payment_option_name") or "").lower()
        
        if float(total or 0) == 0:
            payment_form = "FOC"
        elif has_proforma:
            payment_form = "Pro forma"
        else:
            # Sprawdź payment_rules
            flow = _flow_from_rules(str(event_id), payment_type if isinstance(payment_type, int) else payment_type)
            if flow == "STRIPE":
                payment_form = "Online (Stripe)"
            elif flow == "PROFORMA":
                payment_form = "Pro forma"
            elif flow == "FOC":
                payment_form = "FOC"
            # Fallback: sprawdź payment_option_name z zamówienia
            elif "pro-forma" in payment_option_name or "proforma" in payment_option_name or "pro forma" in payment_option_name:
                payment_form = "Pro forma"
            elif "online" in payment_option_name or "stripe" in payment_option_name or "kart" in payment_option_name:
                payment_form = "Online (Stripe)"
            elif "free" in payment_option_name or "bezpłatn" in payment_option_name or "foc" in payment_option_name:
                payment_form = "FOC"
            else:
                payment_form = "—"

        # Fallback netto: licz z brutto (VAT 23%) jeśli nie mamy z wFirma
        if netto_value is None:
            try:
                netto_value = float(total) / 1.23
            except Exception:
                netto_value = 0.0

        payment_form_html = _payment_pill(payment_form)
        rows.append(f"""
            <tr>
              <td>{event_cell_html}</td>
              <td>{payment_form_html}</td>
              <td><a href="{url_for('admin_bp.order_detail', order_id=order_id, token=token)}"><code>{order_id[:10]}…{order_id[-4:] if len(order_id) > 4 else ''}</code></a></td>
              <td><code>{proforma_number}</code></td>
              <td><code>{invoice_number}</code></td>
              <td style="text-align:right;">{participants_count}</td>
              <td style="text-align:right;">{netto_value:.2f} {currency}</td>
              <td><span class="pill" style="{style}">{label}</span></td>
            </tr>
        """)

    body = f"""
    <style>
      .orders-filter {{
        display: flex;
        gap: 16px;
        flex-wrap: wrap;
        align-items: flex-end;
        margin-bottom: 24px;
        padding: 20px;
        background: #fff;
        border: 1px solid var(--md-border);
        border-radius: 12px;
      }}
      .orders-filter .filter-group {{
        flex: 1;
        min-width: 180px;
      }}
      .orders-filter .filter-group label {{
        display: block;
        font-size: 12px;
        font-weight: 600;
        color: var(--md-text-muted);
        margin-bottom: 6px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }}
      .orders-filter select {{
        width: 100%;
        padding: 10px 14px;
        border: 1px solid var(--md-border);
        border-radius: 8px;
        font-size: 14px;
        background: #fff;
        cursor: pointer;
      }}
      .orders-filter select:focus {{
        outline: none;
        border-color: var(--md-primary);
        box-shadow: 0 0 0 3px rgba(0, 101, 215, 0.1);
      }}
      .orders-filter .filter-actions {{
        display: flex;
        gap: 8px;
      }}
      .orders-table-wrapper {{
        background: #fff;
        border: 1px solid var(--md-border);
        border-radius: 12px;
        overflow: hidden;
        max-width: 1100px;
        margin: 0 auto;
      }}
      .orders-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;
      }}
      .orders-table th {{
        text-align: left;
        padding: 10px 12px;
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--md-text-muted);
        background: #f8fafc;
        border-bottom: 2px solid var(--md-border);
      }}
      .orders-table th.text-right {{ text-align: right; }}
      .orders-table td {{
        padding: 10px 12px;
        border-bottom: 1px solid #f1f5f9;
        vertical-align: middle;
      }}
      .orders-table td.text-right {{ text-align: right; }}
      .orders-table tbody tr {{
        transition: background 0.15s ease;
      }}
      .orders-table tbody tr:hover {{
        background: #f8fafc;
      }}
      .orders-table tbody tr:last-child td {{
        border-bottom: none;
      }}
      .orders-table .order-link {{
        color: var(--md-primary);
        font-weight: 500;
      }}
      .orders-table .order-link:hover {{
        text-decoration: underline;
      }}
      .orders-table code {{
        font-size: 12px;
        background: #f1f5f9;
        padding: 3px 8px;
        border-radius: 4px;
      }}
      .orders-table .order-event-name {{
        font-weight: 700;
        font-size: 15px;
        line-height: 1.2;
        letter-spacing: 0.2px;
        font-family: "Segoe UI Semibold", "Segoe UI", "Trebuchet MS", Arial, sans-serif;
      }}
      .orders-table .order-event-city {{
        font-size: 12px;
        color: #64748b;
        margin-top: 4px;
      }}
      .orders-table .pill-payment {{
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        line-height: 1;
        white-space: nowrap;
      }}
      .orders-empty {{
        padding: 60px 20px;
        text-align: center;
        color: var(--md-text-muted);
      }}
      .orders-stats {{
        display: flex;
        gap: 12px;
        margin-bottom: 24px;
      }}
      .stat-card {{
        flex: 1;
        padding: 16px 20px;
        background: #fff;
        border: 1px solid var(--md-border);
        border-radius: 10px;
      }}
      .stat-card .stat-value {{
        font-size: 24px;
        font-weight: 700;
        color: var(--md-primary);
      }}
      .stat-card .stat-label {{
        font-size: 12px;
        color: var(--md-text-muted);
        margin-top: 4px;
      }}
    </style>

    <div class="orders-filter">
      <form method="get" action="{url_for('admin_bp.orders_list')}" style="display:flex; gap:16px; flex-wrap:wrap; align-items:flex-end; width:100%;">
        <input type="hidden" name="token" value="{token}" />
        <div class="filter-group">
          <label for="status-filter">Status</label>
          <select name="status" id="status-filter">
            <option value="">— wszystkie —</option>
            {status_options}
          </select>
        </div>
        <div class="filter-group">
          <label for="event-filter">Wydarzenie</label>
          <select name="event_id" id="event-filter">
            <option value="">— wszystkie —</option>
            {event_options}
          </select>
        </div>
        <div class="filter-actions">
          <button class="btn btnPrimary" type="submit">Filtruj</button>
        <a class="btn" href="{url_for('admin_bp.orders_list', token=token)}">Wyczyść</a>
        </div>
      </form>
    </div>

    <div class="orders-table-wrapper">
      <table class="orders-table">
        <thead>
          <tr>
            <th>Wydarzenie / Miasto</th>
            <th>Forma płatności</th>
            <th>Nr zamówienia</th>
            <th>Nr proformy</th>
            <th>Nr faktury</th>
            <th class="text-right">Ilość osób</th>
            <th class="text-right">Wartość netto</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows) if rows else '<tr><td colspan="8" class="orders-empty"><img src="/Empty_list_1.jpg" alt="Brak zamówień" style="max-width:420px; width:100%; height:auto; opacity:0.9;" /></td></tr>'}
        </tbody>
      </table>
    </div>
    
    <div class="muted" style="margin-top:12px; font-size:12px;">
      Wyświetlono {len(rows)} zamówień
    </div>
    """
    return _page("Zamówienia", body)


@admin_bp.route("/orders/<order_id>", methods=["GET"])
@_require_permission("orders")
def order_detail(order_id: str):
    """Szczegóły zamówienia."""
    token = _require_admin_token()
    current_user = _get_current_admin_user()
    is_viewer = _is_viewer(current_user)
    
    # Pobierz flash messages - tylko te związane z tym zamówieniem (mark_paid, generate)
    # Pomijamy komunikaty o usunięciu innych zamówień
    from flask import get_flashed_messages
    all_messages = get_flashed_messages(with_categories=True)
    messages = [(cat, msg) for cat, msg in all_messages if "zostało usunięte" not in msg]

    order = get_order(order_id)
    if not order:
        abort(404, description="Nie znaleziono zamówienia")
    
    # Sprawdź dostęp viewera do tego wydarzenia
    event_id = order.get("event_id", "")
    if is_viewer and not _user_can_access_event(current_user, event_id):
        abort(403, description="Brak dostępu do tego zamówienia")

    status = order.get("status", "received")
    label, style = ORDER_STATUS_LABELS.get(status, ("?", ""))
    total = order.get("total") or 0
    currency = order.get("currency", "PLN")
    event_id = order.get("event_id", "")

    # Pobierz event
    ev = get_event(event_id) if event_id else None
    event_name = ev.get("event_name", "") if ev else ""
    event_data = (ev.get("data") if ev else {}) or {}
    event_color_1 = event_data.get("color_gradient_1") or "#0065D7"
    event_color_2 = event_data.get("color_gradient_2") or event_color_1
    
    # Linki do Backstage
    backstage_config_link = event_data.get("event_config_link", "") or ""
    backstage_orders_link = event_data.get("event_orders_link", "") or ""
    backstage_attendees_link = event_data.get("event_attendees_link", "") or ""

    # Pobierz uczestników zamówienia
    participants = get_participants_for_order(order_id)

    # Pobierz dokumenty wFirma
    wfirma_docs = get_wfirma_documents(order_id)
    docs_html = ""
    if wfirma_docs:
        docs_rows = "".join(
            f"<tr><td>{d.get('document_type', '')}</td><td><code>{d.get('wfirma_number', '')}</code></td><td>{d.get('status', '')}</td></tr>"
            for d in wfirma_docs
        )
        docs_html = f"""
        <div style="margin-top:16px;">
          <div class="muted" style="font-weight:700; margin-bottom:8px;">Dokumenty wFirma</div>
          <table style="width:100%; border-collapse:collapse; font-size:13px;">
            <tr style="border-bottom:1px solid #eee;"><th style="text-align:left;">Typ</th><th style="text-align:left;">Numer</th><th style="text-align:left;">Status</th></tr>
            {docs_rows}
          </table>
        </div>
        """

    # === STATUS AUTOMATYZACJI ===
    # Sprawdź jakie dokumenty wFirma istnieją
    proforma_doc = next((d for d in wfirma_docs if d.get("document_type") == "proforma"), None)
    has_proforma = proforma_doc is not None
    proforma_number = proforma_doc.get("wfirma_number", "") if proforma_doc else ""
    has_final_invoice = any(d.get("document_type") == "normal" for d in wfirma_docs)
    
    # Sprawdź jakie maile zostały wysłane
    mail_proforma_sent = mail_log_exists(order_id, "proforma_sent", direction="purchaser")
    mail_payment_confirmation_sent = mail_log_exists(order_id, "payment_confirmation", direction="purchaser")
    
    # Sprawdź statusy uczestników
    participants_stats = count_participants_by_status(order_id)
    total_participants = sum(participants_stats.values())
    emailed_participants = participants_stats.get("emailed", 0)
    
    # Określ oczekiwany flow na podstawie payment_option_name
    payment_option = (order.get("payment_option_name") or "").lower()
    is_proforma_flow = "pro-forma" in payment_option or "proforma" in payment_option
    is_foc_flow = total == 0 or "foc" in payment_option or "free" in payment_option
    is_stripe_flow = not is_proforma_flow and not is_foc_flow and total > 0

    # Przycisk "Oznacz jako opłacone" tylko dla pending_payment (obok statusu) - ukryty dla viewera
    mark_paid_form = ""
    if status == "pending_payment" and not is_viewer:
        proforma_info_btn = f' ({proforma_number})' if proforma_number else ''
        proforma_info_modal = f'<div style="margin-bottom:16px; padding:12px 16px; background:#f0f9ff; border:1px solid #bae6fd; border-radius:8px; font-size:14px;">Proforma: <strong style="color:#0369a1;">{proforma_number}</strong> • {total:.2f} {currency}</div>' if proforma_number else ''
        mark_paid_form = f"""
        <button class="btn btnPrimary" type="button" onclick="document.getElementById('markPaidModal').style.display='flex'">
          Oznacz jako opłacone{proforma_info_btn}
        </button>

        <div id="markPaidModal" class="mark-paid-modal" onclick="if(event.target===this)this.style.display='none'">
          <div class="mark-paid-modal-content">
            <h3>Potwierdzenie płatności</h3>
            {proforma_info_modal}
            <p>
              Oznaczyć zamówienie jako <strong>opłacone</strong>?<br/>
              <span style="font-size:13px;">Zostanie wygenerowana faktura VAT i wysłane powiadomienia.</span>
            </p>
            <div class="modal-actions">
              <form id="markPaidForm" method="post" action="{url_for('admin_bp.order_mark_paid', order_id=order_id)}" style="margin:0;">
                <input type="hidden" name="token" value="{token}" />
                <button id="markPaidSubmit" class="btn btnPrimary" type="submit" style="min-width:160px;">
                  <span class="btn-label">Tak, oznacz</span>
                  <span class="btn-spinner" style="display:none;"></span>
                </button>
              </form>
              <button id="markPaidCancel" class="btn" type="button" onclick="document.getElementById('markPaidModal').style.display='none'" style="min-width:120px;">
                Anuluj
              </button>
            </div>
            <div id="markPaidHint" class="muted" style="margin-top:14px; font-size:12px; display:none;">
              Przetwarzanie… poczekaj chwilę
            </div>
          </div>
        </div>
        <script>
          (function() {{
            var form = document.getElementById('markPaidForm');
            if (!form) return;
            form.addEventListener('submit', function() {{
              var submitBtn = document.getElementById('markPaidSubmit');
              var cancelBtn = document.getElementById('markPaidCancel');
              var hint = document.getElementById('markPaidHint');
              if (submitBtn) {{
                submitBtn.disabled = true;
                var label = submitBtn.querySelector('.btn-label');
                var spinner = submitBtn.querySelector('.btn-spinner');
                if (label) label.textContent = 'Oznaczam...';
                if (spinner) spinner.style.display = 'inline-block';
              }}
              if (cancelBtn) cancelBtn.disabled = true;
              if (hint) hint.style.display = 'block';
            }});
          }})();
        </script>
        """

    # Status pill color based on status
    status_class = "pill-success" if status == "paid" else "pill-warning" if status == "pending_payment" else "pill" if status == "received" else "pill-error"

    body = f"""
    <style>
      .order-breadcrumb {{
        margin-bottom: 20px;
      }}
      .order-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 24px;
        background: linear-gradient(135deg, var(--event-accent) 0%, var(--event-accent-2) 100%);
        border: 1px solid rgba(15, 23, 42, 0.08);
        border-radius: 12px;
        margin-bottom: 24px;
        color: #fff;
        box-shadow: 0 6px 16px rgba(2, 6, 23, 0.12);
        position: sticky;
        top: 12px;
        z-index: 20;
      }}
      @media (max-width: 900px) {{
        .order-header {{
          position: static;
        }}
      }}
      .order-header-info h2 {{
        margin: 0 0 4px 0;
        font-size: 20px;
        font-weight: 600;
        color: #fff;
      }}
      .order-header-info code {{
        font-size: 13px;
        color: #fff;
        background: rgba(255,255,255,0.16);
        border: 1px solid rgba(255,255,255,0.25);
      }}
      .order-header .btnPrimary {{
        background: #fff;
        color: var(--event-accent);
        border: 1px solid rgba(255,255,255,0.6);
        font-weight: 700;
      }}
      .order-header .btnPrimary:hover {{
        background: #f8fafc;
        border-color: #fff;
      }}
      .order-header .pill {{
        color: #0f172a;
        background: #fff;
        border: 1px solid rgba(15, 23, 42, 0.08);
      }}
      .order-header-actions {{
        display: flex;
        align-items: center;
        gap: 12px;
        justify-content: flex-end;
      }}
      .order-sections {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 24px;
      }}
      @media (max-width: 900px) {{
        .order-sections {{ grid-template-columns: 1fr; }}
      }}
      @media (max-width: 768px) {{
        .order-breadcrumb {{ flex-direction: column; align-items: flex-start !important; }}
      }}
      .order-section {{
        background: #fff;
        border: 1px solid var(--md-border);
        border-radius: 12px;
        overflow: hidden;
      }}
      .order-section-header {{
        padding: 16px 20px;
        background: #f8fafc;
        border-bottom: 1px solid var(--md-border);
        border-left: 4px solid var(--event-accent);
        font-weight: 600;
        font-size: 14px;
        color: var(--md-text);
      }}
      .order-section-body {{
        padding: 20px;
      }}
      .order-section {{
        box-shadow: 0 2px 6px rgba(2, 6, 23, 0.04);
      }}
      .order-section:nth-child(odd) .order-section-header {{
        background: #f8fafc;
      }}
      .order-section .kv {{
        grid-template-columns: 140px 1fr;
      }}
      .order-section .kv > div {{
        border-bottom: 1px solid #f8fafc;
        padding: 10px 0;
      }}
      .order-section .kv > div:nth-child(odd) {{
        color: var(--md-text-muted);
        font-weight: 500;
        font-size: 13px;
      }}
      .order-amount {{
        font-size: 20px;
        font-weight: 700;
        color: var(--event-accent);
      }}
      .docs-table {{
        width: 100%;
        max-width: 980px;
        border-collapse: collapse;
        font-size: 13px;
        margin: 10px auto 0;
      }}
      .docs-table th {{
        text-align: left;
        padding: 8px 10px;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--md-text-muted);
        background: #f8fafc;
        border-bottom: 1px solid var(--md-border);
      }}
      .docs-table td {{
        padding: 8px 10px;
        border-bottom: 1px solid #f1f5f9;
      }}
      .action-section {{
        margin-top: 14px;
        padding-top: 14px;
        border-top: 1px solid var(--md-border);
      }}
      .mark-paid-modal {{
        display: none;
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0,0,0,0.5);
        z-index: 9999;
        justify-content: center;
        align-items: center;
      }}
      .mark-paid-modal-content {{
        background: #fff;
        border-radius: 16px;
        padding: 32px 40px;
        max-width: 440px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        text-align: center;
      }}
      .mark-paid-modal h3 {{
        margin: 0 0 16px 0;
        font-size: 20px;
        font-weight: 600;
        color: var(--md-text);
      }}
      .mark-paid-modal p {{
        color: #64748b;
        margin-bottom: 28px;
        line-height: 1.6;
      }}
      .mark-paid-modal .modal-actions {{
        display: flex;
        gap: 12px;
        justify-content: center;
      }}
      .mark-paid-modal .btn {{
        position: relative;
      }}
      .mark-paid-modal .btn[disabled] {{
        opacity: 0.7;
        cursor: not-allowed;
        transform: none;
      }}
      .btn-spinner {{
        display: inline-block;
        width: 16px;
        height: 16px;
        border: 2px solid rgba(255,255,255,0.6);
        border-top-color: #fff;
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
        vertical-align: middle;
      }}
      .btn-spinner.dark {{
        border: 2px solid rgba(2,6,23,0.2);
        border-top-color: #0f172a;
      }}
      @keyframes spin {{
        to {{ transform: rotate(360deg); }}
      }}
    </style>

    <div class="order-breadcrumb" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
      <div>
        <a class="btn" href="{url_for('admin_bp.orders_list', token=token)}">← Lista zamówień</a>
        {'<a class="btn" style="margin-left:8px;" href="' + url_for('admin_bp.event_edit', event_id=event_id, token=token) + '">Wydarzenie</a>' if event_id and not is_viewer else ''}
        {'<a class="btn" style="margin-left:8px;" href="' + url_for('admin_bp.event_preview', event_id=event_id, token=token) + '">Wydarzenie</a>' if event_id and is_viewer else ''}
      </div>
      {'<button class="btn btnDanger" type="button" onclick="document.getElementById(&apos;deleteOrderModal&apos;).style.display=&apos;flex&apos;" style="font-size:13px;">🗑 Usuń zamówienie</button>' if not is_viewer else '<span class="pill" style="background:#e0f2fe; color:#0369a1;">Tryb podglądu</span>'}
    </div>
    
    {''.join([
        f'''<div style="margin-bottom:16px; padding:16px 20px; background:{'#fef2f2' if cat == 'error' else '#fffbeb' if cat == 'warning' else '#f0fdf4'}; border:2px solid {'#fecaca' if cat == 'error' else '#fde68a' if cat == 'warning' else '#bbf7d0'}; border-radius:10px; color:{'#991b1b' if cat == 'error' else '#92400e' if cat == 'warning' else '#166534'}; font-weight:500;">
          {msg}
        </div>'''
        for cat, msg in messages
    ])}
    
    <div class="order-page" style="--event-accent:{event_color_1}; --event-accent-2:{event_color_2}; display:flex; gap:20px; align-items:flex-start;">
    
    <div style="flex:1; min-width:0;">
    <div class="order-header">
      <div class="order-header-info">
        <h2>Zamówienie</h2>
        <code>{order_id}</code>
        </div>
        <div class="order-header-actions">
        <span class="pill {status_class}" style="{style}">{label}</span>
        {mark_paid_form}
      </div>
    </div>

    <div class="order-sections">
      <div class="order-section">
        <div class="order-section-header">Dane nabywcy</div>
        <div class="order-section-body">
        <div class="kv">
            <div>Email</div><div>{order.get('purchaser_email', '') or '—'}</div>
            <div>Imię</div><div>{order.get('purchaser_first_name', '') or '—'}</div>
            <div>Nazwisko</div><div>{order.get('purchaser_last_name', '') or '—'}</div>
            <div>Telefon</div><div>{order.get('purchaser_phone', '') or '—'}</div>
            <div>NIP</div><div>{order.get('purchaser_nip', '') or '—'}</div>
          </div>
        </div>
      </div>

      <div class="order-section">
        <div class="order-section-header">Płatność</div>
        <div class="order-section-body">
        <div class="kv">
            <div>Kwota</div><div class="order-amount">{total:.2f} {currency}</div>
            <div>Opcja</div><div>{order.get('payment_option_name', '') or '—'}</div>
            <div>Kod promocyjny</div><div>{order.get('promo_code', '') or '—'}</div>
            <div>Wydarzenie</div><div>{event_name or '—'}</div>
        </div>
          
          {f'''
          <div style="margin-top:20px;">
            <div class="section-title">Dokumenty wFirma</div>
            <table class="docs-table">
              <thead>
                <tr><th>Typ</th><th>Numer</th><th>Status</th></tr>
              </thead>
              <tbody>
                {"".join(
                    f"<tr><td>{d.get('document_type', '')}</td><td><code>{d.get('wfirma_number', '')}</code></td><td>{d.get('status', '')}</td></tr>"
                    for d in wfirma_docs
                )}
              </tbody>
            </table>
          </div>
          ''' if wfirma_docs else ''}
          
          
        </div>
      </div>
    </div>

    <!-- SEKCJA: Status automatyzacji -->
    <div class="order-section" style="margin-top:24px; grid-column: 1 / -1;">
      <div class="order-section-header">Status automatyzacji</div>
      <div class="order-section-body">
        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:20px;">
          
          <!-- Dokumenty -->
          <div style="padding:16px; background:#f8fafc; border-radius:10px; border:1px solid #e2e8f0;">
            <div style="font-weight:600; margin-bottom:12px; color:#334155; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;">Dokumenty wFirma</div>
            <div style="display:flex; flex-direction:column; gap:8px;">
              <div style="display:flex; align-items:center; gap:8px;">
                <span class="pill {'pill-success' if has_proforma else 'pill-error'}" style="font-size:11px;">{'✓' if has_proforma else '✗'}</span>
                <span style="font-size:13px;">Proforma</span>
                {'<button class="btn" style="margin-left:auto; font-size:11px; padding:4px 10px;" onclick="document.getElementById(&quot;genProformaModal&quot;).style.display=&quot;flex&quot;">Wygeneruj</button>' if not has_proforma and is_proforma_flow else ''}
              </div>
              <div style="display:flex; align-items:center; gap:8px;">
                <span class="pill {'pill-success' if has_final_invoice else 'pill-warning' if status != 'paid' else 'pill-error'}" style="font-size:11px;">{'✓' if has_final_invoice else '—' if status != 'paid' else '✗'}</span>
                <span style="font-size:13px;">Faktura końcowa</span>
                {'<button class="btn" style="margin-left:auto; font-size:11px; padding:4px 10px;" onclick="document.getElementById(&quot;genInvoiceModal&quot;).style.display=&quot;flex&quot;">Wygeneruj</button>' if not has_final_invoice and status == 'paid' else ''}
              </div>
            </div>
          </div>
          
          <!-- Maile do kupującego -->
          <div style="padding:16px; background:#f8fafc; border-radius:10px; border:1px solid #e2e8f0;">
            <div style="font-weight:600; margin-bottom:12px; color:#334155; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;">Maile do kupującego</div>
            <div style="display:flex; flex-direction:column; gap:8px;">
              <div style="display:flex; align-items:center; gap:8px;">
                <span class="pill {'pill-success' if mail_proforma_sent else 'pill-warning' if not is_proforma_flow else 'pill-error'}" style="font-size:11px;">{'✓' if mail_proforma_sent else '—' if not is_proforma_flow else '✗'}</span>
                <span style="font-size:13px;">Email z proformą</span>
              </div>
              <div style="display:flex; align-items:center; gap:8px;">
                <span class="pill {'pill-success' if mail_payment_confirmation_sent else 'pill-warning' if status != 'paid' else 'pill-error'}" style="font-size:11px;">{'✓' if mail_payment_confirmation_sent else '—' if status != 'paid' else '✗'}</span>
                <span style="font-size:13px;">Potwierdzenie płatności</span>
              </div>
            </div>
          </div>
          
          <!-- Uczestnicy -->
          <div style="padding:16px; background:#f8fafc; border-radius:10px; border:1px solid #e2e8f0;">
            <div style="font-weight:600; margin-bottom:12px; color:#334155; font-size:13px; text-transform:uppercase; letter-spacing:0.5px;">Uczestnicy</div>
            <div style="display:flex; flex-direction:column; gap:8px;">
              <div style="display:flex; align-items:center; gap:8px;">
                <span style="font-size:13px;">Łącznie: <strong>{total_participants}</strong></span>
              </div>
              <div style="display:flex; align-items:center; gap:8px;">
                <span class="pill {'pill-success' if emailed_participants == total_participants and total_participants > 0 else 'pill-warning' if status != 'paid' else 'pill-error' if emailed_participants < total_participants else 'pill'}" style="font-size:11px;">
                  {emailed_participants}/{total_participants}
                </span>
                <span style="font-size:13px;">Powiadomieni</span>
              </div>
            </div>
          </div>
          
        </div>
        
        <!-- Legenda -->
        <div style="margin-top:16px; padding-top:16px; border-top:1px solid #e2e8f0; font-size:12px; color:#64748b;">
          <span style="margin-right:16px;"><span class="pill pill-success" style="font-size:10px;">✓</span> Zrealizowano</span>
          <span style="margin-right:16px;"><span class="pill pill-warning" style="font-size:10px;">—</span> Nie dotyczy / oczekuje</span>
          <span><span class="pill pill-error" style="font-size:10px;">✗</span> Brakuje</span>
        </div>
      </div>
    </div>
    
    <!-- SEKCJA: Uczestnicy -->
    <div class="order-section" style="margin-top:24px; grid-column: 1 / -1;">
      <div class="order-section-header" style="display:flex; justify-content:space-between; align-items:center;">
        <span>Uczestnicy ({len(participants)})</span>
      </div>
      <div class="order-section-body" style="padding:0;">
        {f'''
        <table style="width:100%; border-collapse:collapse; font-size:13px;">
          <thead>
            <tr style="background:#f8fafc; border-bottom:1px solid var(--md-border);">
              <th style="text-align:left; padding:12px 16px; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--md-text-muted);">Imię i nazwisko</th>
              <th style="text-align:left; padding:12px 16px; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--md-text-muted);">Email</th>
              <th style="text-align:left; padding:12px 16px; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--md-text-muted);">Telefon</th>
              <th style="text-align:left; padding:12px 16px; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--md-text-muted);">Status</th>
            </tr>
          </thead>
          <tbody>
            {"".join(
              f'''<tr style="border-bottom:1px solid #f1f5f9;">
                <td style="padding:12px 16px;">{(p.get("first_name") or "") + " " + (p.get("last_name") or "")}</td>
                <td style="padding:12px 16px;"><code style="font-size:12px;">{p.get("email") or "—"}</code></td>
                <td style="padding:12px 16px;">{p.get("phone") or "—"}</td>
                <td style="padding:12px 16px;">
                  <span class="pill {"pill-success" if p.get("status") == "emailed" else "pill-warning" if p.get("status") == "registered" else "pill"}" style="font-size:11px;">
                    {"✉ Powiadomiony" if p.get("status") == "emailed" else "📝 Zarejestrowany" if p.get("status") == "registered" else (p.get("status") or "—")}
                  </span>
                </td>
              </tr>'''
              for p in participants
            )}
          </tbody>
        </table>
        ''' if participants else '<div style="padding:24px; text-align:center; color:var(--md-text-muted);">Brak uczestników w tym zamówieniu</div>'}
      </div>
    </div>
    
    </div><!-- koniec głównej treści -->
    
    {f'''
    <div style="width:140px; flex-shrink:0; position:sticky; top:20px; align-self:flex-start;">
      <div style="background:#f0f9ff; border:1px solid #bae6fd; border-radius:10px; padding:12px; text-align:center;">
        <div style="margin-bottom:10px;">
          <img src="/backstage-logo.jpg" alt="Backstage" style="width:28px; height:28px; border-radius:6px;" />
        </div>
        <div style="font-size:10px; font-weight:600; color:#0369a1; margin-bottom:10px; text-transform:uppercase; letter-spacing:0.5px;">Backstage</div>
        <div style="display:flex; flex-direction:column; gap:6px;">
          {f'<a href="{backstage_config_link}" target="_blank" rel="noopener" class="btn" style="font-size:11px; padding:6px 8px; width:100%; box-sizing:border-box; background:#fff; border:1px solid #bae6fd; color:#0369a1;">Konfiguracja ↗</a>' if backstage_config_link else ''}
          {f'<a href="{backstage_orders_link}" target="_blank" rel="noopener" class="btn" style="font-size:11px; padding:6px 8px; width:100%; box-sizing:border-box; background:#fff; border:1px solid #bae6fd; color:#0369a1;">Zamówienia ↗</a>' if backstage_orders_link else ''}
          {f'<a href="{backstage_attendees_link}" target="_blank" rel="noopener" class="btn" style="font-size:11px; padding:6px 8px; width:100%; box-sizing:border-box; background:#fff; border:1px solid #bae6fd; color:#0369a1;">Uczestnicy ↗</a>' if backstage_attendees_link else ''}
        </div>
      </div>
    </div>
    ''' if (backstage_config_link or backstage_orders_link or backstage_attendees_link) and not is_viewer else ''}
    
    </div><!-- koniec flex container -->
    
    <!-- Modal: Generuj proformę -->
    <div id="genProformaModal" class="mark-paid-modal" onclick="if(event.target===this)this.style.display='none'">
      <div class="mark-paid-modal-content">
        <h3>Wygeneruj proformę</h3>
        <p>
          Utworzyć proformę w wFirma dla tego zamówienia?<br/>
          <span style="font-size:13px;">Email z proformą zostanie wysłany do kupującego (jeśli jeszcze nie wysłano).</span>
        </p>
        <div class="modal-actions">
          <form id="genProformaForm" method="post" action="{url_for('admin_bp.order_generate_proforma', order_id=order_id)}" style="margin:0;">
            <input type="hidden" name="token" value="{token}" />
            <button id="genProformaSubmit" class="btn btnPrimary" type="submit" style="min-width:160px;">
              <span class="btn-label">Tak, generuj</span>
              <span class="btn-spinner" style="display:none;"></span>
            </button>
          </form>
          <button class="btn" type="button" onclick="document.getElementById('genProformaModal').style.display='none'" style="min-width:120px;">
            Anuluj
          </button>
        </div>
      </div>
    </div>
    
    <!-- Modal: Generuj fakturę końcową -->
    <div id="genInvoiceModal" class="mark-paid-modal" onclick="if(event.target===this)this.style.display='none'">
      <div class="mark-paid-modal-content">
        <h3>Wygeneruj fakturę końcową</h3>
        <p>
          Utworzyć fakturę VAT w wFirma dla tego zamówienia?<br/>
          <span style="font-size:13px;">Email z potwierdzeniem zostanie wysłany do kupującego (jeśli jeszcze nie wysłano).</span>
        </p>
        <div class="modal-actions">
          <form id="genInvoiceForm" method="post" action="{url_for('admin_bp.order_generate_invoice', order_id=order_id)}" style="margin:0;">
            <input type="hidden" name="token" value="{token}" />
            <button id="genInvoiceSubmit" class="btn btnPrimary" type="submit" style="min-width:160px;">
              <span class="btn-label">Tak, generuj</span>
              <span class="btn-spinner" style="display:none;"></span>
            </button>
          </form>
          <button class="btn" type="button" onclick="document.getElementById('genInvoiceModal').style.display='none'" style="min-width:120px;">
            Anuluj
          </button>
        </div>
      </div>
    </div>
    
    <!-- Modal: Usuń zamówienie -->
    <div id="deleteOrderModal" class="mark-paid-modal" onclick="if(event.target===this)this.style.display='none'">
      <div class="mark-paid-modal-content">
        <h3 style="color:#dc2626;">🗑 Usuń zamówienie</h3>
        <p>
          <strong>UWAGA!</strong> Ta operacja jest <strong>nieodwracalna</strong>.<br/>
          Usunięte zostaną:
        </p>
        <ul style="text-align:left; margin:16px 0; color:#64748b; font-size:13px;">
          <li>Dane zamówienia</li>
          <li>Wszyscy uczestnicy</li>
          <li>Bilety zamówienia</li>
          <li>Historia maili</li>
        </ul>
        <p style="font-size:13px; color:#dc2626; font-weight:500;">
          Dokumenty wFirma NIE zostaną usunięte (trzeba ręcznie).
        </p>
        <div class="modal-actions">
          <form id="deleteOrderForm" method="post" action="{url_for('admin_bp.order_delete', order_id=order_id)}" style="margin:0;">
            <input type="hidden" name="token" value="{token}" />
            <button id="deleteOrderSubmit" class="btn btnDanger" type="submit" style="min-width:160px;">
              <span class="btn-label">Tak, usuń</span>
              <span class="btn-spinner dark" style="display:none;"></span>
            </button>
          </form>
          <button class="btn" type="button" onclick="document.getElementById('deleteOrderModal').style.display='none'" style="min-width:120px;">
            Anuluj
          </button>
        </div>
      </div>
    </div>
    
    <script>
      // Spinner dla modali generowania
      ['genProformaForm', 'genInvoiceForm', 'deleteOrderForm'].forEach(function(formId) {{
        var form = document.getElementById(formId);
        if (!form) return;
        form.addEventListener('submit', function() {{
          var submitBtn = form.querySelector('button[type="submit"]');
          if (submitBtn) {{
            submitBtn.disabled = true;
            var label = submitBtn.querySelector('.btn-label');
            var spinner = submitBtn.querySelector('.btn-spinner');
            if (label) label.textContent = formId === 'deleteOrderForm' ? 'Usuwam...' : 'Generuję...';
            if (spinner) spinner.style.display = 'inline-block';
          }}
        }});
      }});
    </script>
    """
    return _page("Szczegóły zamówienia", body)


@admin_bp.route("/orders/<order_id>/mark-paid", methods=["POST"])
@_require_permission("orders")
def order_mark_paid(order_id: str):
    """
    Oznacza zamówienie jako opłacone (dla proform).
    
    Flow:
    1. Sprawdza czy faktura końcowa (normal) już istnieje
    2. Pobiera konfigurację z payment_rules eventu
    3. Generuje fakturę końcową przez wFirma
    4. Wysyła emaile (potwierdzenie + wewnętrzny)
    5. Zmienia status na 'paid'
    """
    token = _require_admin_token()
    
    # Blokuj dla viewera
    if _is_viewer(_get_current_admin_user()):
        abort(403, description="Brak uprawnień do tej operacji")

    order = get_order(order_id)
    if not order:
        abort(404, description="Nie znaleziono zamówienia")

    # Pobierz dane eventu
    event_id = order.get("event_id", "")
    ev = get_event(event_id) if event_id else None
    event_name = ev.get("event_name", "") if ev else ""
    event_data = (ev.get("data") if ev else {}) or {}

    # Dane kupującego
    purchaser_email = order.get("purchaser_email", "") or ""
    purchaser_first_name = order.get("purchaser_first_name", "") or ""
    purchaser_last_name = order.get("purchaser_last_name", "") or ""
    purchaser_name = f"{purchaser_first_name} {purchaser_last_name}".strip()
    purchaser_nip = order.get("purchaser_nip", "") or ""
    
    # Kwota
    total_raw = order.get("total", 0)
    try:
        total_value = float(total_raw or 0)
    except Exception:
        total_value = 0.0
    currency_value = order.get("currency", "PLN") or "PLN"

    # 1. Sprawdź czy faktura końcowa (normal) już istnieje
    existing_docs = get_wfirma_documents(order_id)
    has_final_invoice = any((d or {}).get("document_type") == "normal" for d in (existing_docs or []))
    
    if has_final_invoice:
        # Faktura już istnieje - tylko zmień status
        print(f"[ADMIN MARK-PAID] Faktura końcowa już istnieje dla {order_id}, tylko zmieniam status")
        update_order_status(order_id, "paid")
        return redirect(url_for("admin_bp.order_detail", order_id=order_id, token=token))

    # 2. Pobierz konfigurację z payment_rules (opcjonalne - dla przyszłego użycia)
    payment_option_name = order.get("payment_option_name", "")
    payment_type = order.get("payment_type")
    rule = match_payment_rule(event_id, payment_option_name, payment_type) if event_id else None
    # rule może zawierać: wfirma_company, wfirma_series_name, wfirma_document_type, itp.
    # Na razie używamy domyślnych wartości z backstage_engine
    
    print(f"[ADMIN MARK-PAID] Tworzę fakturę końcową dla {order_id} | event={event_name[:30] if event_name else 'N/A'}, rule={rule.get('id') if rule else 'default'}")

    # 3. Przygotuj dane do faktury
    raw_payload = order.get("raw", {}) or {}
    
    # Wyciągnij dane rozliczeniowe
    billing_address_data = raw_payload.get("eventOrder_billingAddress", {}) or {}
    billing_address = billing_address_data.get("streetAddress1") or billing_address_data.get("street") or "-"
    billing_zip = billing_address_data.get("zipcode") or billing_address_data.get("zip") or "00-000"
    billing_city = billing_address_data.get("city") or "-"
    
    # Wyciągnij i wzbogać bilety
    enriched_tickets = []
    try:
        from backstage_engine import _extract_tickets_from_payload, _enrich_tickets_with_names
        
        raw_tickets = _extract_tickets_from_payload(raw_payload) if raw_payload else []
        if raw_tickets and event_id:
            enriched_tickets, unknown_ids = _enrich_tickets_with_names(raw_tickets, event_id)
            print(f"[ADMIN MARK-PAID] Wygenerowano {len(enriched_tickets)} pozycji biletów")
    except Exception as e:
        print(f"[ADMIN MARK-PAID] Błąd pobierania biletów: {e}")
    
    order_data_for_invoice = {
        "event_order_id": order_id,
        "event_id": event_id,
        "purchaser_email": purchaser_email,
        "purchaser_first_name": purchaser_first_name,
        "purchaser_last_name": purchaser_last_name,
        "purchaser_nip": purchaser_nip,
        "billing_address": billing_address,
        "billing_zip": billing_zip,
        "billing_city": billing_city,
        "total": total_value,
        "currency": currency_value,
        "tickets": enriched_tickets,
    }

    # 4. Generuj fakturę końcową
    invoice_created = False
    invoice_id = None
    invoice_number = None
    invoice_email_sent = False
    invoice_error = None
    
    try:
        from backstage_engine import _create_paid_invoice
        
        success, invoice_result, error = _create_paid_invoice(
            order_data=order_data_for_invoice,
            event_name=event_name,
            send_email=bool(purchaser_email),  # wFirma wyśle fakturę emailem
        )
        
        if success and invoice_result:
            invoice_created = True
            invoice_id = invoice_result.get("invoice", {}).get("id")
            invoice_number = invoice_result.get("invoice", {}).get("fullnumber")
            invoice_email_sent = invoice_result.get("email_sent", False)
            print(f"[ADMIN MARK-PAID] Faktura utworzona: {invoice_number} (ID: {invoice_id}), email_sent={invoice_email_sent}")
        else:
            invoice_error = error
            print(f"[ADMIN MARK-PAID] BŁĄD tworzenia faktury: {error}")
    except Exception as e:
        invoice_error = str(e)
        print(f"[ADMIN MARK-PAID] WYJĄTEK podczas tworzenia faktury: {e}")

    # 5. Aktualizuj status zamówienia
    update_order_status(order_id, "paid")

    # 6. Wyślij email z potwierdzeniem rezerwacji do kupującego (tylko jeśli nie był wysłany)
    purchaser_email_sent = False
    purchaser_email_error = None
    purchaser_email_already_sent = mail_log_exists(order_id, "payment_confirmation", "purchaser")
    
    if purchaser_email and not purchaser_email_already_sent:
        try:
            from email_templates import render_payment_confirmation_email
            from backstage_engine import _send_email_via_make
            
            purchaser_subject = f"Płatność potwierdzona! Twoja rezerwacja na {event_name}"
            
            purchaser_body_html = render_payment_confirmation_email(
                event_name=event_name,
                purchaser_first_name=purchaser_first_name or "Uczestnik",
                purchaser_last_name=purchaser_last_name,
                purchaser_email=purchaser_email,
                purchaser_phone=order.get("purchaser_phone", ""),
                total_gross=total_value,
                event_config=event_data,
                tickets=enriched_tickets,
            )
            
            # Zapisz do logu
            save_mail_log(
                event_order_id=order_id,
                direction="purchaser",
                template_key="payment_confirmation",
                to_email=purchaser_email,
                subject=purchaser_subject,
                data={
                    "event_order_id": order_id,
                    "event_name": event_name,
                    "purchaser_name": purchaser_name,
                    "total": total_value,
                    "currency": currency_value,
                    "payment_method": "Przelew (proforma)",
                },
            )
            
            # Wyślij email
            result = _send_email_via_make(
                to_email=purchaser_email,
                subject=purchaser_subject,
                body_html=purchaser_body_html,
                event_order_id=order_id,
                template_type="payment_confirmation",
            )
            
            if result.get("success"):
                purchaser_email_sent = True
                print(f"[ADMIN MARK-PAID] Email potwierdzenia wysłany do {purchaser_email}")
            else:
                purchaser_email_error = result.get("error", "Nieznany błąd")
                print(f"[ADMIN MARK-PAID] BŁĄD wysyłki emaila: {purchaser_email_error}")
        except Exception as e:
            purchaser_email_error = str(e)
            print(f"[ADMIN MARK-PAID] WYJĄTEK wysyłki emaila: {e}")
    elif purchaser_email_already_sent:
        print(f"[ADMIN MARK-PAID] Email potwierdzenia już był wysłany - pomijam duplikat")

    # 7. Email wewnętrzny
    import os
    internal_email = os.environ.get("BACKSTAGE_EVENT_INFO_EMAIL") or event_data.get("md_email_techniczny") or event_data.get("md_email_kontakt")
    
    if internal_email:
        try:
            from backstage_engine import _send_email_via_make
            
            # Określ treść emaila w zależności od wyniku
            if invoice_created and purchaser_email_sent:
                internal_subject = f"[PAID OK] Zamówienie opłacone (admin) – {event_name}"
                status_html = '<p style="color: #28a745;"><strong>✓ Faktura utworzona, email wysłany</strong></p>'
            elif invoice_created and purchaser_email_already_sent:
                internal_subject = f"[PAID OK] Zamówienie opłacone (admin) – {event_name}"
                status_html = '<p style="color: #28a745;"><strong>✓ Faktura utworzona</strong></p><p style="color: #17a2b8;">ℹ️ Email do kupującego był już wysłany wcześniej</p>'
            elif invoice_created:
                internal_subject = f"[PAID] Zamówienie opłacone, faktura OK – {event_name}"
                status_html = f'<p style="color: #ffc107;"><strong>✓ Faktura utworzona</strong></p><p style="color: #dc3545;">⚠️ Email nie wysłany: {purchaser_email_error or "brak adresu"}</p>'
            else:
                internal_subject = f"[PAID ERROR] Zamówienie opłacone, BŁĄD faktury – {event_name}"
                status_html = f'<p style="color: #dc3545;"><strong>❌ Błąd faktury: {invoice_error}</strong></p><p><strong>WYMAGANA AKCJA:</strong> Utwórz fakturę ręcznie w wFirma!</p>'
            
            internal_body_html = f"""
            <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2>Zamówienie oznaczone jako opłacone (panel admin)</h2>
                <p><strong>Zamówienie:</strong> {order_id}</p>
                <p><strong>Wydarzenie:</strong> {event_name}</p>
                <hr>
                <p><strong>Kupujący:</strong> {purchaser_name}</p>
                <p><strong>Email:</strong> {purchaser_email or "(brak)"}</p>
                <p><strong>NIP:</strong> {purchaser_nip or "(brak)"}</p>
                <p><strong>Kwota:</strong> {total_value} {currency_value}</p>
                <hr>
                {status_html}
                {f'<p><strong>Nr faktury:</strong> {invoice_number}</p>' if invoice_number else ''}
                <hr>
                <p style="color: #666; font-size: 12px;">Akcja wykonana przez panel admin.</p>
            </body>
            </html>
            """
            
            save_mail_log(
                event_order_id=order_id,
                direction="internal",
                template_key="internal_order_marked_paid",
                to_email=internal_email,
                subject=internal_subject,
                data={
                    "event_order_id": order_id,
                    "event_name": event_name,
                    "invoice_created": invoice_created,
                    "invoice_number": invoice_number,
                    "invoice_error": invoice_error,
                },
            )
            
            _send_email_via_make(
                to_email=internal_email,
                subject=internal_subject,
                body_html=internal_body_html,
                event_order_id=order_id,
                template_type="internal_order_marked_paid",
            )
        except Exception as e:
            print(f"[ADMIN MARK-PAID] Błąd wysyłki emaila wewnętrznego: {e}")

    # 8. Wyślij emaile do uczestników (jeśli są kompletne)
    try:
        from backstage_engine import send_participant_ticket_emails, attendee_webhooks_status
        
        comp = attendee_webhooks_status(order_id)
        if comp.get("complete"):
            stats = send_participant_ticket_emails(
                event_order_id=order_id,
                event_name=event_name,
                event_config=event_data,
            )
            print(f"[ADMIN MARK-PAID] Emaile do uczestników: sent={stats.get('sent', 0)}, failed={stats.get('failed', 0)}")
        else:
            print(f"[ADMIN MARK-PAID] Pomijam emaile do uczestników - brak kompletu webhooków")
    except Exception as e:
        print(f"[ADMIN MARK-PAID] Błąd wysyłki emaili do uczestników: {e}")

    # 9. Komunikat dla użytkownika
    if not invoice_created:
        flash(f"⚠️ UWAGA: Zamówienie oznaczone jako opłacone, ale faktura VAT NIE została wygenerowana! Błąd: {invoice_error}. Musisz utworzyć fakturę ręcznie w wFirma.", "error")
    elif purchaser_email_already_sent:
        flash(f"✓ Zamówienie opłacone! Faktura VAT: {invoice_number}. Email do kupującego był już wcześniej wysłany.", "success")
    elif not purchaser_email_sent and purchaser_email:
        flash(f"✓ Faktura VAT utworzona ({invoice_number}), ale email do kupującego nie został wysłany. Sprawdź logi.", "warning")
    elif not purchaser_email:
        flash(f"✓ Zamówienie opłacone! Faktura VAT: {invoice_number}. Brak adresu email kupującego.", "warning")
    else:
        flash(f"✓ Zamówienie opłacone! Faktura VAT: {invoice_number}, email wysłany do {purchaser_email}.", "success")

    return redirect(url_for("admin_bp.order_detail", order_id=order_id, token=token))


@admin_bp.route("/orders/<order_id>/delete", methods=["POST"])
@_require_permission("orders")
def order_delete(order_id: str):
    """
    Usuwa zamówienie i powiązane dane.
    
    UWAGA: Operacja nieodwracalna! Dokumenty wFirma NIE są usuwane automatycznie.
    """
    token = _require_admin_token()
    
    # Blokuj usuwanie dla viewera
    if _is_viewer(_get_current_admin_user()):
        abort(403, description="Brak uprawnień do usuwania")
    
    order = get_order(order_id)
    if not order:
        flash("Zamówienie nie istnieje lub zostało już usunięte.", "warning")
        return redirect(url_for("admin_bp.orders_list", token=token))
    
    # Zaloguj w audit logu przed usunięciem
    try:
        admin_user = _get_current_admin_user()
        insert_admin_audit_log(
            action="delete_order",
            admin_user_id=admin_user.get("id") if admin_user else None,
            target_email=order.get("purchaser_email", ""),
            ip=_get_client_ip(),
            user_agent=request.headers.get("User-Agent", "")[:500],
            data={
                "order_id": order_id,
                "event_id": order.get("event_id", ""),
                "total": order.get("total", 0),
                "status": order.get("status", ""),
            },
        )
    except Exception as e:
        print(f"[ADMIN DELETE ORDER] Błąd zapisu audit log: {e}")
    
    # Usuń zamówienie
    result = delete_order(order_id)
    
    if result.get("error"):
        flash(f"Błąd usuwania: {result['error']}", "error")
        return redirect(url_for("admin_bp.order_detail", order_id=order_id, token=token))
    
    flash(
        f"Zamówienie {order_id[:20]}... zostało usunięte. "
        f"Usunięto: {result.get('participants', 0)} uczestników, "
        f"{result.get('order_tickets', 0)} biletów, "
        f"{result.get('mail_log', 0)} logów maili.",
        "success"
    )
    return redirect(url_for("admin_bp.orders_list", token=token))


@admin_bp.route("/orders/<order_id>/generate-proforma", methods=["POST"])
@_require_permission("orders")
def order_generate_proforma(order_id: str):
    """
    Ręcznie generuje proformę dla zamówienia.
    
    Flow:
    1. Sprawdza czy proforma już istnieje
    2. Generuje proformę przez wFirma
    3. Wysyła email (jeśli nie był wysłany)
    4. Aktualizuje status na pending_payment
    """
    token = _require_admin_token()

    order = get_order(order_id)
    if not order:
        abort(404, description="Nie znaleziono zamówienia")

    # 1. Sprawdź czy proforma już istnieje
    existing_docs = get_wfirma_documents(order_id)
    has_proforma = any((d or {}).get("document_type") == "proforma" for d in (existing_docs or []))
    
    if has_proforma:
        flash("Proforma już istnieje dla tego zamówienia.", "warning")
        return redirect(url_for("admin_bp.order_detail", order_id=order_id, token=token))

    # Pobierz dane eventu
    event_id = order.get("event_id", "")
    ev = get_event(event_id) if event_id else None
    event_name = ev.get("event_name", "") if ev else ""
    event_data = (ev.get("data") if ev else {}) or {}

    # Dane kupującego
    purchaser_email = order.get("purchaser_email", "") or ""
    purchaser_first_name = order.get("purchaser_first_name", "") or ""
    purchaser_last_name = order.get("purchaser_last_name", "") or ""
    purchaser_name = f"{purchaser_first_name} {purchaser_last_name}".strip()
    purchaser_nip = order.get("purchaser_nip", "") or ""
    
    # Kwota
    total_raw = order.get("total", 0)
    try:
        total_value = float(total_raw or 0)
    except Exception:
        total_value = 0.0
    currency_value = order.get("currency", "PLN") or "PLN"

    print(f"[ADMIN GEN-PROFORMA] Tworzę proformę dla {order_id} | event={event_name[:30] if event_name else 'N/A'}")

    # Przygotuj dane do faktury
    raw_payload = order.get("raw", {}) or {}
    
    billing_address_data = raw_payload.get("eventOrder_billingAddress", {}) or {}
    billing_address = billing_address_data.get("streetAddress1") or billing_address_data.get("street") or "-"
    billing_zip = billing_address_data.get("zipcode") or billing_address_data.get("zip") or "00-000"
    billing_city = billing_address_data.get("city") or "-"
    
    # Wyciągnij i wzbogać bilety
    enriched_tickets = []
    try:
        from backstage_engine import _extract_tickets_from_payload, _enrich_tickets_with_names
        
        raw_tickets = _extract_tickets_from_payload(raw_payload) if raw_payload else []
        if raw_tickets and event_id:
            enriched_tickets, unknown_ids = _enrich_tickets_with_names(raw_tickets, event_id)
            print(f"[ADMIN GEN-PROFORMA] Wygenerowano {len(enriched_tickets)} pozycji biletów")
    except Exception as e:
        print(f"[ADMIN GEN-PROFORMA] Błąd pobierania biletów: {e}")
    
    order_data_for_invoice = {
        "event_order_id": order_id,
        "event_id": event_id,
        "purchaser_email": purchaser_email,
        "purchaser_first_name": purchaser_first_name,
        "purchaser_last_name": purchaser_last_name,
        "purchaser_nip": purchaser_nip,
        "billing_address": billing_address,
        "billing_zip": billing_zip,
        "billing_city": billing_city,
        "total": total_value,
        "currency": currency_value,
        "tickets": enriched_tickets,
    }

    # 2. Generuj proformę
    proforma_created = False
    proforma_number = None
    proforma_error = None
    
    try:
        from backstage_engine import _create_proforma_invoice
        
        success, proforma_result, error = _create_proforma_invoice(
            order_data=order_data_for_invoice,
            event_name=event_name,
            send_email=False,  # Nie wysyłamy przez wFirma, sami wyślemy
        )
        
        if success and proforma_result:
            proforma_created = True
            proforma_number = proforma_result.get("invoice", {}).get("fullnumber")
            print(f"[ADMIN GEN-PROFORMA] Proforma utworzona: {proforma_number}")
        else:
            proforma_error = error
            print(f"[ADMIN GEN-PROFORMA] BŁĄD tworzenia proformy: {error}")
    except Exception as e:
        proforma_error = str(e)
        print(f"[ADMIN GEN-PROFORMA] WYJĄTEK podczas tworzenia proformy: {e}")

    # 3. Aktualizuj status zamówienia
    if proforma_created:
        update_order_status(order_id, "pending_payment")

    # 4. Wyślij email z proformą (jeśli nie był wysłany)
    email_sent = False
    email_error = None
    
    if proforma_created and purchaser_email and not mail_log_exists(order_id, "proforma_sent", "purchaser"):
        try:
            from email_templates import render_proforma_reservation_email
            from backstage_engine import _send_email_via_make
            
            proforma_subject = f"Twoja rejestracja na {event_name} - płatność pro forma"
            
            proforma_body_html = render_proforma_reservation_email(
                event_name=event_name,
                purchaser_first_name=purchaser_first_name or "Uczestnik",
                purchaser_last_name=purchaser_last_name,
                purchaser_email=purchaser_email,
                total_gross=total_value,
                currency=currency_value,
                event_config=event_data,
                tickets=enriched_tickets,
                proforma_number=proforma_number,
            )
            
            save_mail_log(
                event_order_id=order_id,
                direction="purchaser",
                template_key="proforma_sent",
                to_email=purchaser_email,
                subject=proforma_subject,
                data={
                    "event_order_id": order_id,
                    "event_name": event_name,
                    "proforma_number": proforma_number,
                    "total": total_value,
                    "currency": currency_value,
                },
            )
            
            result = _send_email_via_make(
                to_email=purchaser_email,
                subject=proforma_subject,
                body_html=proforma_body_html,
                event_order_id=order_id,
                template_type="proforma_sent",
            )
            
            if result.get("success"):
                email_sent = True
                print(f"[ADMIN GEN-PROFORMA] Email z proformą wysłany do {purchaser_email}")
            else:
                email_error = result.get("error", "Nieznany błąd")
                print(f"[ADMIN GEN-PROFORMA] BŁĄD wysyłki emaila: {email_error}")
        except Exception as e:
            email_error = str(e)
            print(f"[ADMIN GEN-PROFORMA] WYJĄTEK wysyłki emaila: {e}")
    elif mail_log_exists(order_id, "proforma_sent", "purchaser"):
        print(f"[ADMIN GEN-PROFORMA] Email z proformą już był wysłany - pomijam")

    # 5. Komunikat dla użytkownika
    if not proforma_created:
        flash(f"❌ Błąd generowania proformy: {proforma_error}", "error")
    elif not email_sent and purchaser_email and not mail_log_exists(order_id, "proforma_sent", "purchaser"):
        flash(f"✓ Proforma utworzona ({proforma_number}), ale email nie został wysłany: {email_error}", "warning")
    elif not purchaser_email:
        flash(f"✓ Proforma utworzona ({proforma_number}). Brak adresu email kupującego.", "warning")
    else:
        flash(f"✓ Proforma utworzona ({proforma_number}) i email wysłany do {purchaser_email}.", "success")

    return redirect(url_for("admin_bp.order_detail", order_id=order_id, token=token))


@admin_bp.route("/orders/<order_id>/generate-invoice", methods=["POST"])
@_require_permission("orders")
def order_generate_invoice(order_id: str):
    """
    Ręcznie generuje fakturę końcową (VAT) dla zamówienia.
    
    Flow:
    1. Sprawdza czy faktura końcowa już istnieje
    2. Sprawdza czy zamówienie jest opłacone
    3. Generuje fakturę przez wFirma
    4. Wysyła email potwierdzenia (jeśli nie był wysłany)
    """
    token = _require_admin_token()

    order = get_order(order_id)
    if not order:
        abort(404, description="Nie znaleziono zamówienia")

    status = order.get("status", "received")
    
    # Sprawdź czy zamówienie jest opłacone
    if status != "paid":
        flash(f"Nie można wygenerować faktury końcowej - zamówienie nie jest opłacone (status: {status}). Użyj 'Oznacz jako opłacone'.", "error")
        return redirect(url_for("admin_bp.order_detail", order_id=order_id, token=token))

    # 1. Sprawdź czy faktura końcowa już istnieje
    existing_docs = get_wfirma_documents(order_id)
    has_final_invoice = any((d or {}).get("document_type") == "normal" for d in (existing_docs or []))
    
    if has_final_invoice:
        flash("Faktura końcowa już istnieje dla tego zamówienia.", "warning")
        return redirect(url_for("admin_bp.order_detail", order_id=order_id, token=token))

    # Pobierz dane eventu
    event_id = order.get("event_id", "")
    ev = get_event(event_id) if event_id else None
    event_name = ev.get("event_name", "") if ev else ""
    event_data = (ev.get("data") if ev else {}) or {}

    # Dane kupującego
    purchaser_email = order.get("purchaser_email", "") or ""
    purchaser_first_name = order.get("purchaser_first_name", "") or ""
    purchaser_last_name = order.get("purchaser_last_name", "") or ""
    purchaser_name = f"{purchaser_first_name} {purchaser_last_name}".strip()
    purchaser_nip = order.get("purchaser_nip", "") or ""
    
    # Kwota
    total_raw = order.get("total", 0)
    try:
        total_value = float(total_raw or 0)
    except Exception:
        total_value = 0.0
    currency_value = order.get("currency", "PLN") or "PLN"

    print(f"[ADMIN GEN-INVOICE] Tworzę fakturę końcową dla {order_id} | event={event_name[:30] if event_name else 'N/A'}")

    # Przygotuj dane do faktury
    raw_payload = order.get("raw", {}) or {}
    
    billing_address_data = raw_payload.get("eventOrder_billingAddress", {}) or {}
    billing_address = billing_address_data.get("streetAddress1") or billing_address_data.get("street") or "-"
    billing_zip = billing_address_data.get("zipcode") or billing_address_data.get("zip") or "00-000"
    billing_city = billing_address_data.get("city") or "-"
    
    # Wyciągnij i wzbogać bilety
    enriched_tickets = []
    try:
        from backstage_engine import _extract_tickets_from_payload, _enrich_tickets_with_names
        
        raw_tickets = _extract_tickets_from_payload(raw_payload) if raw_payload else []
        if raw_tickets and event_id:
            enriched_tickets, unknown_ids = _enrich_tickets_with_names(raw_tickets, event_id)
            print(f"[ADMIN GEN-INVOICE] Wygenerowano {len(enriched_tickets)} pozycji biletów")
    except Exception as e:
        print(f"[ADMIN GEN-INVOICE] Błąd pobierania biletów: {e}")
    
    order_data_for_invoice = {
        "event_order_id": order_id,
        "event_id": event_id,
        "purchaser_email": purchaser_email,
        "purchaser_first_name": purchaser_first_name,
        "purchaser_last_name": purchaser_last_name,
        "purchaser_nip": purchaser_nip,
        "billing_address": billing_address,
        "billing_zip": billing_zip,
        "billing_city": billing_city,
        "total": total_value,
        "currency": currency_value,
        "tickets": enriched_tickets,
    }

    # 2. Generuj fakturę końcową
    invoice_created = False
    invoice_number = None
    invoice_error = None
    
    try:
        from backstage_engine import _create_paid_invoice
        
        success, invoice_result, error = _create_paid_invoice(
            order_data=order_data_for_invoice,
            event_name=event_name,
            send_email=False,  # Nie wysyłamy przez wFirma, sami wyślemy
        )
        
        if success and invoice_result:
            invoice_created = True
            invoice_number = invoice_result.get("invoice", {}).get("fullnumber")
            print(f"[ADMIN GEN-INVOICE] Faktura utworzona: {invoice_number}")
        else:
            invoice_error = error
            print(f"[ADMIN GEN-INVOICE] BŁĄD tworzenia faktury: {error}")
    except Exception as e:
        invoice_error = str(e)
        print(f"[ADMIN GEN-INVOICE] WYJĄTEK podczas tworzenia faktury: {e}")

    # 3. Wyślij email potwierdzenia (jeśli nie był wysłany)
    email_sent = False
    email_error = None
    
    if invoice_created and purchaser_email and not mail_log_exists(order_id, "payment_confirmation", "purchaser"):
        try:
            from email_templates import render_payment_confirmation_email
            from backstage_engine import _send_email_via_make
            
            confirmation_subject = f"Płatność potwierdzona! Twoja rezerwacja na {event_name}"
            
            confirmation_body_html = render_payment_confirmation_email(
                event_name=event_name,
                purchaser_first_name=purchaser_first_name or "Uczestnik",
                purchaser_last_name=purchaser_last_name,
                purchaser_email=purchaser_email,
                purchaser_phone=order.get("purchaser_phone", ""),
                total_gross=total_value,
                event_config=event_data,
                tickets=enriched_tickets,
            )
            
            save_mail_log(
                event_order_id=order_id,
                direction="purchaser",
                template_key="payment_confirmation",
                to_email=purchaser_email,
                subject=confirmation_subject,
                data={
                    "event_order_id": order_id,
                    "event_name": event_name,
                    "invoice_number": invoice_number,
                    "total": total_value,
                    "currency": currency_value,
                },
            )
            
            result = _send_email_via_make(
                to_email=purchaser_email,
                subject=confirmation_subject,
                body_html=confirmation_body_html,
                event_order_id=order_id,
                template_type="payment_confirmation",
            )
            
            if result.get("success"):
                email_sent = True
                print(f"[ADMIN GEN-INVOICE] Email potwierdzenia wysłany do {purchaser_email}")
            else:
                email_error = result.get("error", "Nieznany błąd")
                print(f"[ADMIN GEN-INVOICE] BŁĄD wysyłki emaila: {email_error}")
        except Exception as e:
            email_error = str(e)
            print(f"[ADMIN GEN-INVOICE] WYJĄTEK wysyłki emaila: {e}")
    elif mail_log_exists(order_id, "payment_confirmation", "purchaser"):
        print(f"[ADMIN GEN-INVOICE] Email potwierdzenia już był wysłany - pomijam")

    # 4. Komunikat dla użytkownika
    if not invoice_created:
        flash(f"❌ Błąd generowania faktury końcowej: {invoice_error}", "error")
    elif not email_sent and purchaser_email and not mail_log_exists(order_id, "payment_confirmation", "purchaser"):
        flash(f"✓ Faktura końcowa utworzona ({invoice_number}), ale email nie został wysłany: {email_error}", "warning")
    elif not purchaser_email:
        flash(f"✓ Faktura końcowa utworzona ({invoice_number}). Brak adresu email kupującego.", "warning")
    else:
        flash(f"✓ Faktura końcowa utworzona ({invoice_number}) i email wysłany do {purchaser_email}.", "success")

    return redirect(url_for("admin_bp.order_detail", order_id=order_id, token=token))


# ---------------------------------------------------------------------------
# ZARZĄDZANIE KONTAMI ADMIN
# ---------------------------------------------------------------------------

@admin_bp.route("/users", methods=["GET"])
@_require_permission("users")
def users_list():
    """Lista kont admina."""
    token = _require_admin_token()
    current_user = _get_current_admin_user()
    can_audit = _user_has_permission(current_user, "audit")
    
    users = list_admin_users()
    
    rows = []
    for u in users:
        status_badge = '<span class="pill pill-success">Aktywne</span>' if u.get("is_active") else '<span class="pill pill-error">Nieaktywne</span>'
        role = (u.get("role") or "user").lower()
        if role == "admin":
            role_badge = '<span class="pill pill-primary">Admin</span>'
        elif role == "viewer":
            role_badge = '<span class="pill" style="background:#e0f2fe; color:#0369a1;">Viewer</span>'
        else:
            role_badge = '<span class="pill pill-neutral">Użytkownik</span>'
        first_name = (u.get("first_name") or "").strip()
        last_name = (u.get("last_name") or "").strip()
        full_name = (f"{first_name} {last_name}".strip()) or "—"
        allowed = _normalize_allowed_pages(u.get("allowed_pages"))
        allowed_events = _normalize_allowed_events(u.get("allowed_events"))
        labels = {k: v for k, v in ADMIN_PAGE_OPTIONS}
        if role == "admin":
            permissions_label = "pełny dostęp"
        elif role == "viewer":
            events_count = len(allowed_events)
            permissions_label = f"{events_count} wydarzeń" if events_count else "brak wydarzeń"
        else:
            permissions_label = ", ".join([labels.get(k, k) for k in allowed]) if allowed else "brak"
        locked = ""
        if u.get("locked_until"):
            import datetime
            locked_until = u["locked_until"]
            now = datetime.datetime.now(datetime.timezone.utc)
            if isinstance(locked_until, datetime.datetime) and locked_until > now:
                locked = f'<span class="pill pill-warning">Zablokowany do {locked_until.strftime("%H:%M")}</span>'
        
        last_login = str(u.get("last_login_at", ""))[:16] if u.get("last_login_at") else "—"
        
        # Generate initials for avatar
        email = u.get('email', '')
        initials = email[0].upper() if email else "?"
        
        rows.append(f"""
            <tr>
              <td>
                <div style="display:flex; align-items:center; gap:12px;">
                  <div style="width:36px; height:36px; border-radius:50%; background:linear-gradient(135deg, #00E09F, #00A1D7); display:flex; align-items:center; justify-content:center; color:#fff; font-weight:600; font-size:14px;">{initials}</div>
                  <span>{email}</span>
                </div>
              </td>
              <td>{full_name}</td>
              <td><div style="display:flex; gap:6px; flex-wrap:wrap;">{role_badge}</div></td>
              <td><span class="muted">{permissions_label}</span></td>
              <td><div style="display:flex; gap:6px; flex-wrap:wrap;">{status_badge} {locked}</div></td>
              <td><span class="muted">{last_login}</span></td>
              <td><span class="muted">{str(u.get('created_at', ''))[:16]}</span></td>
              <td>
                <div style="display:flex; gap:6px;">
                  <a href="{url_for('admin_bp.user_access', user_id=u['id'], token=token)}" class="btn" style="padding:6px 12px; font-size:12px;">Uprawnienia</a>
                  <a href="{url_for('admin_bp.user_reset_password', user_id=u['id'], token=token)}" class="btn" style="padding:6px 12px; font-size:12px;">Reset hasła</a>
                  {f'<a href="{url_for("admin_bp.user_disable", user_id=u["id"], token=token)}" class="btn" style="padding:6px 12px; font-size:12px;">Dezaktywuj</a>' if u.get('is_active') else f'<a href="{url_for("admin_bp.user_enable", user_id=u["id"], token=token)}" class="btn btnPrimary" style="padding:6px 12px; font-size:12px;">Aktywuj</a>'}
                </div>
              </td>
            </tr>
        """)
    
    body = f"""
    <style>
      .users-toolbar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 24px;
      }}
      .users-table-wrapper {{
        background: #fff;
        border: 1px solid var(--md-border);
        border-radius: 12px;
        overflow: hidden;
        max-width: 1100px;
        margin: 0 auto;
      }}
      .users-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;
      }}
      .users-table th {{
        text-align: left;
        padding: 10px 12px;
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--md-text-muted);
        background: #f8fafc;
        border-bottom: 2px solid var(--md-border);
      }}
      .users-table td {{
        padding: 10px 12px;
        border-bottom: 1px solid #f1f5f9;
        vertical-align: middle;
      }}
      .users-table tbody tr {{
        transition: background 0.15s ease;
      }}
      .users-table tbody tr:hover {{
        background: #f8fafc;
      }}
      .users-table tbody tr:last-child td {{
        border-bottom: none;
      }}
      .audit-link {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        margin-top: 20px;
        padding: 12px 16px;
        background: #f8fafc;
        border: 1px solid var(--md-border);
        border-radius: 8px;
        color: var(--md-text-muted);
        font-size: 13px;
        transition: all 0.15s ease;
      }}
      .audit-link:hover {{
        background: #f1f5f9;
        color: var(--md-primary);
        text-decoration: none;
      }}
    </style>

    <div class="users-toolbar">
      <div class="muted">Zarządzanie dostępami do panelu</div>
      <a class="btn btnPrimary" href="{url_for('admin_bp.user_new', token=token)}">+ Dodaj użytkownika</a>
    </div>

    <div class="users-table-wrapper">
      <table class="users-table">
        <thead>
          <tr>
            <th>Email</th>
            <th>Imię i nazwisko</th>
            <th>Rola</th>
            <th>Uprawnienia</th>
            <th>Status</th>
            <th>Ostatnie logowanie</th>
            <th>Utworzono</th>
            <th>Akcje</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows) if rows else '<tr><td colspan="8" style="padding:40px; text-align:center; color:var(--md-text-muted);">Brak kont użytkowników</td></tr>'}
        </tbody>
      </table>
    </div>
    
    {f'<a href="{url_for("admin_bp.audit_log", token=token)}" class="audit-link"><span>📋</span> Zobacz log audytu</a>' if can_audit else ''}
    """
    return _page("Konta i uprawnienia", body)


@admin_bp.route("/users/new", methods=["GET", "POST"])
@_require_permission("users")
def user_new():
    """Dodawanie nowego konta admina."""
    token = _require_admin_token()
    current_user = getattr(request, "admin_user", None)
    
    error = None
    success = None
    
    if request.method == "POST":
        # Weryfikacja CSRF
        if not _verify_csrf_token():
            error = "Błąd CSRF - odśwież stronę i spróbuj ponownie"
        else:
            email = (request.form.get("email") or "").strip().lower()
            first_name = (request.form.get("first_name") or "").strip()
            last_name = (request.form.get("last_name") or "").strip()
            role = (request.form.get("role") or "user").strip().lower()
            allowed_pages = request.form.getlist("allowed_pages") or []
            allowed_events = request.form.getlist("allowed_events") or []

            if not email or "@" not in email:
                error = "Podaj prawidłowy adres email"
            elif get_admin_user_by_email(email):
                error = "Konto z tym emailem już istnieje"
            elif role not in ("admin", "user", "viewer"):
                error = "Nieprawidłowa rola użytkownika"
            else:
                temp_password = _generate_temp_password()
                password_hash = generate_password_hash(temp_password)
                user = create_admin_user(
                    email=email,
                    password_hash=password_hash,
                    first_name=first_name,
                    last_name=last_name,
                    role=role,
                    allowed_pages=allowed_pages if role != "admin" else [],
                    allowed_events=allowed_events if role == "viewer" else [],
                    must_change_password=True,
                )
                
                if user:
                    email_ok = _send_admin_credentials_email(
                        to_email=email,
                        full_name=f"{first_name} {last_name}".strip(),
                        temp_password=temp_password,
                        is_reset=False,
                    )
                    insert_admin_audit_log(
                        action="create_user",
                        admin_user_id=current_user["id"] if current_user else None,
                        target_email=email,
                        ip=_get_client_ip(),
                        user_agent=request.headers.get("User-Agent", "")[:500],
                        data={"role": role, "allowed_pages": allowed_pages, "allowed_events": allowed_events, "email_sent": email_ok},
                    )
                    success = f"Konto {email} zostało utworzone. Hasło wysłane mailem."
                    if not email_ok:
                        success += " (Uwaga: nie udało się wysłać maila)"
                else:
                    error = "Błąd podczas tworzenia konta"
    
    csrf_token = _generate_csrf_token()
    events = list_events(limit=100)
    events_checkbox_rows = []
    for e in events:
        eid = str(e.get("event_id") or "")
        data = e.get("data") or {}
        color = data.get("color_gradient_1") or "#e2e8f0"
        city = data.get("event_location_city") or data.get("event_address_text_city") or "—"
        name = e.get("event_name") or "—"
        events_checkbox_rows.append(
            f'''
            <label class="event-card">
              <input type="checkbox" name="allowed_events" value="{eid}" />
              <div>
                <div class="event-card-title">
                  <span class="event-color-dot" style="background:{color};"></span>
                  {name}
                </div>
                <div class="event-card-meta">
                  <span>{city}</span>
                  <code class="event-id">{eid}</code>
                </div>
              </div>
            </label>
            '''
        )
    events_checkbox_html = "".join(events_checkbox_rows) or '<div class="muted">Brak wydarzeń</div>'
    
    body = f"""
    <style>
      .form-card {{
        max-width: 480px;
        margin: 0 auto;
        background: #fff;
        border: 1px solid var(--md-border);
        border-radius: 12px;
        overflow: hidden;
      }}
      .form-card-header {{
        padding: 20px 24px;
        background: #f8fafc;
        border-bottom: 1px solid var(--md-border);
      }}
      .form-card-header h3 {{
        margin: 0;
        font-size: 18px;
        font-weight: 600;
      }}
      .form-card-body {{
        padding: 24px;
      }}
      .form-group {{
        margin-bottom: 20px;
      }}
      .form-group label {{
        display: block;
        font-size: 13px;
        font-weight: 500;
        color: var(--md-text-muted);
        margin-bottom: 6px;
      }}
      .form-group input {{
        width: 100%;
        padding: 12px 14px;
        border: 1px solid var(--md-border);
        border-radius: 8px;
        font-size: 14px;
      }}
      .permissions-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
        gap: 10px;
      }}
      .perm-item {{
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 10px;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        background: #fff;
        font-size: 13px;
        color: #0f172a;
      }}
      .perm-item input {{
        margin: 0;
      }}
      .events-grid-wrapper {{
        max-height: 260px;
        overflow-y: auto;
        border: 1px solid var(--md-border);
        border-radius: 10px;
        padding: 12px;
        background: #f8fafc;
      }}
      .events-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        gap: 10px;
      }}
      .event-card {{
        display: flex;
        gap: 10px;
        align-items: flex-start;
        padding: 10px 12px;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        background: #fff;
        cursor: pointer;
      }}
      .event-card:hover {{
        border-color: #cbd5e1;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
      }}
      .event-card input {{
        margin-top: 2px;
      }}
      .event-card-title {{
        font-weight: 600;
        font-size: 13px;
        color: #0f172a;
        display: flex;
        align-items: center;
        gap: 6px;
      }}
      .event-color-dot {{
        width: 10px;
        height: 10px;
        border-radius: 50%;
        border: 1px solid #e2e8f0;
        display: inline-block;
      }}
      .event-card-meta {{
        font-size: 11px;
        color: #64748b;
        margin-top: 4px;
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }}
      .event-id {{
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        color: #94a3b8;
      }}
      .form-group input:focus {{
        outline: none;
        border-color: var(--md-primary);
        box-shadow: 0 0 0 3px rgba(0, 101, 215, 0.1);
      }}
    </style>

    <div style="margin-bottom:20px;">
      <a class="btn" href="{url_for('admin_bp.users_list', token=token)}">← Lista kont</a>
    </div>
    
    <div class="form-card">
      <div class="form-card-header">
        <h3>Dodaj nowe konto</h3>
      </div>
      <div class="form-card-body">
        {f'<div class="ok" style="margin-bottom:20px;">{success}</div>' if success else ''}
        {f'<div class="error" style="margin-bottom:20px;">{error}</div>' if error else ''}
        
        <form method="post" action="{url_for('admin_bp.user_new', token=token)}">
          <input type="hidden" name="csrf_token" value="{csrf_token}" />
          
          <div class="form-group">
            <label for="email">Adres email</label>
            <input type="email" id="email" name="email" required placeholder="admin@example.com" />
          </div>

          <div class="form-group">
            <label for="first_name">Imię</label>
            <input type="text" id="first_name" name="first_name" placeholder="Imię" />
          </div>

          <div class="form-group">
            <label for="last_name">Nazwisko</label>
            <input type="text" id="last_name" name="last_name" placeholder="Nazwisko" />
          </div>

          <div class="form-group">
            <label for="role">Rola</label>
            <select id="role" name="role" onchange="toggleEventSection()">
              <option value="user" selected>Użytkownik (ograniczony dostęp)</option>
              <option value="viewer">Viewer (tylko podgląd)</option>
              <option value="admin">Admin (pełny dostęp)</option>
            </select>
          </div>

          <div class="form-group">
            <label>Uprawnienia do kart</label>
            <div class="permissions-grid">
              {''.join([f'<label class="perm-item"><input type="checkbox" name="allowed_pages" value="{k}" checked /> {label}</label>' for k, label in ADMIN_PAGE_OPTIONS])}
            </div>
            <div class="muted" style="margin-top:8px;">Admin ma pełny dostęp niezależnie od wyboru.</div>
          </div>
          
          <div id="events-section" class="form-group" style="display:none;">
            <label>Dostęp do wydarzeń <span style="font-weight:normal; color:#64748b;">(tylko dla roli Viewer)</span></label>
            <div class="events-grid-wrapper">
              <div class="events-grid">
                {events_checkbox_html}
              </div>
            </div>
            <div class="muted" style="margin-top:8px;">Viewer widzi tylko wybrane wydarzenia i ich zamówienia (bez możliwości edycji).</div>
          </div>
          
          <div class="info" style="margin-bottom:16px;">
            Hasło jest generowane automatycznie i wysyłane mailem. Po pierwszym logowaniu wymagamy zmiany hasła.
          </div>
          
          <button class="btn btnPrimary" type="submit" style="width:100%;">Utwórz konto i wyślij hasło</button>
        </form>
      </div>
    </div>
    
    <script>
      function toggleEventSection() {{
        var role = document.getElementById('role').value;
        var section = document.getElementById('events-section');
        section.style.display = (role === 'viewer') ? 'block' : 'none';
      }}
      // Uruchom przy ładowaniu strony
      toggleEventSection();
    </script>
    """
    return _page("Nowe konto", body)


@admin_bp.route("/users/<int:user_id>/reset-password", methods=["GET", "POST"])
@_require_permission("users")
def user_reset_password(user_id: int):
    """Reset hasła dla konta admina."""
    token = _require_admin_token()
    current_user = getattr(request, "admin_user", None)
    
    target_user = get_admin_user_by_id(user_id)
    if not target_user:
        abort(404, description="Nie znaleziono konta")
    
    error = None
    success = None
    
    if request.method == "POST":
        if not _verify_csrf_token():
            error = "Błąd CSRF - odśwież stronę i spróbuj ponownie"
        else:
            temp_password = _generate_temp_password()
            password_hash = generate_password_hash(temp_password)
            if update_admin_user_password(user_id, password_hash, must_change_password=True):
                email_ok = _send_admin_credentials_email(
                    to_email=target_user["email"],
                    full_name=f"{target_user.get('first_name','')} {target_user.get('last_name','')}".strip(),
                    temp_password=temp_password,
                    is_reset=True,
                )
                insert_admin_audit_log(
                    action="reset_password",
                    admin_user_id=current_user["id"] if current_user else None,
                    target_email=target_user["email"],
                    ip=_get_client_ip(),
                    user_agent=request.headers.get("User-Agent", "")[:500],
                    data={"email_sent": email_ok},
                )
                success = f"Nowe hasło wysłane do {target_user['email']}"
                if not email_ok:
                    success += " (Uwaga: nie udało się wysłać maila)"
            else:
                error = "Błąd podczas zmiany hasła"
    
    csrf_token = _generate_csrf_token()
    
    body = f"""
    <style>
      .form-card {{
        max-width: 480px;
        margin: 0 auto;
        background: #fff;
        border: 1px solid var(--md-border);
        border-radius: 12px;
        overflow: hidden;
      }}
      .form-card-header {{
        padding: 20px 24px;
        background: #f8fafc;
        border-bottom: 1px solid var(--md-border);
      }}
      .form-card-header h3 {{
        margin: 0 0 4px 0;
        font-size: 18px;
        font-weight: 600;
      }}
      .form-card-header .muted {{
        margin: 0;
      }}
      .form-card-body {{
        padding: 24px;
      }}
      .form-group {{
        margin-bottom: 20px;
      }}
      .form-group label {{
        display: block;
        font-size: 13px;
        font-weight: 500;
        color: var(--md-text-muted);
        margin-bottom: 6px;
      }}
      .form-group input {{
        width: 100%;
        padding: 12px 14px;
        border: 1px solid var(--md-border);
        border-radius: 8px;
        font-size: 14px;
      }}
      .form-group input:focus {{
        outline: none;
        border-color: var(--md-primary);
        box-shadow: 0 0 0 3px rgba(0, 101, 215, 0.1);
      }}
    </style>

    <div style="margin-bottom:20px;">
      <a class="btn" href="{url_for('admin_bp.users_list', token=token)}">← Lista kont</a>
    </div>
    
    <div class="form-card">
      <div class="form-card-header">
        <h3>Reset hasła</h3>
        <p class="muted">Konto: <b>{target_user['email']}</b></p>
      </div>
      <div class="form-card-body">
        {f'<div class="ok" style="margin-bottom:20px;">{success}</div>' if success else ''}
        {f'<div class="error" style="margin-bottom:20px;">{error}</div>' if error else ''}
        
        <form method="post" action="{url_for('admin_bp.user_reset_password', user_id=user_id, token=token)}">
          <input type="hidden" name="csrf_token" value="{csrf_token}" />
          <div class="info" style="margin-bottom:16px;">
            System wygeneruje nowe hasło, wyśle je mailem i wymusi zmianę po pierwszym logowaniu.
          </div>
          
          <button class="btn btnPrimary" type="submit" style="width:100%;">Resetuj i wyślij hasło</button>
        </form>
      </div>
    </div>
    """
    return _page("Reset hasła", body)


@admin_bp.route("/users/<int:user_id>/access", methods=["GET", "POST"])
@_require_permission("users")
def user_access(user_id: int):
    """Edycja uprawnień i danych użytkownika."""
    token = _require_admin_token()
    current_user = getattr(request, "admin_user", None)

    target_user = get_admin_user_by_id(user_id)
    if not target_user:
        abort(404, description="Nie znaleziono konta")

    error = None
    success = None
    allowed_current = _normalize_allowed_pages(target_user.get("allowed_pages"))
    allowed_events_current = _normalize_allowed_events(target_user.get("allowed_events"))
    if (target_user.get("role") or "user").lower() == "admin":
        allowed_current = [k for k, _ in ADMIN_PAGE_OPTIONS]

    if request.method == "POST":
        if not _verify_csrf_token():
            error = "Błąd CSRF - odśwież stronę i spróbuj ponownie"
        else:
            first_name = (request.form.get("first_name") or "").strip()
            last_name = (request.form.get("last_name") or "").strip()
            role = (request.form.get("role") or "user").strip().lower()
            allowed_pages = request.form.getlist("allowed_pages") or []
            allowed_events = request.form.getlist("allowed_events") or []

            if role not in ("admin", "user", "viewer"):
                error = "Nieprawidłowa rola użytkownika"
            else:
                ok = update_admin_user_access(
                    user_id=user_id,
                    first_name=first_name,
                    last_name=last_name,
                    role=role,
                    allowed_pages=allowed_pages if role != "admin" else [],
                    allowed_events=allowed_events if role == "viewer" else [],
                )
                if ok:
                    insert_admin_audit_log(
                        action="update_user_access",
                        admin_user_id=current_user["id"] if current_user else None,
                        target_email=target_user["email"],
                        ip=_get_client_ip(),
                        user_agent=request.headers.get("User-Agent", "")[:500],
                        data={"role": role, "allowed_pages": allowed_pages, "allowed_events": allowed_events},
                    )
                    success = "Zapisano uprawnienia"
                    target_user = get_admin_user_by_id(user_id) or target_user
                    allowed_current = _normalize_allowed_pages(target_user.get("allowed_pages"))
                    allowed_events_current = _normalize_allowed_events(target_user.get("allowed_events"))
                    if (target_user.get("role") or "user").lower() == "admin":
                        allowed_current = [k for k, _ in ADMIN_PAGE_OPTIONS]
                else:
                    error = "Nie udało się zapisać zmian"

    csrf_token = _generate_csrf_token()
    role_value = (target_user.get("role") or "user").lower()
    full_name = f"{target_user.get('first_name','')} {target_user.get('last_name','')}".strip()
    events = list_events(limit=100)
    events_checkbox_rows = []
    for e in events:
        eid = str(e.get("event_id") or "")
        data = e.get("data") or {}
        color = data.get("color_gradient_1") or "#e2e8f0"
        city = data.get("event_location_city") or data.get("event_address_text_city") or "—"
        name = e.get("event_name") or "—"
        checked_attr = "checked" if eid in allowed_events_current else ""
        events_checkbox_rows.append(
            f'''
            <label class="event-card">
              <input type="checkbox" name="allowed_events" value="{eid}" {checked_attr} />
              <div>
                <div class="event-card-title">
                  <span class="event-color-dot" style="background:{color};"></span>
                  {name}
                </div>
                <div class="event-card-meta">
                  <span>{city}</span>
                  <code class="event-id">{eid}</code>
                </div>
              </div>
            </label>
            '''
        )
    events_checkbox_html = "".join(events_checkbox_rows) or '<div class="muted">Brak wydarzeń</div>'

    body = f"""
    <style>
      .form-card {{
        max-width: 520px;
        margin: 0 auto;
        background: #fff;
        border: 1px solid var(--md-border);
        border-radius: 12px;
        overflow: hidden;
      }}
      .form-card-header {{
        padding: 20px 24px;
        background: #f8fafc;
        border-bottom: 1px solid var(--md-border);
      }}
      .form-card-body {{
        padding: 24px;
      }}
      .form-group {{
        margin-bottom: 18px;
      }}
      .form-group label {{
        display: block;
        font-size: 13px;
        font-weight: 500;
        color: var(--md-text-muted);
        margin-bottom: 6px;
      }}
      .form-group input, .form-group select {{
        width: 100%;
        padding: 12px 14px;
        border: 1px solid var(--md-border);
        border-radius: 8px;
        font-size: 14px;
      }}
      .permissions-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
        gap: 10px;
      }}
      .perm-item {{
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 10px;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        background: #fff;
        font-size: 13px;
        color: #0f172a;
      }}
      .perm-item input {{
        margin: 0;
      }}
      .events-grid-wrapper {{
        max-height: 260px;
        overflow-y: auto;
        border: 1px solid var(--md-border);
        border-radius: 10px;
        padding: 12px;
        background: #f8fafc;
      }}
      .events-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        gap: 10px;
      }}
      .event-card {{
        display: flex;
        gap: 10px;
        align-items: flex-start;
        padding: 10px 12px;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        background: #fff;
        cursor: pointer;
      }}
      .event-card:hover {{
        border-color: #cbd5e1;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
      }}
      .event-card input {{
        margin-top: 2px;
      }}
      .event-card-title {{
        font-weight: 600;
        font-size: 13px;
        color: #0f172a;
        display: flex;
        align-items: center;
        gap: 6px;
      }}
      .event-color-dot {{
        width: 10px;
        height: 10px;
        border-radius: 50%;
        border: 1px solid #e2e8f0;
        display: inline-block;
      }}
      .event-card-meta {{
        font-size: 11px;
        color: #64748b;
        margin-top: 4px;
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }}
      .event-id {{
        font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        color: #94a3b8;
      }}
      .form-group input:focus, .form-group select:focus {{
        outline: none;
        border-color: var(--md-primary);
        box-shadow: 0 0 0 3px rgba(0, 101, 215, 0.1);
      }}
    </style>

    <div style="margin-bottom:20px;">
      <a class="btn" href="{url_for('admin_bp.users_list', token=token)}">← Lista kont</a>
    </div>

    <div class="form-card">
      <div class="form-card-header">
        <h3>Uprawnienia użytkownika</h3>
        <p class="muted">Konto: <b>{target_user.get('email')}</b></p>
      </div>
      <div class="form-card-body">
        {f'<div class="ok" style="margin-bottom:20px;">{success}</div>' if success else ''}
        {f'<div class="error" style="margin-bottom:20px;">{error}</div>' if error else ''}

        <form method="post" action="{url_for('admin_bp.user_access', user_id=user_id, token=token)}">
          <input type="hidden" name="csrf_token" value="{csrf_token}" />

          <div class="form-group">
            <label for="first_name">Imię</label>
            <input type="text" id="first_name" name="first_name" value="{target_user.get('first_name') or ''}" />
          </div>

          <div class="form-group">
            <label for="last_name">Nazwisko</label>
            <input type="text" id="last_name" name="last_name" value="{target_user.get('last_name') or ''}" />
          </div>

          <div class="form-group">
            <label for="role">Rola</label>
            <select id="role" name="role" onchange="toggleEventSectionEdit()">
              <option value="user" {'selected' if role_value == 'user' else ''}>Użytkownik (ograniczony dostęp)</option>
              <option value="viewer" {'selected' if role_value == 'viewer' else ''}>Viewer (tylko podgląd)</option>
              <option value="admin" {'selected' if role_value == 'admin' else ''}>Admin (pełny dostęp)</option>
            </select>
          </div>

          <div class="form-group">
            <label>Uprawnienia do kart</label>
            <div class="permissions-grid">
              {''.join([f'<label class="perm-item"><input type="checkbox" name="allowed_pages" value="{k}" {"checked" if k in allowed_current else ""} /> {label}</label>' for k, label in ADMIN_PAGE_OPTIONS])}
            </div>
            <div class="muted" style="margin-top:8px;">Admin ma pełny dostęp niezależnie od wyboru.</div>
          </div>
          
          <div id="events-section-edit" class="form-group" style="display:{'block' if role_value == 'viewer' else 'none'};">
            <label>Dostęp do wydarzeń <span style="font-weight:normal; color:#64748b;">(tylko dla roli Viewer)</span></label>
            <div class="events-grid-wrapper">
              <div class="events-grid">
                {events_checkbox_html}
              </div>
            </div>
            <div class="muted" style="margin-top:8px;">Viewer widzi tylko wybrane wydarzenia i ich zamówienia (bez możliwości edycji).</div>
          </div>

          <button class="btn btnPrimary" type="submit">Zapisz</button>
        </form>
      </div>
    </div>
    
    <script>
      function toggleEventSectionEdit() {{
        var role = document.getElementById('role').value;
        var section = document.getElementById('events-section-edit');
        section.style.display = (role === 'viewer') ? 'block' : 'none';
      }}
    </script>
    """
    return _page("Uprawnienia", body)


@admin_bp.route("/users/<int:user_id>/disable", methods=["GET", "POST"])
@_require_permission("users")
def user_disable(user_id: int):
    """Dezaktywacja konta admina."""
    token = _require_admin_token()
    current_user = getattr(request, "admin_user", None)
    
    target_user = get_admin_user_by_id(user_id)
    if not target_user:
        abort(404, description="Nie znaleziono konta")
    
    # Nie pozwól dezaktywować samego siebie
    if current_user and current_user["id"] == user_id:
        return _page(
            "Błąd",
            '<div class="error">Nie możesz dezaktywować własnego konta.</div>'
            f'<p><a class="btn" href="{url_for("admin_bp.users_list", token=token)}">← Lista kont</a></p>',
        )
    
    if request.method == "POST":
        if not _verify_csrf_token():
            return _page(
                "Błąd CSRF",
                '<div class="error">Błąd CSRF - odśwież stronę i spróbuj ponownie.</div>'
                f'<p><a class="btn" href="{url_for("admin_bp.users_list", token=token)}">← Lista kont</a></p>',
            )
        
        if update_admin_user_active(user_id, False):
            insert_admin_audit_log(
                action="disable_user",
                admin_user_id=current_user["id"] if current_user else None,
                target_email=target_user["email"],
                ip=_get_client_ip(),
                user_agent=request.headers.get("User-Agent", "")[:500],
            )
        return redirect(url_for("admin_bp.users_list", token=token))
    
    csrf_token = _generate_csrf_token()
    
    body = f"""
    <div style="margin-bottom:12px;">
      <a class="btn" href="{url_for('admin_bp.users_list', token=token)}">← Lista kont</a>
    </div>
    
    <div class="card" style="max-width:500px;">
      <h3 style="margin-top:0;">Dezaktywacja konta</h3>
      <div class="warn" style="margin-bottom:16px;">
        Czy na pewno chcesz dezaktywować konto <b>{target_user['email']}</b>?<br/>
        Użytkownik nie będzie mógł się zalogować.
      </div>
      
      <form method="post" action="{url_for('admin_bp.user_disable', user_id=user_id, token=token)}">
        <input type="hidden" name="csrf_token" value="{csrf_token}" />
        <button class="btn btnDanger" type="submit">Dezaktywuj</button>
        <a class="btn" href="{url_for('admin_bp.users_list', token=token)}" style="margin-left:10px;">Anuluj</a>
      </form>
    </div>
    """
    return _page("Dezaktywacja konta", body)


@admin_bp.route("/users/<int:user_id>/enable", methods=["GET", "POST"])
@_require_permission("users")
def user_enable(user_id: int):
    """Aktywacja konta admina."""
    token = _require_admin_token()
    current_user = getattr(request, "admin_user", None)
    
    target_user = get_admin_user_by_id(user_id)
    if not target_user:
        abort(404, description="Nie znaleziono konta")
    
    if request.method == "POST":
        if not _verify_csrf_token():
            return _page(
                "Błąd CSRF",
                '<div class="error">Błąd CSRF - odśwież stronę i spróbuj ponownie.</div>'
                f'<p><a class="btn" href="{url_for("admin_bp.users_list", token=token)}">← Lista kont</a></p>',
            )
        
        if update_admin_user_active(user_id, True):
            insert_admin_audit_log(
                action="enable_user",
                admin_user_id=current_user["id"] if current_user else None,
                target_email=target_user["email"],
                ip=_get_client_ip(),
                user_agent=request.headers.get("User-Agent", "")[:500],
            )
        return redirect(url_for("admin_bp.users_list", token=token))
    
    csrf_token = _generate_csrf_token()
    
    body = f"""
    <div style="margin-bottom:12px;">
      <a class="btn" href="{url_for('admin_bp.users_list', token=token)}">← Lista kont</a>
    </div>
    
    <div class="card" style="max-width:500px;">
      <h3 style="margin-top:0;">Aktywacja konta</h3>
      <div style="margin-bottom:16px;">
        Czy chcesz aktywować konto <b>{target_user['email']}</b>?
      </div>
      
      <form method="post" action="{url_for('admin_bp.user_enable', user_id=user_id, token=token)}">
        <input type="hidden" name="csrf_token" value="{csrf_token}" />
        <button class="btn btnPrimary" type="submit">Aktywuj</button>
        <a class="btn" href="{url_for('admin_bp.users_list', token=token)}" style="margin-left:10px;">Anuluj</a>
      </form>
    </div>
    """
    return _page("Aktywacja konta", body)


@admin_bp.route("/audit-log", methods=["GET"])
@_require_permission("audit")
def audit_log():
    """Log audytu akcji adminów."""
    token = _require_admin_token()
    
    logs = list_admin_audit_log(limit=100)
    
    ACTION_LABELS = {
        "login_success": ("Logowanie", "pill-success"),
        "login_failed_wrong_password": ("Błędne hasło", "pill-error"),
        "login_failed_unknown_user": ("Nieznany email", "pill-error"),
        "login_failed_inactive": ("Konto nieaktywne", "pill-warning"),
        "login_failed_locked": ("Konto zablokowane", "pill-warning"),
        "logout": ("Wylogowanie", "pill-neutral"),
        "create_user": ("Utworzenie konta", "pill-success"),
        "disable_user": ("Dezaktywacja", "pill-warning"),
        "enable_user": ("Aktywacja", "pill-success"),
        "reset_password": ("Reset hasła", "pill-warning"),
        "bootstrap_create_admin": ("Bootstrap", "pill-success"),
    }
    
    rows = []
    for log in logs:
        action = log.get("action", "")
        label, pill_class = ACTION_LABELS.get(action, (action, "pill"))
        
        rows.append(f"""
            <tr>
              <td><span class="muted">{str(log.get('created_at', ''))[:19]}</span></td>
              <td><span class="pill {pill_class}">{label}</span></td>
              <td>{log.get('admin_email', '') or '—'}</td>
              <td>{log.get('target_email', '') or '—'}</td>
              <td><span class="muted">{log.get('ip', '') or '—'}</span></td>
            </tr>
        """)
    
    body = f"""
    <style>
      .audit-table-wrapper {{
        background: #fff;
        border: 1px solid var(--md-border);
        border-radius: 12px;
        overflow: hidden;
        max-width: 1100px;
        margin: 0 auto;
      }}
      .audit-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;
      }}
      .audit-table th {{
        text-align: left;
        padding: 10px 12px;
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--md-text-muted);
        background: #f8fafc;
        border-bottom: 2px solid var(--md-border);
      }}
      .audit-table td {{
        padding: 10px 12px;
        border-bottom: 1px solid #f1f5f9;
        vertical-align: middle;
      }}
      .audit-table tbody tr {{
        transition: background 0.15s ease;
      }}
      .audit-table tbody tr:hover {{
        background: #f8fafc;
      }}
      .audit-table tbody tr:last-child td {{
        border-bottom: none;
      }}
      .audit-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 20px;
      }}
    </style>

    <div class="audit-header">
      <a class="btn" href="{url_for('admin_bp.users_list', token=token)}">← Lista kont</a>
      <span class="muted">Ostatnie 100 wpisów</span>
    </div>

    <div class="audit-table-wrapper">
      <table class="audit-table">
        <thead>
          <tr>
            <th>Data i czas</th>
            <th>Akcja</th>
            <th>Wykonał</th>
            <th>Dotyczy</th>
            <th>Adres IP</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows) if rows else '<tr><td colspan="5" style="padding:40px; text-align:center; color:var(--md-text-muted);">Brak wpisów w logu audytu</td></tr>'}
        </tbody>
      </table>
    </div>
    """
    return _page("Log audytu", body)


@admin_bp.errorhandler(401)
@admin_bp.errorhandler(403)
@admin_bp.errorhandler(404)
@admin_bp.errorhandler(500)
def _err(e):
    token = (request.args.get("token") or "").strip()
    error_code = getattr(e, "code", 500)
    error_desc = getattr(e, "description", str(e))
    
    body = f"""
    <style>
      .error-page {{
        max-width: 500px;
        margin: 40px auto;
        text-align: center;
      }}
      .error-code {{
        font-size: 72px;
        font-weight: 700;
        color: var(--md-primary);
        margin-bottom: 16px;
        line-height: 1;
      }}
      .error-message {{
        font-size: 18px;
        color: var(--md-text);
        margin-bottom: 24px;
      }}
      .error-details {{
        background: #fee2e2;
        color: #991b1b;
        padding: 16px;
        border-radius: 8px;
        margin-bottom: 24px;
        font-size: 14px;
      }}
    </style>
    
    <div class="error-page">
      <div class="error-code">{error_code}</div>
      <div class="error-message">Wystąpił błąd</div>
      <div class="error-details">{error_desc}</div>
      <a class="btn btnPrimary" href="{url_for('admin_bp.events_list', token=token) if token else url_for('admin_bp.login')}">
        {'Wróć do wydarzeń' if token else 'Zaloguj się'}
      </a>
    </div>
    """
    return _page("Błąd", body), error_code

