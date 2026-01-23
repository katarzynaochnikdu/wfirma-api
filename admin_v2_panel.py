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
    get_wfirma_documents,
    count_participants_by_status,
    # Admin users
    get_admin_user_by_email,
    get_admin_user_by_id,
    list_admin_users,
    update_admin_user_last_login,
    increment_admin_user_failed_login,
    insert_admin_audit_log,
    list_admin_audit_log,
)

admin_v2_bp = Blueprint("admin_v2_bp", __name__, template_folder="templates")


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


def _is_admin_user(user: Optional[Dict[str, Any]]) -> bool:
    """Czy user ma rolę admin (pełny dostęp)."""
    if not user:
        return False
    return (user.get("role") or "").strip().lower() == "admin"


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
            user = _get_current_admin_user()
            if not user:
                return redirect(url_for("admin_v2_bp.login"))
            if not _user_has_permission(user, page):
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
    return {
        "user_email": user.get("email") if user else None,
        "user_name": user.get("full_name") if user else None,
        "user_role": user.get("role") if user else None,
        "user_initials": _get_user_initials(user),
        "can_events": _user_has_permission(user, "events"),
        "can_orders": _user_has_permission(user, "orders"),
        "can_users": _user_has_permission(user, "users"),
        "can_audit": _user_has_permission(user, "audit"),
    }


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
                user_id=user["id"],
                user_email=email,
                action="login",
                details="Login via Admin V2",
                ip_address=request.remote_addr,
            )
            return redirect(url_for("admin_v2_bp.dashboard"))
        else:
            error = "Nieprawidłowy email lub hasło"
            if user:
                increment_admin_user_failed_login(user["id"])
                insert_admin_audit_log(
                    user_id=user["id"],
                    user_email=email,
                    action="login_failed",
                    details="Failed login via Admin V2",
                    ip_address=request.remote_addr,
                )
    
    return render_template("admin_v2/login.html", error=error)


@admin_v2_bp.route("/logout", methods=["GET", "POST"])
def logout():
    """Wylogowanie z panelu."""
    user = _get_current_admin_user()
    if user:
        insert_admin_audit_log(
            user_id=user["id"],
            user_email=user.get("email"),
            action="logout",
            details="Logout via Admin V2",
            ip_address=request.remote_addr,
        )
    session.pop("admin_user_id", None)
    return redirect(url_for("admin_v2_bp.login"))


@admin_v2_bp.route("/", methods=["GET"])
@admin_v2_bp.route("/dashboard", methods=["GET"])
@_require_login
def dashboard():
    """Dashboard z podsumowaniem."""
    user = _get_current_admin_user()
    
    # Pobierz statystyki
    all_orders = list_orders(limit=500)
    all_events = list_events(limit=100)
    
    # Oblicz statystyki
    total_orders = len(all_orders)
    paid_orders = [o for o in all_orders if o.get("status") == "paid"]
    total_revenue = sum(float(o.get("total_price") or 0) for o in paid_orders)
    
    # Zlicz uczestników
    total_participants = 0
    for o in all_orders:
        total_participants += int(o.get("participant_count") or 0)
    
    active_events = len([e for e in all_events if e.get("is_active", True)])
    
    stats = {
        "total_orders": total_orders,
        "total_participants": total_participants,
        "total_revenue": f"{total_revenue:,.2f}".replace(",", " "),
        "active_events": active_events,
    }
    
    # Ostatnie zamówienia
    recent_orders = all_orders[:5]
    
    # Dodaj nazwy wydarzeń do zamówień
    event_map = {e.get("event_id"): e for e in all_events}
    for order in recent_orders:
        event = event_map.get(order.get("event_id"))
        if event:
            order["event_name"] = event.get("event_name", "")
            order["event_color"] = (event.get("data") or {}).get("color_gradient_1", "")
    
    return render_template(
        "admin_v2/dashboard.html",
        active_page="dashboard",
        stats=stats,
        recent_orders=recent_orders,
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
    
    # Filtrowanie tekstowe
    if q_filter:
        orders = [
            o for o in orders
            if q_filter in (o.get("order_id") or "").lower()
            or q_filter in (o.get("purchaser_email") or "").lower()
            or q_filter in (o.get("purchaser_name") or "").lower()
        ]
    
    # Dodaj nazwy wydarzeń
    event_map = {e.get("event_id"): e for e in events}
    for order in orders:
        event = event_map.get(order.get("event_id"))
        if event:
            order["event_name"] = event.get("event_name", "")
            order["event_color"] = (event.get("data") or {}).get("color_gradient_1", "")
    
    return render_template(
        "admin_v2/orders.html",
        active_page="orders",
        orders=orders,
        events=events,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/orders/<order_id>", methods=["GET"])
@_require_permission("orders")
def order_detail(order_id: str):
    """Szczegóły zamówienia."""
    user = _get_current_admin_user()
    
    order = get_order(order_id)
    if not order:
        return redirect(url_for("admin_v2_bp.orders_list"))
    
    # Pobierz uczestników
    participants = get_participants_for_order(order_id) or []
    
    # Pobierz dokumenty wFirma
    wfirma_documents = get_wfirma_documents(order_id) or []
    
    # Pobierz nazwę wydarzenia
    event = get_event(order.get("event_id"))
    if event:
        order["event_name"] = event.get("event_name", "")
        order["event_color"] = (event.get("data") or {}).get("color_gradient_1", "")
    
    return render_template(
        "admin_v2/order_detail.html",
        active_page="orders",
        order=order,
        participants=participants,
        wfirma_documents=wfirma_documents,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/events", methods=["GET"])
@_require_permission("events")
def events_list():
    """Lista wydarzeń."""
    user = _get_current_admin_user()
    
    # Filtry
    status_filter = request.args.get("status", "").strip().lower()
    q_filter = request.args.get("q", "").strip().lower()
    
    all_events = list_events(limit=500)
    
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
    
    # Podziel na aktywne i nieaktywne
    active_events = [e for e in all_events if e.get("is_active", True)]
    inactive_events = [e for e in all_events if not e.get("is_active", True)]
    
    # Dodaj statystyki do wydarzeń
    for event in active_events + inactive_events:
        event_id = event.get("event_id")
        orders = list_orders(event_id=event_id, limit=500)
        event["order_count"] = len(orders)
        event["participant_count"] = sum(int(o.get("participant_count") or 0) for o in orders)
    
    return render_template(
        "admin_v2/events.html",
        active_page="events",
        events=active_events,
        inactive_events=inactive_events,
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
            if q_filter in (log.get("user_email") or "").lower()
            or q_filter in (log.get("action") or "").lower()
            or q_filter in (log.get("details") or "").lower()
        ]
    
    return render_template(
        "admin_v2/audit.html",
        active_page="audit",
        audit_logs=audit_logs,
        **_get_common_context(user),
    )
