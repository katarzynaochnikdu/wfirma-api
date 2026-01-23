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
    
    # Ostatnie zamówienia
    recent_orders = all_orders[:5]
    
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
    
    # Filtrowanie tekstowe
    if q_filter:
        orders = [
            o for o in orders
            if q_filter in (o.get("event_order_id") or "").lower()
            or q_filter in (o.get("purchaser_email") or "").lower()
            or q_filter in (o.get("purchaser_first_name") or "").lower()
            or q_filter in (o.get("purchaser_last_name") or "").lower()
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
        event_data = event.get("data") or {}
        order["event_color"] = event_data.get("color_gradient_1", "")
        order["event_color_2"] = event_data.get("color_gradient_2", "")
    
    # Historia zamówienia (pusta lista - szablon ma fallback)
    order_history = []
    
    return render_template(
        "admin_v2/order_detail.html",
        active_page="orders",
        order=order,
        participants=participants,
        wfirma_documents=wfirma_documents,
        order_history=order_history,
        **_get_common_context(user),
    )


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
    
    return render_template(
        "admin_v2/email-designer.html",
        active_page="email_designer",
        events=events,
        **_get_common_context(user),
    )


# ---------------------------------------------------------------------------
# EVENT ROUTES (wrapper do starego panelu lub nowe)
# ---------------------------------------------------------------------------

@admin_v2_bp.route("/events/new", methods=["GET", "POST"])
@_require_permission("events")
def event_new():
    """Nowe wydarzenie - przekierowanie do starego panelu."""
    # Przekieruj do starego panelu - tam jest pełna logika formularza
    token = session.get("admin_user_id", "")
    return redirect(url_for("admin_bp.event_new", token=token))


@admin_v2_bp.route("/events/<event_id>/edit", methods=["GET", "POST"])
@_require_permission("events")
def event_edit(event_id: str):
    """Edycja wydarzenia - przekierowanie do starego panelu."""
    token = session.get("admin_user_id", "")
    return redirect(url_for("admin_bp.event_edit", event_id=event_id, token=token))


@admin_v2_bp.route("/events/<event_id>/preview", methods=["GET"])
@_require_permission("events")
def event_preview(event_id: str):
    """Podgląd wydarzenia - przekierowanie do starego panelu."""
    token = session.get("admin_user_id", "")
    return redirect(url_for("admin_bp.event_preview", event_id=event_id, token=token))


@admin_v2_bp.route("/events/<event_id>/dashboard", methods=["GET"])
@_require_permission("events")
def event_dashboard(event_id: str):
    """Dashboard pojedynczego wydarzenia."""
    user = _get_current_admin_user()
    
    event = get_event(event_id)
    if not event:
        return redirect(url_for("admin_v2_bp.events_list"))
    
    # Pobierz zamówienia i uczestników dla tego wydarzenia
    orders = list_orders(event_id=event_id, limit=500)
    participants = get_participants_for_event(event_id) or []
    
    # Statystyki
    total_orders = len(orders)
    paid_orders = [o for o in orders if o.get("status") == "paid"]
    total_revenue = sum(float(o.get("total") or 0) for o in paid_orders)
    total_participants = len(participants)
    
    stats = {
        "total_orders": total_orders,
        "total_participants": total_participants,
        "total_revenue": f"{total_revenue:,.2f}".replace(",", " "),
        "paid_orders": len(paid_orders),
    }
    
    # Ostatnie zamówienia
    recent_orders = orders[:10]
    for order in recent_orders:
        order["event_name"] = event.get("event_name", "")
        order["event_color"] = (event.get("data") or {}).get("color_gradient_1", "")
    
    return render_template(
        "admin_v2/event_dashboard.html",
        active_page="events",
        event=event,
        stats=stats,
        recent_orders=recent_orders,
        participants=participants[:20],
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
    
    # Pobierz uczestników - jeśli wybrany event, tylko z niego
    all_participants = []
    if event_id_filter:
        all_participants = get_participants_for_event(event_id_filter) or []
        # Dodaj event info
        event = get_event(event_id_filter)
        for p in all_participants:
            p["event_name"] = event.get("event_name", "") if event else ""
            p["event_color"] = (event.get("data") or {}).get("color_gradient_1", "") if event else ""
    else:
        # Pobierz z wszystkich aktywnych wydarzeń
        for event in events:
            if event.get("is_active", True):
                event_participants = get_participants_for_event(event.get("event_id")) or []
                for p in event_participants:
                    p["event_name"] = event.get("event_name", "")
                    p["event_color"] = (event.get("data") or {}).get("color_gradient_1", "")
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
    
    return render_template(
        "admin_v2/participants.html",
        active_page="participants",
        participants=all_participants,
        events=events,
        stats=stats,
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
