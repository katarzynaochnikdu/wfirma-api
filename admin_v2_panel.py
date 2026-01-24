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
    
    # Mapuj nazwy biletów (nie pokazuj długich ID numerycznych)
    for p in participants:
        ticket_name = p.get("ticket_class_name") or ""
        ticket_id = p.get("ticket_class_id") or ""
        if not ticket_name and ticket_id and len(str(ticket_id)) > 10 and str(ticket_id).isdigit():
            ticket_name = "Bilet Standard"
        p["ticket_name"] = ticket_name or ticket_id or "Bilet Standard"
    
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
                data = {
                    "event_date_start": request.form.get("event_date_start") or "",
                    "event_time_text": request.form.get("event_time_text") or "",
                    "event_description": request.form.get("event_description") or "",
                    "event_location_place": request.form.get("event_location_place") or "",
                    "event_location_address": request.form.get("event_location_address") or "",
                    "event_location_zip": request.form.get("event_location_zip") or "",
                    "event_location_city": request.form.get("event_location_city") or "",
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
    
    return render_template(
        "admin_v2/event_form.html",
        active_page="events",
        event=None,
        event_data=None,
        error=error,
        success=success,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/events/<event_id>/edit", methods=["GET", "POST"])
@_require_permission("events")
def event_edit(event_id: str):
    """Edycja wydarzenia."""
    from pg_storage import upsert_event
    
    user = _get_current_admin_user()
    
    event = get_event(event_id)
    if not event:
        return redirect(url_for("admin_v2_bp.events_list"))
    
    error = None
    success = None
    
    if request.method == "POST":
        event_name = (request.form.get("event_name") or "").strip()
        
        if not event_name:
            error = "Wymagane: Nazwa wydarzenia"
        else:
            is_active = request.form.get("is_active") == "1"
            data = event.get("data") or {}
            
            # Aktualizuj dane
            data.update({
                "event_date_start": request.form.get("event_date_start") or "",
                "event_time_text": request.form.get("event_time_text") or "",
                "event_description": request.form.get("event_description") or "",
                "event_location_place": request.form.get("event_location_place") or "",
                "event_location_address": request.form.get("event_location_address") or "",
                "event_location_zip": request.form.get("event_location_zip") or "",
                "event_location_city": request.form.get("event_location_city") or "",
                "color_gradient_1": request.form.get("color_gradient_1") or "#2563eb",
                "color_gradient_2": request.form.get("color_gradient_2") or "#1e40af",
                "event_mail_link_top_banner": request.form.get("event_mail_link_top_banner") or "",
                "url_event": request.form.get("url_event") or "",
                "md_email_kontakt": request.form.get("md_email_kontakt") or "konferencje@medidesk.com",
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
                success = "Wydarzenie zostało zaktualizowane"
                # Odśwież dane
                event = get_event(event_id)
            except Exception as e:
                error = f"Błąd aktualizacji: {e}"
    
    event_data = event.get("data") or {}
    
    return render_template(
        "admin_v2/event_form.html",
        active_page="events",
        event=event,
        event_data=event_data,
        error=error,
        success=success,
        **_get_common_context(user),
    )


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
        active_events=active_events,
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
        event_data = (event.get("data") or {}) if event else {}
        for p in all_participants:
            p["event_name"] = event.get("event_name", "") if event else ""
            p["event_color"] = event_data.get("color_gradient_1", "hsl(212, 100%, 42%)")
            p["event_color_2"] = event_data.get("color_gradient_2", "hsl(195, 100%, 42%)")
    else:
        # Pobierz z wszystkich aktywnych wydarzeń
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
        # Jeśli ticket_id wygląda jak długi numer (>10 cyfr), nie pokazuj go
        if not ticket_name and ticket_id and len(str(ticket_id)) > 10 and str(ticket_id).isdigit():
            ticket_name = "Bilet Standard"
        p["ticket_name"] = ticket_name or ticket_id or "Bilet Standard"
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


# ---------------------------------------------------------------------------
# WORK QUEUE (Monitoring procesów)
# ---------------------------------------------------------------------------

@admin_v2_bp.route("/work-queue", methods=["GET"])
@_require_login
def work_queue():
    """Monitoring procesów - kolejka błędów i akcji."""
    from datetime import datetime
    
    user = _get_current_admin_user()
    
    # Filtry
    category_filter = request.args.get("category", "").strip()
    
    # Kategorie zadań
    categories = {
        "wfirma": {"label": "wFirma", "icon": "file-text"},
        "make": {"label": "Make.com", "icon": "zap"},
        "stripe": {"label": "Stripe", "icon": "credit-card"},
        "database": {"label": "Baza danych", "icon": "database"},
        "attendee": {"label": "Uczestnicy", "icon": "users"},
        "config": {"label": "Konfiguracja", "icon": "settings"},
    }
    
    # Na razie pusta lista - w przyszłości pobieranie z bazy
    tasks = []
    
    # Statystyki (na razie zerowe)
    stats = {
        "total": 0,
        "critical": 0,
        "errors": 0,
        "warnings": 0,
        "can_retry": 0,
    }
    
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
        **_get_common_context(user),
    )


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


def _build_order_history(order_id: str, order: dict):
    """Buduje listę zdarzeń dla historii zamówienia."""
    history = []
    
    # Mapowanie typów emaili na czytelne nazwy
    EMAIL_TYPE_LABELS = {
        "proforma": ("Proforma wysłana", "document"),
        "proforma_reminder": ("Przypomnienie o płatności", "email"),
        "payment_link": ("Link do płatności wysłany", "email"),
        "payment_confirmation": ("Potwierdzenie płatności", "payment"),
        "registration_confirmation": ("Potwierdzenie rejestracji", "email"),
        "ticket": ("Bilet wysłany", "email"),
        "invoice": ("Faktura wysłana", "document"),
        "stripe_payment_link": ("Link Stripe wysłany", "payment"),
        "paid_confirmation": ("Potwierdzenie zapłaty", "payment"),
        "expired": ("Sesja płatności wygasła", "status_change"),
    }
    
    # Pobierz emaile dla zamówienia
    emails = _get_emails_for_order(order_id)
    
    for email in emails:
        template_key = (email.get("template_key") or "").lower()
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
            "timestamp": created_at.strftime("%d.%m.%Y, %H:%M") if created_at else "—",
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
            "timestamp": paid_at.strftime("%d.%m.%Y, %H:%M") if paid_at else "—",
            "status": "paid",
            "status_label": "Opłacone",
        })
    
    # Dodaj zdarzenie utworzenia zamówienia
    created_at = order.get("created_at")
    history.append({
        "type": "created",
        "title": "Zamówienie utworzone",
        "description": "Zamówienie zostało zarejestrowane w systemie",
        "timestamp": created_at.strftime("%d.%m.%Y, %H:%M") if created_at else "—",
        "status": None,
        "status_label": "Otrzymane",
    })
    
    # Sortuj od najnowszych (ale created na końcu)
    # Historia już jest posortowana - emaile DESC, potem payment, potem created
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


@admin_v2_bp.route("/communication", methods=["GET"])
@_require_permission("orders")
def communication():
    """Historia wysyłek i komunikacji."""
    from datetime import datetime, timedelta
    
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
    
    return render_template(
        "admin_v2/communication.html",
        active_page="communication",
        stats=stats,
        events=events,
        error_emails=error_emails[:10],
        emails=emails,
        **_get_common_context(user),
    )


@admin_v2_bp.route("/communication/<int:email_id>/retry", methods=["POST"])
@_require_permission("orders")
def email_retry(email_id: int):
    """Ponów wysyłkę emaila."""
    # Placeholder - w przyszłości implementacja ponownej wysyłki
    return redirect(url_for("admin_v2_bp.communication"))


# ---------------------------------------------------------------------------
# SETTINGS (Ustawienia)
# ---------------------------------------------------------------------------

@admin_v2_bp.route("/settings", methods=["GET"])
@_require_login
def settings():
    """Strona ustawień."""
    user = _get_current_admin_user()
    
    return render_template(
        "admin_v2/settings.html",
        active_page="settings",
        **_get_common_context(user),
    )


# ---------------------------------------------------------------------------
# EVENT ROOM (Dashboard pojedynczego wydarzenia z zakładkami)
# ---------------------------------------------------------------------------

@admin_v2_bp.route("/events/<event_id>/room", methods=["GET"])
@_require_permission("events")
def event_room(event_id: str):
    """Dashboard pojedynczego wydarzenia z zakładkami."""
    user = _get_current_admin_user()
    
    event = get_event(event_id)
    if not event:
        return redirect(url_for("admin_v2_bp.events_list"))
    
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
    email_errors = len([e for e in emails if e.get("status") in ("failed", "error")])
    notified = len([p for p in participants if p.get("status") == "emailed"])
    
    stats = {
        "orders": len(orders),
        "paid": len(paid_orders),
        "pending": len(pending_orders),
        "participants": len(participants),
        "revenue": total_revenue,
        "pending_revenue": pending_revenue,
        "email_errors": email_errors,
        "emails_sent": len(emails),
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
        if not ticket_name and ticket_id and len(str(ticket_id)) > 10 and str(ticket_id).isdigit():
            ticket_name = "Bilet Standard"
        p["ticket_name"] = ticket_name or ticket_id or "Bilet Standard"
        p["is_notified"] = p.get("status") == "emailed"
        p["company"] = ""  # Brak w danych
    
    # Backstage URLs (placeholder)
    event["backstage_url"] = "#"
    event["backstage_orders_url"] = "#"
    event["backstage_attendees_url"] = "#"
    
    return render_template(
        "admin_v2/event_room.html",
        active_page="events",
        event=event,
        active_tab=active_tab,
        stats=stats,
        orders=orders,
        participants=participants,
        emails=emails,
        **_get_common_context(user),
    )
