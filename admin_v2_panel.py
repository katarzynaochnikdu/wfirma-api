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
    normalized = {
        # Data i czas
        "eventDate": event_data.get("event_day_text_1") or event_data.get("event_date_time") or event_data.get("eventDate") or "",
        "eventTime": event_data.get("event_time_text") or event_data.get("eventTime") or "",
        
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
        
        # Linki publiczne
        "event_public_url": event_data.get("event_public_url") or "",
        "success_page_url": event_data.get("success_page_url") or "",
        "cancel_page_url": event_data.get("cancel_page_url") or "",
    }
    
    # Zachowaj wszystkie oryginalne pola i nadpisz znormalizowanymi
    merged_data = {**event_data, **normalized}
    event["data"] = merged_data
    
    # Mapuj linki Backstage
    event["backstage_url"] = event_data.get("event_config_link") or "#"
    event["backstage_orders_url"] = event_data.get("event_orders_link") or "#"
    event["backstage_attendees_url"] = event_data.get("event_attendees_link") or "#"
    
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
            p.get("ticket_class_name") or p.get("ticket_class_id") or "Bilet Standard",
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


@admin_v2_bp.route("/orders/<order_id>/status", methods=["POST"])
@_require_permission("orders")
def order_update_status(order_id: str):
    """Aktualizuje status zamówienia (AJAX)."""
    from flask import jsonify
    from pg_storage import update_order_status
    
    user = _get_current_admin_user()
    new_status = request.form.get("status", "").strip()
    
    valid_statuses = ["received", "pending_payment", "paid", "cancelled", "refunded"]
    if new_status not in valid_statuses:
        return jsonify({"success": False, "error": "Nieprawidłowy status"}), 400
    
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


@admin_v2_bp.route("/orders/<order_id>/send-reminder", methods=["POST"])
@_require_permission("orders")
def order_send_reminder(order_id: str):
    """Wysyła przypomnienie o płatności (placeholder)."""
    from flask import jsonify
    # TODO: Integracja z Make/email
    return jsonify({"success": True, "message": "Przypomnienie zostanie wysłane"})


@admin_v2_bp.route("/orders/<order_id>/resend-ticket", methods=["POST"])
@_require_permission("orders")
def order_resend_ticket(order_id: str):
    """Ponownie wysyła bilet (placeholder)."""
    from flask import jsonify
    # TODO: Integracja z Make/email
    return jsonify({"success": True, "message": "Bilet zostanie ponownie wysłany"})


@admin_v2_bp.route("/orders/<order_id>/cancel", methods=["POST"])
@_require_permission("orders")
def order_cancel(order_id: str):
    """Anuluje zamówienie."""
    from flask import jsonify
    from pg_storage import update_order_status
    
    user = _get_current_admin_user()
    result = update_order_status(order_id, "cancelled")
    
    if result:
        insert_admin_audit_log(
            action="order_cancelled",
            admin_user_id=user.get("id"),
            target_id=order_id,
            ip=request.remote_addr,
        )
        return jsonify({"success": True})
    
    return jsonify({"success": False, "error": "Nie znaleziono zamówienia"}), 404


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
    
    # Dodaj statystyki i normalizuj dane wydarzeń
    for event in active_events + inactive_events:
        event_id = event.get("event_id")
        orders = list_orders(event_id=event_id, limit=500)
        event["order_count"] = len(orders)
        event["participant_count"] = sum(int(o.get("participant_count") or 0) for o in orders)
        # Normalizuj pola z Backstage
        _normalize_event_data(event)
    
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
        **_get_common_context(user),
    )


@admin_v2_bp.route("/communication/<int:email_id>/retry", methods=["POST"])
@_require_permission("orders")
def email_retry(email_id: int):
    """Ponów wysyłkę emaila."""
    # Placeholder - w przyszłości implementacja ponownej wysyłki
    return redirect(url_for("admin_v2_bp.communication"))


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
            {"name": "Bilet Standard", "quantity": 2, "price": 615.00, "total_gross": 1230.00},
        ],
        "payment_url": "https://checkout.stripe.com/example",
        "order_number": "ORD-2026-001234",
        "proforma_number": "PF/2026/001234",
        "participant_first_name": "Anna",
        "participant_last_name": "Nowak",
        "participant_email": "anna.nowak@example.com",
        "ticket_name": "Bilet VIP",
    }
    
    # Kolory i style wydarzenia
    event_config = {
        "banner_url": "",
        "color_gradient_1": "hsl(212, 100%, 42%)",
        "color_gradient_2": "hsl(195, 100%, 42%)",
        "email_footer_text": "© 2026 Medidesk. Wszystkie prawa zastrzeżone.",
        "organizer_name": "Medidesk Sp. z o.o.",
        "organizer_email": "kontakt@medidesk.pl",
        "organizer_phone": "+48 22 123 45 67",
    }
    
    # Mapowanie kluczy szablonów na tematy emaili
    template_subjects = {
        "stripe_payment_link": f"Link do płatności - {sample_data['event_name']}",
        "proforma_sent": f"Faktura proforma - {sample_data['event_name']}",
        "payment_confirmation": f"Potwierdzenie płatności - {sample_data['event_name']}",
        "registration_confirmation": f"Potwierdzenie rejestracji - {sample_data['event_name']}",
        "checkout_reminder": f"Przypomnienie o płatności - {sample_data['event_name']}",
        "checkout_expired_new_link": f"Nowy link do płatności - {sample_data['event_name']}",
        "participant_ticket": f"Twój bilet na {sample_data['event_name']}",
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
                company_name=sample_data["company_name"],
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
        
        else:
            # Dla szablonów bez dedykowanej funkcji render - pokaż placeholder
            html_content = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 40px; text-align: center; color: #64748b;">
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
    """Strona ustawień."""
    user = _get_current_admin_user()
    
    return render_template(
        "admin_v2/settings.html",
        active_page="settings",
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
    
    # Backstage URLs są już ustawione przez _normalize_event_data()
    
    # Buduj strukturę buckets dla zakładki Płatności
    buckets = _build_payment_buckets(orders)

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
        **_get_common_context(user),
    )
