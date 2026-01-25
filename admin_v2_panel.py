"""
Admin Panel V2 - Nowy panel administracyjny z nowoczesnym UI
Blueprint działający równolegle z istniejącym /admin
Włączany przez ADMIN_V2_ENABLED=1 w ENV
"""
import os
from functools import wraps
from typing import Any, Dict, List, Optional

from flask import Blueprint, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from pg_storage import (
    # Events
    list_events,
    get_event,
    get_event_ticket_stats,
    # Orders
    list_orders,
    get_order,
    get_participants_for_order,
    get_participants_for_event,
    get_participant_by_id,
    get_wfirma_documents,
    count_participants_by_status,
    # Admin users
    get_admin_user_by_email,
    get_admin_user_by_id,
    list_admin_users,
    create_admin_user,
    update_admin_user_last_login,
    update_admin_user_password,
    update_admin_user_active,
    update_admin_user_access,
    delete_admin_user,
    increment_admin_user_failed_login,
    insert_admin_audit_log,
    list_admin_audit_log,
)

admin_v2_bp = Blueprint("admin_v2_bp", __name__, template_folder="templates")

# ---------------------------------------------------------------------------
# CONFIGURATION (ENV)
# ---------------------------------------------------------------------------

# Zoho Flow webhook do synchronizacji wydarzeń
ZOHO_FLOW_EVENT_UPDATE_WEBHOOK = os.environ.get("ZOHO_FLOW_EVENT_UPDATE_WEBHOOK", "")
if not ZOHO_FLOW_EVENT_UPDATE_WEBHOOK:
    print("[ADMIN_V2] WARNING: ZOHO_FLOW_EVENT_UPDATE_WEBHOOK nie jest skonfigurowany")

# ---------------------------------------------------------------------------
# HELPERS - reuse logic from admin_panel.py
# ---------------------------------------------------------------------------

def _get_current_admin_user() -> Optional[Dict[str, Any]]:
    """Zwraca aktualnie zalogowanego admina z sesji (lub None)."""
    user_id = session.get("admin_user_id")
    if not user_id:
        return None
    user = get_admin_user_by_id(user_id)
    if not user or not user.get("is_active"):
        session.pop("admin_user_id", None)
        return None
    return user


def _normalize_allowed_pages(value: Any) -> List[str]:
    import json
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


def _user_has_permission(user: Optional[Dict[str, Any]], page: str) -> bool:
    """Sprawdza czy user ma dostęp do danej strony."""
    if not user:
        return False
    role = (user.get("role") or "").strip().lower() or "admin"
    if role == "admin":
        return True
    allowed = _normalize_allowed_pages(user.get("allowed_pages"))
    return page in allowed


def _user_has_event_access(user: Optional[Dict[str, Any]], event_id: str) -> bool:
    """Sprawdza czy user ma dostęp do konkretnego wydarzenia."""
    if not user:
        return False
    role = (user.get("role") or "").strip().lower()
    # Admin i user mają dostęp do wszystkich wydarzeń
    if role in ("admin", "user"):
        return True
    # Viewer ma dostęp tylko do wydarzeń z allowed_events
    if role == "viewer":
        allowed_event_ids = user.get("allowed_events") or []
        if isinstance(allowed_event_ids, str):
            import json
            try:
                allowed_event_ids = json.loads(allowed_event_ids)
            except:
                allowed_event_ids = []
        allowed_event_ids = [str(eid) for eid in allowed_event_ids if eid]
        return str(event_id) in allowed_event_ids
    return False


def _is_admin_user(user: Optional[Dict[str, Any]]) -> bool:
    """Czy user ma rolę admin (pełny dostęp)."""
    if not user:
        return False
    return (user.get("role") or "").strip().lower() == "admin"


def _is_viewer(user: Optional[Dict[str, Any]]) -> bool:
    """Czy user ma rolę viewer (tylko odczyt)."""
    if not user:
        return False
    return (user.get("role") or "").strip().lower() == "viewer"


def _get_user_initials(user: Optional[Dict[str, Any]]) -> str:
    """Zwraca inicjały użytkownika."""
    if not user:
        return "AD"
    name = user.get("full_name") or user.get("email") or ""
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    elif parts:
        return parts[0][:2].upper()
    return "AD"


def _require_login(f):
    """Dekorator wymagający zalogowania do panelu V2."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _get_current_admin_user()
        if not user:
            return redirect(url_for("admin_v2_bp.login"))
        request.admin_user = user
        return f(*args, **kwargs)
    return decorated


def _require_permission(page: str):
    """Dekorator wymagający uprawnień do danej strony."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            from flask import jsonify
            user = _get_current_admin_user()
            
            # Sprawdź czy to request AJAX/API (oczekuje JSON)
            is_ajax = (
                request.headers.get("X-Requested-With") == "XMLHttpRequest" or
                request.content_type == "application/json" or
                request.path.startswith("/admin-v2/api/") or
                "apply-backstage" in request.path or
                "sync-backstage" in request.path or
                "preview-data" in request.path
            )
            
            if not user:
                if is_ajax:
                    return jsonify({"success": False, "error": "Sesja wygasła. Zaloguj się ponownie."}), 401
                return redirect(url_for("admin_v2_bp.login"))
            if not _user_has_permission(user, page):
                if is_ajax:
                    return jsonify({"success": False, "error": "Brak uprawnień do tej operacji."}), 403
                return render_template(
                    "admin_v2/base.html",
                    active_page="",
                    **_get_common_context(user),
                ), 403
            request.admin_user = user
            return f(*args, **kwargs)
        return decorated
    return decorator


def _get_common_context(user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Zwraca wspólny kontekst dla wszystkich szablonów V2."""
    if user is None:
        user = _get_current_admin_user()
    
    # Licznik błędów do wyświetlenia w sidebarze (na razie placeholder)
    work_queue_count = 0
    
    return {
        "user_email": user.get("email") if user else None,
        "user_name": user.get("full_name") if user else None,
        "user_role": user.get("role") if user else None,
        "user_initials": _get_user_initials(user),
        "can_events": _user_has_permission(user, "events"),
        "can_orders": _user_has_permission(user, "orders"),
        "can_users": _user_has_permission(user, "users"),
        "can_audit": _user_has_permission(user, "audit"),
        "work_queue_count": work_queue_count,
    }


# ---------------------------------------------------------------------------
# EVENT DATA NORMALIZATION
# ---------------------------------------------------------------------------

def _normalize_event_data(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizuje dane wydarzenia - mapuje pola z Backstage na nazwy oczekiwane przez template.
    
    Backstage używa nazw pól jak:
    - event_location_city, event_day_text_1, event_mail_link_top_banner
    
    Template oczekuje:
    - eventCity, eventDate, email_header_url
    """
    if not event:
        return event
    
    event_data = event.get("data") or {}
    
    # Mapuj pola na nazwy oczekiwane przez template
    
    # Normalizacja dat - pobierz z różnych źródeł
    # event_date_time to pełny datetime (2026-02-26T10:00:00), event_date to sama data (2026-02-26)
    raw_start = event_data.get("event_date_time") or event_data.get("event_date") or event_data.get("eventDate") or ""
    raw_end = event_data.get("event_end_date_time") or event_data.get("event_end_date") or ""
    raw_start_time = event_data.get("event_time") or event_data.get("event_time_text") or event_data.get("eventTime") or ""
    raw_end_time = event_data.get("event_end_time") or ""
    
    # Wyciągnij datę z datetime jeśli potrzeba
    start_date = raw_start[:10] if raw_start else ""  # YYYY-MM-DD
    end_date = raw_end[:10] if raw_end else ""
    
    # Wyciągnij godzinę z datetime jeśli nie mamy osobnej
    if not raw_start_time and raw_start and "T" in raw_start:
        raw_start_time = raw_start[11:16]  # HH:MM
    if not raw_end_time and raw_end and "T" in raw_end:
        raw_end_time = raw_end[11:16]
    
    # Zrekonstruuj event_date_time i event_end_date_time dla formularza edycji
    # Format datetime-local: YYYY-MM-DDTHH:MM
    
    def _ensure_iso_datetime(value: str, fallback_date: str = "", fallback_time: str = "00:00") -> str:
        """Konwertuje datę do formatu ISO YYYY-MM-DDTHH:MM dla datetime-local input."""
        if not value and not fallback_date:
            return ""
        
        # Już poprawny format ISO (2026-02-05T10:00 lub 2026-02-05T10:00:00)
        if value and len(value) >= 16 and value[4] == "-" and value[7] == "-" and value[10] == "T":
            return value[:16]  # YYYY-MM-DDTHH:MM
        
        # Format polski DD-MM-YYYY HH:MM lub DD.MM.YYYY HH:MM
        import re
        polish_match = re.match(r"(\d{2})[-./](\d{2})[-./](\d{4})[\sT]?(\d{2}):(\d{2})", value or "")
        if polish_match:
            day, month, year, hour, minute = polish_match.groups()
            return f"{year}-{month}-{day}T{hour}:{minute}"
        
        # Format ISO bez T (2026-02-05 10:00)
        iso_space_match = re.match(r"(\d{4})-(\d{2})-(\d{2})\s(\d{2}):(\d{2})", value or "")
        if iso_space_match:
            year, month, day, hour, minute = iso_space_match.groups()
            return f"{year}-{month}-{day}T{hour}:{minute}"
        
        # Fallback: użyj date i time
        if fallback_date:
            time_part = fallback_time or "00:00"
            if len(time_part) >= 5:
                return f"{fallback_date}T{time_part[:5]}"
        
        return ""
    
    reconstructed_start_datetime = _ensure_iso_datetime(
        event_data.get("event_date_time") or "",
        start_date,
        raw_start_time
    )
    reconstructed_end_datetime = _ensure_iso_datetime(
        event_data.get("event_end_date_time") or "",
        end_date,
        raw_end_time
    )
    
    normalized = {
        # Data i czas - rozpoczęcie (używamy formatu ISO YYYY-MM-DD, filtr format_date_pl sformatuje)
        "eventDate": start_date or "",
        "eventTime": raw_start_time or "",
        # Data i czas - zakończenie
        "eventEndDate": end_date or "",
        "eventEndTime": raw_end_time or "",
        # Format datetime-local dla formularza edycji (zawsze ISO)
        "event_date_time": reconstructed_start_datetime,
        "event_end_date_time": reconstructed_end_datetime,
        # Stary format tekstowy (dla kompatybilności wstecznej)
        "event_day_text_1": event_data.get("event_day_text_1") or "",
        # Czy wielodniowe
        "isMultiDay": bool(end_date and end_date != start_date),
        
        # Lokalizacja
        "eventCity": event_data.get("event_location_city") or event_data.get("eventCity") or "",
        "eventLocation": event_data.get("event_location_place") or event_data.get("eventLocation") or "",
        "eventAddress": event_data.get("event_location_address") or event_data.get("eventAddress") or "",
        "event_location_zip": event_data.get("event_location_zip") or "",
        
        # Grafiki i branding
        "email_header_url": event_data.get("event_mail_link_top_banner") or event_data.get("email_header_url") or "",
        "event_logo_url": event_data.get("event_logo_link") or event_data.get("event_logo_url") or "",
        "color_gradient_1": event_data.get("color_gradient_1") or "#0065D7",
        "color_gradient_2": event_data.get("color_gradient_2") or event_data.get("color_gradient_1") or "#00A1D7",
        
        # Kontakt
        "md_email_kontakt": event_data.get("md_email_kontakt") or "eventy@medidesk.com",
        "md_mobile_kontakt": event_data.get("md_mobile_kontakt") or "+48 729 927 389",
        
        # Linki publiczne (w starej bazie: url_event, url_success, url_cancel)
        "event_public_url": event_data.get("url_event") or event_data.get("event_public_url") or "",
        "success_page_url": event_data.get("url_success") or event_data.get("success_page_url") or "",
        "cancel_page_url": event_data.get("url_cancel") or event_data.get("cancel_page_url") or "",
    }
    
    # Zachowaj wszystkie oryginalne pola i nadpisz znormalizowanymi
    merged_data = {**event_data, **normalized}
    event["data"] = merged_data
    
    # Generuj linki Backstage dynamicznie
    # Portal ID z konfiguracji lub domyślne dla Medidesk
    backstage_portal_id = event_data.get("backstage_portal_id") or "20101549222"
    # Użyj backstage_event_id (Zoho ID) zamiast lokalnego event_id
    backstage_event_id = event_data.get("backstage_event_id") or event.get("event_id", "")
    
    # Format: https://backstage.zoho.eu/portal/{portal_id}/events/{event_id}/{page}
    if backstage_event_id:
        backstage_base = f"https://backstage.zoho.eu/portal/{backstage_portal_id}/events/{backstage_event_id}"
        event["backstage_url"] = f"{backstage_base}/overview"
        event["backstage_orders_url"] = f"{backstage_base}/orders"
        event["backstage_attendees_url"] = f"{backstage_base}/attendees"
    else:
        event["backstage_url"] = "#"
        event["backstage_orders_url"] = "#"
        event["backstage_attendees_url"] = "#"
    
    return event


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@admin_v2_bp.route("/login", methods=["GET", "POST"])
def login():
    """Strona logowania V2 (używa tego samego systemu sesji co V1)."""
    if _get_current_admin_user():
        return redirect(url_for("admin_v2_bp.dashboard"))
    
    error = None
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        
        user = get_admin_user_by_email(email)
        if user and user.get("is_active") and check_password_hash(user.get("password_hash", ""), password):
            session["admin_user_id"] = user["id"]
            update_admin_user_last_login(user["id"])
            insert_admin_audit_log(
                action="login_success",
                admin_user_id=user["id"],
                target_email=email,
                ip=request.remote_addr,
            )
            return redirect(url_for("admin_v2_bp.dashboard"))
        else:
            error = "Nieprawidłowy email lub hasło"
            if user:
                increment_admin_user_failed_login(user["id"])
                insert_admin_audit_log(
                    action="login_failed",
                    admin_user_id=user["id"],
                    target_email=email,
                    ip=request.remote_addr,
                )
    
    return render_template("admin_v2/login.html", error=error)


@admin_v2_bp.route("/logout", methods=["GET", "POST"])
def logout():
    """Wylogowanie z panelu."""
    user = _get_current_admin_user()
    if user:
        insert_admin_audit_log(
            action="logout",
            admin_user_id=user["id"],
            target_email=user.get("email"),
            ip=request.remote_addr,
        )
    session.pop("admin_user_id", None)
    return redirect(url_for("admin_v2_bp.login"))


@admin_v2_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Strona 'zapomniałem hasła' - generuje token resetujący."""
    import uuid
    from datetime import datetime, timedelta
    from pg_storage import _with_conn, _put_conn
    
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        
        if email:
            user = get_admin_user_by_email(email)
            
            if user:
                # Generuj token
                token = str(uuid.uuid4())
                expires = datetime.utcnow() + timedelta(hours=1)
                
                # Zapisz token w DB
                pool = None
                conn = None
                try:
                    pool, conn = _with_conn()
                    cur = conn.cursor()
                    cur.execute("""
                        UPDATE admin_users
                        SET password_reset_token = %s,
                            password_reset_expires = %s
                        WHERE id = %s
                    """, (token, expires, user['id']))
                    
                    # Audit log
                    insert_admin_audit_log(
                        action="password_reset_requested",
                        admin_user_id=user['id'],
                        target_email=email,
                        ip=request.remote_addr,
                    )
                    
                    # Wyślij email z linkiem (jeśli Make jest skonfigurowany)
                    try:
                        from backstage_engine import _send_email_via_make
                        reset_url = f"{request.host_url}admin-v2/reset-password?token={token}"
                        
                        email_html = f"""
                        <html>
                        <body style="font-family: Arial, sans-serif; padding: 20px;">
                            <h2 style="color: #0065D7;">Reset hasła - Medidesk Admin Panel</h2>
                            <p>Otrzymaliśmy prośbę o reset hasła dla Twojego konta.</p>
                            <p>Kliknij poniższy link, aby ustawić nowe hasło:</p>
                            <p><a href="{reset_url}" style="display: inline-block; padding: 12px 24px; background-color: #0065D7; color: #fff; text-decoration: none; border-radius: 6px;">Ustaw nowe hasło</a></p>
                            <p><small>Link wygasa za 1 godzinę.</small></p>
                            <hr>
                            <p style="color: #666; font-size: 12px;">Jeśli nie prosiłeś o reset hasła, zignoruj ten email.</p>
                        </body>
                        </html>
                        """
                        
                        _send_email_via_make(
                            to_email=email,
                            subject="Reset hasła - Medidesk Admin Panel",
                            body_html=email_html,
                            template_type="password_reset",
                        )
                    except Exception as e:
                        print(f"[FORGOT_PASSWORD] Błąd wysyłki emaila: {e}")
                        # Kontynuuj mimo błędu wysyłki
                    
                finally:
                    if pool is not None and conn is not None:
                        _put_conn(pool, conn)
        
        # Zawsze pokazuj sukces (nie ujawniaj czy email istnieje)
        return render_template("admin_v2/forgot_password_sent.html")
    
    return render_template("admin_v2/forgot_password.html")


@admin_v2_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    """Strona resetowania hasła z tokenem."""
    from werkzeug.security import generate_password_hash
    from pg_storage import _with_conn, _put_conn
    
    token = request.args.get("token") or request.form.get("token")
    error = None
    success = None
    
    if not token:
        return redirect(url_for("admin_v2_bp.login"))
    
    if request.method == "POST":
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        
        if not password or len(password) < 8:
            error = "Hasło musi mieć co najmniej 8 znaków"
        elif password != password2:
            error = "Hasła nie są identyczne"
        else:
            # Sprawdź token
            pool = None
            conn = None
            try:
                pool, conn = _with_conn()
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, email FROM admin_users
                    WHERE password_reset_token = %s
                      AND password_reset_expires > NOW()
                """, (token,))
                
                user = cur.fetchone()
                if not user:
                    error = "Token wygasł lub jest nieprawidłowy. Spróbuj ponownie."
                else:
                    user_id, user_email = user
                    
                    # Zmień hasło
                    password_hash = generate_password_hash(password)
                    cur.execute("""
                        UPDATE admin_users
                        SET password_hash = %s,
                            password_reset_token = NULL,
                            password_reset_expires = NULL,
                            failed_login_count = 0,
                            locked_until = NULL,
                            updated_at = NOW()
                        WHERE id = %s
                    """, (password_hash, user_id))
                    
                    # Audit log
                    insert_admin_audit_log(
                        action="password_reset_completed",
                        admin_user_id=user_id,
                        target_email=user_email,
                        ip=request.remote_addr,
                    )
                    
                    success = True
            finally:
                if pool is not None and conn is not None:
                    _put_conn(pool, conn)
    
    if success:
        return redirect(url_for("admin_v2_bp.login") + "?reset=success")
    
    return render_template("admin_v2/reset_password.html", token=token, error=error)


@admin_v2_bp.route("/", methods=["GET"])
@admin_v2_bp.route("/dashboard", methods=["GET"])
@_require_login
def dashboard():
    """Dashboard z podsumowaniem (z cache'em dla statystyk)."""
    from pg_storage import get_cached_stats, set_cached_stats
    
    user = _get_current_admin_user()
    
    # Sprawdź cache statystyk (5 minut TTL)
    cached = get_cached_stats("dashboard_main_stats")
    
    if cached:
        stats = cached.get("stats", {})
        all_orders = cached.get("all_orders", [])
        all_events = cached.get("all_events", [])
        paid_orders = cached.get("paid_orders", [])
        print("[DASHBOARD] Using cached stats")
    else:
        print("[DASHBOARD] Computing fresh stats...")
        
        # Pobierz statystyki
        all_orders = list_orders(limit=500)
        all_events = list_events(limit=100)
        
        # Oblicz statystyki
        total_orders = len(all_orders)
        paid_orders = [o for o in all_orders if o.get("status") == "paid"]
        total_revenue = sum(float(o.get("total") or 0) for o in paid_orders)
        
        # Zlicz uczestników (przez count_participants_by_status dla każdego zamówienia)
        total_participants = 0
        for o in all_orders:
            try:
                p_counts = count_participants_by_status(o.get("event_order_id"))
                total_participants += sum(p_counts.values()) if p_counts else 0
            except Exception:
                pass
        
        active_events = len([e for e in all_events if e.get("is_active", True)])
        
        stats = {
            "total_orders": total_orders,
            "total_participants": total_participants,
            "total_revenue": f"{total_revenue:,.2f}".replace(",", " "),
            "active_events": active_events,
        }
        
        # Zapisz do cache (5 minut)
        # Uwaga: nie cachujemy pełnych obiektów zamówień/eventów, tylko minimalne dane
        cache_data = {
            "stats": stats,
            "all_orders": all_orders[:100],  # Ogranicz dla cache
            "all_events": all_events[:50],
            "paid_orders": paid_orders[:100],
        }
        set_cached_stats("dashboard_main_stats", cache_data, ttl_minutes=5)
    
    # FILTROWANIE WEDŁUG UPRAWNIEŃ UŻYTKOWNIKA (dla viewer)
    role = (user.get("role") or "").lower()
    if role == "viewer":
        allowed_event_ids = user.get("allowed_events") or []
        if isinstance(allowed_event_ids, str):
            import json
            try:
                allowed_event_ids = json.loads(allowed_event_ids)
            except:
                allowed_event_ids = []
        allowed_event_ids = [str(eid) for eid in allowed_event_ids if eid]
        # Filtruj wydarzenia
        all_events = [e for e in all_events if str(e.get("event_id")) in allowed_event_ids]
        # Filtruj zamówienia (tylko z dozwolonych wydarzeń)
        all_orders = [o for o in all_orders if str(o.get("event_id")) in allowed_event_ids]
        paid_orders = [o for o in paid_orders if str(o.get("event_id")) in allowed_event_ids]
        # Przelicz statystyki
        stats = {
            "total_orders": len(all_orders),
            "total_participants": sum(
                sum((count_participants_by_status(o.get("event_order_id")) or {}).values())
                for o in all_orders
            ),
            "total_revenue": f"{sum(float(o.get('total') or 0) for o in paid_orders):,.2f}".replace(",", " "),
            "active_events": len([e for e in all_events if e.get("is_active", True)]),
        }
    
    # Ostatnie zamówienia
    recent_orders = all_orders[:5]
    
    # Ostatnie wydarzenia (aktywne, sortowane po dacie)
    recent_events = [e for e in all_events if e.get("is_active")][:5]
    
    # Dodaj nazwy wydarzeń do zamówień
    event_map = {e.get("event_id"): e for e in all_events}
    for order in recent_orders:
        event = event_map.get(order.get("event_id"))
        if event:
            order["event_name"] = event.get("event_name", "")
            order["event_color"] = (event.get("data") or {}).get("color_gradient_1", "")
    
    # Dane do wykresów
    from collections import defaultdict
    from datetime import datetime
    
    # Przychód wg miesiąca (ostatnie 6 miesięcy)
    revenue_by_month = defaultdict(float)
    month_names_pl = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze', 'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru']
    
    for o in paid_orders:
        created = o.get("created_at")
        if created:
            if isinstance(created, str):
                try:
                    created = datetime.fromisoformat(created.replace('Z', '+00:00'))
                except Exception:
                    continue
            month_key = f"{created.year}-{created.month:02d}"
            revenue_by_month[month_key] += float(o.get("total") or 0)
    
    # Sortuj i weź ostatnie 6 miesięcy
    sorted_months = sorted(revenue_by_month.keys())[-6:]
    revenue_labels = []
    revenue_values = []
    for m in sorted_months:
        year, month = m.split('-')
        revenue_labels.append(month_names_pl[int(month) - 1])
        revenue_values.append(round(revenue_by_month[m], 2))
    
    # Metody płatności
    payment_methods = defaultdict(int)
    for o in all_orders:
        payment_type = (o.get("payment_option_name") or "Inne").strip()
        if not payment_type:
            payment_type = "Inne"
        # Skróć długie nazwy
        if len(payment_type) > 15:
            payment_type = payment_type[:12] + "..."
        payment_methods[payment_type] += 1
    
    chart_data = {
        "revenue": revenue_values if revenue_values else [0],
        "revenue_labels": revenue_labels if revenue_labels else ["Brak danych"],
        "payment_methods": dict(payment_methods) if payment_methods else {"Brak": 1},
    }
    
    return render_template(
        "admin_v2/dashboard.html",
        active_page="dashboard",
        stats=stats,
        recent_orders=recent_orders,
        recent_events=recent_events,
        chart_data=chart_data,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/orders", methods=["GET"])
@_require_permission("orders")
def orders_list():
    """Lista zamówień."""
    user = _get_current_admin_user()
    
    # Filtry
    status_filter = request.args.get("status", "").strip()
    event_filter = request.args.get("event_id", "").strip()
    q_filter = request.args.get("q", "").strip().lower()
    
    # Pobierz dane
    orders = list_orders(
        event_id=event_filter or None,
        status=status_filter or None,
        limit=200,
    )
    events = list_events(limit=100)
    
    # FILTROWANIE WEDŁUG UPRAWNIEŃ UŻYTKOWNIKA (dla viewer)
    role = (user.get("role") or "").lower()
    if role == "viewer":
        allowed_event_ids = user.get("allowed_events") or []
        if isinstance(allowed_event_ids, str):
            import json
            try:
                allowed_event_ids = json.loads(allowed_event_ids)
            except:
                allowed_event_ids = []
        allowed_event_ids = [str(eid) for eid in allowed_event_ids if eid]
        # Filtruj wydarzenia w dropdown
        events = [e for e in events if str(e.get("event_id")) in allowed_event_ids]
        # Filtruj zamówienia
        orders = [o for o in orders if str(o.get("event_id")) in allowed_event_ids]
    
    # Filtrowanie tekstowe
    if q_filter:
        orders = [
            o for o in orders
            if q_filter in (o.get("event_order_id") or "").lower()
            or q_filter in (o.get("purchaser_email") or "").lower()
            or q_filter in (o.get("purchaser_first_name") or "").lower()
            or q_filter in (o.get("purchaser_last_name") or "").lower()
        ]
    
    # Sortowanie
    sort_column = request.args.get("sort", "date").strip()
    sort_direction = request.args.get("dir", "desc").strip()
    
    # Dodaj nazwy wydarzeń i mapuj pola dla szablonu
    event_map = {e.get("event_id"): e for e in events}
    for order in orders:
        event = event_map.get(order.get("event_id"))
        if event:
            order["event_name"] = event.get("event_name", "")
            event_data = event.get("data") or {}
            order["event_color"] = event_data.get("color_gradient_1", "hsl(212, 100%, 42%)")
            order["event_color_2"] = event_data.get("color_gradient_2", "hsl(195, 100%, 42%)")
        
        # Mapuj pola kupującego dla szablonu
        order["buyer_first_name"] = order.get("purchaser_first_name", "")
        order["buyer_last_name"] = order.get("purchaser_last_name", "")
        order["buyer_email"] = order.get("purchaser_email", "")
        order["buyer_company"] = order.get("purchaser_company", "")
        order["participants_count"] = order.get("participant_count", 1)
    
    return render_template(
        "admin_v2/orders.html",
        active_page="orders",
        orders=orders,
        events=events,
        total_orders=len(orders),
        sort_column=sort_column,
        sort_direction=sort_direction,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/orders/export", methods=["GET"])
@_require_permission("orders")
def orders_export():
    """Eksport zamówień do CSV."""
    import csv
    import io
    from flask import Response
    
    # Filtry (te same co lista)
    status_filter = request.args.get("status", "").strip()
    event_filter = request.args.get("event_id", "").strip()
    
    orders = list_orders(
        event_id=event_filter or None,
        status=status_filter or None,
        limit=1000,
    )
    events = list_events(limit=100)
    event_map = {e.get("event_id"): e for e in events}
    
    # Twórz CSV
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    
    # Nagłówki
    writer.writerow([
        'ID zamówienia', 'Wydarzenie', 'Nabywca', 'Email', 'Firma',
        'Uczestników', 'Kwota', 'Status', 'Data utworzenia'
    ])
    
    # Dane
    for o in orders:
        event = event_map.get(o.get("event_id"), {})
        created = o.get("created_at")
        writer.writerow([
            o.get("event_order_id", ""),
            event.get("event_name", o.get("event_id", "")),
            f"{o.get('purchaser_first_name', '')} {o.get('purchaser_last_name', '')}".strip(),
            o.get("purchaser_email", ""),
            o.get("purchaser_company", ""),
            o.get("participant_count", 1),
            f"{o.get('total', 0)} {o.get('currency', 'PLN')}",
            o.get("status", ""),
            created.strftime("%Y-%m-%d %H:%M") if created else "",
        ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': 'attachment; filename=zamowienia.csv',
            'Content-Type': 'text/csv; charset=utf-8'
        }
    )


@admin_v2_bp.route("/participants/export", methods=["GET"])
@_require_permission("orders")
def participants_export():
    """Eksport uczestników do CSV."""
    import csv
    import io
    from flask import Response
    
    event_filter = request.args.get("event_id", "").strip()
    
    if event_filter:
        participants = get_participants_for_event(event_filter) or []
    else:
        # Wszystkie wydarzenia
        events = list_events(limit=100)
        participants = []
        for e in events:
            p_list = get_participants_for_event(e.get("event_id")) or []
            for p in p_list:
                p["event_name"] = e.get("event_name", "")
            participants.extend(p_list)
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    
    writer.writerow([
        'Imię', 'Nazwisko', 'Email', 'Wydarzenie', 'Typ biletu', 'Status', 'Data'
    ])
    
    for p in participants:
        created = p.get("created_at")
        writer.writerow([
            p.get("first_name", ""),
            p.get("last_name", ""),
            p.get("email", ""),
            p.get("event_name", ""),
            (p.get("ticket_class_name") or p.get("ticket_class_id") or "Standard").replace("Bilet ", "").replace("bilet ", ""),
            p.get("status", ""),
            created.strftime("%Y-%m-%d %H:%M") if created else "",
        ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': 'attachment; filename=uczestnicy.csv',
            'Content-Type': 'text/csv; charset=utf-8'
        }
    )


@admin_v2_bp.route("/orders/<order_id>", methods=["GET"])
@_require_permission("orders")
def order_detail(order_id: str):
    """Szczegóły zamówienia."""
    user = _get_current_admin_user()
    
    order = get_order(order_id)
    if not order:
        return redirect(url_for("admin_v2_bp.orders_list"))
    
    # Sprawdź dostęp do wydarzenia zamówienia (dla viewer)
    order_event_id = order.get("event_id")
    if order_event_id and not _user_has_event_access(user, order_event_id):
        return render_template(
            "admin_v2/base.html",
            active_page="",
            **_get_common_context(user),
        ), 403
    
    # Pobierz uczestników
    participants = get_participants_for_order(order_id) or []
    
    # Mapuj nazwy biletów (nie pokazuj długich ID numerycznych)
    for p in participants:
        ticket_name = p.get("ticket_class_name") or ""
        ticket_id = p.get("ticket_class_id") or ""
        # Usuń słowo "Bilet" z nazwy jeśli jest
        if ticket_name:
            ticket_name = ticket_name.replace("Bilet ", "").replace("bilet ", "")
        if not ticket_name and ticket_id and len(str(ticket_id)) > 10 and str(ticket_id).isdigit():
            ticket_name = "Standard"
        p["ticket_name"] = ticket_name or ticket_id or "Standard"
    
    # Pobierz dokumenty wFirma
    wfirma_documents = get_wfirma_documents(order_id) or []
    
    # Pobierz nazwę wydarzenia
    event = get_event(order.get("event_id"))
    if event:
        order["event_name"] = event.get("event_name", "")
        event_data = event.get("data") or {}
        order["event_color"] = event_data.get("color_gradient_1", "")
        order["event_color_2"] = event_data.get("color_gradient_2", "")
    
    # Buduj historię zamówienia z emaili
    order_history = _build_order_history(order_id, order)
    
    # Pobierz emaile i przefiltruj wewnętrzne (do admina, @medidesk.com)
    all_emails = _get_emails_for_order(order_id)
    emails = [
        e for e in all_emails
        if not (
            (e.get("to_email") or "").lower().endswith("@medidesk.com") or
            "admin" in (e.get("to_email") or "").lower() or
            (e.get("template_key") or "").startswith("internal_")
        )
    ]
    
    return render_template(
        "admin_v2/order_detail.html",
        active_page="orders",
        order=order,
        participants=participants,
        wfirma_documents=wfirma_documents,
        order_history=order_history,
        emails=emails,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/orders/<order_id>/status", methods=["POST"])
@_require_permission("orders")
def order_update_status(order_id: str):
    """Aktualizuje status zamówienia (AJAX)."""
    from flask import jsonify
    from pg_storage import update_order_status
    
    user = _get_current_admin_user()
    
    # #region agent log
    import json as _json
    try:
        with open(r'c:\Users\kochn\.cursor\Medidesk\wFirma\APIV1\.cursor\debug.log', 'a', encoding='utf-8') as _f:
            _f.write(_json.dumps({"location":"admin_v2_panel.py:order_update_status","message":"Request received","data":{"order_id":order_id,"content_type":request.content_type,"form_data":dict(request.form),"is_json":request.is_json},"timestamp":__import__('time').time(),"sessionId":"debug-session","hypothesisId":"H1"}) + '\n')
    except: pass
    # #endregion
    
    # Support both form data and JSON
    new_status = ""
    if request.is_json:
        json_data = request.get_json(silent=True) or {}
        new_status = json_data.get("status", "").strip()
    else:
        new_status = request.form.get("status", "").strip()
    
    # #region agent log
    try:
        with open(r'c:\Users\kochn\.cursor\Medidesk\wFirma\APIV1\.cursor\debug.log', 'a', encoding='utf-8') as _f:
            _f.write(_json.dumps({"location":"admin_v2_panel.py:order_update_status:parsed","message":"Status parsed","data":{"new_status":new_status,"order_id":order_id},"timestamp":__import__('time').time(),"sessionId":"debug-session","hypothesisId":"H1,H2"}) + '\n')
    except: pass
    # #endregion
    
    # Pobierz zamówienie żeby sprawdzić dostęp
    order = get_order(order_id)
    if not order:
        return jsonify({"success": False, "error": "Nie znaleziono zamówienia"}), 404
    
    # Sprawdź dostęp do wydarzenia zamówienia
    if order.get("event_id") and not _user_has_event_access(user, order["event_id"]):
        return jsonify({"success": False, "error": "Brak dostępu do tego zamówienia"}), 403
    
    # Viewer nie może zmieniać statusu
    if _is_viewer(user):
        return jsonify({"success": False, "error": "Nie masz uprawnień do zmiany statusu"}), 403
    
    valid_statuses = ["received", "pending_payment", "paid", "cancelled", "refunded"]
    if new_status not in valid_statuses:
        return jsonify({"success": False, "error": f"Nieprawidłowy status: '{new_status}'"}), 400
    
    # Jeśli zmiana na "paid" - wywołaj pełny flow z generowaniem faktury i emailami
    if new_status == "paid":
        # #region agent log
        try:
            with open(r'c:\Users\kochn\.cursor\Medidesk\wFirma\APIV1\.cursor\debug.log', 'a', encoding='utf-8') as _f:
                _f.write(_json.dumps({"location":"admin_v2_panel.py:order_update_status:mark_paid","message":"Triggering mark_paid flow","data":{"order_id":order_id},"timestamp":__import__('time').time(),"sessionId":"debug-session","hypothesisId":"H3"}) + '\n')
        except: pass
        # #endregion
        return _handle_mark_paid(order_id, user)
    
    result = update_order_status(order_id, new_status)
    if result:
        # Zapisz w logach audytu
        insert_admin_audit_log(
            action="order_status_change",
            admin_user_id=user.get("id"),
            target_id=order_id,
            extra={"new_status": new_status},
            ip=request.remote_addr,
        )
        return jsonify({"success": True, "status": new_status})
    
    return jsonify({"success": False, "error": "Nie znaleziono zamówienia"}), 404


def _handle_mark_paid(order_id: str, user: dict):
    """
    Pełny flow oznaczania zamówienia jako opłacone:
    1. Sprawdza czy faktura końcowa już istnieje
    2. Generuje fakturę VAT w wFirma
    3. Wysyła email z potwierdzeniem do klienta
    4. Wysyła powiadomienie wewnętrzne
    5. Zmienia status na 'paid'
    """
    from flask import jsonify
    from pg_storage import update_order_status, get_wfirma_documents
    
    # #region agent log
    import json as _json
    try:
        with open(r'c:\Users\kochn\.cursor\Medidesk\wFirma\APIV1\.cursor\debug.log', 'a', encoding='utf-8') as _f:
            _f.write(_json.dumps({"location":"admin_v2_panel.py:_handle_mark_paid","message":"Starting mark_paid flow","data":{"order_id":order_id},"timestamp":__import__('time').time(),"sessionId":"debug-session","hypothesisId":"H3"}) + '\n')
    except: pass
    # #endregion
    
    order = get_order(order_id)
    if not order:
        return jsonify({"success": False, "error": "Nie znaleziono zamówienia"}), 404
    
    event_id = order.get("event_id", "")
    event = get_event(event_id) if event_id else None
    event_name = event.get("event_name", "") if event else ""
    event_data = (event.get("data") if event else {}) or {}
    
    # Dane kupującego
    purchaser_email = order.get("purchaser_email", "") or ""
    purchaser_first_name = order.get("purchaser_first_name", "") or ""
    purchaser_last_name = order.get("purchaser_last_name", "") or ""
    purchaser_name = f"{purchaser_first_name} {purchaser_last_name}".strip()
    
    total_value = float(order.get("total", 0) or 0)
    currency_value = order.get("currency", "PLN") or "PLN"
    
    # 1. Sprawdź czy faktura końcowa już istnieje
    existing_docs = get_wfirma_documents(order_id) or []
    has_final_invoice = any((d or {}).get("document_type") == "normal" for d in existing_docs)
    
    errors = []
    invoice_generated = False
    email_sent = False
    
    # 2. Generuj fakturę końcową jeśli nie istnieje
    if not has_final_invoice and total_value > 0:
        try:
            from backstage_engine import _create_paid_invoice
            
            # #region agent log
            try:
                with open(r'c:\Users\kochn\.cursor\Medidesk\wFirma\APIV1\.cursor\debug.log', 'a', encoding='utf-8') as _f:
                    _f.write(_json.dumps({"location":"admin_v2_panel.py:_handle_mark_paid:gen_invoice","message":"Generating invoice","data":{"order_id":order_id,"total":total_value},"timestamp":__import__('time').time(),"sessionId":"debug-session","hypothesisId":"H3"}) + '\n')
            except: pass
            # #endregion
            
            # Przygotuj dane zamówienia dla wFirma
            order_data_for_invoice = {
                "event_order_id": order_id,
                "purchaser_email": purchaser_email,
                "purchaser_first_name": purchaser_first_name,
                "purchaser_last_name": purchaser_last_name,
                "purchaser_company": order.get("purchaser_company", ""),
                "purchaser_nip": order.get("purchaser_nip", ""),
                "purchaser_phone": order.get("purchaser_phone", ""),
                "total": total_value,
                "currency": currency_value,
                "raw": order.get("raw", {}),
            }
            
            success, invoice_result, invoice_error = _create_paid_invoice(
                order_data=order_data_for_invoice,
                event_name=event_name,
                send_email=False,  # Email wyślemy osobno z naszym szablonem
            )
            
            if success:
                invoice_generated = True
                print(f"[V2 MARK-PAID] Wygenerowano fakturę dla {order_id}")
            else:
                errors.append(f"Błąd generowania faktury: {invoice_error or 'nieznany'}")
                print(f"[V2 MARK-PAID] Błąd faktury: {invoice_error}")
        except Exception as e:
            errors.append(f"Wyjątek generowania faktury: {str(e)}")
            print(f"[V2 MARK-PAID] Wyjątek faktury: {e}")
    elif has_final_invoice:
        invoice_generated = True  # Już istnieje
    
    # 3. Wysyłka emaila z potwierdzeniem płatności
    if purchaser_email:
        try:
            from backstage_engine import _send_email_via_make
            from email_templates import render_payment_confirmation_email
            from pg_storage import save_mail_log
            
            # #region agent log
            try:
                with open(r'c:\Users\kochn\.cursor\Medidesk\wFirma\APIV1\.cursor\debug.log', 'a', encoding='utf-8') as _f:
                    _f.write(_json.dumps({"location":"admin_v2_panel.py:_handle_mark_paid:send_email","message":"Sending confirmation email","data":{"order_id":order_id,"to":purchaser_email},"timestamp":__import__('time').time(),"sessionId":"debug-session","hypothesisId":"H3"}) + '\n')
            except: pass
            # #endregion
            
            email_html = render_payment_confirmation_email(
                event_name=event_name,
                purchaser_first_name=purchaser_first_name,
                purchaser_last_name=purchaser_last_name,
                purchaser_email=purchaser_email,
                purchaser_phone=order.get("purchaser_phone", "") or "",
                total_gross=total_value,
                event_config=event_data,
                tickets=None,  # TODO: pobrać bilety z zamówienia
            )
            
            subject = f"Potwierdzenie płatności - {event_name}"
            
            # NAJPIERW zapisz do mail_log żeby mieć mail_id
            mail_log_result = save_mail_log(
                event_order_id=order_id,
                template_key="payment_confirmation",
                to_email=purchaser_email,
                subject=subject,
                direction="purchaser",
            )
            mail_id = mail_log_result.get("id") if mail_log_result else None
            
            # POTEM wyślij email z mail_id
            make_result = _send_email_via_make(
                to_email=purchaser_email,
                subject=subject,
                body_html=email_html,
                event_order_id=order_id,
                template_type="payment_confirmation",
                mail_id=mail_id,
            )
            
            if make_result.get("success"):
                email_sent = True
                print(f"[V2 MARK-PAID] Email wysłany do {purchaser_email}, mail_id={mail_id}")
            else:
                errors.append(f"Błąd wysyłki email: {make_result.get('error', 'nieznany')}")
        except Exception as e:
            errors.append(f"Wyjątek wysyłki email: {str(e)}")
            print(f"[V2 MARK-PAID] Wyjątek email: {e}")
    
    # 4. Zmień status na paid
    update_order_status(order_id, "paid")
    
    # 5. Wyślij emaile z biletami do uczestników
    participant_email_stats = {"sent": 0, "failed": 0, "skipped": 0}
    try:
        from backstage_engine import send_participant_ticket_emails, attendee_webhooks_status
        
        comp = attendee_webhooks_status(order_id)
        if comp.get("complete"):
            participant_email_stats = send_participant_ticket_emails(
                event_order_id=order_id,
                event_name=event_name,
                event_config=event_data,
                event_id=order.get("event_id", ""),
            )
            print(f"[V2 MARK-PAID] Emaile do uczestników: sent={participant_email_stats.get('sent', 0)}, failed={participant_email_stats.get('failed', 0)}, skipped={participant_email_stats.get('skipped', 0)}")
        else:
            print(f"[V2 MARK-PAID] Pomijam emaile do uczestników - brak kompletu webhooków: expected={comp.get('expected')}, received={comp.get('received')}")
            participant_email_stats["skipped_reason"] = "attendee_webhooks_incomplete"
    except Exception as e:
        errors.append(f"Błąd wysyłki potwierdzeń: {str(e)}")
        print(f"[V2 MARK-PAID] Błąd wysyłki potwierdzeń do uczestników: {e}")
    
    # 7. Audit log
    insert_admin_audit_log(
        action="order_marked_paid",
        admin_user_id=user.get("id") if user else None,
        target_id=order_id,
        extra={
            "invoice_generated": invoice_generated,
            "email_sent": email_sent,
            "participant_emails": participant_email_stats,
            "errors": errors,
        },
        ip=request.remote_addr,
    )
    
    # #region agent log
    try:
        with open(r'c:\Users\kochn\.cursor\Medidesk\wFirma\APIV1\.cursor\debug.log', 'a', encoding='utf-8') as _f:
            _f.write(_json.dumps({"location":"admin_v2_panel.py:_handle_mark_paid:done","message":"Mark paid completed","data":{"order_id":order_id,"invoice_generated":invoice_generated,"email_sent":email_sent,"errors":errors},"timestamp":__import__('time').time(),"sessionId":"debug-session","hypothesisId":"H3"}) + '\n')
    except: pass
    # #endregion
    
    if errors:
        return jsonify({
            "success": True,
            "status": "paid",
            "warnings": errors,
            "message": f"Status zmieniony na opłacone. Uwagi: {'; '.join(errors)}"
        })
    
    tickets_sent = participant_email_stats.get("sent", 0)
    tickets_msg = f", potwierdzenia wysłane ({tickets_sent})" if tickets_sent > 0 else ""
    
    return jsonify({
        "success": True,
        "status": "paid",
        "message": "Zamówienie oznaczone jako opłacone" + (", faktura wygenerowana" if invoice_generated else "") + (", email wysłany" if email_sent else "") + tickets_msg
    })


@admin_v2_bp.route("/orders/<order_id>/send-reminder", methods=["POST"])
@_require_permission("orders")
def order_send_reminder(order_id: str):
    """Wysyła przypomnienie o płatności."""
    from flask import jsonify
    from datetime import datetime, timedelta
    from pg_storage import get_stripe_session_by_order_id, save_mail_log
    from backstage_engine import _send_email_via_make
    from email_templates import render_checkout_reminder_email
    
    user = _get_current_admin_user()
    order = get_order(order_id)
    
    if not order:
        return jsonify({"success": False, "error": "Nie znaleziono zamówienia"}), 404
    
    # Sprawdź dostęp do wydarzenia zamówienia
    if order.get("event_id") and not _user_has_event_access(user, order["event_id"]):
        return jsonify({"success": False, "error": "Brak dostępu do tego zamówienia"}), 403
    
    # Viewer nie może wysyłać przypomnień
    if _is_viewer(user):
        return jsonify({"success": False, "error": "Nie masz uprawnień do wysyłania przypomnień"}), 403
    
    # Sprawdź status (tylko pending_payment lub received)
    if order.get("status") not in ["pending_payment", "received"]:
        return jsonify({"success": False, "error": "Zamówienie nie oczekuje na płatność"}), 400
    
    # Pobierz wydarzenie
    event = get_event(order.get("event_id"))
    if not event:
        return jsonify({"success": False, "error": "Nie znaleziono wydarzenia"}), 404
    
    # Pobierz sesję Stripe (jeśli istnieje) - opcjonalna dla proforma
    stripe_session = get_stripe_session_by_order_id(order_id)
    checkout_url = None
    expires_in = None
    expires_at_str = None
    is_proforma = "proforma" in str(order.get("payment_type") or "").lower() or "pro" in str(order.get("payment_option_name") or "").lower()
    
    if stripe_session and stripe_session.get("url"):
        checkout_url = stripe_session.get("url")
        # Sprawdź czy link nie wygasł
        session_created = stripe_session.get("created_at")
        if session_created:
            try:
                if hasattr(session_created, "tzinfo") and session_created.tzinfo:
                    now = datetime.now(session_created.tzinfo)
                else:
                    now = datetime.now()
                expires_at = session_created + timedelta(hours=24)
                if now > expires_at:
                    checkout_url = None  # Link wygasł
                else:
                    time_left = expires_at - now
                    hours_left = int(time_left.total_seconds() / 3600)
                    expires_in = f"{hours_left} godzin" if hours_left > 1 else "mniej niż godzina"
                    expires_at_str = expires_at.strftime("%d.%m.%Y, %H:%M")
            except Exception as e:
                print(f"[order_send_reminder] Błąd obliczania expires_at: {e}")
                expires_in = "24 godziny"
                expires_at_str = "wkrótce"
    
    # Jeśli nie ma aktywnego linku Stripe i nie jest to proforma - błąd
    if not checkout_url and not is_proforma:
        return jsonify({"success": False, "error": "Brak aktywnego linku do płatności. Utwórz nową sesję Stripe."}), 400
    
    # Pobierz email kupującego
    purchaser_email = order.get("purchaser_email")
    if not purchaser_email:
        return jsonify({"success": False, "error": "Brak adresu email kupującego"}), 400
    
    # Renderuj email
    event_config = event.get("data") or {}
    try:
        total_value = float(order.get("total", 0) or 0)
    except Exception:
        total_value = 0.0
    
    event_name = event.get("event_name", "Wydarzenie")
    
    if is_proforma and not checkout_url:
        # Dla proformy bez Stripe - email z przypomnieniem o proformie
        from email_templates import render_proforma_reservation_email
        proforma_number = order.get("proforma_number", "")
        
        # Pobierz bilety z zamówienia
        tickets = []
        order_data = order.get("data") or {}
        if "tickets" in order_data:
            tickets = order_data.get("tickets", [])
        elif "items" in order_data:
            tickets = order_data.get("items", [])
        
        try:
            html = render_proforma_reservation_email(
                event_name=event_name,
                purchaser_first_name=order.get("purchaser_first_name", ""),
                purchaser_last_name=order.get("purchaser_last_name", ""),
                purchaser_email=purchaser_email,
                purchaser_phone=order.get("purchaser_phone", ""),
                event_config=event_config,
                tickets=tickets,
                proforma_number=proforma_number,
            )
        except Exception as e:
            print(f"[order_send_reminder] Błąd renderowania emaila proforma: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"success": False, "error": f"Błąd generowania emaila: {e}"}), 500
        subject = f"Przypomnienie: Proforma {proforma_number} - {event_name}"
        template_key = "proforma_reminder"
    else:
        # Dla Stripe - standardowy email z linkiem
        try:
            html = render_checkout_reminder_email(
                event_name=event_name,
                purchaser_first_name=order.get("purchaser_first_name", ""),
                purchaser_last_name=order.get("purchaser_last_name", ""),
                purchaser_email=purchaser_email,
                total_gross=total_value,
                checkout_url=checkout_url,
                expires_at=expires_at_str,
                expires_in=expires_in,
                event_config=event_config,
            )
        except Exception as e:
            print(f"[order_send_reminder] Błąd renderowania emaila: {e}")
            return jsonify({"success": False, "error": f"Błąd generowania emaila: {e}"}), 500
        subject = f"Przypomnienie o płatności - {event_name}"
        template_key = "checkout_reminder"
    
    # Zapisz w mail_log
    mail_log_result = save_mail_log(
        event_order_id=order_id,
        direction="purchaser",
        template_key=template_key,
        to_email=purchaser_email,
        subject=subject,
    )
    mail_id = mail_log_result.get("id") if mail_log_result else None
    
    # Wyślij przez Make
    result = _send_email_via_make(
        to_email=purchaser_email,
        subject=subject,
        body_html=html,
        event_order_id=order_id,
        template_type=template_key,
        mail_id=mail_id,
    )
    
    # Audit log
    insert_admin_audit_log(
        action="order_reminder_sent",
        admin_user_id=user.get("id") if user else None,
        target_id=order_id,
        extra={"to_email": purchaser_email, "success": result.get("success")},
        ip=request.remote_addr,
    )
    
    if result.get("success"):
        return jsonify({"success": True, "message": "Przypomnienie zostało wysłane"})
    else:
        return jsonify({"success": False, "error": result.get("error", "Błąd wysyłki")}), 500


@admin_v2_bp.route("/orders/<order_id>/resend-ticket", methods=["POST"])
@_require_permission("orders")
def order_resend_ticket(order_id: str):
    """Ponownie wysyła bilety do wszystkich uczestników zamówienia."""
    from flask import jsonify
    from pg_storage import get_participants_for_order, save_mail_log
    from backstage_engine import _send_email_via_make
    from email_templates import render_participant_ticket_email
    import traceback
    
    print(f"[order_resend_ticket] START order_id={order_id}")
    
    try:
        user = _get_current_admin_user()
        order = get_order(order_id)
        print(f"[order_resend_ticket] order found: {order is not None}, status: {order.get('status') if order else 'N/A'}")
        
        if not order:
            return jsonify({"success": False, "error": "Nie znaleziono zamówienia"}), 404
        
        # Sprawdź status (tylko paid)
        if order.get("status") != "paid":
            return jsonify({"success": False, "error": "Zamówienie nie jest opłacone"}), 400
        
        # Pobierz wydarzenie
        event = get_event(order.get("event_id"))
        print(f"[order_resend_ticket] event found: {event is not None}")
        if not event:
            return jsonify({"success": False, "error": "Nie znaleziono wydarzenia"}), 404
        
        # Pobierz uczestników
        participants = get_participants_for_order(order_id)
        print(f"[order_resend_ticket] participants count: {len(participants) if participants else 0}")
        
        if not participants:
            return jsonify({"success": False, "error": "Brak uczestników w zamówieniu"}), 404
    except Exception as e:
        print(f"[order_resend_ticket] SETUP ERROR: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Błąd inicjalizacji: {e}"}), 500
    
    event_config = event.get("data") or {}
    event_name = event.get("event_name", "Wydarzenie")
    event_id = order.get("event_id", "")
    
    sent_count = 0
    failed_count = 0
    errors = []
    
    # Wyślij bilet dla każdego uczestnika
    for participant in participants:
        participant_email = participant.get("email")
        if not participant_email:
            failed_count += 1
            errors.append(f"Brak emaila dla uczestnika {participant.get('first_name', '')} {participant.get('last_name', '')}")
            continue
        
        # Pobierz dane biletu
        ticket_name = participant.get("ticket_class_name") or participant.get("ticket_name") or "Standard"
        # Usuń słowo "Bilet" z nazwy jeśli jest
        if ticket_name and isinstance(ticket_name, str):
            ticket_name = ticket_name.replace("Bilet ", "").replace("bilet ", "")
        ticket_id = participant.get("ticket_id", "")
        
        # Oblicz cenę biletu (średnia z zamówienia jeśli nie ma szczegółów)
        try:
            participant_data = participant.get("data") or {}
            ticket_price = float(participant_data.get("price", 0) or 0)
            if not ticket_price and len(participants) > 0:
                total = float(order.get("total", 0) or 0)
                ticket_price = total / len(participants)
        except Exception:
            ticket_price = 0.0
        
        # Renderuj email z biletem
        try:
            html = render_participant_ticket_email(
                event_name=event_name,
                participant_first_name=participant.get("first_name", ""),
                participant_last_name=participant.get("last_name", ""),
                participant_email=participant_email,
                ticket_name=ticket_name,
                ticket_id=ticket_id,
                ticket_price=ticket_price,
                event_config=event_config,
                event_id=event_id,
            )
        except Exception as e:
            print(f"[order_resend_ticket] Błąd renderowania emaila: {e}")
            failed_count += 1
            errors.append(f"Błąd generowania emaila dla {participant_email}: {e}")
            continue
        
        subject = f"Potwierdzenie rezerwacji na {event_name}"
        
        # Zapisz w mail_log
        mail_log_result = save_mail_log(
            event_order_id=order_id,
            direction="participant",
            template_key="participant_ticket_resend",
            to_email=participant_email,
            subject=subject,
        )
        mail_id = mail_log_result.get("id") if mail_log_result else None
        
        # Wyślij
        result = _send_email_via_make(
            to_email=participant_email,
            subject=subject,
            body_html=html,
            event_order_id=order_id,
            template_type="participant_ticket",
            mail_id=mail_id,
        )
        
        if result.get("success"):
            sent_count += 1
        else:
            failed_count += 1
            errors.append(f"Błąd wysyłki do {participant_email}: {result.get('error', 'Nieznany błąd')}")
    
    # Audit log
    insert_admin_audit_log(
        action="tickets_resent",
        admin_user_id=user.get("id") if user else None,
        target_id=order_id,
        extra={"sent": sent_count, "failed": failed_count, "total_participants": len(participants)},
        ip=request.remote_addr,
    )
    
    message = f"Wysłano {sent_count} potwierdzeń rezerwacji"
    if failed_count > 0:
        message += f", {failed_count} błędów"
    
    return jsonify({
        "success": sent_count > 0 or failed_count == 0,
        "sent": sent_count,
        "failed": failed_count,
        "errors": errors[:5] if errors else [],  # Ogranicz liczbę błędów w odpowiedzi
        "message": message,
    })


@admin_v2_bp.route("/orders/<order_id>/cancel", methods=["POST"])
@_require_permission("orders")
def order_cancel(order_id: str):
    """Anuluje zamówienie, generuje korektę jeśli była faktura, wykonuje refund Stripe, wysyła emaile."""
    from flask import jsonify
    from datetime import datetime
    from pg_storage import update_order_status, get_wfirma_documents, save_wfirma_document, get_participants_for_order, save_mail_log, get_event, get_stripe_session_by_order_id
    from backstage_engine import _send_email_via_make
    from email_templates import render_order_cancelled_email, render_participant_cancelled_email
    
    user = _get_current_admin_user()
    order = get_order(order_id)
    
    if not order:
        return jsonify({"success": False, "error": "Nie znaleziono zamówienia"}), 404
    
    # Sprawdź dostęp do wydarzenia zamówienia
    if order.get("event_id") and not _user_has_event_access(user, order["event_id"]):
        return jsonify({"success": False, "error": "Brak dostępu do tego zamówienia"}), 403
    
    # Viewer nie może anulować
    if _is_viewer(user):
        return jsonify({"success": False, "error": "Nie masz uprawnień do anulowania zamówień"}), 403
    
    if order.get("status") in ["cancelled", "refunded"]:
        return jsonify({"success": False, "error": "Zamówienie jest już anulowane lub zwrócone"}), 400
    
    was_paid = order.get("status") == "paid"
    correction_created = False
    correction_number = None
    correction_error = None
    emails_sent = {"purchaser": False, "participants": 0}
    
    # Parametr czy wykonać zwrot Stripe (domyślnie tak dla płatności Stripe)
    with_refund = request.form.get("with_refund", "1") == "1"
    
    # Zwrot Stripe (jeśli było opłacone przez Stripe i użytkownik zaznaczył checkbox)
    refund_created = False
    refund_amount = None
    refund_currency = None
    refund_error = None
    is_stripe_payment = False
    
    # Sprawdź czy to płatność Stripe
    payment_type = str(order.get("payment_type") or "").lower()
    payment_option = str(order.get("payment_option_name") or "").lower()
    is_proforma = "proforma" in payment_type or "pro" in payment_option
    
    if was_paid and not is_proforma and with_refund:
        # Sprawdź czy mamy sesję Stripe z payment_intent_id
        try:
            stripe_session = get_stripe_session_by_order_id(order_id)
            if stripe_session and stripe_session.get("payment_intent_id"):
                is_stripe_payment = True
                payment_intent_id = stripe_session.get("payment_intent_id")
                checkout_session_id = stripe_session.get("checkout_session_id") or ""
                
                # Wykryj czy to sandbox po checkout_session_id (cs_test_*) lub raw.stripe_mode
                is_sandbox = checkout_session_id.startswith("cs_test_")
                raw_data = stripe_session.get("raw") or {}
                if isinstance(raw_data, str):
                    try:
                        import json
                        raw_data = json.loads(raw_data)
                    except:
                        raw_data = {}
                if raw_data.get("stripe_mode") == "sandbox":
                    is_sandbox = True
                
                # Dodatkowe logowanie dla debugowania
                print(f"[CANCEL DEBUG] stripe_session keys: {list(stripe_session.keys())}")
                print(f"[CANCEL DEBUG] checkout_session_id starts with cs_test_: {checkout_session_id.startswith('cs_test_')}")
                print(f"[CANCEL DEBUG] raw_data.stripe_mode: {raw_data.get('stripe_mode')}")
                
                print(f"[CANCEL] Zamówienie {order_id} - płatność Stripe ({'SANDBOX' if is_sandbox else 'PROD'})")
                print(f"[CANCEL] payment_intent_id={payment_intent_id}, checkout_session_id={checkout_session_id[:30]}...")
                
                try:
                    import stripe
                    # Użyj odpowiedniego klucza API (sandbox lub produkcja)
                    if is_sandbox:
                        stripe_api_key = os.environ.get("STRIPE_RENDER_API_KEY_SANDBOX")
                        key_name = "SANDBOX"
                    else:
                        stripe_api_key = os.environ.get("STRIPE_RENDER_API_KEY")
                        key_name = "PROD"
                    
                    print(f"[CANCEL] Używam klucza Stripe: {key_name}, key_exists={bool(stripe_api_key)}")
                    
                    if stripe_api_key:
                        stripe.api_key = stripe_api_key
                        
                        # Wykonaj zwrot
                        print(f"[CANCEL] Wywołuję stripe.Refund.create(payment_intent={payment_intent_id})")
                        refund = stripe.Refund.create(
                            payment_intent=payment_intent_id,
                            reason="requested_by_customer",
                        )
                        
                        refund_created = True
                        refund_amount = refund.amount / 100.0
                        refund_currency = refund.currency.upper()
                        print(f"[CANCEL] Refund utworzony: {refund.id}, kwota: {refund_amount} {refund_currency}")
                    else:
                        key_name = "STRIPE_RENDER_API_KEY_SANDBOX" if is_sandbox else "STRIPE_RENDER_API_KEY"
                        refund_error = f"Brak konfiguracji {key_name}"
                        print(f"[CANCEL] Błąd refundu: {refund_error}")
                except Exception as e:
                    refund_error = f"Błąd Stripe: {str(e)}"
                    print(f"[CANCEL] Wyjątek przy refundzie: {e}")
        except Exception as e:
            print(f"[CANCEL] Błąd sprawdzania sesji Stripe: {e}")
    
    # Pobierz dane wydarzenia
    event_id = order.get("event_id", "")
    event = get_event(event_id) if event_id else None
    event_name = order.get("event_name") or (event.get("event_name") if event else "") or "Wydarzenie"
    event_data = (event.get("data") or {}) if event else {}
    
    # Sprawdź czy zamówienie ma fakturę VAT (document_type = 'normal')
    had_invoice = False
    try:
        documents = get_wfirma_documents(order_id)
        vat_invoice = None
        for doc in documents:
            if doc.get("document_type") == "normal" and doc.get("wfirma_invoice_id"):
                vat_invoice = doc
                had_invoice = True
                break
        
        if vat_invoice:
            # Jest faktura VAT - generuj korektę
            print(f"[CANCEL] Zamówienie {order_id} ma fakturę VAT: {vat_invoice.get('wfirma_number')}, generuję korektę...")
            
            try:
                from app import wfirma_create_correction, wfirma_get_company_id, load_token
                
                token = load_token()
                if token:
                    company_id = wfirma_get_company_id(token)
                    correction, resp = wfirma_create_correction(
                        token=token,
                        source_invoice_id=vat_invoice.get("wfirma_invoice_id"),
                        correction_description="Anulowanie zamówienia",
                        company_id=company_id,
                    )
                    
                    if correction:
                        correction_created = True
                        correction_number = correction.get("fullnumber")
                        
                        # Zapisz korektę do bazy
                        save_wfirma_document(
                            event_order_id=order_id,
                            wfirma_invoice_id=correction.get("id"),
                            wfirma_number=correction_number,
                            document_type="correction",
                            raw=correction,
                        )
                        print(f"[CANCEL] Korekta utworzona: {correction_number}")
                    else:
                        correction_error = "Nie udało się utworzyć korekty w wFirma"
                        print(f"[CANCEL] Błąd tworzenia korekty: {resp.text[:500] if resp else 'brak odpowiedzi'}")
                else:
                    correction_error = "Brak tokenu wFirma"
            except Exception as e:
                correction_error = f"Błąd generowania korekty: {str(e)}"
                print(f"[CANCEL] Wyjątek: {e}")
    except Exception as e:
        print(f"[CANCEL] Błąd sprawdzania dokumentów: {e}")
    
    # Zmień status zamówienia na cancelled
    result = update_order_status(order_id, "cancelled")
    
    if not result:
        return jsonify({"success": False, "error": "Nie udało się anulować zamówienia"}), 500
    
    cancel_date = datetime.now().strftime("%d.%m.%Y, %H:%M")
    
    # Wyślij email do kupującego (jeśli było opłacone lub miało fakturę)
    purchaser_email = order.get("purchaser_email", "")
    if purchaser_email and (was_paid or had_invoice):
        try:
            html = render_order_cancelled_email(
                event_name=event_name,
                purchaser_first_name=order.get("purchaser_first_name", "") or "Kliencie",
                purchaser_email=purchaser_email,
                order_id=order_id,
                cancel_date=cancel_date,
                had_invoice=had_invoice,
                correction_number=correction_number,
                event_config=event_data,
            )
            subject = f"Anulowanie zamówienia - {event_name}"
            
            # NAJPIERW zapisz do mail_log żeby mieć mail_id
            mail_log_result = save_mail_log(
                event_order_id=order_id,
                direction="purchaser",
                template_key="order_cancelled",
                to_email=purchaser_email,
                subject=subject,
            )
            mail_id = mail_log_result.get("id") if mail_log_result else None
            
            # POTEM wyślij z mail_id dla callbacka
            mail_result = _send_email_via_make(
                to_email=purchaser_email,
                subject=subject,
                body_html=html,
                event_order_id=order_id,
                template_type="order_cancelled",
                mail_id=mail_id,
            )
            
            if mail_result.get("success"):
                emails_sent["purchaser"] = True
                print(f"[CANCEL] Email do kupującego wysłany: {purchaser_email}, mail_id={mail_id}")
            else:
                print(f"[CANCEL] Błąd wysyłki do kupującego: {mail_result.get('error')}")
        except Exception as e:
            print(f"[CANCEL] Wyjątek przy wysyłce do kupującego: {e}")
    
    # Wyślij emaile do uczestników (jeśli było opłacone - dostali bilety)
    if was_paid:
        try:
            participants = get_participants_for_order(order_id) or []
            for p in participants:
                p_email = p.get("email", "")
                p_status = p.get("status", "")
                
                # Wysyłaj tylko do uczestników którzy dostali bilety (status 'emailed')
                if not p_email or p_status != "emailed":
                    continue
                
                try:
                    html = render_participant_cancelled_email(
                        event_name=event_name,
                        participant_first_name=p.get("first_name", "") or "Uczestniku",
                        participant_last_name=p.get("last_name", ""),
                        participant_email=p_email,
                        event_config=event_data,
                    )
                    subject = f"Anulowanie rejestracji - {event_name}"
                    
                    # NAJPIERW zapisz do mail_log żeby mieć mail_id
                    mail_log_result = save_mail_log(
                        event_order_id=order_id,
                        direction="participant",
                        template_key="participant_cancelled",
                        to_email=p_email,
                        subject=subject,
                    )
                    mail_id = mail_log_result.get("id") if mail_log_result else None
                    
                    # POTEM wyślij z mail_id dla callbacka
                    mail_result = _send_email_via_make(
                        to_email=p_email,
                        subject=subject,
                        body_html=html,
                        event_order_id=order_id,
                        template_type="participant_cancelled",
                        mail_id=mail_id,
                    )
                    
                    if mail_result.get("success"):
                        emails_sent["participants"] += 1
                        print(f"[CANCEL] Email do uczestnika wysłany: {p_email}, mail_id={mail_id}")
                    else:
                        print(f"[CANCEL] Błąd wysyłki do uczestnika {p_email}: {mail_result.get('error')}")
                except Exception as e:
                    print(f"[CANCEL] Błąd wysyłki do uczestnika {p_email}: {e}")
        except Exception as e:
            print(f"[CANCEL] Błąd pobierania uczestników: {e}")
    
    # Audit log
    insert_admin_audit_log(
        action="order_cancelled",
        admin_user_id=user.get("id") if user else None,
        target_id=order_id,
        extra={
            "was_paid": was_paid,
            "had_invoice": had_invoice,
            "correction_created": correction_created,
            "correction_number": correction_number,
            "correction_error": correction_error,
            "is_stripe_payment": is_stripe_payment,
            "with_refund_requested": with_refund,
            "refund_created": refund_created,
            "refund_amount": refund_amount,
            "refund_currency": refund_currency,
            "refund_error": refund_error,
            "emails_sent": emails_sent,
        },
        ip=request.remote_addr,
    )
    
    # Buduj komunikat
    message = "Zamówienie zostało anulowane"
    if refund_created:
        message += f", zwrot Stripe: {refund_amount:.2f} {refund_currency}"
    if correction_created:
        message += f", wygenerowano korektę: {correction_number}"
    if emails_sent["purchaser"]:
        message += ", email do kupującego wysłany"
    if emails_sent["participants"] > 0:
        message += f", emaile do {emails_sent['participants']} uczestników wysłane"
    if refund_error:
        message += f". Uwaga (zwrot): {refund_error}"
    if correction_error:
        message += f". Uwaga (korekta): {correction_error}"
    
    return jsonify({
        "success": True,
        "message": message,
        "correction_created": correction_created,
        "correction_number": correction_number,
        "refund_created": refund_created,
        "refund_amount": refund_amount,
        "refund_currency": refund_currency,
        "emails_sent": emails_sent,
    })


@admin_v2_bp.route("/orders/<order_id>/refund", methods=["POST"])
@_require_permission("orders")
def order_refund(order_id: str):
    """Realizuje zwrot płatności Stripe."""
    from flask import jsonify
    from pg_storage import get_stripe_session_by_order_id, update_order_status, save_error_task
    
    user = _get_current_admin_user()
    order = get_order(order_id)
    
    if not order:
        return jsonify({"success": False, "error": "Nie znaleziono zamówienia"}), 404
    
    # Sprawdź dostęp do wydarzenia zamówienia
    if order.get("event_id") and not _user_has_event_access(user, order["event_id"]):
        return jsonify({"success": False, "error": "Brak dostępu do tego zamówienia"}), 403
    
    # Viewer nie może wykonywać zwrotów
    if _is_viewer(user):
        return jsonify({"success": False, "error": "Nie masz uprawnień do wykonywania zwrotów"}), 403
    
    if order.get("status") != "paid":
        return jsonify({"success": False, "error": "Zamówienie nie jest opłacone (status: {})".format(order.get("status"))}), 400
    
    # Pobierz sesję Stripe
    stripe_session = get_stripe_session_by_order_id(order_id)
    if not stripe_session:
        return jsonify({"success": False, "error": "Brak danych płatności Stripe dla tego zamówienia"}), 404
    
    payment_intent_id = stripe_session.get("payment_intent_id")
    if not payment_intent_id:
        return jsonify({"success": False, "error": "Brak Payment Intent ID - nie można wykonać zwrotu"}), 400
    
    # Przyczyna zwrotu (opcjonalnie z formularza)
    reason = request.form.get("reason", "requested_by_customer")
    if reason not in ["duplicate", "fraudulent", "requested_by_customer"]:
        reason = "requested_by_customer"
    
    # Wykryj czy to sandbox po checkout_session_id (cs_test_*) lub raw.stripe_mode
    checkout_session_id = stripe_session.get("checkout_session_id") or ""
    is_sandbox = checkout_session_id.startswith("cs_test_")
    raw_data = stripe_session.get("raw") or {}
    if isinstance(raw_data, str):
        try:
            import json
            raw_data = json.loads(raw_data)
        except:
            raw_data = {}
    if raw_data.get("stripe_mode") == "sandbox":
        is_sandbox = True
    
    print(f"[order_refund] order={order_id}, payment_intent={payment_intent_id}")
    print(f"[order_refund] checkout_session_id={checkout_session_id[:30]}..., is_sandbox={is_sandbox}")
    
    try:
        import stripe
        
        # Użyj odpowiedniego klucza API (sandbox lub produkcja)
        if is_sandbox:
            stripe_api_key = os.environ.get("STRIPE_RENDER_API_KEY_SANDBOX")
            key_name = "STRIPE_RENDER_API_KEY_SANDBOX"
        else:
            stripe_api_key = os.environ.get("STRIPE_RENDER_API_KEY")
            key_name = "STRIPE_RENDER_API_KEY"
        
        print(f"[order_refund] using_key={key_name}, key_exists={bool(stripe_api_key)}")
        
        if not stripe_api_key:
            return jsonify({"success": False, "error": f"Brak konfiguracji {key_name}"}), 500
        
        stripe.api_key = stripe_api_key
        
        # Wykonaj zwrot
        refund = stripe.Refund.create(
            payment_intent=payment_intent_id,
            reason=reason,
        )
        
        # Aktualizuj status zamówienia
        update_order_status(order_id, "refunded")
        
        # Zapisz w audit log
        insert_admin_audit_log(
            action="order_refunded",
            admin_user_id=user.get("id") if user else None,
            target_id=order_id,
            extra={
                "refund_id": refund.id,
                "reason": reason,
                "amount": refund.amount,
                "currency": refund.currency,
            },
            ip=request.remote_addr,
        )
        
        return jsonify({
            "success": True,
            "refund_id": refund.id,
            "amount": refund.amount / 100.0,  # Stripe zwraca w groszach
            "currency": refund.currency.upper(),
            "message": f"Zwrot zrealizowany: {refund.amount / 100.0:.2f} {refund.currency.upper()}",
        })
        
    except ImportError:
        return jsonify({"success": False, "error": "Biblioteka Stripe nie jest zainstalowana"}), 500
    except Exception as e:
        error_msg = str(e)
        print(f"[order_refund] Stripe error: {error_msg}")
        
        # Zapisz błąd do Work Queue
        save_error_task(
            category="stripe",
            severity="error",
            title=f"Błąd zwrotu płatności: {order_id}",
            description=error_msg,
            event_order_id=order_id,
            error_data={"payment_intent_id": payment_intent_id, "reason": reason},
            can_retry=True,
        )
        
        return jsonify({"success": False, "error": f"Błąd Stripe: {error_msg}"}), 500


@admin_v2_bp.route("/orders/<order_id>/send-proforma", methods=["POST"])
@_require_permission("orders")
def order_send_proforma(order_id: str):
    """Wysyła email z proformą do kupującego."""
    from flask import jsonify
    from pg_storage import get_order
    
    user = _get_current_admin_user()
    
    order = get_order(order_id)
    if not order:
        return jsonify({"success": False, "error": "Nie znaleziono zamówienia"}), 404
    
    # Sprawdź dostęp do wydarzenia zamówienia
    if order.get("event_id") and not _user_has_event_access(user, order["event_id"]):
        return jsonify({"success": False, "error": "Brak dostępu do tego zamówienia"}), 403
    
    # Viewer nie może wysyłać proform
    if _is_viewer(user):
        return jsonify({"success": False, "error": "Nie masz uprawnień do wysyłania proform"}), 403
    
    try:
        from email_templates import render_proforma_sent_email
        
        buyer_email = order.get("buyer_email")
        if not buyer_email:
            return jsonify({"success": False, "error": "Brak adresu email kupującego"}), 400
        
        proforma_number = order.get("proforma_number")
        if not proforma_number:
            return jsonify({"success": False, "error": "Zamówienie nie ma numeru proformy"}), 400
        
        # Pobierz dane wydarzenia
        event = get_event(order.get("event_id"))
        event_name = event.get("event_name", "Wydarzenie") if event else "Wydarzenie"
        
        # Renderuj email
        html_content = render_proforma_sent_email(
            buyer_name=f"{order.get('buyer_first_name', '')} {order.get('buyer_last_name', '')}".strip(),
            event_name=event_name,
            proforma_number=proforma_number,
            total=order.get("total", 0),
            payment_deadline=order.get("payment_deadline", "7 dni"),
            checkout_url=order.get("checkout_url", ""),
        )
        
        # Wyślij przez Make webhook
        from backstage_engine import _send_email_via_make
        result = _send_email_via_make(
            to_email=buyer_email,
            subject=f"Faktura proforma {proforma_number} - {event_name}",
            body_html=html_content,
            event_order_id=order_id,
            template_type="proforma_resent",
        )
        
        if result.get("success"):
            user = _get_current_admin_user()
            insert_admin_audit_log(
                action="proforma_sent",
                admin_user_id=user.get("id") if user else None,
                target_id=order_id,
                extra={"proforma_number": proforma_number, "email": buyer_email},
                ip=request.remote_addr,
            )
            return jsonify({"success": True, "message": f"Proforma wysłana do {buyer_email}"})
        else:
            return jsonify({"success": False, "error": result.get("error", "Błąd wysyłki")}), 500
            
    except Exception as e:
        print(f"[order_send_proforma] Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@admin_v2_bp.route("/orders/<order_id>/delete", methods=["POST"])
@_require_permission("orders")
def order_delete(order_id: str):
    """Usuwa zamówienie i powiązane dane (NIEODWRACALNE!)."""
    from flask import jsonify
    from pg_storage import get_order, delete_order
    
    user = _get_current_admin_user()
    
    # Tylko admin może usuwać zamówienia
    if not _is_admin_user(user):
        return jsonify({"success": False, "error": "Tylko administrator może usuwać zamówienia"}), 403
    
    order = get_order(order_id)
    if not order:
        return jsonify({"success": False, "error": "Nie znaleziono zamówienia"}), 404
    
    # Sprawdź dostęp do wydarzenia zamówienia
    if order.get("event_id") and not _user_has_event_access(user, order["event_id"]):
        return jsonify({"success": False, "error": "Brak dostępu do tego zamówienia"}), 403
    
    if not order:
        return jsonify({"success": False, "error": "Zamówienie nie istnieje lub zostało już usunięte"}), 404
    
    try:
        # Zaloguj przed usunięciem
        order_total = order.get("total")
        insert_admin_audit_log(
            action="order_deleted",
            admin_user_id=user.get("id") if user else None,
            target_id=order_id,
            extra={
                "buyer_email": order.get("buyer_email"),
                "event_id": order.get("event_id"),
                "total": float(order_total) if order_total is not None else None,
                "status": order.get("status"),
            },
            ip=request.remote_addr,
        )
        
        # Usuń zamówienie (i powiązane dane: uczestników, bilety, maile)
        result = delete_order(order_id)
        
        if result and not result.get("error"):
            return jsonify({"success": True, "message": "Zamówienie zostało usunięte", "deleted": result})
        else:
            return jsonify({"success": False, "error": result.get("error", "Błąd podczas usuwania")}), 500
            
    except Exception as e:
        print(f"[order_delete] Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@admin_v2_bp.route("/documents/<int:doc_id>/pdf", methods=["GET"])
@_require_permission("orders")
def document_download_pdf(doc_id: int):
    """Pobiera PDF dokumentu wFirma."""
    from flask import Response, jsonify
    from pg_storage import get_wfirma_token
    import requests
    
    # Pobierz dokument z bazy
    from pg_storage import ensure_schema, _with_conn, _dict_cursor, _put_conn
    
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            "SELECT * FROM wfirma_documents WHERE id = %s",
            (doc_id,),
        )
        doc = cur.fetchone()
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)
    
    if not doc:
        return jsonify({"success": False, "error": "Dokument nie istnieje"}), 404
    
    invoice_id = doc.get("wfirma_invoice_id")
    if not invoice_id:
        return jsonify({"success": False, "error": "Brak ID dokumentu wFirma"}), 400
    
    # Pobierz token wFirma i sprawdź czy nie wygasł
    import time
    wfirma_token = get_wfirma_token("md")
    if not wfirma_token or not wfirma_token.get("access_token"):
        return jsonify({"success": False, "error": "Brak tokenu wFirma - skonfiguruj integrację"}), 500
    
    # Sprawdź czy access token nie wygasł
    access_token = wfirma_token["access_token"]
    expires_at = wfirma_token.get("access_token_expires_at", 0)
    
    if time.time() >= expires_at:
        # Token wygasł - odśwież go
        print(f"[document_download_pdf] Access token wygasł, odświeżam...")
        try:
            from app import refresh_access_token
            new_token = refresh_access_token(company="md")
            if new_token:
                access_token = new_token
                print(f"[document_download_pdf] Token odświeżony pomyślnie")
            else:
                return jsonify({"success": False, "error": "Nie udało się odświeżyć tokenu wFirma - sprawdź integrację"}), 500
        except Exception as refresh_err:
            print(f"[document_download_pdf] Błąd odświeżania tokenu: {refresh_err}")
            return jsonify({"success": False, "error": f"Błąd odświeżania tokenu: {refresh_err}"}), 500
    
    try:
        # Pobierz PDF z wFirma API
        api_url = f"https://api2.wfirma.pl/invoices/download/{invoice_id}"
        params = {
            "inputFormat": "json",
            "outputFormat": "json",
            "oauth_version": "2",
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/pdf"
        }
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
        
        resp = requests.post(api_url, headers=headers, params=params, json=body, stream=True, timeout=30)
        
        if resp.status_code == 200 and 'pdf' in resp.headers.get('Content-Type', '').lower():
            # Nazwa pliku
            doc_number = doc.get("wfirma_number", "dokument").replace("/", "-")
            filename = f"{doc_number}.pdf"
            
            return Response(
                resp.content,
                mimetype='application/pdf',
                headers={
                    'Content-Disposition': f'attachment; filename="{filename}"',
                    'Content-Type': 'application/pdf'
                }
            )
        else:
            error_msg = f"wFirma zwróciło błąd: {resp.status_code}"
            try:
                error_data = resp.json()
                if "status" in error_data:
                    error_msg = error_data.get("status", {}).get("message", error_msg)
            except:
                pass
            return jsonify({"success": False, "error": error_msg}), 500
            
    except requests.Timeout:
        return jsonify({"success": False, "error": "Timeout podczas pobierania PDF"}), 504
    except Exception as e:
        print(f"[document_download_pdf] Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# EMAIL DESIGNER
# ---------------------------------------------------------------------------

@admin_v2_bp.route("/email-designer", methods=["GET"])
@_require_permission("events")
def email_designer():
    """Email Designer - projektowanie szablonów email."""
    user = _get_current_admin_user()
    
    # Pobierz wydarzenia dla dropdowna
    events = list_events(limit=100)
    
    # Pobierz ID szablonu do edycji (jeśli podano)
    template_id = request.args.get("template_id", type=int)
    template_data = None
    
    if template_id:
        from pg_storage import get_email_template
        template_data = get_email_template(template_id)
    
    return render_template(
        "admin_v2/email-designer.html",
        active_page="email_designer",
        events=events,
        template_data=template_data,
        **_get_common_context(user),
    )


# ---------------------------------------------------------------------------
# EMAIL TEMPLATES API
# ---------------------------------------------------------------------------


@admin_v2_bp.route("/api/templates", methods=["GET"])
@_require_permission("events")
def api_templates_list():
    """API: Lista szablonów emaili."""
    from flask import jsonify
    from pg_storage import list_email_templates, count_email_templates
    
    category = request.args.get("category")
    template_type = request.args.get("type")
    event_id = request.args.get("event_id")
    search = request.args.get("search")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    
    offset = (page - 1) * per_page
    
    templates = list_email_templates(
        category=category,
        template_type=template_type,
        event_id=event_id,
        search=search,
        limit=per_page,
        offset=offset,
    )
    
    total = count_email_templates(category=category, template_type=template_type)
    
    return jsonify({
        "success": True,
        "templates": templates,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (total + per_page - 1) // per_page,
        },
    })


@admin_v2_bp.route("/api/templates/<int:template_id>", methods=["GET"])
@_require_permission("events")
def api_template_get(template_id: int):
    """API: Pobierz szablon."""
    from flask import jsonify
    from pg_storage import get_email_template
    
    template = get_email_template(template_id)
    
    if not template:
        return jsonify({"success": False, "error": "Szablon nie istnieje"}), 404
    
    return jsonify({
        "success": True,
        "template": template,
    })


@admin_v2_bp.route("/api/templates", methods=["POST"])
@_require_permission("events")
def api_template_create():
    """API: Utwórz nowy szablon."""
    from flask import jsonify
    from pg_storage import save_email_template
    
    try:
        user = _get_current_admin_user()
        data = request.get_json() or {}
        
        name = data.get("name", "").strip()
        subject = data.get("subject", "").strip()
        blocks = data.get("blocks", [])
        category = data.get("category", "custom")
        template_type = data.get("template_type", "custom")
        html_content = data.get("html_content")
        event_id = data.get("event_id") or None
        
        if not name:
            return jsonify({"success": False, "error": "Nazwa szablonu jest wymagana"}), 400
        
        template_id = save_email_template(
            name=name,
            subject=subject,
            blocks=blocks,
            category=category,
            template_type=template_type,
            html_content=html_content,
            event_id=event_id,
            admin_user_id=user.get("id") if user else None,
        )
        
        if not template_id:
            return jsonify({"success": False, "error": "Błąd zapisu szablonu - sprawdź logi serwera"}), 500
        
        # Audit log (ignore errors)
        try:
            insert_admin_audit_log(
                action="template_created",
                admin_user_id=user.get("id") if user else None,
                target_id=str(template_id),
                extra={"name": name, "category": category, "type": template_type},
                ip=request.remote_addr,
            )
        except Exception as audit_err:
            print(f"[TEMPLATE] Audit log error (ignored): {audit_err}")
        
        return jsonify({
            "success": True,
            "template_id": template_id,
            "message": f"Szablon '{name}' został utworzony",
        })
    except Exception as e:
        import traceback
        print(f"[TEMPLATE CREATE ERROR] {e}")
        print(traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500


@admin_v2_bp.route("/api/templates/<int:template_id>", methods=["PUT"])
@_require_permission("events")
def api_template_update(template_id: int):
    """API: Aktualizuj szablon."""
    from flask import jsonify
    from pg_storage import save_email_template, get_email_template
    
    user = _get_current_admin_user()
    
    # Sprawdź czy istnieje
    existing = get_email_template(template_id)
    if not existing:
        return jsonify({"success": False, "error": "Szablon nie istnieje"}), 404
    
    # Nie pozwól edytować szablonów systemowych
    if existing.get("is_system"):
        return jsonify({"success": False, "error": "Nie można edytować szablonów systemowych"}), 403
    
    data = request.get_json() or {}
    
    name = data.get("name", existing["name"]).strip()
    subject = data.get("subject", existing["subject"]).strip()
    blocks = data.get("blocks", existing["blocks"])
    category = data.get("category", existing["category"])
    template_type = data.get("template_type", existing["template_type"])
    html_content = data.get("html_content", existing.get("html_content"))
    event_id = data.get("event_id", existing.get("event_id"))
    
    if not name:
        return jsonify({"success": False, "error": "Nazwa szablonu jest wymagana"}), 400
    
    result_id = save_email_template(
        name=name,
        subject=subject,
        blocks=blocks,
        category=category,
        template_type=template_type,
        html_content=html_content,
        event_id=event_id,
        admin_user_id=user.get("id") if user else None,
        template_id=template_id,
    )
    
    if not result_id:
        return jsonify({"success": False, "error": "Błąd aktualizacji szablonu"}), 500
    
    # Audit log
    insert_admin_audit_log(
        action="template_updated",
        admin_user_id=user.get("id") if user else None,
        target_id=str(template_id),
        extra={"name": name},
        ip=request.remote_addr,
    )
    
    return jsonify({
        "success": True,
        "template_id": template_id,
        "message": f"Szablon '{name}' został zaktualizowany",
    })


@admin_v2_bp.route("/api/templates/<int:template_id>", methods=["DELETE"])
@_require_permission("events")
def api_template_delete(template_id: int):
    """API: Usuń szablon."""
    from flask import jsonify
    from pg_storage import delete_email_template, get_email_template
    
    try:
        user = _get_current_admin_user()
        
        # Sprawdź czy istnieje
        existing = get_email_template(template_id)
        if not existing:
            return jsonify({"success": False, "error": "Szablon nie istnieje"}), 404
        
        # Nie pozwól usuwać szablonów systemowych
        if existing.get("is_system"):
            return jsonify({"success": False, "error": "Nie można usunąć szablonów systemowych"}), 403
        
        success = delete_email_template(template_id)
        
        if not success:
            return jsonify({"success": False, "error": "Błąd usuwania szablonu"}), 500
        
        # Audit log (ignore errors)
        try:
            insert_admin_audit_log(
                action="template_deleted",
                admin_user_id=user.get("id") if user else None,
                target_id=str(template_id),
                extra={"name": existing.get("name")},
                ip=request.remote_addr,
            )
        except Exception as audit_err:
            print(f"[TEMPLATE] Audit log error (ignored): {audit_err}")
        
        return jsonify({
            "success": True,
            "message": f"Szablon '{existing.get('name')}' został usunięty",
        })
    except Exception as e:
        import traceback
        print(f"[TEMPLATE DELETE ERROR] {e}")
        print(traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500


@admin_v2_bp.route("/api/templates/<int:template_id>/duplicate", methods=["POST"])
@_require_permission("events")
def api_template_duplicate(template_id: int):
    """API: Duplikuj szablon."""
    from flask import jsonify
    from pg_storage import duplicate_email_template, get_email_template
    
    user = _get_current_admin_user()
    data = request.get_json() or {}
    new_name = data.get("name")
    
    # Sprawdź czy istnieje
    existing = get_email_template(template_id)
    if not existing:
        return jsonify({"success": False, "error": "Szablon nie istnieje"}), 404
    
    new_id = duplicate_email_template(
        template_id=template_id,
        new_name=new_name,
        admin_user_id=user.get("id") if user else None,
    )
    
    if not new_id:
        return jsonify({"success": False, "error": "Błąd duplikowania szablonu"}), 500
    
    # Audit log
    insert_admin_audit_log(
        action="template_duplicated",
        admin_user_id=user.get("id") if user else None,
        target_id=str(new_id),
        extra={"source_id": template_id, "source_name": existing.get("name")},
        ip=request.remote_addr,
    )
    
    return jsonify({
        "success": True,
        "template_id": new_id,
        "message": f"Szablon został zduplikowany",
    })


@admin_v2_bp.route("/api/events/<event_id>/preview-data", methods=["GET"])
@_require_permission("events")
def api_event_preview_data(event_id: str):
    """API: Pobiera dane wydarzenia do podglądu szablonu emaila."""
    from flask import jsonify
    from pg_storage import get_participants_for_event
    
    try:
        event = get_event(event_id)
        if not event:
            return jsonify({"success": False, "error": "Wydarzenie nie istnieje"}), 404
        
        event_data = event.get("data") or {}
        
        # Pobierz przykładowego uczestnika (jeśli istnieje)
        try:
            all_participants = get_participants_for_event(event_id)
            sample_participant = all_participants[0] if all_participants else {}
        except Exception:
            sample_participant = {}
        
        # Pobierz przykładowe zamówienie
        try:
            orders = list_orders(event_id=event_id, limit=1)
            sample_order = orders[0] if orders else {}
        except Exception:
            sample_order = {}
        
        # Bezpieczne parsowanie total
        def safe_float(val, default=0.0):
            if val is None or val == "":
                return default
            try:
                return float(val)
            except (ValueError, TypeError):
                return default
        
        # Przygotuj dane do podstawienia placeholderów
        preview_data = {
            # Wydarzenie
            "event_name": event.get("event_name", "Nazwa wydarzenia"),
            "event_date": event_data.get("eventDate") or event_data.get("event_date") or "2026-03-15",
            "event_time": event_data.get("eventTime") or event_data.get("event_time") or "09:00",
            "event_end_date": event_data.get("event_end_date") or "",
            "event_end_time": event_data.get("event_end_time") or "",
            "event_location": event_data.get("event_location_place") or event_data.get("eventLocation") or event_data.get("location") or "Lokalizacja wydarzenia",
            "event_city": event_data.get("event_location_city") or event_data.get("eventCity") or "Warszawa",
            "event_address": event_data.get("event_location_address") or event_data.get("eventAddress") or "ul. Przykładowa 1",
            "event_description": event_data.get("event_description") or event_data.get("eventDescription") or "",
            
            # Linki wydarzenia
            "event_public_url": event_data.get("event_public_url") or event_data.get("backstage_website_url") or "https://example.com/event",
            "success_page_url": event_data.get("success_page_url") or "https://example.com/success",
            "cancel_page_url": event_data.get("cancel_page_url") or "https://example.com/cancel",
            
            # Branding
            "event_logo_url": event_data.get("event_logo_url") or "",
            "email_header_url": event_data.get("email_header_url") or "",
            "color_gradient_1": event_data.get("color_gradient_1") or "#0065D7",
            "color_gradient_2": event_data.get("color_gradient_2") or "#00A3E0",
            
            # Kontakt
            "contact_email": event_data.get("md_email_kontakt") or "kontakt@example.com",
            "contact_phone": event_data.get("md_mobile_kontakt") or "+48 123 456 789",
            
            # Nabywca (z przykładowego zamówienia)
            "buyer_name": sample_order.get("purchaser_name") or "Jan Kowalski",
            "buyer_email": sample_order.get("purchaser_email") or "jan.kowalski@example.com",
            "buyer_phone": sample_order.get("purchaser_phone") or "+48 123 456 789",
            "buyer_company": sample_order.get("purchaser_company") or "Firma Przykładowa Sp. z o.o.",
            "buyer_nip": sample_order.get("purchaser_nip") or "1234567890",
            "buyer_address": sample_order.get("purchaser_address") or "ul. Firmowa 10, 00-001 Warszawa",
            
            # Uczestnik (z przykładowego uczestnika)
            "participant_name": f"{sample_participant.get('first_name', 'Anna')} {sample_participant.get('last_name', 'Nowak')}",
            "participant_first_name": sample_participant.get("first_name") or "Anna",
            "participant_last_name": sample_participant.get("last_name") or "Nowak",
            "participant_email": sample_participant.get("email") or "anna.nowak@example.com",
            "participant_company": sample_participant.get("company") or "Firma Uczestnika",
            "participant_position": sample_participant.get("position") or "Specjalista",
            "ticket_name": sample_participant.get("ticket_name") or "Standard",
            "ticket_code": sample_participant.get("ticket_code") or "TICKET-123456",
            
            # Płatność
            "order_id": sample_order.get("event_order_id") or "ORD-2026-001",
            "order_total": f"{safe_float(sample_order.get('total'), 499.00):.2f} PLN",
            "payment_status": sample_order.get("status") or "paid",
            "payment_url": sample_order.get("checkout_url") or "https://checkout.stripe.com/pay/xxx",
            
            # Organizator
            "organizer_name": "Medidesk",
            "organizer_address": "ul. Organizatora 5, 00-001 Warszawa",
            "organizer_email": event_data.get("md_email_kontakt") or "kontakt@medidesk.pl",
            "organizer_phone": event_data.get("md_mobile_kontakt") or "+48 123 456 789",
            "organizer_website": "https://medidesk.pl",
            
            # Daty formatowane
            "current_date": "24.01.2026",
            "current_year": "2026",
        }
        
        return jsonify({
            "success": True,
            "event_id": event_id,
            "event_name": event.get("event_name"),
            "preview_data": preview_data,
        })
    except Exception as e:
        import traceback
        print(f"[PREVIEW-DATA ERROR] {event_id}: {e}")
        print(traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# EVENT ROUTES (nowe strony V2)
# ---------------------------------------------------------------------------

@admin_v2_bp.route("/events/new", methods=["GET", "POST"])
@_require_permission("events")
def event_new():
    """Tworzenie nowego wydarzenia."""
    from pg_storage import upsert_event
    
    user = _get_current_admin_user()
    error = None
    success = None
    
    if request.method == "POST":
        event_id = (request.form.get("event_id") or "").strip()
        event_name = (request.form.get("event_name") or "").strip()
        
        if not event_id or not event_name:
            error = "Wymagane: ID wydarzenia i Nazwa wydarzenia"
        else:
            # Sprawdź czy event_id już istnieje
            existing = get_event(event_id)
            if existing:
                error = f"Wydarzenie o ID '{event_id}' już istnieje"
            else:
                # Zbierz dane
                is_active = request.form.get("is_active") == "1"
                
                # Pola synchronizowane z Zoho
                event_date_time = request.form.get("event_date_time") or ""
                event_end_date_time = request.form.get("event_end_date_time") or ""
                event_description = request.form.get("event_description") or ""
                event_summary = request.form.get("event_summary") or ""
                
                # Formatuj daty do ISO (dodaj sekundy jeśli brak)
                if event_date_time and len(event_date_time) == 16:
                    event_date_time = event_date_time + ":00"
                if event_end_date_time and len(event_end_date_time) == 16:
                    event_end_date_time = event_end_date_time + ":00"
                
                data = {
                    # Pola synchronizowane
                    "event_date_time": event_date_time,
                    "event_end_date_time": event_end_date_time,
                    "event_description": event_description,
                    "event_summary": event_summary,
                    # Pola tylko lokalne
                    "color_gradient_1": request.form.get("color_gradient_1") or "#2563eb",
                    "color_gradient_2": request.form.get("color_gradient_2") or "#1e40af",
                    "event_mail_link_top_banner": request.form.get("event_mail_link_top_banner") or "",
                    "url_event": request.form.get("url_event") or "",
                    "md_email_kontakt": request.form.get("md_email_kontakt") or "konferencje@medidesk.com",
                }
                
                try:
                    upsert_event(event_id, event_name, status="active", notes="", data=data, is_active=is_active)
                    return redirect(url_for("admin_v2_bp.event_dashboard", event_id=event_id))
                except Exception as e:
                    error = f"Błąd tworzenia wydarzenia: {e}"
    
    # Pobierz listę wszystkich wydarzeń dla funkcji "Kopiuj z innego"
    all_events = list_events()
    
    return render_template(
        "admin_v2/event_form.html",
        active_page="events",
        event=None,
        event_data=None,
        all_events=all_events,
        error=error,
        success=success,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/events/<event_id>/edit", methods=["GET", "POST"])
@_require_permission("events")
def event_edit(event_id: str):
    """Edycja wydarzenia."""
    import requests as http_requests
    from pg_storage import upsert_event
    
    user = _get_current_admin_user()
    
    # Sprawdź dostęp do tego konkretnego wydarzenia
    if not _user_has_event_access(user, event_id):
        return render_template(
            "admin_v2/base.html",
            active_page="",
            **_get_common_context(user),
        ), 403
    
    # Viewer nie może edytować
    if request.method == "POST" and _is_viewer(user):
        return jsonify({"success": False, "error": "Nie masz uprawnień do edycji"}), 403
    
    event = get_event(event_id)
    if not event:
        return redirect(url_for("admin_v2_bp.events_list"))
    
    error = None
    webhook_sent = False
    
    if request.method == "POST":
        event_name = (request.form.get("event_name") or "").strip()
        
        if not event_name:
            error = "Wymagane: Nazwa wydarzenia"
        else:
            is_active = request.form.get("is_active") == "1"
            data = event.get("data") or {}
            
            # Pola synchronizowane z Zoho
            event_date_time = request.form.get("event_date_time") or ""
            event_end_date_time = request.form.get("event_end_date_time") or ""
            event_description = request.form.get("event_description") or ""
            event_summary = request.form.get("event_summary") or ""
            
            # Formatuj daty do ISO (dodaj sekundy jeśli brak)
            if event_date_time and len(event_date_time) == 16:
                event_date_time = event_date_time + ":00"
            if event_end_date_time and len(event_end_date_time) == 16:
                event_end_date_time = event_end_date_time + ":00"
            
            # Aktualizuj dane - pola synchronizowane
            data.update({
                "event_date_time": event_date_time,
                "event_end_date_time": event_end_date_time,
                "event_description": event_description,
                "event_summary": event_summary,
            })
            
            # Aktualizuj dane - pola tylko lokalne
            data.update({
                "color_gradient_1": request.form.get("color_gradient_1") or "#2563eb",
                "color_gradient_2": request.form.get("color_gradient_2") or "#1e40af",
                "event_mail_link_top_banner": request.form.get("event_mail_link_top_banner") or "",
                "url_event": request.form.get("url_event") or "",
                "url_success": request.form.get("url_success") or "",
                "url_cancel": request.form.get("url_cancel") or "",
                "map_hotel_link": request.form.get("map_hotel_link") or "",
                # Dane kontaktowe
                "md_email_kontakt": request.form.get("md_email_kontakt") or "eventy@medidesk.com",
                "md_phone_kontakt": request.form.get("md_phone_kontakt") or "+48729927389",
                "md_email_technical": request.form.get("md_email_technical") or "adminzoho@medidesk.com",
                "md_phone_technical": request.form.get("md_phone_technical") or "+48888469553",
            })
            
            try:
                upsert_event(
                    event_id=event_id,
                    event_name=event_name,
                    status=event.get("status") or "active",
                    notes=event.get("notes") or "",
                    data=data,
                    is_active=is_active
                )
                
                # Wyślij webhook do Zoho Flow (jeśli skonfigurowany)
                webhook_sent = False
                if ZOHO_FLOW_EVENT_UPDATE_WEBHOOK:
                    try:
                        webhook_payload = {
                            "event_id": event_id,
                            "event_name": event_name,
                            "status": event.get("status") or "active",
                            "is_active": is_active,
                            "start_date": event_date_time,
                            "end_date": event_end_date_time,
                            "event_description": event_description,
                            "event_summary": event_summary,
                            "updated_by": user.get("email", "unknown") if user else "unknown",
                        }
                        resp = http_requests.post(
                            ZOHO_FLOW_EVENT_UPDATE_WEBHOOK,
                            json=webhook_payload,
                            headers={"Content-Type": "application/json"},
                            timeout=10,
                        )
                        webhook_sent = resp.status_code in (200, 201, 202)
                        print(f"[EVENT EDIT] Webhook sent: {webhook_sent}, event={event_id}")
                    except Exception as wh_err:
                        print(f"[EVENT EDIT] Webhook error: {wh_err}")
                else:
                    print(f"[EVENT EDIT] Webhook skipped: ZOHO_FLOW_EVENT_UPDATE_WEBHOOK not configured")
                
                # Po zapisie przekieruj do event room
                from flask import flash
                flash("Wydarzenie zostało zaktualizowane" + (" i zsynchronizowane z Zoho" if webhook_sent else ""), "success")
                return redirect(url_for("admin_v2_bp.event_room", event_id=event_id))
            except Exception as e:
                error = f"Błąd aktualizacji: {e}"
    
    # Normalizuj dane wydarzenia (rekonstruuje event_date_time jeśli brak)
    event = _normalize_event_data(event)
    event_data = event.get("data") or {}
    
    # Pobierz typy biletów dla wydarzenia
    from pg_storage import get_ticket_classes
    ticket_classes = get_ticket_classes(event_id)
    
    # Pobierz listę wszystkich wydarzeń dla funkcji "Kopiuj z innego"
    all_events = list_events()
    
    return render_template(
        "admin_v2/event_form.html",
        active_page="events",
        event=event,
        event_data=event_data,
        ticket_classes=ticket_classes,
        all_events=all_events,
        error=error,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/events/<event_id>/delete", methods=["POST"])
@_require_permission("events")
def event_delete(event_id: str):
    """Usuwa wydarzenie wraz ze wszystkimi powiązanymi danymi (zamówienia, uczestnicy, maile)."""
    from flask import jsonify
    from pg_storage import delete_event_cascade
    
    user = _get_current_admin_user()
    
    # Tylko admin może usuwać wydarzenia
    if not _is_admin_user(user):
        return jsonify({"success": False, "error": "Tylko administrator może usuwać wydarzenia"}), 403
    
    # Sprawdź dostęp do wydarzenia
    if not _user_has_event_access(user, event_id):
        return jsonify({"success": False, "error": "Brak dostępu do tego wydarzenia"}), 403
    
    # Sprawdź czy wydarzenie istnieje
    event = get_event(event_id)
    if not event:
        return jsonify({"success": False, "error": "Nie znaleziono wydarzenia"}), 404
    
    event_name = event.get("event_name", event_id)
    
    try:
        # Kaskadowe usuwanie
        deleted = delete_event_cascade(event_id)
        
        # Audit log
        insert_admin_audit_log(
            action="event_deleted_cascade",
            admin_user_id=user.get("id") if user else None,
            target_id=event_id,
            extra={
                "event_name": event_name,
                "deleted_counts": deleted,
            },
            ip=request.remote_addr,
        )
        
        return jsonify({
            "success": True,
            "message": f"Wydarzenie '{event_name}' zostało usunięte",
            "deleted": deleted,
        })
        
    except Exception as e:
        print(f"[event_delete] Error: {e}")
        return jsonify({"success": False, "error": f"Błąd usuwania: {e}"}), 500


@admin_v2_bp.route("/events/<event_id>/sync-backstage", methods=["POST"])
@_require_permission("events")
def event_sync_backstage(event_id: str):
    """Pobiera dane wydarzenia z Backstage API i zwraca podgląd zmian (bez zapisu)."""
    from flask import jsonify
    
    user = _get_current_admin_user()
    
    # Sprawdź dostęp do wydarzenia
    if not _user_has_event_access(user, event_id):
        return jsonify({"success": False, "error": "Brak dostępu do tego wydarzenia"}), 403
    
    # Viewer nie może synchronizować (tylko podgląd)
    if _is_viewer(user):
        return jsonify({"success": False, "error": "Nie masz uprawnień do synchronizacji"}), 403
    
    user = _get_current_admin_user()
    
    # Sprawdź dostęp do wydarzenia
    if not _user_has_event_access(user, event_id):
        return jsonify({"success": False, "error": "Brak dostępu do tego wydarzenia"}), 403
    
    # Viewer może przeglądać dane z Backstage (readonly)
    # Nie blokujemy tego endpointu dla viewer
    
    # Sprawdź czy wydarzenie istnieje
    event = get_event(event_id)
    if not event:
        return jsonify({"success": False, "error": "Nie znaleziono wydarzenia"}), 404
    
    # Sprawdź konfigurację Backstage API
    try:
        from zoho_backstage_api import is_backstage_configured, sync_event_from_backstage
    except ImportError as e:
        return jsonify({"success": False, "error": f"Moduł zoho_backstage_api niedostępny: {e}"}), 500
    
    if not is_backstage_configured():
        return jsonify({
            "success": False, 
            "error": "Backstage API nie jest skonfigurowane. Ustaw BACKSTAGE_CLIENT_ID, BACKSTAGE_CLIENT_SECRET i BACKSTAGE_REFRESH_TOKEN."
        }), 400
    
    # Pobierz dane z Backstage (bez zapisu)
    result = sync_event_from_backstage(event_id)
    
    if not result.get("success"):
        return jsonify({"success": False, "error": result.get("error", "Nieznany błąd")}), 500
    
    # Przygotuj porównanie: obecne vs nowe
    current_data = event.get("data") or {}
    new_data = result.get("event_data", {})
    
    # DEBUG: Loguj dane lokalizacji
    print(f"[SYNC COMPARE DEBUG] Event ID: {event_id}")
    print(f"[SYNC COMPARE DEBUG] Current data location fields:")
    print(f"  event_location_place: {current_data.get('event_location_place')}")
    print(f"  eventLocation: {current_data.get('eventLocation')}")
    print(f"  event_location_city: {current_data.get('event_location_city')}")
    print(f"  eventCity: {current_data.get('eventCity')}")
    print(f"[SYNC COMPARE DEBUG] New data location fields:")
    print(f"  event_location_place: {new_data.get('event_location_place')}")
    print(f"  event_location_address: {new_data.get('event_location_address')}")
    print(f"  event_location_city: {new_data.get('event_location_city')}")
    
    # Pola do porównania (label, klucz, typ)
    # Używamy KANONICZNYCH nazw pól ale sprawdzamy też aliasy
    def get_current(key, *aliases):
        """Pobiera aktualną wartość - sprawdza kanoniczny klucz i aliasy."""
        val = current_data.get(key)
        for alias in aliases:
            if val:
                break
            val = current_data.get(alias)
        return val
    
    def get_current_date(key):
        """Pobiera datę - wyciąga z różnych formatów (event_date_time -> event_date)."""
        # Najpierw sprawdź kanoniczny klucz
        val = current_data.get(key)
        if val:
            return val[:10] if len(val) >= 10 else val
        # Sprawdź format datetime
        if key == "event_date":
            dt = current_data.get("event_date_time") or current_data.get("eventDate") or ""
            return dt[:10] if dt else ""
        if key == "event_end_date":
            dt = current_data.get("event_end_date_time") or current_data.get("eventEndDate") or ""
            return dt[:10] if dt else ""
        return ""
    
    def get_current_time(key):
        """Pobiera godzinę - wyciąga z różnych formatów."""
        val = current_data.get(key)
        if val:
            return val[:5] if len(val) >= 5 else val
        # Sprawdź format datetime
        if key == "event_time":
            dt = current_data.get("event_date_time") or ""
            if "T" in dt:
                return dt.split("T")[1][:5]
            return current_data.get("eventTime") or ""
        if key == "event_end_time":
            dt = current_data.get("event_end_date_time") or ""
            if "T" in dt:
                return dt.split("T")[1][:5]
            return current_data.get("eventEndTime") or ""
        return ""
    
    compare_fields = [
        ("Nazwa wydarzenia", "event_name", "text", event.get("event_name"), result.get("event_name")),
        # Lokalizacja - kanoniczne nazwy (event_location_*)
        ("Miejsce (venue)", "event_location_place", "text", 
         get_current("event_location_place", "eventLocation"), new_data.get("event_location_place")),
        ("Adres", "event_location_address", "text", 
         get_current("event_location_address", "eventAddress"), new_data.get("event_location_address")),
        ("Miasto", "event_location_city", "text", 
         get_current("event_location_city", "eventCity"), new_data.get("event_location_city")),
        ("Pełny adres", "location", "text", current_data.get("location"), new_data.get("location")),
        # Daty - wyciągamy z różnych formatów
        ("Data wydarzenia", "event_date", "date", get_current_date("event_date"), new_data.get("event_date")),
        ("Godzina rozpoczęcia", "event_time", "time", get_current_time("event_time"), new_data.get("event_time")),
        ("Data zakończenia", "event_end_date", "date", get_current_date("event_end_date"), new_data.get("event_end_date")),
        ("Godzina zakończenia", "event_end_time", "time", get_current_time("event_end_time"), new_data.get("event_end_time")),
        # Opis
        ("Opis", "event_description", "textarea", current_data.get("event_description"), new_data.get("event_description")),
        ("Podsumowanie", "event_summary", "textarea", current_data.get("event_summary"), new_data.get("event_summary")),
        # Metadane
        ("Status Backstage", "backstage_status", "text", current_data.get("backstage_status"), new_data.get("backstage_status")),
        ("Typ wydarzenia", "event_type", "text", current_data.get("event_type"), new_data.get("event_type")),
        ("URL strony", "backstage_website_url", "url", current_data.get("backstage_website_url"), new_data.get("backstage_website_url")),
        ("Miniatura", "thumbnail_url", "image", current_data.get("thumbnail_url"), new_data.get("thumbnail_url")),
    ]
    
    # Buduj listę zmian
    changes = []
    for label, key, field_type, current_val, new_val in compare_fields:
        current_str = str(current_val or "").strip()
        new_str = str(new_val or "").strip()
        
        has_change = current_str != new_str and new_str  # zmiana tylko jeśli nowa wartość niepusta
        
        changes.append({
            "key": key,
            "label": label,
            "type": field_type,
            "current": current_val or "",
            "new": new_val or "",
            "has_change": has_change,
            "selected": has_change,  # domyślnie zaznacz jeśli jest zmiana
        })
    
    # Klasy biletów
    ticket_classes = result.get("ticket_classes", [])
    
    return jsonify({
        "success": True,
        "mode": "preview",
        "event_id": event_id,
        "event_name": result.get("event_name"),
        "changes": changes,
        "ticket_classes": ticket_classes,
        "ticket_classes_count": len(ticket_classes),
        "new_data": new_data,  # pełne dane do zapisu
    })


@admin_v2_bp.route("/events/<event_id>/apply-backstage", methods=["POST"])
@_require_permission("events")
def event_apply_backstage(event_id: str):
    """Zapisuje wybrane pola z Backstage do wydarzenia."""
    from flask import jsonify
    from pg_storage import upsert_event, save_ticket_class
    
    user = _get_current_admin_user()
    
    # Sprawdź dostęp do wydarzenia
    if not _user_has_event_access(user, event_id):
        return jsonify({"success": False, "error": "Brak dostępu do tego wydarzenia"}), 403
    
    # Viewer nie może aplikować zmian
    if _is_viewer(user):
        return jsonify({"success": False, "error": "Nie masz uprawnień do edycji"}), 403
    
    user = _get_current_admin_user()
    
    # Sprawdź dostęp do wydarzenia
    if not _user_has_event_access(user, event_id):
        return jsonify({"success": False, "error": "Brak dostępu do tego wydarzenia"}), 403
    
    # Viewer nie może aplikować zmian
    if _is_viewer(user):
        return jsonify({"success": False, "error": "Nie masz uprawnień do edycji"}), 403
    
    # Sprawdź czy wydarzenie istnieje
    event = get_event(event_id)
    if not event:
        return jsonify({"success": False, "error": "Nie znaleziono wydarzenia"}), 404
    
    data = request.get_json() or {}
    selected_keys = data.get("selected_keys", [])
    new_data = data.get("new_data", {})
    new_event_name = data.get("event_name")
    save_tickets = data.get("save_tickets", False)
    ticket_classes = data.get("ticket_classes", [])
    
    if not selected_keys and not save_tickets:
        return jsonify({"success": False, "error": "Nie wybrano żadnych pól do aktualizacji"}), 400
    
    try:
        current_data = event.get("data") or {}
        
        # Aplikuj tylko wybrane pola
        updated_fields = []
        for key in selected_keys:
            if key in new_data:
                current_data[key] = new_data[key]
                updated_fields.append(key)
        
        # Synchronizuj wszystkie warianty dat (jeśli wybrano jakiekolwiek pole daty/czasu)
        date_fields_selected = {"event_date", "event_time", "event_end_date", "event_end_time"} & set(selected_keys)
        if date_fields_selected:
            # Pobierz wartości dat z new_data (już są wszystkie warianty z Backstage API)
            for variant in ["event_date", "event_time", "event_end_date", "event_end_time",
                            "event_date_time", "event_end_date_time", 
                            "eventDate", "eventTime", "eventEndDate", "eventEndTime"]:
                if variant in new_data and new_data[variant]:
                    current_data[variant] = new_data[variant]
        
        # Dodaj timestamp synchronizacji
        current_data["backstage_synced_at"] = new_data.get("backstage_synced_at")
        
        # Aktualizuj nazwę wydarzenia jeśli wybrana
        final_event_name = event.get("event_name")
        if "event_name" in selected_keys and new_event_name:
            final_event_name = new_event_name
        
        # Zapisz wydarzenie
        upsert_event(
            event_id=event_id,
            event_name=final_event_name,
            status=event.get("status") or "active",
            notes=event.get("notes") or "",
            data=current_data,
            is_active=event.get("is_active", True),
        )
        
        # Zapisz klasy biletów jeśli wybrane
        saved_tickets = 0
        if save_tickets and ticket_classes:
            for tc in ticket_classes:
                tc_id = tc.get("ticket_class_id")
                if tc_id:
                    save_ticket_class(
                        event_id=event_id,
                        ticket_class_id=tc_id,
                        ticket_name=tc.get("ticket_name", ""),
                        data=tc,
                    )
                    saved_tickets += 1
        
        # Audit log
        insert_admin_audit_log(
            action="event_backstage_applied",
            admin_user_id=user.get("id") if user else None,
            target_id=event_id,
            extra={
                "updated_fields": updated_fields,
                "saved_tickets": saved_tickets,
            },
            ip=request.remote_addr,
        )
        
        return jsonify({
            "success": True,
            "message": f"Zaktualizowano {len(updated_fields)} pól" + (f" i {saved_tickets} klas biletów" if saved_tickets else ""),
            "updated_fields": updated_fields,
            "saved_tickets": saved_tickets,
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": f"Błąd zapisu: {e}"}), 500


@admin_v2_bp.route("/events/<event_id>/sync-tickets", methods=["POST"])
@_require_permission("events")
def event_sync_tickets(event_id: str):
    """Pobiera typy biletów z Backstage API i zapisuje lokalnie."""
    from flask import jsonify
    from zoho_backstage_api import fetch_ticket_classes, is_backstage_configured, map_ticket_class_to_local
    from pg_storage import save_ticket_class
    
    user = _get_current_admin_user()
    
    # Sprawdź dostęp do wydarzenia
    if not _user_has_event_access(user, event_id):
        return jsonify({"success": False, "error": "Brak dostępu do tego wydarzenia"}), 403
    
    # Viewer nie może synchronizować
    if _is_viewer(user):
        return jsonify({"success": False, "error": "Nie masz uprawnień do synchronizacji"}), 403
    
    # Sprawdź czy wydarzenie istnieje
    event = get_event(event_id)
    if not event:
        return jsonify({"success": False, "error": "Nie znaleziono wydarzenia"}), 404
    
    # Sprawdź konfigurację Backstage
    if not is_backstage_configured():
        return jsonify({
            "success": False, 
            "error": "Backstage API nie jest skonfigurowane. Ustaw zmienne środowiskowe."
        }), 400
    
    try:
        # Pobierz typy biletów z Backstage
        ticket_classes, error = fetch_ticket_classes(event_id)
        
        if error:
            return jsonify({"success": False, "error": f"Błąd Backstage API: {error}"}), 500
        
        if not ticket_classes:
            return jsonify({
                "success": True,
                "message": "Brak typów biletów w Backstage dla tego wydarzenia",
                "count": 0,
            })
        
        # Zapisz typy biletów lokalnie
        saved_count = 0
        for tc in ticket_classes:
            tc_data = map_ticket_class_to_local(tc)
            tc_id = tc_data.get("ticket_class_id")
            if tc_id:
                save_ticket_class(
                    event_id=event_id,
                    ticket_class_id=tc_id,
                    ticket_name=tc_data.get("ticket_name", ""),
                    data=tc_data,
                )
                saved_count += 1
        
        # Audit log
        insert_admin_audit_log(
            action="tickets_synced_from_backstage",
            admin_user_id=user.get("id") if user else None,
            target_id=event_id,
            extra={"saved_count": saved_count},
            ip=request.remote_addr,
        )
        
        return jsonify({
            "success": True,
            "message": f"Pobrano {saved_count} typ(ów) biletów z Backstage",
            "count": saved_count,
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": f"Błąd: {e}"}), 500


@admin_v2_bp.route("/events/<event_id>/preview", methods=["GET"])
@_require_permission("events")
def event_preview(event_id: str):
    """Podgląd wydarzenia."""
    user = _get_current_admin_user()
    
    event = get_event(event_id)
    if not event:
        return redirect(url_for("admin_v2_bp.events_list"))
    
    return render_template(
        "admin_v2/event_preview.html",
        active_page="events",
        event=event,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/events/<event_id>/dashboard", methods=["GET"])
@_require_permission("events")
def event_dashboard(event_id: str):
    """Dashboard pojedynczego wydarzenia - przekierowanie do Event Room."""
    # Dashboard jest teraz zakładką "Sprzedaż" w Event Room
    return redirect(url_for("admin_v2_bp.event_room", event_id=event_id, tab="sales"))


@admin_v2_bp.route("/events", methods=["GET"])
@_require_permission("events")
def events_list():
    """Lista wydarzeń."""
    user = _get_current_admin_user()
    
    # Filtry
    status_filter = request.args.get("status", "").strip().lower()
    q_filter = request.args.get("q", "").strip().lower()
    
    all_events = list_events(limit=500)
    
    # FILTROWANIE WEDŁUG UPRAWNIEŃ UŻYTKOWNIKA (dla viewer)
    role = (user.get("role") or "").lower()
    if role == "viewer":
        allowed_event_ids = user.get("allowed_events") or []
        if isinstance(allowed_event_ids, str):
            import json
            try:
                allowed_event_ids = json.loads(allowed_event_ids)
            except:
                allowed_event_ids = []
        # Konwertuj na stringi dla bezpiecznego porównania
        allowed_event_ids = [str(eid) for eid in allowed_event_ids if eid]
        all_events = [e for e in all_events if str(e.get("event_id")) in allowed_event_ids]
    
    # Filtrowanie tekstowe
    if q_filter:
        all_events = [
            e for e in all_events
            if q_filter in (e.get("event_name") or "").lower()
            or q_filter in (e.get("event_id") or "").lower()
        ]
    
    # Filtrowanie po statusie
    if status_filter == "active":
        all_events = [e for e in all_events if e.get("is_active", True)]
    elif status_filter == "completed":
        all_events = [e for e in all_events if not e.get("is_active", True)]
    
    # Dodaj statystyki i normalizuj dane dla wszystkich wydarzeń
    for event in all_events:
        event_id = event.get("event_id")
        orders = list_orders(event_id=event_id, limit=500)
        event["order_count"] = len(orders)
        event["participant_count"] = sum(int(o.get("participant_count") or 0) for o in orders)
        # Normalizuj pola z Backstage
        _normalize_event_data(event)
    
    # Podziel na 3 kategorie:
    # 1. Aktywne - is_active=True i opublikowane (backstage_status != "unpublished")
    # 2. W konfiguracji - nieopublikowane (backstage_status == "unpublished")
    # 3. Nieaktywne - is_active=False
    active_events = []
    config_events = []
    inactive_events = []
    
    for e in all_events:
        event_data = e.get("data") or {}
        backstage_status = event_data.get("backstage_status", "").lower()
        is_active = e.get("is_active", True)
        
        if not is_active:
            inactive_events.append(e)
        elif backstage_status == "unpublished":
            config_events.append(e)
        else:
            active_events.append(e)
    
    # Funkcja pomocnicza do grupowania po miesiącach/latach
    def group_by_month(events_list, ascending=False):
        """Grupuj wydarzenia po miesiącu/roku, sortuj chronologicznie."""
        from collections import defaultdict
        from datetime import datetime
        
        groups = defaultdict(list)
        for event in events_list:
            event_data = event.get("data") or {}
            # Pobierz datę wydarzenia - użyj event_date_time lub eventDate
            date_str = event_data.get("event_date_time") or event_data.get("eventDate") or event_data.get("event_date") or ""
            if date_str:
                try:
                    # Parsuj datę (format: YYYY-MM-DD lub YYYY-MM-DDTHH:MM)
                    dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
                    month_key = dt.strftime("%Y-%m")
                    month_label = dt.strftime("%B %Y").capitalize()
                    # Polskie nazwy miesięcy
                    pl_months = {
                        "January": "Styczeń", "February": "Luty", "March": "Marzec",
                        "April": "Kwiecień", "May": "Maj", "June": "Czerwiec",
                        "July": "Lipiec", "August": "Sierpień", "September": "Wrzesień",
                        "October": "Październik", "November": "Listopad", "December": "Grudzień"
                    }
                    for en, pl in pl_months.items():
                        month_label = month_label.replace(en, pl)
                    groups[(month_key, month_label)].append(event)
                except Exception:
                    groups[("0000-00", "Bez daty")].append(event)
            else:
                groups[("0000-00", "Bez daty")].append(event)
        
        # Sortuj grupy chronologicznie (ascending dla aktywnych - od najbliższych)
        sorted_groups = []
        for (key, label), events in sorted(groups.items(), key=lambda x: x[0][0], reverse=not ascending):
            # Sortuj wydarzenia w grupie po dacie (użyj pełnej daty z czasem)
            def get_event_datetime(e):
                ed = e.get("data") or {}
                return ed.get("event_date_time") or ed.get("eventDate") or ""
            events_sorted = sorted(events, key=get_event_datetime, reverse=not ascending)
            sorted_groups.append({"key": key, "label": label, "events": events_sorted})
        
        return sorted_groups
    
    # Pogrupuj każdą kategorię (aktywne rosnąco - od najbliższych, reszta malejąco)
    active_grouped = group_by_month(active_events, ascending=True)
    config_grouped = group_by_month(config_events, ascending=True)
    inactive_grouped = group_by_month(inactive_events, ascending=False)
    
    return render_template(
        "admin_v2/events.html",
        active_page="events",
        active_events=active_events,
        config_events=config_events,
        inactive_events=inactive_events,
        active_grouped=active_grouped,
        config_grouped=config_grouped,
        inactive_grouped=inactive_grouped,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/participants", methods=["GET"])
@_require_permission("orders")  # Reuse orders permission for participants
def participants_list():
    """Lista wszystkich uczestników."""
    user = _get_current_admin_user()
    
    # Filtry
    event_id_filter = request.args.get("event_id", "").strip()
    status_filter = request.args.get("status", "").strip()
    q_filter = request.args.get("q", "").strip().lower()
    
    # Pobierz wydarzenia do filtra
    events = list_events(limit=200)
    
    # FILTROWANIE WEDŁUG UPRAWNIEŃ UŻYTKOWNIKA (dla viewer)
    role = (user.get("role") or "").lower()
    if role == "viewer":
        allowed_event_ids = user.get("allowed_events") or []
        if isinstance(allowed_event_ids, str):
            import json
            try:
                allowed_event_ids = json.loads(allowed_event_ids)
            except:
                allowed_event_ids = []
        allowed_event_ids = [str(eid) for eid in allowed_event_ids if eid]
        # Filtruj wydarzenia w dropdown
        events = [e for e in events if str(e.get("event_id")) in allowed_event_ids]
    
    # Pobierz uczestników - jeśli wybrany event, tylko z niego
    all_participants = []
    if event_id_filter:
        all_participants = get_participants_for_event(event_id_filter) or []
        # Dodaj event info
        event = get_event(event_id_filter)
        event_data = (event.get("data") or {}) if event else {}
        for p in all_participants:
            p["event_name"] = event.get("event_name", "") if event else ""
            p["event_color"] = event_data.get("color_gradient_1", "hsl(212, 100%, 42%)")
            p["event_color_2"] = event_data.get("color_gradient_2", "hsl(195, 100%, 42%)")
    else:
        # Pobierz z wszystkich aktywnych wydarzeń (już przefiltrowanych według uprawnień)
        for event in events:
            if event.get("is_active", True):
                event_participants = get_participants_for_event(event.get("event_id")) or []
                event_data = event.get("data") or {}
                for p in event_participants:
                    p["event_name"] = event.get("event_name", "")
                    p["event_color"] = event_data.get("color_gradient_1", "hsl(212, 100%, 42%)")
                    p["event_color_2"] = event_data.get("color_gradient_2", "hsl(195, 100%, 42%)")
                all_participants.extend(event_participants)
    
    # Filtrowanie po statusie
    if status_filter:
        all_participants = [p for p in all_participants if p.get("status") == status_filter]
    
    # Filtrowanie tekstowe
    if q_filter:
        all_participants = [
            p for p in all_participants
            if q_filter in (p.get("email") or "").lower()
            or q_filter in (p.get("first_name") or "").lower()
            or q_filter in (p.get("last_name") or "").lower()
        ]
    
    # Statystyki
    stats = {
        "total": len(all_participants),
        "emailed": len([p for p in all_participants if p.get("status") == "emailed"]),
        "registered": len([p for p in all_participants if p.get("status") == "registered"]),
        "pending": len([p for p in all_participants if p.get("status") == "pending"]),
    }
    
    # Ogranicz do 500 dla wydajności
    all_participants = all_participants[:500]
    
    # Mapuj pola dla szablonu
    for p in all_participants:
        # Preferuj nazwę biletu, ale nie pokazuj długich ID numerycznych
        ticket_name = p.get("ticket_class_name") or ""
        ticket_id = p.get("ticket_class_id") or ""
        # Usuń słowo "Bilet" z nazwy jeśli jest
        if ticket_name:
            ticket_name = ticket_name.replace("Bilet ", "").replace("bilet ", "")
        # Jeśli ticket_id wygląda jak długi numer (>10 cyfr), nie pokazuj go
        if not ticket_name and ticket_id and len(str(ticket_id)) > 10 and str(ticket_id).isdigit():
            ticket_name = "Standard"
        p["ticket_name"] = ticket_name or ticket_id or "Standard"
        p["is_notified"] = p.get("status") == "emailed"
        p["company"] = p.get("company") or ""
    
    return render_template(
        "admin_v2/participants.html",
        active_page="participants",
        participants=all_participants,
        events=events,
        stats=stats,
        total_participants=stats["total"],
        **_get_common_context(user),
    )


@admin_v2_bp.route("/participants/<participant_id>", methods=["GET"])
@_require_permission("orders")
def participant_detail(participant_id):
    """Szczegóły uczestnika."""
    print(f"[PARTICIPANT DETAIL] Called with participant_id={participant_id} (type={type(participant_id).__name__})")
    user = _get_current_admin_user()
    
    from pg_storage import get_participant_by_attendee_id
    
    participant = None
    
    # Strategia 1: Spróbuj jako ID bazy danych (małe liczby)
    try:
        participant_id_int = int(participant_id)
        if participant_id_int < 1000000000:  # Małe ID = prawdopodobnie z bazy
            participant = get_participant_by_id(participant_id_int)
            print(f"[PARTICIPANT DETAIL] get_participant_by_id({participant_id_int}) returned: {participant is not None}")
    except (ValueError, TypeError):
        pass
    
    # Strategia 2: Spróbuj jako attendee_id z Zoho (duże liczby)
    if not participant:
        participant = get_participant_by_attendee_id(str(participant_id))
        print(f"[PARTICIPANT DETAIL] get_participant_by_attendee_id({participant_id}) returned: {participant is not None}")
    
    if not participant:
        print(f"[PARTICIPANT DETAIL] Participant not found by any method, redirecting to list")
        return redirect(url_for("admin_v2_bp.participants_list"))
    
    # Rozpakuj dane wydarzenia (bezpieczne parsowanie JSONB)
    event_data = participant.get("event_data") or {}
    if isinstance(event_data, str):
        try:
            event_data = json.loads(event_data)
        except Exception:
            event_data = {}
    if not isinstance(event_data, dict):
        event_data = {}
    
    participant["event_color"] = event_data.get("color_gradient_1", "#0065D7")
    participant["event_color_2"] = event_data.get("color_gradient_2", "#00A1D7")
    
    # Normalizacja dat (obsługa różnych formatów)
    raw_start = event_data.get("event_date_time") or event_data.get("event_date") or event_data.get("eventDate") or ""
    raw_time = event_data.get("event_time") or event_data.get("event_time_text") or event_data.get("eventTime") or ""
    start_date = raw_start[:10] if raw_start else ""
    if not raw_time and "T" in raw_start:
        raw_time = raw_start.split("T")[1][:5]
    
    participant["event_date"] = start_date or ""
    participant["event_time"] = raw_time or ""
    participant["event_location"] = (
        event_data.get("location")
        or event_data.get("event_location_place")
        or event_data.get("eventLocation")
        or ""
    )
    
    # Rozpakuj dodatkowe dane uczestnika z JSON
    p_data = participant.get("data") or {}
    participant["company"] = p_data.get("company") or p_data.get("firma") or ""
    participant["position"] = p_data.get("position") or p_data.get("stanowisko") or ""
    participant["dietary"] = p_data.get("dietary") or p_data.get("dieta") or ""
    participant["notes"] = p_data.get("notes") or p_data.get("uwagi") or ""
    
    # Mapuj nazwę biletu i usuń słowo "Bilet"
    ticket_name = participant.get("ticket_class_name") or ""
    ticket_id = participant.get("ticket_class_id") or ""
    # Usuń słowo "Bilet" z nazwy jeśli jest
    if ticket_name:
        ticket_name = ticket_name.replace("Bilet ", "").replace("bilet ", "")
    if not ticket_name and ticket_id and len(str(ticket_id)) > 10 and str(ticket_id).isdigit():
        ticket_name = "Standard"
    participant["ticket_name"] = ticket_name or ticket_id or "Standard"
    
    # Pobierz historię komunikacji dla uczestnika
    from pg_storage import get_mail_log_by_email
    emails = []
    if participant.get("email"):
        try:
            emails = get_mail_log_by_email(participant["email"]) or []
        except Exception:
            emails = []
    
    # Zbuduj historię uczestnika
    participant_history = []
    
    # Dodaj zdarzenie utworzenia
    if participant.get("created_at"):
        participant_history.append({
            "type": "registration",
            "title": "Rejestracja uczestnika",
            "description": f"Uczestnik został zarejestrowany w ramach zamówienia",
            "timestamp": _format_datetime_pl(participant["created_at"]),
        })
    
    # Mapowanie template_key na czytelną nazwę
    template_key_labels = {
        "participant_ticket": "Potwierdzenie rezerwacji",
        "participant_ticket_resend": "Ponowne potwierdzenie rezerwacji",
        "participant_cancel": "Anulowanie rezerwacji",
        "participant_cancelled": "Anulowanie rezerwacji",
        "purchaser_payment_confirmation": "Potwierdzenie płatności",
        "purchaser_order_confirmation": "Potwierdzenie zamówienia",
        "purchaser_payment_reminder": "Przypomnienie o płatności",
        "purchaser_order_cancel": "Anulowanie zamówienia",
        "order_cancelled": "Anulowanie zamówienia",
    }
    
    # Dodaj emaile
    for email in emails:
        template_key = email.get("template_key") or ""
        email_title = template_key_labels.get(template_key, email.get("subject") or "Email")
        
        participant_history.append({
            "type": "email",
            "title": email_title,
            "description": email.get("subject") or "",
            "status": email.get("status"),
            "status_label": {
                "sent": "Wysłano",
                "delivered": "Dostarczono",
                "queued": "W kolejce",
                "error": "Błąd",
                "bounced": "Odrzucono",
            }.get(email.get("status"), email.get("status")),
            "timestamp": _format_datetime_pl(email.get("sent_at")),
        })
    
    # Sortuj historię po czasie (najnowsze na górze)
    participant_history.sort(
        key=lambda x: x.get("timestamp", ""),
        reverse=True
    )
    
    return render_template(
        "admin_v2/participant_detail.html",
        active_page="participants",
        participant=participant,
        participant_history=participant_history,
        emails=emails,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/participants/<int:participant_id>/edit", methods=["GET", "POST"])
@_require_permission("orders")
def participant_edit(participant_id: int):
    """Edycja danych uczestnika."""
    from pg_storage import _with_conn, _put_conn
    
    user = _get_current_admin_user()
    participant = get_participant_by_id(participant_id)
    
    if not participant:
        return redirect(url_for("admin_v2_bp.participants_list"))
    
    error = None
    success = None
    
    if request.method == "POST":
        # Pobierz dane z formularza
        email = request.form.get("email", "").strip()
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        phone = request.form.get("phone", "").strip()
        company = request.form.get("company", "").strip()
        position = request.form.get("position", "").strip()
        
        if not email:
            error = "Email jest wymagany"
        elif not first_name:
            error = "Imię jest wymagane"
        else:
            # Aktualizuj w DB
            pool = None
            conn = None
            try:
                pool, conn = _with_conn()
                cur = conn.cursor()
                
                # Pobierz obecne data JSON
                cur.execute("SELECT data FROM participants WHERE id = %s", (participant_id,))
                row = cur.fetchone()
                current_data = row[0] if row else {}
                if not isinstance(current_data, dict):
                    current_data = {}
                
                # Aktualizuj data z dodatkowymi polami
                current_data["company"] = company
                current_data["position"] = position
                
                import json
                import psycopg2.extras
                
                cur.execute("""
                    UPDATE participants
                    SET email = %s, first_name = %s, last_name = %s, phone = %s,
                        data = %s,
                        updated_at = NOW()
                    WHERE id = %s
                """, (
                    email, first_name, last_name, phone,
                    psycopg2.extras.Json(current_data),
                    participant_id
                ))
                
                # Audit log
                insert_admin_audit_log(
                    action="participant_edited",
                    admin_user_id=user.get("id") if user else None,
                    target_id=str(participant_id),
                    extra={
                        "email": email,
                        "first_name": first_name,
                        "last_name": last_name,
                    },
                    ip=request.remote_addr,
                )
                
                success = "Dane uczestnika zostały zaktualizowane"
                
                # Odśwież dane uczestnika
                participant = get_participant_by_id(participant_id)
                
            except Exception as e:
                error = f"Błąd aktualizacji: {e}"
            finally:
                if pool is not None and conn is not None:
                    _put_conn(pool, conn)
    
    # Rozpakuj dane z JSON
    p_data = participant.get("data") or {}
    participant["company"] = p_data.get("company") or p_data.get("firma") or ""
    participant["position"] = p_data.get("position") or p_data.get("stanowisko") or ""
    
    return render_template(
        "admin_v2/participant_edit.html",
        active_page="participants",
        participant=participant,
        error=error,
        success=success,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/users", methods=["GET"])
@_require_permission("users")
def users_list():
    """Lista kont administratorów."""
    user = _get_current_admin_user()
    
    users = list_admin_users() or []
    
    return render_template(
        "admin_v2/users.html",
        active_page="users",
        users=users,
        **_get_common_context(user),
    )


# Opcje uprawnień do stron
ADMIN_PAGE_OPTIONS_V2 = [
    ("events", "Wydarzenia"),
    ("orders", "Zamówienia"),
    ("participants", "Uczestnicy"),
    ("users", "Konta i uprawnienia"),
    ("audit", "Log audytu"),
]


@admin_v2_bp.route("/users/new", methods=["GET", "POST"])
@_require_permission("users")
def user_new():
    """Tworzenie nowego konta administratora."""
    from werkzeug.security import generate_password_hash
    import secrets
    import string
    
    user = _get_current_admin_user()
    events = list_events(limit=200) or []
    error = None
    success = None
    
    if request.method == "POST":
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
            # Generuj tymczasowe hasło
            alphabet = string.ascii_letters + string.digits
            temp_password = ''.join(secrets.choice(alphabet) for _ in range(12))
            password_hash = generate_password_hash(temp_password)
            
            new_user = create_admin_user(
                email=email,
                password_hash=password_hash,
                first_name=first_name,
                last_name=last_name,
                role=role,
                allowed_pages=allowed_pages if role != "admin" else [],
                allowed_events=allowed_events if role == "viewer" else [],
                must_change_password=True,
            )
            
            if new_user:
                # Wyślij email z hasłem
                from backstage_engine import _send_email_via_make
                email_result = _send_email_via_make(
                    to_email=email,
                    subject="Twoje konto w panelu administracyjnym Medidesk",
                    body_html=f"""
                    <p>Cześć {first_name or 'Użytkowniku'},</p>
                    <p>Utworzono dla Ciebie konto w panelu administracyjnym.</p>
                    <p><strong>Login:</strong> {email}<br>
                    <strong>Hasło tymczasowe:</strong> {temp_password}</p>
                    <p>Po pierwszym logowaniu zostaniesz poproszony o zmianę hasła.</p>
                    <p><a href="https://wfirma-api.onrender.com/admin-v2/login">Zaloguj się tutaj</a></p>
                    """,
                    template_type="admin_account_created",
                )
                
                # Log audytu
                insert_admin_audit_log(
                    action="create_user",
                    admin_user_id=user["id"] if user else None,
                    target_email=email,
                    ip=request.remote_addr,
                    user_agent=request.headers.get("User-Agent", "")[:500],
                    data={"role": role, "email_sent": email_result.get('success', False)}
                )
                
                success = f"Konto utworzone. Hasło zostało wysłane na {email}."
            else:
                error = "Nie udało się utworzyć konta"
    
    return render_template(
        "admin_v2/user_form.html",
        active_page="users",
        mode="new",
        target_user=None,
        events=events,
        page_options=ADMIN_PAGE_OPTIONS_V2,
        error=error,
        success=success,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@_require_permission("users")
def user_edit(user_id: int):
    """Edycja uprawnień użytkownika."""
    user = _get_current_admin_user()
    target_user = get_admin_user_by_id(user_id)
    
    if not target_user:
        return redirect(url_for("admin_v2_bp.users_list"))
    
    events = list_events(limit=200) or []
    error = None
    success = None
    
    # Pobierz aktualne uprawnienia
    allowed_current = target_user.get("allowed_pages") or []
    if isinstance(allowed_current, str):
        import json
        try:
            allowed_current = json.loads(allowed_current)
        except:
            allowed_current = []
    
    allowed_events_current = target_user.get("allowed_events") or []
    if isinstance(allowed_events_current, str):
        import json
        try:
            allowed_events_current = json.loads(allowed_events_current)
        except:
            allowed_events_current = []
    
    # Admin ma pełne uprawnienia
    if (target_user.get("role") or "user").lower() == "admin":
        allowed_current = [k for k, _ in ADMIN_PAGE_OPTIONS_V2]
    
    if request.method == "POST":
        first_name = (request.form.get("first_name") or "").strip()
        last_name = (request.form.get("last_name") or "").strip()
        role = (request.form.get("role") or "user").strip().lower()
        allowed_pages = request.form.getlist("allowed_pages") or []
        allowed_events = request.form.getlist("allowed_events") or []
        is_active = request.form.get("is_active") == "1"
        
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
                is_active=is_active,
            )
            
            if ok:
                insert_admin_audit_log(
                    action="update_user_access",
                    admin_user_id=user["id"] if user else None,
                    target_email=target_user["email"],
                    ip=request.remote_addr,
                    user_agent=request.headers.get("User-Agent", "")[:500],
                    data={"role": role, "is_active": is_active}
                )
                success = "Zapisano zmiany"
                
                # Odśwież dane użytkownika
                target_user = get_admin_user_by_id(user_id) or target_user
                allowed_current = target_user.get("allowed_pages") or []
                if isinstance(allowed_current, str):
                    import json
                    try:
                        allowed_current = json.loads(allowed_current)
                    except:
                        allowed_current = []
                allowed_events_current = target_user.get("allowed_events") or []
                if isinstance(allowed_events_current, str):
                    import json
                    try:
                        allowed_events_current = json.loads(allowed_events_current)
                    except:
                        allowed_events_current = []
                if (target_user.get("role") or "user").lower() == "admin":
                    allowed_current = [k for k, _ in ADMIN_PAGE_OPTIONS_V2]
            else:
                error = "Nie udało się zapisać zmian"
    
    return render_template(
        "admin_v2/user_form.html",
        active_page="users",
        mode="edit",
        target_user=target_user,
        events=events,
        page_options=ADMIN_PAGE_OPTIONS_V2,
        allowed_current=allowed_current,
        allowed_events_current=allowed_events_current,
        error=error,
        success=success,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@_require_permission("users")
def user_reset_password(user_id: int):
    """Reset hasła użytkownika (AJAX)."""
    from flask import jsonify
    from werkzeug.security import generate_password_hash
    import secrets
    import string
    
    user = _get_current_admin_user()
    target_user = get_admin_user_by_id(user_id)
    
    if not target_user:
        return jsonify({"success": False, "error": "Nie znaleziono konta"}), 404
    
    # Generuj nowe hasło
    alphabet = string.ascii_letters + string.digits
    temp_password = ''.join(secrets.choice(alphabet) for _ in range(12))
    password_hash = generate_password_hash(temp_password)
    
    ok = update_admin_user_password(user_id, password_hash, must_change_password=True)
    
    if ok:
        # Wyślij email z nowym hasłem
        from backstage_engine import _send_email_via_make
        email_result = _send_email_via_make(
            to_email=target_user["email"],
            subject="Reset hasła - Panel administracyjny Medidesk",
            body_html=f"""
            <p>Cześć {target_user.get('first_name') or 'Użytkowniku'},</p>
            <p>Twoje hasło zostało zresetowane.</p>
            <p><strong>Nowe hasło tymczasowe:</strong> {temp_password}</p>
            <p>Po zalogowaniu zostaniesz poproszony o zmianę hasła.</p>
            <p><a href="https://wfirma-api.onrender.com/admin-v2/login">Zaloguj się tutaj</a></p>
            """,
            template_type="admin_password_reset",
        )
        
        insert_admin_audit_log(
            action="reset_password",
            admin_user_id=user["id"] if user else None,
            target_email=target_user["email"],
            ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent", "")[:500],
            data={"email_sent": email_result.get('success', False)}
        )
        
        return jsonify({"success": True, "message": f"Nowe hasło wysłane na {target_user['email']}"})
    else:
        return jsonify({"success": False, "error": "Nie udało się zresetować hasła"}), 500


@admin_v2_bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@_require_permission("users")
def user_toggle_active(user_id: int):
    """Włącz/wyłącz konto (AJAX)."""
    from flask import jsonify
    
    user = _get_current_admin_user()
    target_user = get_admin_user_by_id(user_id)
    
    if not target_user:
        return jsonify({"success": False, "error": "Nie znaleziono konta"}), 404
    
    # Nie można dezaktywować własnego konta
    if user and user["id"] == user_id:
        return jsonify({"success": False, "error": "Nie możesz dezaktywować własnego konta"}), 400
    
    new_status = not target_user.get("is_active", True)
    ok = update_admin_user_active(user_id, new_status)
    
    if ok:
        insert_admin_audit_log(
            action="toggle_user_active",
            admin_user_id=user["id"] if user else None,
            target_email=target_user["email"],
            ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent", "")[:500],
            data={"is_active": new_status}
        )
        
        return jsonify({
            "success": True, 
            "is_active": new_status,
            "message": "Konto aktywowane" if new_status else "Konto dezaktywowane"
        })
    else:
        return jsonify({"success": False, "error": "Nie udało się zmienić statusu"}), 500


@admin_v2_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@_require_permission("users")
def user_delete(user_id: int):
    """Usuń konto (AJAX)."""
    from flask import jsonify
    
    user = _get_current_admin_user()
    target_user = get_admin_user_by_id(user_id)
    
    if not target_user:
        return jsonify({"success": False, "error": "Nie znaleziono konta"}), 404
    
    # Nie można usunąć własnego konta
    if user and user["id"] == user_id:
        return jsonify({"success": False, "error": "Nie możesz usunąć własnego konta"}), 400
    
    # Tylko admin może usuwać konta
    if user and user.get("role") != "admin":
        return jsonify({"success": False, "error": "Tylko administrator może usuwać konta"}), 403
    
    ok = delete_admin_user(user_id)
    
    if ok:
        insert_admin_audit_log(
            action="delete_user",
            admin_user_id=user["id"] if user else None,
            target_email=target_user["email"],
            ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent", "")[:500],
        )
        
        return jsonify({"success": True, "message": "Konto zostało usunięte"})
    else:
        return jsonify({"success": False, "error": "Nie udało się usunąć konta"}), 500


@admin_v2_bp.route("/audit-log", methods=["GET"])
@_require_permission("audit")
def audit_log():
    """Log audytu."""
    user = _get_current_admin_user()
    
    # Filtry
    action_filter = request.args.get("action", "").strip()
    q_filter = request.args.get("q", "").strip().lower()
    
    audit_logs = list_admin_audit_log(limit=200) or []
    
    # Filtrowanie po akcji
    if action_filter:
        audit_logs = [log for log in audit_logs if log.get("action") == action_filter]
    
    # Filtrowanie tekstowe
    if q_filter:
        audit_logs = [
            log for log in audit_logs
            if q_filter in (log.get("admin_email") or "").lower()
            or q_filter in (log.get("action") or "").lower()
            or q_filter in (log.get("target_email") or "").lower()
        ]
    
    return render_template(
        "admin_v2/audit.html",
        active_page="audit",
        audit_logs=audit_logs,
        **_get_common_context(user),
    )


# ---------------------------------------------------------------------------
# WORK QUEUE (Monitoring procesów)
# ---------------------------------------------------------------------------

@admin_v2_bp.route("/work-queue", methods=["GET"])
@_require_login
def work_queue():
    """Monitoring procesów - kolejka błędów i akcji."""
    from datetime import datetime
    from pg_storage import list_error_tasks, get_error_queue_stats
    
    user = _get_current_admin_user()
    
    # Filtry
    category_filter = request.args.get("category", "").strip()
    severity_filter = request.args.get("severity", "").strip()
    
    # Kategorie zadań
    categories = {
        "wfirma": {"label": "wFirma", "icon": "file-text"},
        "make": {"label": "Make.com", "icon": "zap"},
        "stripe": {"label": "Stripe", "icon": "credit-card"},
        "database": {"label": "Baza danych", "icon": "database"},
        "attendee": {"label": "Uczestnicy", "icon": "users"},
        "config": {"label": "Konfiguracja", "icon": "settings"},
        "backstage": {"label": "Backstage", "icon": "globe"},
        "email": {"label": "Email", "icon": "mail"},
    }
    
    # Pobierz zadania z bazy danych
    try:
        tasks = list_error_tasks(
            category=category_filter or None,
            severity=severity_filter or None,
            resolved=False,
            limit=200
        )
        
        # Pobierz statystyki
        stats = get_error_queue_stats()
    except Exception as e:
        print(f"[work_queue] Error fetching tasks: {e}")
        tasks = []
        stats = {"total": 0, "critical": 0, "errors": 0, "warnings": 0, "can_retry": 0}
    
    # Eventy wymagające konfiguracji (sprawdź czy mają wymagane pola)
    events_needing_config = []
    try:
        all_events = list_events(limit=100)
        for ev in all_events:
            if ev.get("is_active"):
                data = ev.get("data") or {}
                # Sprawdź czy brakuje kluczowych pól
                if not data.get("event_mail_link_top_banner") or not data.get("md_email_kontakt"):
                    events_needing_config.append(ev)
    except Exception as e:
        # Jeśli baza danych jest niedostępna, kontynuuj z pustą listą
        print(f"[work_queue] Error fetching events: {e}")
        all_events = []
    
    # Aktualna data po polsku
    months_pl = ['stycznia', 'lutego', 'marca', 'kwietnia', 'maja', 'czerwca',
                 'lipca', 'sierpnia', 'września', 'października', 'listopada', 'grudnia']
    now = datetime.now()
    days_pl = ['Poniedziałek', 'Wtorek', 'Środa', 'Czwartek', 'Piątek', 'Sobota', 'Niedziela']
    current_date = f"{days_pl[now.weekday()]}, {now.day} {months_pl[now.month - 1]} {now.year}"
    
    return render_template(
        "admin_v2/work_queue.html",
        active_page="work_queue",
        tasks=tasks,
        stats=stats,
        categories=categories,
        events_needing_config=events_needing_config,
        current_date=current_date,
        category_filter=category_filter,
        severity_filter=severity_filter,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/work-queue/retry-all", methods=["POST"])
@_require_login
def work_queue_retry_all():
    """Ponów wszystkie możliwe do ponowienia zadania."""
    from flask import jsonify
    from pg_storage import list_error_tasks, retry_error_task
    
    user = _get_current_admin_user()
    
    try:
        tasks = list_error_tasks(resolved=False, limit=500)
        retried = 0
        failed = 0
        
        for task in tasks:
            if task.get("can_retry") and task.get("retry_count", 0) < task.get("max_retries", 3):
                result = retry_error_task(task["id"])
                if result.get("success"):
                    retried += 1
                else:
                    failed += 1
        
        # Audit log
        insert_admin_audit_log(
            action="work_queue_retry_all",
            admin_user_id=user.get("id") if user else None,
            extra={"retried": retried, "failed": failed},
            ip=request.remote_addr,
        )
        
        return jsonify({
            "success": True,
            "retried": retried,
            "failed": failed,
            "message": f"Ponowiono {retried} zadań" + (f", {failed} błędów" if failed > 0 else "")
        })
    except Exception as e:
        print(f"[work_queue_retry_all] Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@admin_v2_bp.route("/work-queue/<int:task_id>/retry", methods=["POST"])
@_require_login
def work_queue_retry(task_id: int):
    """Ponów pojedyncze zadanie."""
    from flask import jsonify
    from pg_storage import retry_error_task, get_error_task
    
    user = _get_current_admin_user()
    
    try:
        task = get_error_task(task_id)
        if not task:
            return jsonify({"success": False, "error": "Zadanie nie istnieje"}), 404
        
        result = retry_error_task(task_id)
        
        if result.get("success"):
            # Audit log
            insert_admin_audit_log(
                action="work_queue_retry",
                admin_user_id=user.get("id") if user else None,
                target_id=str(task_id),
                extra={"task_title": task.get("title"), "category": task.get("category")},
                ip=request.remote_addr,
            )
        
        return jsonify(result)
    except Exception as e:
        print(f"[work_queue_retry] Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@admin_v2_bp.route("/work-queue/<int:task_id>/resolve", methods=["POST"])
@_require_login
def work_queue_resolve(task_id: int):
    """Oznacz zadanie jako rozwiązane."""
    from flask import jsonify
    from pg_storage import resolve_error_task, get_error_task
    
    user = _get_current_admin_user()
    
    try:
        task = get_error_task(task_id)
        if not task:
            return jsonify({"success": False, "error": "Zadanie nie istnieje"}), 404
        
        success = resolve_error_task(task_id)
        
        if success:
            # Audit log
            insert_admin_audit_log(
                action="work_queue_resolve",
                admin_user_id=user.get("id") if user else None,
                target_id=str(task_id),
                extra={"task_title": task.get("title"), "category": task.get("category")},
                ip=request.remote_addr,
            )
            return jsonify({"success": True, "message": "Zadanie zostało rozwiązane"})
        else:
            return jsonify({"success": False, "error": "Nie udało się oznaczyć zadania jako rozwiązane"}), 500
    except Exception as e:
        print(f"[work_queue_resolve] Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@admin_v2_bp.route("/work-queue/<int:task_id>/delete", methods=["POST"])
@_require_login
def work_queue_delete(task_id: int):
    """Usuń zadanie z kolejki monitoringu (trwale)."""
    from flask import jsonify
    from pg_storage import delete_error_task, get_error_task
    
    user = _get_current_admin_user()
    
    try:
        task = get_error_task(task_id)
        if not task:
            return jsonify({"success": False, "error": "Zadanie nie istnieje"}), 404
        
        success = delete_error_task(task_id)
        
        if success:
            # Audit log
            insert_admin_audit_log(
                action="work_queue_delete",
                admin_user_id=user.get("id") if user else None,
                target_id=str(task_id),
                extra={"task_title": task.get("title"), "category": task.get("category")},
                ip=request.remote_addr,
            )
            return jsonify({"success": True, "message": "Zadanie zostało usunięte"})
        else:
            return jsonify({"success": False, "error": "Nie udało się usunąć zadania"}), 500
    except Exception as e:
        print(f"[work_queue_delete] Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# ORDER HISTORY BUILDER
# ---------------------------------------------------------------------------

def _get_emails_for_order(order_id: str):
    """Pobiera emaile wysłane dla danego zamówienia."""
    from pg_storage import ensure_schema, _with_conn, _put_conn, _dict_cursor
    
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        
        query = """
            SELECT id, event_order_id, direction, template_key, to_email, 
                   subject, status, error, data, created_at
            FROM mail_log
            WHERE event_order_id = %s
            ORDER BY created_at DESC
        """
        cur.execute(query, (order_id,))
        return [dict(r) for r in (cur.fetchall() or [])]
    except Exception as e:
        print(f"[DB] _get_emails_for_order error: {e}")
        return []
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def _format_datetime_pl(dt):
    """Formatuje datetime do polskiej strefy czasowej (Europe/Warsaw)."""
    if not dt:
        return "—"
    try:
        from datetime import timezone, timedelta
        # Polska strefa czasowa: UTC+1 (zima) lub UTC+2 (lato)
        # Uproszczona wersja - użyj UTC+1 (CET)
        if dt.tzinfo is None:
            # Załóż że jest w UTC
            from datetime import datetime as dt_module
            utc_dt = dt.replace(tzinfo=timezone.utc)
        else:
            utc_dt = dt
        # Konwertuj do CET (UTC+1)
        cet = timezone(timedelta(hours=1))
        local_dt = utc_dt.astimezone(cet)
        return local_dt.strftime("%d.%m.%Y, %H:%M")
    except Exception:
        # Fallback - formatuj bez konwersji
        if hasattr(dt, "strftime"):
            return dt.strftime("%d.%m.%Y, %H:%M")
        return str(dt)


def _build_order_history(order_id: str, order: dict):
    """Buduje listę zdarzeń dla historii zamówienia."""
    from datetime import datetime
    
    history = []
    
    # Mapowanie typów emaili na czytelne nazwy
    EMAIL_TYPE_LABELS = {
        "proforma": ("Proforma wysłana", "document"),
        "proforma_reminder": ("Przypomnienie o płatności", "email"),
        "checkout_reminder": ("Przypomnienie o płatności", "email"),
        "payment_link": ("Link do płatności wysłany", "email"),
        "payment_confirmation": ("Potwierdzenie płatności", "payment"),
        "registration_confirmation": ("Potwierdzenie rejestracji", "email"),
        "ticket": ("Potwierdzenie rezerwacji wysłane", "email"),
        "participant_ticket": ("Potwierdzenie rezerwacji wysłane", "email"),
        "participant_ticket_resend": ("Potwierdzenie rezerwacji wysłane ponownie", "email"),
        "invoice": ("Faktura wysłana", "document"),
        "stripe_payment_link": ("Link Stripe wysłany", "payment"),
        "paid_confirmation": ("Potwierdzenie zapłaty", "payment"),
        "expired": ("Sesja płatności wygasła", "status_change"),
    }
    
    # Pobierz emaile dla zamówienia
    emails = _get_emails_for_order(order_id)
    
    for email in emails:
        # Pomijaj emaile wewnętrzne (do admina, @medidesk.com)
        to_email = (email.get("to_email") or "").lower()
        template_key_raw = email.get("template_key") or ""
        if (
            to_email.endswith("@medidesk.com") or
            "admin" in to_email or
            template_key_raw.startswith("internal_")
        ):
            continue
        
        template_key = template_key_raw.lower()
        created_at = email.get("created_at")
        
        # Znajdź pasujący typ
        event_type = "email"
        title = "Email wysłany"
        
        for key, (label, etype) in EMAIL_TYPE_LABELS.items():
            if key in template_key:
                title = label
                event_type = etype
                break
        
        # Jeśli nie znaleziono, użyj subject lub template_key
        if title == "Email wysłany":
            subject = email.get("subject") or ""
            if subject:
                title = subject[:50] + ("..." if len(subject) > 50 else "")
        
        history.append({
            "type": event_type,
            "title": title,
            "description": f"Do: {email.get('to_email', '—')}",
            "timestamp": _format_datetime_pl(created_at),
            "_sort_date": created_at or datetime.min,
            "status": email.get("status"),
            "status_label": {"sent": "Wysłano", "delivered": "Dostarczono", "error": "Błąd", "queued": "W kolejce"}.get(email.get("status"), ""),
        })
    
    # Dodaj zdarzenie płatności jeśli opłacone
    if order.get("status") == "paid":
        paid_at = order.get("updated_at") or order.get("created_at")
        history.append({
            "type": "payment",
            "title": "Płatność potwierdzona",
            "description": f"Kwota: {order.get('total', 0)} zł",
            "timestamp": _format_datetime_pl(paid_at),
            "_sort_date": paid_at or datetime.min,
            "status": "paid",
            "status_label": "Opłacone",
        })
    
    # Dodaj zdarzenie utworzenia zamówienia
    created_at = order.get("created_at")
    history.append({
        "type": "created",
        "title": "Zamówienie utworzone",
        "description": "Zamówienie zostało zarejestrowane w systemie",
        "timestamp": _format_datetime_pl(created_at),
        "_sort_date": created_at or datetime.min,
        "status": None,
        "status_label": "Otrzymane",
    })
    
    # Sortuj chronologicznie od najnowszych do najstarszych
    history.sort(key=lambda x: x.get("_sort_date", datetime.min), reverse=True)
    
    # Usuń pomocnicze pole sortowania
    for item in history:
        item.pop("_sort_date", None)
    
    return history


# ---------------------------------------------------------------------------
# COMMUNICATION (Historia wysyłek)
# ---------------------------------------------------------------------------

def _list_mail_logs(event_id: str = None, status: str = None, email_type: str = None, limit: int = 200):
    """Pobiera logi wysyłek maili z bazy."""
    from pg_storage import ensure_schema, _with_conn, _put_conn, _dict_cursor
    
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        
        query = """
            SELECT m.id, m.event_order_id, m.direction, m.template_key, m.to_email, 
                   m.subject, m.status, m.error, m.data, m.created_at,
                   o.event_id
            FROM mail_log m
            LEFT JOIN orders o ON m.event_order_id = o.event_order_id
            WHERE 1=1
        """
        params = []
        
        if event_id:
            query += " AND o.event_id = %s"
            params.append(event_id)
        
        if status:
            query += " AND m.status = %s"
            params.append(status)
        
        if email_type:
            query += " AND m.template_key ILIKE %s"
            params.append(f"%{email_type}%")
        
        query += " ORDER BY m.created_at DESC LIMIT %s"
        params.append(limit)
        
        cur.execute(query, tuple(params))
        return [dict(r) for r in (cur.fetchall() or [])]
    except Exception as e:
        print(f"[DB] _list_mail_logs error: {e}")
        return []
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def _get_system_email_templates() -> Dict[str, List[Dict[str, Any]]]:
    """
    Zwraca listę wszystkich szablonów emaili w systemie pogrupowanych wg kategorii.
    
    Kategorie:
    - purchaser: Szablony dla kupujących (linki płatności, potwierdzenia, przypomnienia)
    - participant: Szablony dla uczestników (bilety)
    - internal: Szablony wewnętrzne (powiadomienia dla admina)
    """
    return {
        "purchaser": [
            {
                "key": "stripe_payment_link",
                "name": "Link do płatności Stripe",
                "description": "Wysyłany po rejestracji z linkiem do płatności online",
                "icon": "credit-card",
                "color": "blue",
            },
            {
                "key": "proforma_sent",
                "name": "Proforma wysłana",
                "description": "Informacja o wystawionej fakturze proforma z załącznikiem PDF",
                "icon": "file-text",
                "color": "purple",
            },
            {
                "key": "payment_confirmation",
                "name": "Potwierdzenie płatności",
                "description": "Wysyłany po udanej płatności z podziękowaniem",
                "icon": "check-circle",
                "color": "green",
            },
            {
                "key": "registration_confirmation",
                "name": "Potwierdzenie rejestracji (FOC)",
                "description": "Dla zamówień z 100% rabatem (Free of Charge)",
                "icon": "user-check",
                "color": "teal",
            },
            {
                "key": "checkout_reminder",
                "name": "Przypomnienie o płatności",
                "description": "Wysyłany gdy sesja płatności zbliża się do wygaśnięcia",
                "icon": "clock",
                "color": "amber",
            },
            {
                "key": "checkout_expired_new_link",
                "name": "Nowy link po wygaśnięciu",
                "description": "Gdy sesja płatności wygasła - nowy link do płatności",
                "icon": "refresh-cw",
                "color": "amber",
            },
        ],
        "participant": [
            {
                "key": "participant_ticket",
                "name": "Bilet uczestnika",
                "description": "Email z biletem elektronicznym na wydarzenie",
                "icon": "ticket",
                "color": "cyan",
            },
        ],
        "internal": [
            {
                "key": "internal_order_received",
                "name": "Nowe zamówienie",
                "description": "Powiadomienie wewnętrzne o nowym zamówieniu",
                "icon": "inbox",
                "color": "blue",
            },
            {
                "key": "internal_order_paid",
                "name": "Zamówienie opłacone",
                "description": "Powiadomienie wewnętrzne o otrzymanej płatności",
                "icon": "banknote",
                "color": "green",
            },
            {
                "key": "internal_payment_expired",
                "name": "Płatność wygasła",
                "description": "Powiadomienie gdy sesja płatności Stripe wygasła",
                "icon": "alert-circle",
                "color": "amber",
            },
            {
                "key": "internal_payment_failed",
                "name": "Płatność nieudana",
                "description": "Powiadomienie o nieudanej płatności",
                "icon": "x-circle",
                "color": "red",
            },
            {
                "key": "internal_invoice_error",
                "name": "Błąd faktury",
                "description": "Problem z wystawieniem faktury w wFirma",
                "icon": "file-x",
                "color": "red",
            },
        ],
    }


def _get_template_usage_stats() -> Dict[str, int]:
    """Pobiera statystyki użycia szablonów (ile razy każdy był użyty)."""
    from pg_storage import _with_conn, _put_conn, _dict_cursor
    
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        
        cur.execute("""
            SELECT template_key, COUNT(*) as count
            FROM mail_log
            WHERE template_key IS NOT NULL
            GROUP BY template_key
        """)
        
        return {row["template_key"]: row["count"] for row in (cur.fetchall() or [])}
    except Exception as e:
        print(f"[DB] _get_template_usage_stats error: {e}")
        return {}
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


@admin_v2_bp.route("/communication", methods=["GET"])
@_require_permission("orders")
def communication():
    """Historia wysyłek i komunikacji."""
    from datetime import datetime, timedelta
    from pg_storage import list_email_templates
    
    user = _get_current_admin_user()
    
    # Filtry
    status_filter = request.args.get("status", "").strip()
    type_filter = request.args.get("type", "").strip()
    event_filter = request.args.get("event_id", "").strip()
    q_filter = request.args.get("q", "").strip().lower()
    
    # Pobierz wydarzenia do filtra
    events = list_events(limit=100)
    
    # Pobierz logi maili
    emails = _list_mail_logs(
        event_id=event_filter or None,
        status=status_filter or None,
        email_type=type_filter or None,
        limit=200
    )
    
    # Dodaj nazwy wydarzeń
    event_map = {e.get("event_id"): e.get("event_name") for e in events}
    for email in emails:
        email["event_name"] = event_map.get(email.get("event_id"), "")
        # Mapuj pola
        email["recipient"] = email.get("to_email", "")
        email["type"] = email.get("template_key", "")
        email["sent_at"] = email.get("created_at")
        email["error_message"] = email.get("error", "")
    
    # Filtrowanie tekstowe
    if q_filter:
        emails = [
            e for e in emails
            if q_filter in (e.get("recipient") or "").lower()
            or q_filter in (e.get("subject") or "").lower()
        ]
    
    # Błędne wysyłki
    error_emails = [e for e in emails if e.get("status") in ("failed", "error", "bounced")]
    
    # Statystyki
    today = datetime.now().date()
    sent_today = len([e for e in emails if e.get("sent_at") and e["sent_at"].date() == today])
    delivered = len([e for e in emails if e.get("status") == "sent"])
    errors = len(error_emails)
    total = len(emails)
    delivery_rate = round((delivered / total * 100) if total > 0 else 0)
    
    stats = {
        "sent_today": sent_today,
        "delivered": delivered,
        "errors": errors,
        "delivery_rate": delivery_rate,
    }
    
    # Szablony emaili i statystyki użycia
    email_templates = _get_system_email_templates()
    template_usage = _get_template_usage_stats()
    
    # Dodaj statystyki użycia do każdego szablonu
    for category in email_templates.values():
        for template in category:
            template["usage_count"] = template_usage.get(template["key"], 0)

    # Szablony niestandardowe (edytowalne w kreatorze)
    custom_templates = list_email_templates(category="custom", limit=100)
    
    # Aktywny tab (historia lub szablony)
    active_tab = request.args.get("tab", "history")
    
    return render_template(
        "admin_v2/communication.html",
        active_page="communication",
        active_tab=active_tab,
        stats=stats,
        events=events,
        error_emails=error_emails[:10],
        emails=emails,
        email_templates=email_templates,
        custom_templates=custom_templates,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/communication/<int:email_id>/retry", methods=["POST"])
@_require_permission("orders")
def email_retry(email_id: int):
    """Ponów wysyłkę emaila."""
    from flask import jsonify
    from pg_storage import get_mail_task, update_mail_task_status
    from backstage_engine import _send_email_via_make
    
    user = _get_current_admin_user()
    email = get_mail_task(email_id)
    
    if not email:
        return jsonify({"success": False, "error": "Nie znaleziono emaila"}), 404
    
    # Sprawdź czy email można ponowić
    if email.get("status") not in ["failed", "error", "queued"]:
        return jsonify({"success": False, "error": "Email nie może być wysłany ponownie (status: {})".format(email.get("status"))}), 400
    
    # Sprawdź czy mamy treść emaila
    email_data = email.get("data") or {}
    body_html = email_data.get("body_html", "")
    
    if not body_html:
        return jsonify({"success": False, "error": "Brak treści emaila do ponownej wysyłki"}), 400
    
    to_email = email.get("to_email")
    if not to_email:
        return jsonify({"success": False, "error": "Brak adresu email odbiorcy"}), 400
    
    subject = email.get("subject", "")
    if not subject:
        subject = "Ponowiona wiadomość"
    
    # Ponów wysyłkę
    result = _send_email_via_make(
        to_email=to_email,
        subject=subject,
        body_html=body_html,
        event_order_id=email.get("event_order_id", ""),
        template_type=email.get("template_key", ""),
        mail_id=email_id,
    )
    
    # Aktualizuj status
    if result.get("success"):
        update_mail_task_status(email_id, "sent", None)
        status_msg = "sent"
    else:
        error_msg = result.get("error", "Nieznany błąd")
        update_mail_task_status(email_id, "failed", error_msg)
        status_msg = "failed"
    
    # Audit log
    insert_admin_audit_log(
        action="email_retry",
        admin_user_id=user.get("id") if user else None,
        target_id=str(email_id),
        extra={"to_email": to_email, "success": result.get("success"), "new_status": status_msg},
        ip=request.remote_addr,
    )
    
    if result.get("success"):
        return jsonify({"success": True, "message": "Email został wysłany ponownie"})
    else:
        return jsonify({"success": False, "error": result.get("error", "Błąd wysyłki")}), 500


@admin_v2_bp.route("/communication/<int:email_id>/delete", methods=["POST"])
@_require_permission("admin")
def email_delete(email_id: int):
    """Usuń wpis z historii wysyłek (tylko admin)."""
    from flask import jsonify
    from pg_storage import delete_mail_log
    
    user = _get_current_admin_user()
    
    result = delete_mail_log(email_id)
    
    # Audit log
    insert_admin_audit_log(
        action="email_delete",
        admin_user_id=user.get("id") if user else None,
        target_id=str(email_id),
        extra={"success": result},
        ip=request.remote_addr,
    )
    
    if result:
        return jsonify({"success": True, "message": "Wpis został usunięty"})
    else:
        return jsonify({"success": False, "error": "Nie znaleziono wpisu"}), 404


@admin_v2_bp.route("/communication/export", methods=["GET"])
@_require_permission("orders")
def communication_export():
    """Eksport historii komunikacji do CSV."""
    import csv
    import io
    from flask import Response
    
    event_filter = request.args.get("event_id", "").strip()
    
    emails = _list_mail_logs(event_id=event_filter or None, limit=1000)
    events = list_events(limit=100)
    event_map = {e.get("event_id"): e for e in events}
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    
    writer.writerow([
        'Data', 'Odbiorca', 'Typ', 'Temat', 'Status', 'Wydarzenie', 'ID zamówienia'
    ])
    
    for e in emails:
        event = event_map.get(e.get("event_id"), {})
        created = e.get("created_at")
        writer.writerow([
            created.strftime("%Y-%m-%d %H:%M") if created else "",
            e.get("to_email", ""),
            e.get("template_key", ""),
            e.get("subject", ""),
            e.get("status", ""),
            event.get("event_name", ""),
            e.get("event_order_id", ""),
        ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': 'attachment; filename=komunikacja.csv',
            'Content-Type': 'text/csv; charset=utf-8'
        }
    )


@admin_v2_bp.route("/templates/<template_key>/preview", methods=["GET"])
@_require_permission("orders")
def template_preview(template_key: str):
    """
    Podgląd szablonu emaila z przykładowymi danymi.
    Zwraca HTML szablonu gotowy do wyświetlenia w modalu.
    """
    from flask import jsonify
    from email_templates import get_default_event_config
    
    event_id = (request.args.get("event_id") or "").strip()
    event = get_event(event_id) if event_id else None
    event_data = {}
    if event:
        event = _normalize_event_data(event)
        event_data = event.get("data") or {}
    
    # Przykładowe dane do podglądu szablonów
    # WAŻNE: tickets muszą mieć pole "price" lub "total_gross" - inaczej 
    # email_templates.py nadpisze zmienną total_gross na None (bug w kodzie)
    sample_data = {
        "event_name": "Konferencja Medyczna 2026",
        "purchaser_first_name": "Jan",
        "purchaser_last_name": "Kowalski",
        "purchaser_email": "jan.kowalski@example.com",
        "purchaser_phone": "+48 123 456 789",
        "company_name": "Przykładowa Firma Sp. z o.o.",
        "company_nip": "1234567890",
        "total_gross": 1230.00,
        "total_net": 1000.00,
        "event_date": "15-16 marca 2026",
        "event_city": "Warszawa",
        "event_location": "Hotel Marriott, ul. Jerozolimskie 65/79",
        "tickets": [
            {"name": "Standard", "quantity": 2, "price": 615.00, "total_gross": 1230.00},
        ],
        "payment_url": "https://checkout.stripe.com/example",
        "order_number": "ORD-2026-001234",
        "proforma_number": "PF/2026/001234",
        "participant_first_name": "Anna",
        "participant_last_name": "Nowak",
        "participant_email": "anna.nowak@example.com",
        "ticket_name": "Bilet VIP",
    }
    
    # Kolory i style wydarzenia (domyślne + nadpisanie z eventu jeśli podany)
    event_config = get_default_event_config()
    event_config.update({
        "email_footer_text": "© 2026 Medidesk. Wszystkie prawa zastrzeżone.",
        "organizer_name": "Medidesk Sp. z o.o.",
        "organizer_email": "kontakt@medidesk.pl",
        "organizer_phone": "+48 22 123 45 67",
    })
    if event_data:
        event_config.update(event_data)
        # Uzupełnij banner jeśli używamy nowych pól
        if not event_config.get("event_mail_link_top_banner"):
            event_config["event_mail_link_top_banner"] = event_data.get("email_header_url") or event_data.get("event_logo_url") or event_config.get("event_mail_link_top_banner")
    
    # Podstaw event-specific data do preview
    if event:
        sample_data["event_name"] = event.get("event_name") or sample_data["event_name"]
        sample_data["event_date"] = event_data.get("eventDate") or event_data.get("event_date") or sample_data["event_date"]
        sample_data["event_city"] = event_data.get("event_location_city") or event_data.get("eventCity") or sample_data["event_city"]
        sample_data["event_location"] = event_data.get("location") or event_data.get("event_location_place") or event_data.get("eventLocation") or sample_data["event_location"]
        
        # Jeśli mamy zamówienie dla eventu, użyj realnych danych kupującego i kwoty
        try:
            orders = list_orders(event_id=event_id, limit=1)
            if orders:
                order = orders[0]
                sample_data["purchaser_first_name"] = order.get("purchaser_first_name") or sample_data["purchaser_first_name"]
                sample_data["purchaser_last_name"] = order.get("purchaser_last_name") or sample_data["purchaser_last_name"]
                sample_data["purchaser_email"] = order.get("purchaser_email") or sample_data["purchaser_email"]
                sample_data["purchaser_phone"] = order.get("purchaser_phone") or sample_data["purchaser_phone"]
                sample_data["company_name"] = order.get("purchaser_company") or sample_data["company_name"]
                sample_data["company_nip"] = order.get("purchaser_nip") or sample_data["company_nip"]
                sample_data["total_gross"] = float(order.get("total") or sample_data["total_gross"])
        except Exception:
            pass
    
    # Mapowanie kluczy szablonów na tematy emaili
    template_subjects = {
        "stripe_payment_link": f"Link do płatności - {sample_data['event_name']}",
        "proforma_sent": f"Faktura proforma - {sample_data['event_name']}",
        "payment_confirmation": f"Potwierdzenie płatności - {sample_data['event_name']}",
        "registration_confirmation": f"Potwierdzenie rejestracji - {sample_data['event_name']}",
        "checkout_reminder": f"Przypomnienie o płatności - {sample_data['event_name']}",
        "checkout_expired_new_link": f"Nowy link do płatności - {sample_data['event_name']}",
        "participant_ticket": f"Potwierdzenie rezerwacji na {sample_data['event_name']}",
        "internal_order_received": f"[Medidesk] Nowe zamówienie - {sample_data['event_name']}",
        "internal_order_paid": f"[Medidesk] Zamówienie opłacone - {sample_data['event_name']}",
        "internal_payment_expired": f"[Medidesk] Płatność wygasła - {sample_data['event_name']}",
        "internal_payment_failed": f"[Medidesk] Płatność nieudana - {sample_data['event_name']}",
        "internal_invoice_error": f"[Medidesk] Błąd faktury - {sample_data['event_name']}",
    }
    
    try:
        html_content = None
        template_subject = template_subjects.get(template_key, f"Email: {template_key}")
        
        # Renderuj odpowiedni szablon
        if template_key == "stripe_payment_link":
            from email_templates import render_stripe_payment_email
            html_content = render_stripe_payment_email(
                template_type="personal",
                event_name=sample_data["event_name"],
                purchaser_first_name=sample_data["purchaser_first_name"],
                purchaser_last_name=sample_data["purchaser_last_name"],
                purchaser_email=sample_data["purchaser_email"],
                purchaser_phone=sample_data["purchaser_phone"],
                purchaser_nip=None,
                total_gross=sample_data["total_gross"],
                tickets=sample_data["tickets"],
                stripe_payment_url=sample_data["payment_url"],
                event_config=event_config,
            )
        
        elif template_key == "payment_confirmation":
            from email_templates import render_payment_confirmation_email
            html_content = render_payment_confirmation_email(
                event_name=sample_data["event_name"],
                purchaser_first_name=sample_data["purchaser_first_name"],
                purchaser_last_name=sample_data["purchaser_last_name"],
                purchaser_email=sample_data["purchaser_email"],
                purchaser_phone=sample_data["purchaser_phone"],
                total_gross=sample_data["total_gross"],
                tickets=sample_data["tickets"],
                event_config=event_config,
            )
        
        elif template_key == "registration_confirmation":
            from email_templates import render_foc_confirmation_email
            html_content = render_foc_confirmation_email(
                event_name=sample_data["event_name"],
                purchaser_first_name=sample_data["purchaser_first_name"],
                purchaser_last_name=sample_data["purchaser_last_name"],
                purchaser_email=sample_data["purchaser_email"],
                purchaser_phone=sample_data["purchaser_phone"],
                tickets=sample_data["tickets"],
                event_config=event_config,
            )
        
        elif template_key == "participant_ticket":
            from email_templates import render_participant_ticket_email
            html_content = render_participant_ticket_email(
                event_name=sample_data["event_name"],
                participant_first_name=sample_data["participant_first_name"],
                participant_last_name=sample_data["participant_last_name"],
                participant_email=sample_data["participant_email"],
                ticket_name=sample_data["ticket_name"],
                ticket_id="TICKET-2026-001234",
                ticket_price=615.00,
                event_config=event_config,
            )
        
        elif template_key == "checkout_reminder":
            from email_templates import render_checkout_reminder_email
            html_content = render_checkout_reminder_email(
                event_name=sample_data["event_name"],
                purchaser_first_name=sample_data["purchaser_first_name"],
                purchaser_last_name=sample_data["purchaser_last_name"],
                purchaser_email=sample_data["purchaser_email"],
                total_gross=sample_data["total_gross"],
                checkout_url=sample_data["payment_url"],
                expires_at="20.03.2026, 15:00",
                expires_in="24 godziny",
                event_config=event_config,
            )
        
        elif template_key == "checkout_expired_new_link":
            from email_templates import render_checkout_expired_new_link_email
            html_content = render_checkout_expired_new_link_email(
                event_name=sample_data["event_name"],
                purchaser_first_name=sample_data["purchaser_first_name"],
                purchaser_last_name=sample_data["purchaser_last_name"],
                purchaser_email=sample_data["purchaser_email"],
                total_gross=sample_data["total_gross"],
                new_checkout_url=sample_data["payment_url"],
                new_expires_at="20.03.2026, 15:00",
                original_order_date="15.03.2026",
                event_config=event_config,
            )
        
        elif template_key == "proforma_sent":
            from email_templates import render_proforma_reservation_email
            html_content = render_proforma_reservation_email(
                event_name=sample_data["event_name"],
                purchaser_first_name=sample_data["purchaser_first_name"],
                purchaser_last_name=sample_data["purchaser_last_name"],
                purchaser_email=sample_data["purchaser_email"],
                purchaser_phone=sample_data.get("purchaser_phone", "+48 123 456 789"),
                event_config=event_config,
                tickets=sample_data["tickets"],
                proforma_number="PRO/2026/03/0042",
            )
        
        elif template_key == "internal_order_received":
            html_content = f"""
            <!DOCTYPE html>
            <html><head><meta charset="UTF-8"></head>
            <body style="font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5;">
                <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div style="background: linear-gradient(135deg, #3b82f6, #1d4ed8); color: white; padding: 24px; text-align: center;">
                        <h1 style="margin: 0; font-size: 24px;">📥 Nowe zamówienie</h1>
                    </div>
                    <div style="padding: 24px;">
                        <p style="margin: 0 0 16px; color: #374151;">Otrzymano nowe zamówienie na wydarzenie:</p>
                        <div style="background: #f8fafc; border-left: 4px solid #3b82f6; padding: 16px; margin-bottom: 16px;">
                            <strong style="color: #1e293b;">{sample_data['event_name']}</strong>
                        </div>
                        <table style="width: 100%; border-collapse: collapse; margin-top: 16px;">
                            <tr><td style="padding: 8px 0; color: #6b7280;">Kupujący:</td><td style="padding: 8px 0; font-weight: 600;">{sample_data['purchaser_first_name']} {sample_data['purchaser_last_name']}</td></tr>
                            <tr><td style="padding: 8px 0; color: #6b7280;">Email:</td><td style="padding: 8px 0;">{sample_data['purchaser_email']}</td></tr>
                            <tr><td style="padding: 8px 0; color: #6b7280;">Firma:</td><td style="padding: 8px 0;">{sample_data['company_name']}</td></tr>
                            <tr><td style="padding: 8px 0; color: #6b7280;">Kwota:</td><td style="padding: 8px 0; font-weight: 600; color: #059669;">{sample_data['total_gross']:.2f} PLN</td></tr>
                        </table>
                    </div>
                </div>
            </body>
            </html>
            """
        
        elif template_key == "internal_order_paid":
            html_content = f"""
            <!DOCTYPE html>
            <html><head><meta charset="UTF-8"></head>
            <body style="font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5;">
                <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div style="background: linear-gradient(135deg, #10b981, #059669); color: white; padding: 24px; text-align: center;">
                        <h1 style="margin: 0; font-size: 24px;">✅ Płatność otrzymana</h1>
                    </div>
                    <div style="padding: 24px;">
                        <p style="margin: 0 0 16px; color: #374151;">Otrzymano płatność za zamówienie:</p>
                        <div style="background: #f0fdf4; border-left: 4px solid #10b981; padding: 16px; margin-bottom: 16px;">
                            <strong style="color: #1e293b;">{sample_data['event_name']}</strong>
                        </div>
                        <table style="width: 100%; border-collapse: collapse; margin-top: 16px;">
                            <tr><td style="padding: 8px 0; color: #6b7280;">Kupujący:</td><td style="padding: 8px 0; font-weight: 600;">{sample_data['purchaser_first_name']} {sample_data['purchaser_last_name']}</td></tr>
                            <tr><td style="padding: 8px 0; color: #6b7280;">Email:</td><td style="padding: 8px 0;">{sample_data['purchaser_email']}</td></tr>
                            <tr><td style="padding: 8px 0; color: #6b7280;">Firma:</td><td style="padding: 8px 0;">{sample_data['company_name']}</td></tr>
                            <tr><td style="padding: 8px 0; color: #6b7280;">Kwota:</td><td style="padding: 8px 0; font-weight: 600; color: #059669;">{sample_data['total_gross']:.2f} PLN</td></tr>
                            <tr><td style="padding: 8px 0; color: #6b7280;">Status:</td><td style="padding: 8px 0;"><span style="background: #dcfce7; color: #166534; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600;">OPŁACONE</span></td></tr>
                        </table>
                    </div>
                </div>
            </body>
            </html>
            """
        
        elif template_key == "internal_payment_expired":
            html_content = f"""
            <!DOCTYPE html>
            <html><head><meta charset="UTF-8"></head>
            <body style="font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5;">
                <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div style="background: linear-gradient(135deg, #f59e0b, #d97706); color: white; padding: 24px; text-align: center;">
                        <h1 style="margin: 0; font-size: 24px;">⏰ Płatność wygasła</h1>
                    </div>
                    <div style="padding: 24px;">
                        <p style="margin: 0 0 16px; color: #374151;">Link do płatności wygasł dla zamówienia:</p>
                        <div style="background: #fffbeb; border-left: 4px solid #f59e0b; padding: 16px; margin-bottom: 16px;">
                            <strong style="color: #1e293b;">{sample_data['event_name']}</strong>
                        </div>
                        <table style="width: 100%; border-collapse: collapse; margin-top: 16px;">
                            <tr><td style="padding: 8px 0; color: #6b7280;">Kupujący:</td><td style="padding: 8px 0; font-weight: 600;">{sample_data['purchaser_first_name']} {sample_data['purchaser_last_name']}</td></tr>
                            <tr><td style="padding: 8px 0; color: #6b7280;">Email:</td><td style="padding: 8px 0;">{sample_data['purchaser_email']}</td></tr>
                            <tr><td style="padding: 8px 0; color: #6b7280;">Kwota:</td><td style="padding: 8px 0; font-weight: 600;">{sample_data['total_gross']:.2f} PLN</td></tr>
                            <tr><td style="padding: 8px 0; color: #6b7280;">Status:</td><td style="padding: 8px 0;"><span style="background: #fef3c7; color: #92400e; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600;">WYGASŁO</span></td></tr>
                        </table>
                    </div>
                </div>
            </body>
            </html>
            """
        
        elif template_key == "internal_payment_failed":
            html_content = f"""
            <!DOCTYPE html>
            <html><head><meta charset="UTF-8"></head>
            <body style="font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5;">
                <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div style="background: linear-gradient(135deg, #ef4444, #dc2626); color: white; padding: 24px; text-align: center;">
                        <h1 style="margin: 0; font-size: 24px;">❌ Płatność nieudana</h1>
                    </div>
                    <div style="padding: 24px;">
                        <p style="margin: 0 0 16px; color: #374151;">Płatność nie powiodła się dla zamówienia:</p>
                        <div style="background: #fef2f2; border-left: 4px solid #ef4444; padding: 16px; margin-bottom: 16px;">
                            <strong style="color: #1e293b;">{sample_data['event_name']}</strong>
                        </div>
                        <table style="width: 100%; border-collapse: collapse; margin-top: 16px;">
                            <tr><td style="padding: 8px 0; color: #6b7280;">Kupujący:</td><td style="padding: 8px 0; font-weight: 600;">{sample_data['purchaser_first_name']} {sample_data['purchaser_last_name']}</td></tr>
                            <tr><td style="padding: 8px 0; color: #6b7280;">Email:</td><td style="padding: 8px 0;">{sample_data['purchaser_email']}</td></tr>
                            <tr><td style="padding: 8px 0; color: #6b7280;">Kwota:</td><td style="padding: 8px 0; font-weight: 600;">{sample_data['total_gross']:.2f} PLN</td></tr>
                            <tr><td style="padding: 8px 0; color: #6b7280;">Status:</td><td style="padding: 8px 0;"><span style="background: #fee2e2; color: #991b1b; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 600;">NIEUDANA</span></td></tr>
                        </table>
                    </div>
                </div>
            </body>
            </html>
            """
        
        elif template_key == "internal_invoice_error":
            html_content = f"""
            <!DOCTYPE html>
            <html><head><meta charset="UTF-8"></head>
            <body style="font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5;">
                <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div style="background: linear-gradient(135deg, #8b5cf6, #7c3aed); color: white; padding: 24px; text-align: center;">
                        <h1 style="margin: 0; font-size: 24px;">⚠️ Błąd faktury</h1>
                    </div>
                    <div style="padding: 24px;">
                        <p style="margin: 0 0 16px; color: #374151;">Wystąpił błąd podczas generowania faktury:</p>
                        <div style="background: #f5f3ff; border-left: 4px solid #8b5cf6; padding: 16px; margin-bottom: 16px;">
                            <strong style="color: #1e293b;">{sample_data['event_name']}</strong>
                        </div>
                        <table style="width: 100%; border-collapse: collapse; margin-top: 16px;">
                            <tr><td style="padding: 8px 0; color: #6b7280;">Kupujący:</td><td style="padding: 8px 0; font-weight: 600;">{sample_data['purchaser_first_name']} {sample_data['purchaser_last_name']}</td></tr>
                            <tr><td style="padding: 8px 0; color: #6b7280;">Firma:</td><td style="padding: 8px 0;">{sample_data['company_name']}</td></tr>
                            <tr><td style="padding: 8px 0; color: #6b7280;">NIP:</td><td style="padding: 8px 0;">{sample_data['company_nip']}</td></tr>
                            <tr><td style="padding: 8px 0; color: #6b7280;">Kwota:</td><td style="padding: 8px 0; font-weight: 600;">{sample_data['total_gross']:.2f} PLN</td></tr>
                        </table>
                        <p style="margin-top: 16px; padding: 12px; background: #fef2f2; border-radius: 4px; color: #991b1b; font-size: 13px;">
                            ⚠️ Wymaga ręcznej interwencji - sprawdź logi systemu
                        </p>
                    </div>
                </div>
            </body>
            </html>
            """
        
        else:
            # Dla szablonów bez dedykowanej funkcji render - pokaż placeholder
            html_content = f"""
            <div style="font-family: Arial, Helvetica, sans-serif; padding: 40px; text-align: center; color: #64748b;">
                <div style="font-size: 48px; margin-bottom: 16px;">📧</div>
                <h2 style="color: #1e293b; margin-bottom: 8px;">Szablon: {template_key}</h2>
                <p>Podgląd tego szablonu nie jest jeszcze dostępny.</p>
                <p style="font-size: 12px; margin-top: 24px;">
                    Ten szablon jest generowany dynamicznie przez system<br>
                    i wymaga specjalnych danych do renderowania.
                </p>
            </div>
            """
            template_subject = f"[Podgląd] {template_key}"
        
        return jsonify({
            "success": True,
            "template_key": template_key,
            "subject": template_subject,
            "html": html_content,
        })
        
    except Exception as e:
        print(f"[TEMPLATE_PREVIEW] Error rendering {template_key}: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "template_key": template_key,
        }), 500


# ---------------------------------------------------------------------------
# SETTINGS (Ustawienia)
# ---------------------------------------------------------------------------

@admin_v2_bp.route("/settings", methods=["GET"])
@_require_login
def settings():
    """Strona ustawień z statusem integracji."""
    from pg_storage import get_wfirma_token
    
    user = _get_current_admin_user()
    
    # Status integracji
    integrations = {}
    
    # 1. Stripe
    stripe_api_key = os.environ.get("STRIPE_RENDER_API_KEY", "")
    stripe_webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    integrations["stripe"] = {
        "name": "Stripe",
        "icon": "credit-card",
        "configured": bool(stripe_api_key and stripe_webhook_secret),
        "details": {
            "api_key": "✓ Skonfigurowany" if stripe_api_key else "✗ Brak klucza API",
            "webhook": "✓ Skonfigurowany" if stripe_webhook_secret else "✗ Brak sekretu webhooka",
            "webhook_url": f"{request.host_url}api/stripe/webhook",
        },
    }
    
    # 2. wFirma
    try:
        wfirma_token = get_wfirma_token("md")
        wfirma_configured = bool(wfirma_token)
        wfirma_expires = None
        if wfirma_token and wfirma_token.get("refresh_token_expires_at"):
            import time
            from datetime import datetime
            expires_ts = wfirma_token.get("refresh_token_expires_at")
            if expires_ts:
                wfirma_expires = datetime.fromtimestamp(expires_ts).strftime("%d.%m.%Y %H:%M")
    except Exception:
        wfirma_configured = False
        wfirma_expires = None
    
    integrations["wfirma"] = {
        "name": "wFirma",
        "icon": "file-text",
        "configured": wfirma_configured,
        "details": {
            "token": "✓ Token aktywny" if wfirma_configured else "✗ Brak tokenu - wymaga autoryzacji",
            "expires": f"Refresh token wygasa: {wfirma_expires}" if wfirma_expires else "—",
            "auth_url": f"{request.host_url}auth?company=md",
        },
    }
    
    # 3. Make.com (wysyłka emaili)
    make_webhook = os.environ.get("MAKE_WEBHOOK_SEND_EMAIL_REQUEST", "")
    make_api_key = os.environ.get("RENDER_EMAIL_KEY_SEND_REQUEST", "")
    integrations["make"] = {
        "name": "Make.com",
        "icon": "zap",
        "configured": bool(make_webhook and make_api_key),
        "details": {
            "webhook": "✓ Skonfigurowany" if make_webhook else "✗ Brak webhooka",
            "api_key": "✓ Skonfigurowany" if make_api_key else "✗ Brak klucza API",
        },
    }
    
    # 4. GUS/REGON
    gus_api_key = os.environ.get("GUS_API_KEY") or os.environ.get("BIR1_medidesk", "")
    integrations["gus"] = {
        "name": "GUS/REGON",
        "icon": "building",
        "configured": bool(gus_api_key),
        "details": {
            "api_key": "✓ Skonfigurowany" if gus_api_key else "✗ Brak klucza API",
            "mode": "Produkcja" if os.environ.get("GUS_USE_TEST", "").lower() != "true" else "Test",
        },
    }
    
    # 5. Zoho Flow
    zoho_webhook = os.environ.get("ZOHO_FLOW_EVENT_UPDATE_WEBHOOK", "")
    integrations["zoho"] = {
        "name": "Zoho Flow",
        "icon": "globe",
        "configured": bool(zoho_webhook),
        "details": {
            "webhook": "✓ Skonfigurowany" if zoho_webhook else "✗ Brak webhooka do synchronizacji wydarzeń",
        },
    }
    
    # 6. Zoho Backstage API
    backstage_client_id = os.environ.get("BACKSTAGE_CLIENT_ID", "")
    backstage_client_secret = os.environ.get("BACKSTAGE_CLIENT_SECRET", "")
    backstage_refresh_token = os.environ.get("BACKSTAGE_REFRESH_TOKEN", "")
    backstage_configured = bool(backstage_client_id and backstage_client_secret and backstage_refresh_token)
    integrations["backstage_api"] = {
        "name": "Backstage API",
        "icon": "cloud-download",
        "configured": backstage_configured,
        "details": {
            "client_id": "✓ Skonfigurowany" if backstage_client_id else "✗ Brak CLIENT_ID",
            "client_secret": "✓ Skonfigurowany" if backstage_client_secret else "✗ Brak CLIENT_SECRET",
            "refresh_token": "✓ Skonfigurowany" if backstage_refresh_token else "✗ Brak REFRESH_TOKEN",
        },
    }
    
    # Powiadomienia email
    email_config = {
        "technical": os.environ.get("BACKSTAGE_TECHNICAL_INFO_EMAIL", ""),
        "events": os.environ.get("BACKSTAGE_EVENT_INFO_EMAIL", ""),
        "wfirma_alerts": os.environ.get("WFIRMA_TOKEN_EXPIRES_ALERT_EMAIL", ""),
    }
    
    return render_template(
        "admin_v2/settings.html",
        active_page="settings",
        integrations=integrations,
        email_config=email_config,
        **_get_common_context(user),
    )


# ---------------------------------------------------------------------------
# PAYMENT BUCKETS HELPER
# ---------------------------------------------------------------------------

def _build_payment_buckets(orders: list) -> dict:
    """Buduje strukturę buckets dla zakładki Płatności."""
    from datetime import datetime, timedelta
    
    today = datetime.now().date()
    
    buckets = {
        "due_today": {"orders": [], "total": 0},
        "overdue": {"orders": [], "total": 0},
        "upcoming": {"orders": [], "total": 0},
        "paid": {"orders": [], "total": 0},
        "cancelled": {"orders": [], "total": 0},
    }
    
    for order in orders:
        status = order.get("status", "")
        total = float(order.get("total") or 0)
        created_at = order.get("created_at")
        
        if status == "paid":
            buckets["paid"]["orders"].append(order)
            buckets["paid"]["total"] += total
        elif status in ("cancelled", "expired", "refunded"):
            buckets["cancelled"]["orders"].append(order)
            buckets["cancelled"]["total"] += total
        elif status in ("pending_payment", "received"):
            # Określ bucket na podstawie daty utworzenia
            if created_at:
                order_date = created_at.date() if hasattr(created_at, 'date') else created_at
                days_old = (today - order_date).days if isinstance(order_date, type(today)) else 0
                
                if days_old >= 7:
                    buckets["overdue"]["orders"].append(order)
                    buckets["overdue"]["total"] += total
                elif days_old >= 3:
                    buckets["due_today"]["orders"].append(order)
                    buckets["due_today"]["total"] += total
                else:
                    buckets["upcoming"]["orders"].append(order)
                    buckets["upcoming"]["total"] += total
            else:
                buckets["upcoming"]["orders"].append(order)
                buckets["upcoming"]["total"] += total
    
    return buckets


# ---------------------------------------------------------------------------
# EVENT ROOM (Dashboard pojedynczego wydarzenia z zakładkami)
# ---------------------------------------------------------------------------

@admin_v2_bp.route("/events/<event_id>/room", methods=["GET"])
@_require_permission("events")
def event_room(event_id: str):
    """Dashboard pojedynczego wydarzenia z zakładkami."""
    user = _get_current_admin_user()
    
    # Sprawdź dostęp do tego konkretnego wydarzenia
    if not _user_has_event_access(user, event_id):
        return render_template(
            "admin_v2/base.html",
            active_page="",
            **_get_common_context(user),
        ), 403
    
    event = get_event(event_id)
    if not event:
        return redirect(url_for("admin_v2_bp.events_list"))
    
    # Normalizuj dane wydarzenia (mapuj pola Backstage)
    _normalize_event_data(event)
    
    # Aktywna zakładka
    active_tab = request.args.get("tab", "sales").strip()
    valid_tabs = ["sales", "payments", "orders", "participants", "communication", "config"]
    if active_tab not in valid_tabs:
        active_tab = "sales"
    
    # Pobierz zamówienia
    orders = list_orders(event_id=event_id, limit=500)
    
    # Pobierz uczestników
    participants = get_participants_for_event(event_id) or []
    
    # Pobierz logi maili dla tego wydarzenia
    emails = _list_mail_logs(event_id=event_id, limit=100)
    for email in emails:
        email["recipient"] = email.get("to_email", "")
        email["type"] = email.get("template_key", "")
        email["sent_at"] = email.get("created_at")
    
    # Statystyki
    paid_orders = [o for o in orders if o.get("status") == "paid"]
    pending_orders = [o for o in orders if o.get("status") == "pending_payment"]
    total_revenue = sum(float(o.get("total") or 0) for o in paid_orders)
    pending_revenue = sum(float(o.get("total") or 0) for o in pending_orders)
    
    # Filtruj emaile - tylko zewnętrzne (nie internal_*, nie do admina)
    def is_internal_email(e):
        email_type = (e.get("type") or "").lower()
        recipient = (e.get("recipient") or "").lower()
        return (
            email_type.startswith("internal") or 
            "admin" in recipient or 
            recipient.endswith("@medidesk.com")
        )
    external_emails = [e for e in emails if not is_internal_email(e)]
    sent_emails = [e for e in external_emails if e.get("status") in ("sent", "delivered")]
    email_errors = len([e for e in external_emails if e.get("status") in ("failed", "error", "bounced")])
    notified = len([p for p in participants if p.get("status") == "emailed"])
    
    stats = {
        "orders": len(orders),
        "paid": len(paid_orders),
        "pending": len(pending_orders),
        "participants": len(participants),
        "revenue": total_revenue,
        "pending_revenue": pending_revenue,
        "email_errors": email_errors,
        "emails_sent": len(sent_emails),
        "notified": notified,
        "pending_notification": len(participants) - notified,
        "delivery_rate": None,  # Brak danych
    }
    
    # Mapuj pola zamówień dla szablonu
    for order in orders:
        order["buyer_first_name"] = order.get("purchaser_first_name", "")
        order["buyer_last_name"] = order.get("purchaser_last_name", "")
        order["buyer_email"] = order.get("purchaser_email", "")
        order["buyer_company"] = order.get("purchaser_company", "")
        order["order_id"] = order.get("event_order_id", "")
        order["participants_count"] = order.get("participant_count", 1)
    
    # Mapuj pola uczestników dla szablonu
    for p in participants:
        # Preferuj nazwę biletu, ale nie pokazuj długich ID numerycznych
        ticket_name = p.get("ticket_class_name") or ""
        ticket_id = p.get("ticket_class_id") or ""
        # Usuń słowo "Bilet" z nazwy jeśli jest
        if ticket_name:
            ticket_name = ticket_name.replace("Bilet ", "").replace("bilet ", "")
        if not ticket_name and ticket_id and len(str(ticket_id)) > 10 and str(ticket_id).isdigit():
            ticket_name = "Standard"
        p["ticket_name"] = ticket_name or ticket_id or "Standard"
        p["is_notified"] = p.get("status") == "emailed"
        p["company"] = ""  # Brak w danych
    
    # Backstage URLs są już ustawione przez _normalize_event_data()
    
    # Buduj strukturę buckets dla zakładki Płatności
    buckets = _build_payment_buckets(orders)
    
    # Pobierz typy biletów dla tego wydarzenia
    from pg_storage import get_ticket_classes
    ticket_classes = get_ticket_classes(event_id) or []

    return render_template(
        "admin_v2/event_room.html",
        active_page="events",
        event=event,
        active_tab=active_tab,
        stats=stats,
        orders=orders,
        participants=participants,
        emails=emails,
        buckets=buckets,
        ticket_classes=ticket_classes,
        **_get_common_context(user),
    )
