"""
Backstage Engine - obsługa webhooków z Zoho Backstage.
Odpowiada za routing płatności (FOC / PROFORMA / STRIPE) i generowanie mail_tasks.
"""
import hashlib
import json
import datetime
import os
import requests
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

# Konfiguracja Make.com webhook do wysyłki email
MAKE_WEBHOOK_SEND_EMAIL_REQUEST = os.environ.get("MAKE_WEBHOOK_SEND_EMAIL_REQUEST", "")
RENDER_EMAIL_KEY_SEND_REQUEST = os.environ.get("RENDER_EMAIL_KEY_SEND_REQUEST", "")

# Email wewnętrzny - info techniczne o błędach
BACKSTAGE_TECHNICAL_INFO_EMAIL = os.environ.get("BACKSTAGE_TECHNICAL_INFO_EMAIL", "")
# Email wewnętrzny - powiadomienia o zamówieniach/płatnościach (nie błędy)
BACKSTAGE_EVENT_INFO_EMAIL = os.environ.get("BACKSTAGE_EVENT_INFO_EMAIL", "")


# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------

def _log(level: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
    """Loguje wiadomość z timestampem i opcjonalnymi danymi."""
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[{ts}] [BACKSTAGE] [{level}]"
    if data:
        # Skróć długie wartości
        safe_data = {}
        for k, v in data.items():
            if isinstance(v, str) and len(v) > 200:
                safe_data[k] = v[:200] + "..."
            elif isinstance(v, dict) and len(str(v)) > 500:
                safe_data[k] = f"<dict with {len(v)} keys>"
            else:
                safe_data[k] = v
        print(f"{prefix} {message} | {json.dumps(safe_data, ensure_ascii=False, default=str)}")
    else:
        print(f"{prefix} {message}")


# ---------------------------------------------------------------------------
# MAKE.COM EMAIL WEBHOOK
# ---------------------------------------------------------------------------

def _is_make_email_configured() -> bool:
    """Sprawdza czy Make webhook do wysyłki email jest skonfigurowany."""
    return bool(MAKE_WEBHOOK_SEND_EMAIL_REQUEST and RENDER_EMAIL_KEY_SEND_REQUEST)


def _send_email_via_make(
    to_email: str,
    subject: str,
    body_html: str,
    event_order_id: str = "",
    template_type: str = "",
    stripe_url: str = "",
    extra_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Wysyła email przez webhook Make.com.
    
    Args:
        to_email: Adres odbiorcy
        subject: Temat
        body_html: Treść HTML
        event_order_id: ID zamówienia
        template_type: Typ szablonu (stripe_payment_link, etc.)
        stripe_url: URL płatności Stripe (opcjonalnie)
        extra_data: Dodatkowe dane do przekazania
    
    Returns:
        Dict z status, error, etc.
    """
    if not _is_make_email_configured():
        _log("ERROR", "Make webhook nie skonfigurowany (brak MAKE_WEBHOOK_SEND_EMAIL_REQUEST lub RENDER_EMAIL_KEY_SEND_REQUEST)")
        return {
            "success": False,
            "error": "Make webhook nie skonfigurowany",
        }
    
    _log("INFO", "Wysyłam email przez Make webhook", {"to": to_email, "subject": subject})
    
    try:
        payload = {
            "to": to_email,
            "subject": subject,
            "body_html": body_html,
            "event_order_id": event_order_id,
            "template_type": template_type,
            "stripe_url": stripe_url,
            **(extra_data or {}),
        }
        
        headers = {
            "Content-Type": "application/json",
            "x-make-apikey": RENDER_EMAIL_KEY_SEND_REQUEST,
        }
        
        _log("DEBUG", f"POST {MAKE_WEBHOOK_SEND_EMAIL_REQUEST[:50]}...")
        
        response = requests.post(
            MAKE_WEBHOOK_SEND_EMAIL_REQUEST,
            json=payload,
            headers=headers,
            timeout=30,
        )
        
        _log("DEBUG", f"Make response: {response.status_code}", {"body": response.text[:200] if response.text else ""})
        
        if response.status_code in (200, 201, 202):
            _log("INFO", "Email wysłany przez Make pomyślnie!", {"to": to_email})
            return {
                "success": True,
                "message": f"Email wysłany przez Make do {to_email}",
                "to": to_email,
                "subject": subject,
                "make_response": response.text[:500] if response.text else "",
            }
        else:
            error_msg = f"Make webhook zwrócił {response.status_code}: {response.text[:200]}"
            _log("ERROR", error_msg)
            return {
                "success": False,
                "error": error_msg,
            }
            
    except requests.Timeout:
        _log("ERROR", "Timeout przy wywołaniu Make webhook")
        return {
            "success": False,
            "error": "Timeout przy wywołaniu Make webhook (30s)",
        }
    except Exception as e:
        _log("ERROR", f"Błąd przy wywołaniu Make webhook: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def _send_error_notification(
    error_type: str,
    error_message: str,
    event_order_id: str = "",
    event_id: str = "",
    extra_data: Optional[Dict[str, Any]] = None,
    # Kompatybilność wsteczna (w kodzie były wywołania z event_name/extra_context)
    event_name: str = "",
    extra_context: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Wysyła email wewnętrzny o błędzie.
    
    Args:
        error_type: Typ błędu (np. "EVENT_NOT_FOUND", "TICKET_NOT_FOUND", "EMAIL_ERROR")
        error_message: Szczegółowy opis błędu
        event_order_id: ID zamówienia
        event_id: ID wydarzenia
        extra_data: Dodatkowe dane do wyświetlenia
    """
    if not BACKSTAGE_TECHNICAL_INFO_EMAIL:
        _log("WARN", f"Brak BACKSTAGE_TECHNICAL_INFO_EMAIL - nie wysłano powiadomienia o błędzie: {error_type}")
        return
    
    if not _is_make_email_configured():
        _log("WARN", f"Make webhook nie skonfigurowany - nie wysłano powiadomienia o błędzie: {error_type}")
        return
    
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Kompatybilność: scal extra_context -> extra_data
    if extra_context:
        if extra_data:
            merged = dict(extra_data)
            merged.update(extra_context)
            extra_data = merged
        else:
            extra_data = dict(extra_context)
    if event_name:
        # ułatwia czytanie alertu; nie nadpisuj jeśli już jest
        if extra_data is None:
            extra_data = {"event_name": event_name}
        elif "event_name" not in extra_data:
            extra_data["event_name"] = event_name

    # Przygotuj dodatkowe dane jako HTML
    extra_html = ""
    if extra_data:
        extra_items = []
        for k, v in extra_data.items():
            val_str = str(v)[:500] if len(str(v)) > 500 else str(v)
            extra_items.append(f"<li><strong>{k}:</strong> {val_str}</li>")
        extra_html = f"<ul>{''.join(extra_items)}</ul>"
    
    subject = f"[ERROR] {error_type} – Backstage Engine"
    body_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color: #dc3545;">🚨 Błąd w Backstage Engine</h2>
        <p><strong>Typ błędu:</strong> {error_type}</p>
        <p><strong>Czas:</strong> {ts}</p>
        <hr>
        <p><strong>Zamówienie:</strong> {event_order_id or "(brak)"}</p>
        <p><strong>Event ID:</strong> {event_id or "(brak)"}</p>
        <hr>
        <p><strong>Komunikat błędu:</strong></p>
        <pre style="background: #f8f9fa; padding: 10px; border-radius: 4px; overflow-x: auto;">{error_message}</pre>
        {f'<hr><p><strong>Dodatkowe dane:</strong></p>{extra_html}' if extra_html else ''}
        <hr>
        <p style="color: #666; font-size: 12px;">Email wygenerowany automatycznie przez Backstage Engine (Render).</p>
    </body>
    </html>
    """
    
    _log("INFO", f"Wysyłam powiadomienie o błędzie: {error_type}", {"to": BACKSTAGE_TECHNICAL_INFO_EMAIL})
    
    try:
        payload = {
            "to": BACKSTAGE_TECHNICAL_INFO_EMAIL,
            "subject": subject,
            "body_html": body_html,
            "event_order_id": event_order_id,
            "template_type": f"error_{error_type.lower()}",
        }
        
        headers = {
            "Content-Type": "application/json",
            "x-make-apikey": RENDER_EMAIL_KEY_SEND_REQUEST,
        }
        
        response = requests.post(
            MAKE_WEBHOOK_SEND_EMAIL_REQUEST,
            json=payload,
            headers=headers,
            timeout=15,
        )
        
        if response.status_code in (200, 202):
            _log("INFO", f"Powiadomienie o błędzie wysłane | status={response.status_code}")
        else:
            _log("ERROR", f"Błąd wysyłki powiadomienia: {response.status_code} | {response.text[:200]}")
            
    except Exception as e:
        _log("ERROR", f"Wyjątek przy wysyłce powiadomienia o błędzie: {e}")


def send_participant_ticket_emails(
    event_order_id: str,
    event_name: str,
    event_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Wysyła emaile z biletami do WSZYSTKICH uczestników zamówienia.
    
    Każdy uczestnik dostaje swój indywidualny email z informacją o swoim bilecie:
    - nazwa/typ biletu
    - cena
    - ewentualne zniżki
    - szczegóły wydarzenia
    
    Args:
        event_order_id: ID zamówienia
        event_name: Nazwa wydarzenia
        event_config: Konfiguracja wydarzenia (kolory, banery, etc.)
    
    Returns:
        Dict z statystykami: {"sent": X, "failed": Y, "skipped": Z, "details": [...]}
    """
    from pg_storage import get_participants_for_order, get_ticket_classes, update_participant_status
    from email_templates import render_participant_ticket_email
    
    stats = {"sent": 0, "failed": 0, "skipped": 0, "details": []}
    
    # Pobierz uczestników
    participants = get_participants_for_order(event_order_id)
    if not participants:
        _log("INFO", "Brak uczestników do wysłania emaili", {"event_order_id": event_order_id})
        return stats
    
    _log("INFO", "Rozpoczynam wysyłkę emaili do uczestników", {
        "event_order_id": event_order_id,
        "participants_count": len(participants),
    })
    
    # Pobierz nazwy biletów
    ticket_name_map = {}
    if participants:
        # Znajdź event_id z pierwszego uczestnika (z data lub z order)
        try:
            order = get_order(event_order_id)
            event_id = order.get("event_id", "") if order else ""
            if event_id:
                ticket_classes = get_ticket_classes(event_id)
                ticket_name_map = {tc["ticket_class_id"]: tc["ticket_name"] for tc in ticket_classes}
                _log("DEBUG", "Mapa nazw biletów dla uczestników", {"count": len(ticket_name_map)})
        except Exception as e:
            _log("WARNING", f"Nie udało się pobrać nazw biletów: {e}")
    
    for p in participants:
        participant_email = p.get("email", "")
        participant_first_name = p.get("first_name", "")
        participant_last_name = p.get("last_name", "")
        ticket_id = p.get("ticket_id", "")
        ticket_class_id = p.get("ticket_class_id", "")
        participant_data = p.get("data", {}) or {}
        participant_id = p.get("id")
        status = p.get("status", "")
        
        # Pomiń jeśli brak emaila lub status cancelled
        if not participant_email:
            _log("DEBUG", "Pomijam uczestnika bez emaila", {"ticket_id": ticket_id})
            stats["skipped"] += 1
            stats["details"].append({"ticket_id": ticket_id, "status": "skipped", "reason": "no_email"})
            continue
        
        if status == "cancelled":
            _log("DEBUG", "Pomijam anulowanego uczestnika", {"ticket_id": ticket_id, "email": participant_email})
            stats["skipped"] += 1
            stats["details"].append({"ticket_id": ticket_id, "status": "skipped", "reason": "cancelled"})
            continue
        
        if status == "emailed":
            _log("DEBUG", "Uczestnik już otrzymał email", {"ticket_id": ticket_id, "email": participant_email})
            stats["skipped"] += 1
            stats["details"].append({"ticket_id": ticket_id, "status": "skipped", "reason": "already_emailed"})
            continue
        
        # Pobierz dane biletu
        ticket_name = (
            ticket_name_map.get(ticket_class_id)
            or participant_data.get("ticket_name")
            or "Bilet"
        )
        ticket_price = participant_data.get("price_gross", 0)
        discount_amount = participant_data.get("discount_amount", 0)
        
        # Renderuj email
        try:
            body_html = render_participant_ticket_email(
                event_name=event_name,
                participant_first_name=participant_first_name,
                participant_last_name=participant_last_name,
                participant_email=participant_email,
                ticket_name=ticket_name,
                ticket_id=ticket_id,
                ticket_price=float(ticket_price) if ticket_price else 0.0,
                discount_amount=float(discount_amount) if discount_amount else 0.0,
                event_config=event_config,
            )
        except Exception as e:
            _log("ERROR", f"Błąd renderowania emaila uczestnika: {e}", {"ticket_id": ticket_id})
            stats["failed"] += 1
            stats["details"].append({"ticket_id": ticket_id, "email": participant_email, "status": "failed", "error": str(e)})
            continue
        
        # Wyślij email
        subject = f"Twój bilet – {event_name}"
        
        _log("INFO", "Wysyłam email do uczestnika", {
            "to": participant_email,
            "ticket_name": ticket_name,
            "ticket_id": ticket_id[:20] + "..." if len(ticket_id) > 20 else ticket_id,
        })
        
        result = _send_email_via_make(
            to_email=participant_email,
            subject=subject,
            body_html=body_html,
            event_order_id=event_order_id,
            template_type="participant_ticket",
        )
        
        if result.get("success"):
            stats["sent"] += 1
            stats["details"].append({"ticket_id": ticket_id, "email": participant_email, "status": "sent"})
            
            # Zaktualizuj status uczestnika na 'emailed'
            if participant_id:
                try:
                    update_participant_status(participant_id, "emailed")
                except Exception:
                    pass
        else:
            stats["failed"] += 1
            stats["details"].append({
                "ticket_id": ticket_id,
                "email": participant_email,
                "status": "failed",
                "error": result.get("error", "Unknown error"),
            })
            _log("WARNING", "Nie udało się wysłać emaila do uczestnika", {
                "email": participant_email,
                "error": result.get("error"),
            })
    
    _log("INFO", "Zakończono wysyłkę emaili do uczestników", {
        "event_order_id": event_order_id,
        "sent": stats["sent"],
        "failed": stats["failed"],
        "skipped": stats["skipped"],
    })
    
    return stats


from pg_storage import (
    get_event,
    match_payment_rule,
    save_backstage_webhook,
    mark_backstage_webhook_processed,
    upsert_order,
    update_order_status,
    get_order,
    save_stripe_session,
    save_wfirma_document,
    save_mail_log,
)


# ---------------------------------------------------------------------------
# FLOW TYPES
# ---------------------------------------------------------------------------
FLOW_FOC = "FOC"          # Free of Charge (total=0, tylko mail)
FLOW_PROFORMA = "PROFORMA"  # Proforma wFirma + czekamy na przelew
FLOW_STRIPE = "STRIPE"      # Stripe checkout session


# ---------------------------------------------------------------------------
# MAIL TASK TEMPLATES
# ---------------------------------------------------------------------------
# Klucze szablonów odpowiadają plikom w katalogu HTML/ lub nazwie w Make.com
TEMPLATE_REGISTRATION_CONFIRMATION = "registration_confirmation"
TEMPLATE_PROFORMA_SENT = "proforma_sent"
TEMPLATE_STRIPE_PAYMENT_LINK = "stripe_payment_link"
TEMPLATE_PAYMENT_CONFIRMATION = "payment_confirmation"
TEMPLATE_INTERNAL_ORDER_RECEIVED = "internal_order_received"
TEMPLATE_INTERNAL_ORDER_PAID = "internal_order_paid"


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------


def _generate_dedupe_key(event_order_id: str, event_id: str) -> str:
    """Generuje klucz deduplikacji dla webhooka."""
    raw = f"{event_order_id}:{event_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _extract_order_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Wyciąga dane zamówienia z payloadu Backstage.
    Obsługuje różne warianty struktury (raw/nested/flat).
    """
    # Backstage wysyła dane w różnych formatach - próbujemy kilka ścieżek
    raw = payload.get("raw") or payload

    # event_order_id
    event_order_id = (
        raw.get("event_order_id")
        or raw.get("eventOrder_id")
        or raw.get("eventOrderId")
        or payload.get("event_order_id")
        or ""
    )

    # event_id - Backstage używa "events" lub "eventOrder_eventId"
    event_id = (
        raw.get("event_id")
        or raw.get("eventId")
        or raw.get("events")  # Backstage format
        or raw.get("eventOrder_eventId")  # Backstage format
        or raw.get("event", {}).get("id")
        or payload.get("event_id")
        or payload.get("events")
        or ""
    )

    # sandbox - czy to test
    # Jeśli pole sandbox istnieje i ma jakąkolwiek wartość (nawet "{$sandbox}"), to sandbox = True
    sandbox_raw = payload.get("sandbox") or raw.get("sandbox")
    if sandbox_raw is None or sandbox_raw == "" or sandbox_raw is False:
        sandbox = False
    elif isinstance(sandbox_raw, bool):
        sandbox = sandbox_raw
    elif isinstance(sandbox_raw, str) and sandbox_raw.lower() in ("false", "0", "no"):
        sandbox = False
    else:
        sandbox = True  # Każda inna wartość = sandbox mode
    _log("DEBUG", "Sandbox mode", {"sandbox": sandbox, "sandbox_raw": sandbox_raw})

    # Pobierz dane z buyer_details lub customFormData (Backstage format)
    buyer_details = payload.get("buyer_details") or raw.get("buyer_details") or []
    custom_form_data = payload.get("customFormData") or raw.get("customFormData") or []
    
    buyer_form = {}
    # Próbuj buyer_details najpierw
    if buyer_details and isinstance(buyer_details, list) and len(buyer_details) > 0:
        buyer_form = buyer_details[0].get("formEntries") or {}
        _log("DEBUG", "Znaleziono buyer_details", {"buyer_form_keys": list(buyer_form.keys()) if buyer_form else []})
    # Fallback na customFormData
    elif custom_form_data and isinstance(custom_form_data, list) and len(custom_form_data) > 0:
        buyer_form = custom_form_data[0].get("formEntries") or {}
        _log("DEBUG", "Znaleziono customFormData", {"buyer_form_keys": list(buyer_form.keys()) if buyer_form else []})

    # purchaser info - próbuj z różnych źródeł
    purchaser_email = (
        payload.get("purchaser_email")  # Top level w webhook
        or raw.get("purchaser_email")
        or raw.get("purchaserEmail")
        or buyer_form.get("purchaser_email")
        or raw.get("eventOrder_orderBy")  # Backstage: email zamawiającego
        or payload.get("eventOrder_orderBy")  # Może być na top level
        or ""
    )
    purchaser_first_name = (
        raw.get("purchaser_first_name")
        or raw.get("purchaserFirstName")
        or buyer_form.get("purchaser_first_name")
        or payload.get("purchaser_first_name")
        or raw.get("userProfile_name")  # Backup: Backstage userProfile
        or payload.get("userProfile_name")
        or ""
    )
    purchaser_last_name = (
        raw.get("purchaser_last_name")
        or raw.get("purchaserLastName")
        or buyer_form.get("purchaser_last_name")
        or payload.get("purchaser_last_name")
        or raw.get("userProfile_lastName")  # Backup: Backstage userProfile
        or payload.get("userProfile_lastName")
        or ""
    )
    purchaser_phone = (
        raw.get("purchaser_phone")
        or raw.get("purchaserPhone")
        or buyer_form.get("purchaser_mobile_no")  # Backstage format
        or buyer_form.get("purchaser_phone")
        or payload.get("purchaser_phone")
        or raw.get("userProfile_telephone")  # Backup: Backstage userProfile
        or payload.get("userProfile_telephone")
        or ""
    )

    # NIP - może być w custom fields lub buyer_form
    purchaser_nip = (
        raw.get("purchaser_nip")
        or raw.get("nip")
        or raw.get("NIP")
        or raw.get("tax_registration_no")  # Backstage format
        or buyer_form.get("nip")
        or buyer_form.get("NIP")
        or buyer_form.get("purchaser_nip")
        or buyer_form.get("tax_registration_no")  # Backstage format!
        or ""
    )
    # Szukaj NIP w custom fields jeśli nie znaleziono
    custom_fields = raw.get("custom_fields") or raw.get("customFields") or {}
    if not purchaser_nip and isinstance(custom_fields, dict):
        for k, v in custom_fields.items():
            if "nip" in k.lower() and v:
                purchaser_nip = str(v).strip()
                break
    # Szukaj też w buyer_form
    if not purchaser_nip and isinstance(buyer_form, dict):
        for k, v in buyer_form.items():
            if "nip" in k.lower() and v:
                purchaser_nip = str(v).strip()
                break

    # payment info
    payment_option_name = (
        raw.get("eventOrder_paymentOptionName")
        or payload.get("eventOrder_paymentOptionName")
        or raw.get("payment_option_name")
        or raw.get("paymentOptionName")
        or ""
    )
    payment_type_raw = (
        raw.get("eventOrder_paymentType")
        or payload.get("eventOrder_paymentType")
        or raw.get("payment_type")
        or raw.get("paymentType")
    )
    payment_type = int(payment_type_raw) if payment_type_raw is not None else None

    # total / kwota - może być na top level lub w raw
    total_raw = (
        payload.get("total")  # Top level w webhook
        or raw.get("total")
        or raw.get("orderCost_grandTotal")  # Backstage format
        or payload.get("orderCost_grandTotal")  # Może być na top level
        or raw.get("eventOrder_total")
        or raw.get("order_total")
        or 0
    )
    try:
        total = float(total_raw)
    except (ValueError, TypeError):
        total = 0.0

    # promo code
    promo_code = (
        raw.get("promo_code")
        or raw.get("promoCode")
        or raw.get("eventOrder_promoCode")
        or raw.get("orderCost_promoCode")  # Backstage format
        or payload.get("orderCost_promoCode")  # Może być na top level
        or ""
    )

    # currency
    currency = (
        raw.get("currency")
        or raw.get("eventOrder_currency")
        or payload.get("currency")
        or "PLN"
    )

    # Billing address - dane rozliczeniowe
    billing_address = raw.get("eventOrder_billingAddress") or payload.get("billing") or {}
    billing_street = (
        billing_address.get("streetAddress1") or 
        billing_address.get("street") or 
        billing_address.get("address") or
        "-"
    )
    billing_zip = (
        billing_address.get("zipcode") or 
        billing_address.get("zip") or 
        billing_address.get("postalCode") or
        "00-000"
    )
    billing_city = (
        billing_address.get("city") or 
        billing_address.get("town") or
        "-"
    )

    # Ekstrakcja biletów z payload
    tickets = _extract_tickets_from_payload(payload)

    return {
        "event_order_id": str(event_order_id).strip(),
        "event_id": str(event_id).strip(),
        "purchaser_email": str(purchaser_email).strip(),
        "purchaser_first_name": str(purchaser_first_name).strip(),
        "purchaser_last_name": str(purchaser_last_name).strip(),
        "purchaser_phone": str(purchaser_phone).strip(),
        "purchaser_nip": str(purchaser_nip).strip(),
        "billing_address": str(billing_street).strip(),
        "billing_zip": str(billing_zip).strip(),
        "billing_city": str(billing_city).strip(),
        "payment_option_name": str(payment_option_name).strip(),
        "payment_type": payment_type,
        "total": total,
        "promo_code": str(promo_code).strip(),
        "currency": str(currency).strip().upper() or "PLN",
        "sandbox": sandbox,
        "tickets": tickets,
    }


def _extract_tickets_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Ekstrahuje listę biletów z payloadu Backstage.
    Zwraca listę słowników z name, quantity, unit_price, total_price, vat_rate.
    """
    raw = payload.get("raw") or payload
    
    # Próbuj różne źródła biletów
    tickets_raw = (
        payload.get("tickets") or 
        raw.get("orderTickets") or 
        raw.get("tickets") or 
        []
    )
    
    if not tickets_raw or not isinstance(tickets_raw, list):
        return []
    
    tickets = []
    for idx, t in enumerate(tickets_raw):
        # Backstage format
        ticket_class_id = t.get("ticketClass") or t.get("ticket_class_id") or ""
        # Ceny mogą być wprost na obiekcie biletu albo w lineItemPayments[0]
        line_item = None
        try:
            lip = t.get("lineItemPayments")
            if isinstance(lip, list) and lip:
                line_item = lip[0] if isinstance(lip[0], dict) else None
        except Exception:
            line_item = None

        # Preferuj kwoty z lineItemPayments (są najbardziej wiarygodne)
        unit_gross_raw = (
            (line_item or {}).get("totalAmount")
            or t.get("totalPrice")
            or t.get("total_price")
            or None
        )
        unit_net_raw = (
            (line_item or {}).get("itemPrice")
            or (line_item or {}).get("actualPrice")
            or t.get("ticketPrice")
            or t.get("actualTicketPrice")
            or t.get("price")
            or 0
        )
        tax_percent_raw = (line_item or {}).get("taxPercent")
        tax_amount_raw = (line_item or {}).get("taxAmount")
        discount_amount_raw = (line_item or {}).get("discountAmount") if line_item else (t.get("discountAmount") or t.get("discount"))

        try:
            unit_net = float(unit_net_raw or 0)
        except (ValueError, TypeError):
            unit_net = 0.0

        # VAT amount / gross
        try:
            vat_amount = float(tax_amount_raw if tax_amount_raw is not None else (t.get("taxedPrice") or t.get("vat_amount") or 0))
        except (ValueError, TypeError):
            vat_amount = 0.0

        try:
            discount_amount = float(discount_amount_raw) if discount_amount_raw is not None else 0.0
        except (ValueError, TypeError):
            discount_amount = 0.0

        try:
            vat_rate = float(tax_percent_raw) if tax_percent_raw is not None else 23.0
        except (ValueError, TypeError):
            vat_rate = 23.0

        # Gross unit: jeśli totalAmount jest podane (na 1 bilet), użyj go; w przeciwnym razie wylicz z netto+VAT
        if unit_gross_raw is not None:
            try:
                unit_gross = float(unit_gross_raw)
            except (ValueError, TypeError):
                unit_gross = 0.0
        else:
            if vat_rate and vat_rate > 0:
                unit_gross = round(unit_net * (1 + (vat_rate / 100.0)), 2)
            else:
                unit_gross = unit_net

        total_price = unit_gross  # 1 rekord = 1 bilet w Backstage
        
        # Jeśli nie było taxPercent, spróbuj wyliczyć z kwot (fallback)
        if (tax_percent_raw is None) and unit_net > 0 and vat_amount > 0:
            try:
                vat_rate = round((vat_amount / unit_net) * 100)
            except Exception:
                vat_rate = 23.0
        
        # Pobierz nazwę biletu - najpierw z ticket class, potem domyślna
        ticket_name = t.get("ticketName") or t.get("ticket_name") or f"Bilet ({ticket_class_id[:8]}...)" if ticket_class_id else "Bilet"
        
        tickets.append({
            "ticket_class_id": str(ticket_class_id),
            "name": ticket_name,
            "quantity": 1,  # Każdy rekord to 1 bilet w Backstage
            "unit_price_net": round(unit_net, 2),
            "unit_price_gross": round(unit_gross, 2),
            "total_gross": total_price,
            "vat_rate": vat_rate,
            "vat_amount": vat_amount,
            "discount_amount": round(discount_amount, 2),
        })

        # Szczegółowe logi cenowe (limituj, żeby nie zalać logów)
        if idx < 20:
            _log("DEBUG", "TICKET RAW->CALC", {
                "idx": idx,
                "ticket_class_id": str(ticket_class_id),
                "ticket_name": ticket_name,
                "has_lineItemPayments": bool(line_item),
                "src_totalAmount": (line_item or {}).get("totalAmount") if line_item else None,
                "src_itemPrice": (line_item or {}).get("itemPrice") if line_item else None,
                "src_actualPrice": (line_item or {}).get("actualPrice") if line_item else None,
                "src_taxPercent": (line_item or {}).get("taxPercent") if line_item else None,
                "src_taxAmount": (line_item or {}).get("taxAmount") if line_item else None,
                "src_discountAmount": (line_item or {}).get("discountAmount") if line_item else t.get("discountAmount"),
                "src_ticketPrice": t.get("ticketPrice"),
                "src_actualTicketPrice": t.get("actualTicketPrice"),
                "calc_unit_net": round(unit_net, 2),
                "calc_unit_gross": round(unit_gross, 2),
                "calc_vat_rate": vat_rate,
                "calc_vat_amount": round(vat_amount, 2),
                "calc_discount_amount": round(discount_amount, 2),
            })
    
    # Agreguj bilety o tym samym ticket_class_id
    aggregated = {}
    for t in tickets:
        key = t["ticket_class_id"]
        if key in aggregated:
            aggregated[key]["quantity"] += 1
            aggregated[key]["total_gross"] += t["total_gross"]
            aggregated[key]["vat_amount"] += t["vat_amount"]
            aggregated[key]["discount_amount"] += t.get("discount_amount", 0)
        else:
            aggregated[key] = t.copy()

    aggregated_list = list(aggregated.values())
    try:
        # Podsumowanie po agregacji (też limitowane)
        preview = []
        for a in aggregated_list[:10]:
            preview.append({
                "ticket_class_id": a.get("ticket_class_id"),
                "name": a.get("name"),
                "quantity": a.get("quantity"),
                "unit_price_gross": a.get("unit_price_gross"),
                "unit_price_net": a.get("unit_price_net"),
                "total_gross": round(float(a.get("total_gross") or 0), 2),
                "vat_rate": a.get("vat_rate"),
                "vat_amount": round(float(a.get("vat_amount") or 0), 2),
                "discount_amount": round(float(a.get("discount_amount") or 0), 2),
            })
        _log("DEBUG", "TICKETS EXTRACTED (aggregated)", {
            "tickets_raw_count": len(tickets_raw) if isinstance(tickets_raw, list) else None,
            "tickets_items_count": len(tickets),
            "tickets_aggregated_count": len(aggregated_list),
            "preview_first": preview,
        })
    except Exception:
        pass

    return aggregated_list


def _extract_individual_tickets_for_participants(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Ekstrahuje INDYWIDUALNE bilety (nie zagregowane) z payloadu Backstage.
    Każdy bilet ma swój unikalny ticket_id - potrzebne do przypisania uczestników.
    
    Zwraca listę: [{ticket_id, ticket_class_id, ticket_name, price, ...}]
    """
    raw = payload.get("raw") or payload
    
    tickets_raw = (
        payload.get("tickets") or 
        raw.get("orderTickets") or 
        raw.get("tickets") or 
        []
    )
    
    if not tickets_raw or not isinstance(tickets_raw, list):
        return []
    
    individual_tickets = []
    for t in tickets_raw:
        ticket_id = t.get("ticketId") or t.get("ticket_id") or t.get("id") or ""
        ticket_class_id = t.get("ticketClass") or t.get("ticket_class_id") or ""
        ticket_name = t.get("ticketName") or t.get("ticket_name") or ""
        
        # Cena z lineItemPayments lub bezpośrednio
        line_item = None
        try:
            lip = t.get("lineItemPayments")
            if isinstance(lip, list) and lip:
                line_item = lip[0] if isinstance(lip[0], dict) else None
        except Exception:
            pass
        
        price_gross = 0.0
        price_net = 0.0
        discount = 0.0
        try:
            if line_item:
                price_gross = float(line_item.get("totalAmount") or 0)
                price_net = float(line_item.get("itemPrice") or line_item.get("actualPrice") or 0)
                discount = float(line_item.get("discountAmount") or 0)
            else:
                price_gross = float(t.get("totalPrice") or 0)
                price_net = float(t.get("ticketPrice") or t.get("actualTicketPrice") or 0)
                discount = float(t.get("discount") or t.get("discountAmount") or 0)
        except (ValueError, TypeError):
            pass
        
        individual_tickets.append({
            "ticket_id": str(ticket_id),
            "ticket_class_id": str(ticket_class_id),
            "ticket_name": ticket_name,
            "price_gross": round(price_gross, 2),
            "price_net": round(price_net, 2),
            "discount_amount": round(discount, 2),
            "promo_code": t.get("promoCode") or "",
            "raw": t,  # Zachowaj surowe dane
        })
    
    return individual_tickets


def _extract_attendees_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Ekstrahuje dane uczestników z payloadu Backstage.
    Zwraca listę uczestników z ich danymi.
    
    Struktura attendee w Backstage (gdy wypełnione):
    - ticketId: ID biletu
    - email, firstName, lastName, phone
    - formEntries: dodatkowe pola formularza
    """
    raw = payload.get("raw") or payload
    attendees_raw = raw.get("attendees") or payload.get("attendees") or []
    
    if not attendees_raw or not isinstance(attendees_raw, list):
        return []
    
    attendees = []
    for a in attendees_raw:
        ticket_id = a.get("ticketId") or a.get("ticket_id") or a.get("orderTicketId") or ""
        
        # Dane mogą być bezpośrednio lub w formEntries
        form_entries = a.get("formEntries") or {}
        
        attendees.append({
            "ticket_id": str(ticket_id),
            "email": a.get("email") or form_entries.get("email") or form_entries.get("attendee_email") or "",
            "first_name": a.get("firstName") or a.get("first_name") or form_entries.get("firstName") or form_entries.get("first_name") or form_entries.get("attendee_first_name") or "",
            "last_name": a.get("lastName") or a.get("last_name") or form_entries.get("lastName") or form_entries.get("last_name") or form_entries.get("attendee_last_name") or "",
            "phone": a.get("phone") or a.get("mobile") or form_entries.get("phone") or form_entries.get("mobile") or form_entries.get("attendee_phone") or "",
            "raw": a,
        })
    
    return attendees


def _save_participants_for_order(
    event_order_id: str,
    purchaser_data: Dict[str, Any],
    individual_tickets: List[Dict[str, Any]],
    attendees: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Zapisuje uczestników dla zamówienia.
    
    Logika:
    1. Dla każdego biletu tworzy slot uczestnika
    2. Jeśli są dane attendee dla biletu - wypełnia je
    3. Jeśli tylko 1 bilet i brak attendees - przypisuje purchasera
    4. W przeciwnym razie - status 'pending' (do wypełnienia)
    
    Zwraca: {"saved": int, "pending": int, "registered": int}
    """
    from pg_storage import save_participant
    
    stats = {"saved": 0, "pending": 0, "registered": 0}
    
    # Mapuj attendees po ticket_id
    attendee_by_ticket = {}
    for att in attendees:
        tid = att.get("ticket_id")
        if tid:
            attendee_by_ticket[tid] = att
    
    purchaser_email = purchaser_data.get("purchaser_email", "")
    purchaser_first = purchaser_data.get("purchaser_first_name", "")
    purchaser_last = purchaser_data.get("purchaser_last_name", "")
    purchaser_phone = purchaser_data.get("purchaser_phone", "")
    
    for i, ticket in enumerate(individual_tickets):
        ticket_id = ticket.get("ticket_id", "")
        ticket_class_id = ticket.get("ticket_class_id", "")
        
        if not ticket_id:
            continue
        
        # Sprawdź czy mamy dane attendee dla tego biletu
        attendee = attendee_by_ticket.get(ticket_id)
        
        if attendee and attendee.get("email"):
            # Mamy dane uczestnika
            participant_id = save_participant(
                event_order_id=event_order_id,
                ticket_id=ticket_id,
                ticket_class_id=ticket_class_id,
                email=attendee.get("email", ""),
                first_name=attendee.get("first_name", ""),
                last_name=attendee.get("last_name", ""),
                phone=attendee.get("phone", ""),
                status="registered",
                data={
                    "ticket_name": ticket.get("ticket_name", ""),
                    "price_gross": ticket.get("price_gross", 0),
                    "source": "attendee_data",
                },
            )
            if participant_id:
                stats["saved"] += 1
                stats["registered"] += 1
        elif purchaser_email and not attendees:
            # Brak danych attendees - przypisz purchasera do WSZYSTKICH biletów
            # (purchaser może być uczestnikiem wszystkich biletów, lub dane zostaną
            # zaktualizowane później przez webhook "Attendee registered for event")
            participant_id = save_participant(
                event_order_id=event_order_id,
                ticket_id=ticket_id,
                ticket_class_id=ticket_class_id,
                email=purchaser_email,
                first_name=purchaser_first,
                last_name=purchaser_last,
                phone=purchaser_phone,
                status="registered",
                data={
                    "ticket_name": ticket.get("ticket_name", ""),
                    "price_gross": ticket.get("price_gross", 0),
                    "source": "purchaser_fallback",  # Może być zaktualizowane przez attendee webhook
                    "ticket_index": i,
                },
            )
            if participant_id:
                stats["saved"] += 1
                stats["registered"] += 1
        else:
            # Brak danych purchasera i attendees - slot do wypełnienia
            participant_id = save_participant(
                event_order_id=event_order_id,
                ticket_id=ticket_id,
                ticket_class_id=ticket_class_id,
                email="",
                first_name="",
                last_name="",
                phone="",
                status="pending",
                data={
                    "ticket_name": ticket.get("ticket_name", ""),
                    "price_gross": ticket.get("price_gross", 0),
                    "source": "pending_slot",
                },
            )
            if participant_id:
                stats["saved"] += 1
                stats["pending"] += 1
    
    return stats


def _enrich_tickets_with_names(tickets: List[Dict[str, Any]], event_id: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Wzbogaca bilety o nazwy z bazy danych (event_ticket_classes).
    
    Args:
        tickets: Lista biletów z _extract_tickets_from_payload
        event_id: ID wydarzenia
    
    Returns:
        (wzbogacone_bilety, lista_nieznanych_ticket_class_id)
    """
    if not tickets or not event_id:
        return tickets, []
    
    # Pobierz mapowanie ticket_class_id -> ticket_name z bazy
    try:
        from pg_storage import get_ticket_classes
        ticket_classes = get_ticket_classes(event_id)
        
        # Zbuduj słownik mapowania
        name_map = {}
        for tc in ticket_classes:
            tc_id = tc.get("ticket_class_id", "")
            tc_name = tc.get("ticket_name", "")
            if tc_id and tc_name:
                name_map[tc_id] = tc_name
        
        _log("DEBUG", "Mapowanie nazw biletów", {
            "event_id": event_id,
            "ticket_classes_count": len(ticket_classes),
            "name_map_count": len(name_map),
        })
        
    except Exception as e:
        _log("WARNING", "Błąd pobierania ticket_classes z bazy", {"error": str(e)})
        return tickets, []
    
    # Wzbogać bilety o nazwy
    enriched = []
    unknown_ids = []
    
    for t in tickets:
        ticket_class_id = t.get("ticket_class_id", "")
        enriched_ticket = t.copy()
        
        if ticket_class_id in name_map:
            # Znaleziono w bazie - użyj nazwy z bazy
            enriched_ticket["name"] = name_map[ticket_class_id]
            enriched_ticket["unknown"] = False
        else:
            # Nie znaleziono - zachowaj oryginalną nazwę, oznacz jako nieznany
            if ticket_class_id and ticket_class_id not in unknown_ids:
                unknown_ids.append(ticket_class_id)
            enriched_ticket["unknown"] = True
            # Popraw nazwę jeśli to tylko ID
            if enriched_ticket.get("name", "").startswith("Bilet ("):
                enriched_ticket["name"] = f"Bilet (nierozpoznany: {ticket_class_id[:12]}...)"
        
        enriched.append(enriched_ticket)
    
    if unknown_ids:
        _log("WARNING", "Nierozpoznane bilety", {
            "event_id": event_id,
            "unknown_count": len(unknown_ids),
            "unknown_ids": unknown_ids[:5],  # Pierwsze 5
        })
    
    return enriched, unknown_ids


def _build_invoice_positions(tickets: List[Dict[str, Any]], event_name: str = "") -> List[Dict[str, Any]]:
    """
    Buduje pozycje faktury z listy biletów.
    Format zgodny z wFirma API.
    """
    if not tickets:
        # Jeśli brak biletów, użyj jednej pozycji z nazwą wydarzenia
        return [{
            "name": event_name or "Udział w wydarzeniu",
            "unit": "szt.",
            "count": 1,
            "price": 0,  # Zostanie uzupełnione z total
            "vat": "23",
        }]
    
    positions = []
    for t in tickets:
        name = t.get("name") or "Bilet"
        if event_name:
            name = f"{name} - {event_name}"
        
        vat_rate = t.get("vat_rate", 23)
        # wFirma akceptuje stawki jako string: "23", "8", "5", "0", "zw", "np"
        vat_str = str(vat_rate) if vat_rate in (23, 8, 5, 0) else "23"
        
        positions.append({
            "name": name,
            "unit": "szt.",
            "count": t.get("quantity", 1),
            "price": t.get("unit_price_net", 0),  # Cena netto jednostkowa
            "vat": vat_str,
        })
    
    return positions


def _get_event_config(event_id: str) -> Optional[Dict[str, Any]]:
    """Pobiera konfigurację eventu z bazy danych."""
    ev = get_event(event_id)
    if not ev:
        return None
    return {
        "event_id": ev.get("event_id"),
        "event_name": ev.get("event_name"),
        "data": ev.get("data") or {},
    }


def _determine_flow(order_data: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Określa flow na podstawie danych zamówienia.
    Zwraca (flow_type, matched_rule).
    """
    total = order_data.get("total", 0)
    event_id = order_data.get("event_id", "")
    payment_option_name = order_data.get("payment_option_name", "")
    payment_type = order_data.get("payment_type")

    payment_option_lower = (payment_option_name or "").lower().strip()
    _log("DEBUG", "FLOW: dane wejściowe", {
        "event_id": event_id,
        "total": total,
        "payment_option_name": payment_option_name,
        "payment_option_lower": payment_option_lower,
        "payment_type": payment_type,
    })

    # 1. Jeśli total = 0 → zawsze FOC
    if total == 0 or total is None:
        _log("INFO", "FLOW: wybrano FOC (total=0)", {"event_id": event_id, "payment_option_name": payment_option_name, "payment_type": payment_type})
        return FLOW_FOC, None

    # 2. Spróbuj dopasować regułę z bazy
    rule = match_payment_rule(event_id, payment_option_name, payment_type)
    if rule:
        _log("INFO", "FLOW: dopasowano regułę z bazy", {
            "rule_id": rule.get("id"),
            "rule_flow": rule.get("flow"),
            "payment_option_name_pattern": rule.get("payment_option_name_pattern"),
            "payment_option_id": rule.get("payment_option_id"),
            "payment_type": rule.get("payment_type"),
            "is_default": rule.get("is_default"),
        })
        return rule.get("flow", FLOW_STRIPE), rule

    # 3. Fallback: heurystyka na podstawie nazwy opcji płatności
    # UWAGA: Backstage potrafi mieć "Pro forma" z odstępem, albo "pro-forma"
    if ("pro-forma" in payment_option_lower) or ("proforma" in payment_option_lower) or ("pro forma" in payment_option_lower):
        _log("INFO", "FLOW: wybrano PROFORMA (heurystyka po nazwie opcji)", {"payment_option_name": payment_option_name})
        return FLOW_PROFORMA, None
    if "online" in payment_option_lower or "karta" in payment_option_lower:
        _log("INFO", "FLOW: wybrano STRIPE (heurystyka po nazwie opcji)", {"payment_option_name": payment_option_name})
        return FLOW_STRIPE, None

    # 4. Domyślnie: STRIPE
    _log("INFO", "FLOW: wybrano STRIPE (fallback domyślny)", {"payment_option_name": payment_option_name})
    return FLOW_STRIPE, None


def _build_mail_task(
    template_key: str,
    to_email: str,
    subject: str,
    data: Dict[str, Any],
    direction: str = "purchaser",
) -> Dict[str, Any]:
    """Buduje strukturę mail_task dla Make.com."""
    return {
        "template": template_key,
        "to": to_email,
        "subject": subject,
        "direction": direction,
        "data": data,
    }


# ---------------------------------------------------------------------------
# WFIRMA INVOICE CREATION
# ---------------------------------------------------------------------------

# Konfiguracja wFirma
WFIRMA_COMPANY = os.environ.get("WFIRMA_COMPANY", "md")  # md lub test
WFIRMA_SERIES_NAME = os.environ.get("WFIRMA_SERIES_NAME", "FV/EV")
WFIRMA_API_KEY = os.environ.get("MAKE_RENDER_API_KEY", "")  # Ten sam klucz co dla innych API


def _create_wfirma_invoice(
    order_data: Dict[str, Any],
    event_name: str,
    document_type: str = "normal",  # "normal" (VAT) lub "proforma"
    payment_status: str = "paid",   # "paid" lub "unpaid"
    send_email: bool = True,
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Tworzy fakturę w wFirma przez wewnętrzne wywołanie API.
    
    Args:
        order_data: Dane zamówienia z _extract_order_data
        event_name: Nazwa wydarzenia
        document_type: "normal" (faktura VAT) lub "proforma"
        payment_status: "paid" (opłacona) lub "unpaid" (nieopłacona)
        send_email: Czy wysłać fakturę emailem
    
    Returns:
        (success, invoice_data, error_message)
    """
    event_order_id = order_data.get("event_order_id", "")
    
    _log("INFO", "WFIRMA: START tworzenia dokumentu", {
        "document_type": document_type,
        "event_order_id": event_order_id,
        "payment_status": payment_status,
        "company": WFIRMA_COMPANY,
        "series_name": WFIRMA_SERIES_NAME,
        "event_name": event_name[:30] if event_name else None,
        "total": order_data.get("total", 0),
        "currency": order_data.get("currency", "PLN"),
        "purchaser_email": order_data.get("purchaser_email", ""),
        "purchaser_nip": (order_data.get("purchaser_nip", "")[:5] + "...") if order_data.get("purchaser_nip") else "",
    })
    
    # Przygotuj dane do faktury
    purchaser_name = f"{order_data.get('purchaser_first_name', '')} {order_data.get('purchaser_last_name', '')}".strip()
    purchaser_nip = order_data.get("purchaser_nip", "")
    purchaser_email = order_data.get("purchaser_email", "")
    total = order_data.get("total", 0)
    currency = order_data.get("currency", "PLN")
    raw_tickets = order_data.get("tickets", [])
    
    # Wzbogać bilety o nazwy z bazy danych (event_ticket_classes)
    event_id = order_data.get("event_id", "")
    if raw_tickets and event_id:
        enriched_tickets, unknown_ids = _enrich_tickets_with_names(raw_tickets, event_id)
        if unknown_ids:
            _log("DEBUG", "WFIRMA: Nierozpoznane ticket_class_id", {
                "event_order_id": event_order_id,
                "unknown_ids": unknown_ids[:5],
            })
        tickets = enriched_tickets
    else:
        tickets = raw_tickets
    
    # Adres rozliczeniowy
    billing_address = order_data.get("billing_address", "-")
    billing_zip = order_data.get("billing_zip", "00-000")
    billing_city = order_data.get("billing_city", "-")
    
    # Buduj pozycje faktury
    positions = _build_invoice_positions(tickets, event_name)
    
    # Jeśli brak pozycji lub cena = 0, użyj total z zamówienia
    if not positions or (len(positions) == 1 and positions[0].get("price", 0) == 0):
        # Oblicz cenę netto z brutto (VAT 23%)
        price_net = round(total / 1.23, 2)
        positions = [{
            "name": f"Udział w wydarzeniu: {event_name}" if event_name else "Udział w wydarzeniu",
            "unit": "szt.",
            "count": 1,
            "price": price_net,
            "vat": "23",
        }]

    # Preview pozycji (max 5) - żeby było widać co idzie do wFirma
    try:
        positions_preview = []
        for p in positions[:5]:
            positions_preview.append({
                "name": (p.get("name") or "")[:80],
                "count": p.get("count"),
                "price": p.get("price"),
                "vat": p.get("vat"),
            })
        _log("DEBUG", "WFIRMA: Pozycje (preview)", {
            "event_order_id": event_order_id,
            "positions_count": len(positions),
            "positions_preview": positions_preview,
        })
    except Exception:
        pass
    
    # Data faktury
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # Payload do workflow endpoint
    invoice_payload = {
        "company": WFIRMA_COMPANY,
        "series_name": WFIRMA_SERIES_NAME,
        "payment_status": payment_status,
        "payment_due_days": 0 if payment_status == "paid" else 7,
        "description": event_name,
        "nip": purchaser_nip,
        "purchaser_name": purchaser_name or "Uczestnik",
        "purchaser_address": billing_address,
        "purchaser_zip": billing_zip,
        "purchaser_city": billing_city,
        "document_type": document_type,
        "invoice": {
            "issue_date": today,
            "sale_date": today,
            "payment_due_days": 0 if payment_status == "paid" else 7,
            "payment_method": "transfer",
            "place": "Warszawa",
            "currency": currency,
            "positions": positions,
        },
        "send_email": send_email and bool(purchaser_email),
        "email": purchaser_email,
    }
    
    _log("DEBUG", "WFIRMA: Payload faktury", {
        "document_type": document_type,
        "positions_count": len(positions),
        "nip": purchaser_nip[:5] + "..." if purchaser_nip else None,
        "send_email": send_email and bool(purchaser_email),
        "email": purchaser_email,
        "payment_due_days": 0 if payment_status == "paid" else 7,
        "billing_zip": billing_zip,
        "billing_city": billing_city,
    })
    
    # Wywołaj workflow wFirma wewnętrznie (bez HTTP), żeby uniknąć deadlocków/timeoutów przy 1 workerze.
    # Uwaga: to dalej przechodzi przez ten sam endpoint i logikę, ale bez sieci.
    try:
        import time
        from app import app as flask_app

        _log("DEBUG", "WFIRMA: Wywołuję workflow lokalnie (test_client)", {"path": "/api/workflow/create-invoice-from-nip"})

        t0 = time.time()
        with flask_app.test_client() as client:
            resp = client.post(
                "/api/workflow/create-invoice-from-nip",
                json=invoice_payload,
                headers={"X-API-Key": WFIRMA_API_KEY},
            )
        dt_ms = int((time.time() - t0) * 1000)

        status_code = getattr(resp, "status_code", None)
        try:
            result = resp.get_json(silent=True) or {}
        except Exception:
            try:
                result = {"_raw": (resp.get_data(as_text=True) or "")[:1000]}
            except Exception:
                result = {}

        _log("INFO", "WFIRMA: Odpowiedź workflow (local)", {
            "event_order_id": event_order_id,
            "document_type": document_type,
            "payment_status": payment_status,
            "status_code": status_code,
            "duration_ms": dt_ms,
            "success": bool(result.get("success")) if isinstance(result, dict) else None,
            "result_keys": list(result.keys()) if isinstance(result, dict) else None,
        })

        if status_code == 200 and result.get("success"):
            invoice_id = result.get("invoice", {}).get("id")
            invoice_number = result.get("invoice", {}).get("fullnumber")
            
            _log("INFO", "WFIRMA: SUCCESS dokument utworzony", {
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "email_sent": result.get("email_sent", False),
                "document_type": document_type,
                "payment_status": payment_status,
                "duration_ms": dt_ms,
            })
            
            # Zapisz do bazy
            try:
                from pg_storage import save_wfirma_document
                save_wfirma_document(
                    event_order_id=event_order_id,
                    wfirma_invoice_id=str(invoice_id) if invoice_id else "",
                    wfirma_number=invoice_number or "",
                    document_type=document_type,
                    email_to=purchaser_email,
                    raw=result,
                )
            except Exception as db_err:
                err_txt = str(db_err)
                # Jeśli to duplikat (unikalny indeks na normal invoice) – traktuj jako "już istnieje"
                if (
                    "uniq_wfirma_normal_per_order" in err_txt
                    or "duplicate key value violates unique constraint" in err_txt
                    or "UNIQUE constraint failed" in err_txt
                ):
                    existing_preview = None
                    try:
                        from pg_storage import get_wfirma_documents
                        docs = get_wfirma_documents(event_order_id)
                        if docs:
                            d0 = docs[0]
                            existing_preview = {
                                "wfirma_number": d0.get("wfirma_number"),
                                "wfirma_invoice_id": d0.get("wfirma_invoice_id"),
                                "document_type": d0.get("document_type"),
                                "status": d0.get("status"),
                                "created_at": str(d0.get("created_at"))[:19] if d0.get("created_at") else None,
                            }
                    except Exception:
                        pass

                    _log("INFO", "WFIRMA: Dokument już zapisany w bazie (duplikat) – pomijam zapis", {
                        "event_order_id": event_order_id,
                        "document_type": document_type,
                        "wfirma_invoice_id": str(invoice_id) if invoice_id else "",
                        "wfirma_number": invoice_number or "",
                        "existing_doc_preview": existing_preview,
                    })
                else:
                    _log("WARNING", "WFIRMA: Nie udało się zapisać do bazy", {"error": err_txt})
            
            return True, result, None
        else:
            error_msg = result.get("error") or result.get("message") or f"HTTP {status_code}"
            _log("ERROR", "WFIRMA: ERROR tworzenia dokumentu", {
                "event_order_id": event_order_id,
                "document_type": document_type,
                "payment_status": payment_status,
                "status": status_code,
                "duration_ms": dt_ms,
                "error": error_msg,
                "details": result.get("details", "")[:200] if result.get("details") else None,
                "response_snippet": (result.get("_raw") or "")[:500] if isinstance(result, dict) else None,
            })
            # Jeśli 401 - token wygasł / brak autoryzacji: wyślij jednoznaczny alert
            if status_code == 401:
                try:
                    _send_error_notification(
                        error_type="WFIRMA_AUTH_REQUIRED",
                        error_message=(
                            "wFirma odmówiła dostępu (401). Najczęściej oznacza to, że refresh token wygasł.\n\n"
                            f"Company: {WFIRMA_COMPANY}\n"
                            "WYMAGANA AKCJA: wejdź na /auth?company=md i przejdź pełną autoryzację OAuth.\n"
                            "Po autoryzacji system zapisze nowe tokeny (WFIRMA_MD_*)."
                        ),
                        event_order_id=event_order_id,
                        event_id=order_data.get("event_id", ""),
                        extra_data={
                            "status_code": status_code,
                            "error": error_msg,
                            "document_type": document_type,
                            "payment_status": payment_status,
                            "event_name": event_name,
                            "purchaser_email": purchaser_email,
                        },
                    )
                except Exception:
                    pass
            return False, None, error_msg
            
    except requests.exceptions.Timeout:
        _log("ERROR", "WFIRMA: Timeout podczas tworzenia dokumentu", {
            "event_order_id": event_order_id,
            "document_type": document_type,
            "payment_status": payment_status,
        })
        return False, None, "Timeout podczas komunikacji z wFirma"
    except requests.exceptions.ConnectionError as e:
        _log("ERROR", "WFIRMA: Błąd połączenia", {
            "event_order_id": event_order_id,
            "document_type": document_type,
            "payment_status": payment_status,
            "error": str(e),
        })
        return False, None, f"Błąd połączenia: {str(e)}"
    except Exception as e:
        _log("ERROR", "WFIRMA: Wyjątek podczas tworzenia dokumentu", {
            "event_order_id": event_order_id,
            "document_type": document_type,
            "payment_status": payment_status,
            "error": str(e),
        })
        return False, None, str(e)


def _create_paid_invoice(
    order_data: Dict[str, Any],
    event_name: str,
    send_email: bool = True,
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Tworzy opłaconą fakturę VAT po płatności Stripe.
    """
    _log("INFO", "WFIRMA: Wywołanie _create_paid_invoice", {"event_order_id": order_data.get("event_order_id", ""), "event_name": event_name[:30] if event_name else None})
    return _create_wfirma_invoice(
        order_data=order_data,
        event_name=event_name,
        document_type="normal",
        payment_status="paid",
        send_email=send_email,
    )


def _create_proforma_invoice(
    order_data: Dict[str, Any],
    event_name: str,
    send_email: bool = True,
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Tworzy fakturę proforma dla flow PROFORMA.
    """
    _log("INFO", "WFIRMA: Wywołanie _create_proforma_invoice", {"event_order_id": order_data.get("event_order_id", ""), "event_name": event_name[:30] if event_name else None})
    return _create_wfirma_invoice(
        order_data=order_data,
        event_name=event_name,
        document_type="proforma",
        payment_status="unpaid",
        send_email=send_email,
    )


# ---------------------------------------------------------------------------
# FLOW HANDLERS
# ---------------------------------------------------------------------------


def _handle_foc_flow(
    order_data: Dict[str, Any],
    event_config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Obsługuje flow FOC (Free of Charge).
    - Ustawia status na 'paid' (darmowe)
    - Wysyła email z potwierdzeniem rejestracji (przez Make webhook)
    """
    event_order_id = order_data["event_order_id"]
    purchaser_email = order_data["purchaser_email"]
    purchaser_first_name = order_data.get("purchaser_first_name", "")
    purchaser_last_name = order_data.get("purchaser_last_name", "")
    purchaser_phone = order_data.get("purchaser_phone", "")
    event_name = (event_config.get("event_name") if event_config else "") or "Wydarzenie"
    event_data = (event_config.get("data") if event_config else {}) or {}
    event_id = order_data.get("event_id", "")

    _log("INFO", "FOC FLOW: Rozpoczynam przetwarzanie", {
        "event_order_id": event_order_id,
        "event_name": event_name,
        "purchaser_email": purchaser_email,
    })

    # Aktualizuj status zamówienia na 'paid' (darmowe = od razu opłacone)
    update_order_status(event_order_id, "paid")

    mail_tasks = []
    email_sent = False

    # Wzbogać bilety o nazwy z bazy
    raw_tickets = order_data.get("tickets", [])
    if raw_tickets and event_id:
        enriched_tickets, unknown_ids = _enrich_tickets_with_names(raw_tickets, event_id)
        if unknown_ids:
            _log("DEBUG", "FOC FLOW: Nierozpoznane ticket_class_id", {"unknown_ids": unknown_ids[:5]})
    else:
        enriched_tickets = raw_tickets

    # Mail do kupującego: potwierdzenie rejestracji (wysyłka przez Make)
    if purchaser_email and _is_make_email_configured():
        try:
            from email_templates import render_foc_confirmation_email
            
            subject = f"Potwierdzenie rejestracji – {event_name}"
            body_html = render_foc_confirmation_email(
                event_name=event_name,
                purchaser_first_name=purchaser_first_name,
                purchaser_last_name=purchaser_last_name,
                purchaser_email=purchaser_email,
                purchaser_phone=purchaser_phone,
                event_config=event_data,
                tickets=enriched_tickets,
            )
            
            _log("INFO", "FOC FLOW: Wysyłam email potwierdzenia przez Make", {
                "to": purchaser_email,
                "subject": subject,
            })
            
            result = _send_email_via_make(
                to_email=purchaser_email,
                subject=subject,
                body_html=body_html,
                event_order_id=event_order_id,
                template_type="foc_confirmation",
            )
            
            if result.get("success"):
                _log("INFO", "FOC FLOW: Email wysłany pomyślnie!", {"to": purchaser_email})
                email_sent = True
            else:
                _log("WARNING", "FOC FLOW: Błąd wysyłki emaila", {"error": result.get("error")})
                # Wyślij powiadomienie wewnętrzne o błędzie
                _send_error_notification(
                    error_type="FOC_EMAIL_ERROR",
                    error_message=f"Nie udało się wysłać potwierdzenia rejestracji FOC.\n\nBłąd: {result.get('error')}",
                    event_order_id=event_order_id,
                    event_id=event_id,
                    extra_data={
                        "purchaser_email": purchaser_email,
                        "event_name": event_name,
                    },
                )
        except Exception as e:
            _log("ERROR", "FOC FLOW: Wyjątek przy wysyłce emaila", {"error": str(e)})
            _send_error_notification(
                error_type="FOC_EMAIL_EXCEPTION",
                error_message=f"Wyjątek przy wysyłce potwierdzenia FOC.\n\nBłąd: {str(e)}",
                event_order_id=event_order_id,
                event_id=event_id,
            )

    # Mail task do logu (nawet jeśli wysłany bezpośrednio)
    if purchaser_email:
        mail_tasks.append(_build_mail_task(
            template_key=TEMPLATE_REGISTRATION_CONFIRMATION,
            to_email=purchaser_email,
            subject=f"Potwierdzenie rejestracji – {event_name}",
            data={
                "event_order_id": event_order_id,
                "event_name": event_name,
                "purchaser_name": f"{purchaser_first_name} {purchaser_last_name}".strip(),
                "purchaser_email": purchaser_email,
                "email_sent_via_make": email_sent,
                **event_data,
            },
            direction="purchaser",
        ))

    # Mail wewnętrzny: powiadomienie o zamówieniu (info, nie error)
    internal_email = event_data.get("md_email_techniczny") or event_data.get("md_email_kontakt") or BACKSTAGE_EVENT_INFO_EMAIL
    if internal_email:
        mail_tasks.append(_build_mail_task(
            template_key=TEMPLATE_INTERNAL_ORDER_RECEIVED,
            to_email=internal_email,
            subject=f"[FOC] Nowe zamówienie – {event_name}",
            data={
                "event_order_id": event_order_id,
                "event_name": event_name,
                "flow": FLOW_FOC,
                "total": 0,
                "purchaser_email": purchaser_email,
                "purchaser_name": f"{purchaser_first_name} {purchaser_last_name}".strip(),
            },
            direction="internal",
        ))

    # Wyślij indywidualne emaile do WSZYSTKICH uczestników (każdy swój bilet)
    participant_email_stats = {"sent": 0, "failed": 0, "skipped": 0}
    try:
        participant_email_stats = send_participant_ticket_emails(
            event_order_id=event_order_id,
            event_name=event_name,
            event_config=event_data,
        )
        _log("INFO", "FOC FLOW: Emaile do uczestników wysłane", {
            "sent": participant_email_stats.get("sent", 0),
            "failed": participant_email_stats.get("failed", 0),
            "skipped": participant_email_stats.get("skipped", 0),
        })
    except Exception as e:
        _log("ERROR", f"FOC FLOW: Błąd wysyłki emaili do uczestników: {e}")

    _log("INFO", "FOC FLOW: Zakończono", {
        "event_order_id": event_order_id,
        "email_sent": email_sent,
        "participant_emails_sent": participant_email_stats.get("sent", 0),
        "mail_tasks_count": len(mail_tasks),
    })

    return {
        "flow": FLOW_FOC,
        "status": "completed",
        "order_status": "paid",
        "mail_tasks": mail_tasks,
        "email_sent": email_sent,
    }


def _handle_proforma_flow(
    order_data: Dict[str, Any],
    event_config: Optional[Dict[str, Any]],
    rule: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Obsługuje flow PROFORMA.
    - Tworzy fakturę proforma w wFirma
    - Wysyła proformę emailem do kupującego (przez wFirma)
    - Ustawia status na 'pending_payment'
    """
    event_order_id = order_data["event_order_id"]
    purchaser_email = order_data["purchaser_email"]
    event_name = (event_config.get("event_name") if event_config else "") or "Wydarzenie"
    event_data = (event_config.get("data") if event_config else {}) or {}

    _log("INFO", "PROFORMA FLOW: Rozpoczynam tworzenie proformy", {
        "event_order_id": event_order_id,
        "event_name": event_name,
        "total": order_data.get("total", 0),
    })

    # Aktualizuj status zamówienia
    update_order_status(event_order_id, "pending_payment")

    mail_tasks = []
    proforma_result = None
    proforma_error = None
    reservation_email_sent = False

    # Wzbogać bilety o nazwy z bazy (dla maila rezerwacyjnego)
    event_id = order_data.get("event_id", "")
    raw_tickets = order_data.get("tickets", [])
    if raw_tickets and event_id:
        enriched_tickets, unknown_ids = _enrich_tickets_with_names(raw_tickets, event_id)
        if unknown_ids:
            _log("DEBUG", "PROFORMA FLOW: Nierozpoznane ticket_class_id", {"unknown_ids": unknown_ids[:5]})
    else:
        enriched_tickets = raw_tickets

    # Utwórz proformę w wFirma
    try:
        success, proforma_result, proforma_error = _create_proforma_invoice(
            order_data=order_data,
            event_name=event_name,
            send_email=bool(purchaser_email),  # wFirma wyśle email z proformą
        )
        
        if success and proforma_result:
            _log("INFO", "PROFORMA FLOW: Proforma utworzona pomyślnie", {
                "invoice_id": proforma_result.get("invoice", {}).get("id"),
                "invoice_number": proforma_result.get("invoice", {}).get("fullnumber"),
                "email_sent": proforma_result.get("email_sent", False),
            })
        else:
            _log("ERROR", "PROFORMA FLOW: Błąd tworzenia proformy", {"error": proforma_error})
            
            # Wyślij powiadomienie o błędzie
            _send_error_notification(
                error_type="PROFORMA_CREATE_ERROR",
                error_message=f"Nie udało się utworzyć faktury proforma.\n\nBłąd: {proforma_error}",
                event_order_id=event_order_id,
                event_name=event_name,
                extra_context={
                    "purchaser": f"{order_data.get('purchaser_first_name', '')} {order_data.get('purchaser_last_name', '')}".strip(),
                    "email": purchaser_email,
                    "total": f"{order_data.get('total', 0)} {order_data.get('currency', 'PLN')}",
                    "nip": order_data.get("purchaser_nip", ""),
                }
            )
            
    except Exception as e:
        proforma_error = str(e)
        _log("ERROR", "PROFORMA FLOW: Wyjątek podczas tworzenia proformy", {"error": proforma_error})

    # Mail do kupującego (BACKSTAGE): rezerwacja + informacja o pro-formie (wysyłka przez Make)
    if purchaser_email and _is_make_email_configured():
        try:
            from email_templates import render_proforma_reservation_email

            proforma_number = None
            if proforma_result:
                proforma_number = proforma_result.get("invoice", {}).get("fullnumber")

            subject = f"Rezerwacja miejsca – {event_name} (pro-forma w 24h)"
            body_html = render_proforma_reservation_email(
                event_name=event_name,
                purchaser_first_name=order_data.get("purchaser_first_name", ""),
                purchaser_last_name=order_data.get("purchaser_last_name", ""),
                purchaser_email=purchaser_email,
                purchaser_phone=order_data.get("purchaser_phone", ""),
                event_config=event_data,
                tickets=enriched_tickets,
                proforma_number=proforma_number,
            )

            _log("INFO", "PROFORMA FLOW: Wysyłam email rezerwacyjny przez Make", {
                "to": purchaser_email,
                "subject": subject,
                "has_proforma_number": bool(proforma_number),
            })

            result = _send_email_via_make(
                to_email=purchaser_email,
                subject=subject,
                body_html=body_html,
                event_order_id=event_order_id,
                template_type="proforma_reservation",
            )

            if result.get("success"):
                reservation_email_sent = True
                _log("INFO", "PROFORMA FLOW: Email rezerwacyjny wysłany pomyślnie", {"to": purchaser_email})
            else:
                _log("WARNING", "PROFORMA FLOW: Błąd wysyłki emaila rezerwacyjnego", {"error": result.get("error")})
                _send_error_notification(
                    error_type="PROFORMA_RESERVATION_EMAIL_ERROR",
                    error_message=f"Nie udało się wysłać maila rezerwacyjnego (PROFORMA).\n\nBłąd: {result.get('error')}",
                    event_order_id=event_order_id,
                    event_id=event_id,
                    extra_data={
                        "purchaser_email": purchaser_email,
                        "event_name": event_name,
                    },
                )
        except Exception as e:
            _log("ERROR", "PROFORMA FLOW: Wyjątek przy wysyłce emaila rezerwacyjnego", {"error": str(e)})
            _send_error_notification(
                error_type="PROFORMA_RESERVATION_EMAIL_EXCEPTION",
                error_message=f"Wyjątek przy wysyłce maila rezerwacyjnego (PROFORMA).\n\nBłąd: {str(e)}",
                event_order_id=event_order_id,
                event_id=event_id,
            )

    # Mail task do logu (nawet jeśli wysłany bezpośrednio)
    if purchaser_email:
        mail_tasks.append(_build_mail_task(
            template_key=TEMPLATE_PROFORMA_SENT,
            to_email=purchaser_email,
            subject=f"Rezerwacja miejsca – {event_name} (pro-forma w 24h)",
            data={
                "event_order_id": event_order_id,
                "event_name": event_name,
                "flow": FLOW_PROFORMA,
                "purchaser_email": purchaser_email,
                "purchaser_name": f"{order_data.get('purchaser_first_name', '')} {order_data.get('purchaser_last_name', '')}".strip(),
                "reservation_email_sent_via_make": reservation_email_sent,
                "proforma_number": proforma_result.get("invoice", {}).get("fullnumber") if proforma_result else None,
                **event_data,
            },
            direction="purchaser",
        ))

    # Mail wewnętrzny o nowym zamówieniu (info, nie error)
    internal_email = event_data.get("md_email_techniczny") or event_data.get("md_email_kontakt") or BACKSTAGE_EVENT_INFO_EMAIL
    if internal_email:
        proforma_info = ""
        if proforma_result:
            proforma_info = f"\n\nProforma: {proforma_result.get('invoice', {}).get('fullnumber', 'N/A')}"
            if proforma_result.get("email_sent"):
                proforma_info += " (wysłana do klienta)"
        elif proforma_error:
            proforma_info = f"\n\n⚠️ Błąd proformy: {proforma_error}"
        
        mail_tasks.append(_build_mail_task(
            template_key=TEMPLATE_INTERNAL_ORDER_RECEIVED,
            to_email=internal_email,
            subject=f"[PROFORMA] Nowe zamówienie – {event_name}",
            data={
                "event_order_id": event_order_id,
                "event_name": event_name,
                "flow": FLOW_PROFORMA,
                "total": order_data.get("total", 0),
                "currency": order_data.get("currency", "PLN"),
                "purchaser_email": purchaser_email,
                "purchaser_name": f"{order_data.get('purchaser_first_name', '')} {order_data.get('purchaser_last_name', '')}".strip(),
                "purchaser_nip": order_data.get("purchaser_nip", ""),
                "proforma_info": proforma_info,
                "proforma_number": proforma_result.get("invoice", {}).get("fullnumber") if proforma_result else None,
            },
            direction="internal",
        ))

    return {
        "flow": FLOW_PROFORMA,
        "status": "ok" if proforma_result else "error",
        "order_status": "pending_payment",
        "proforma_created": bool(proforma_result),
        "proforma_invoice_id": proforma_result.get("invoice", {}).get("id") if proforma_result else None,
        "proforma_number": proforma_result.get("invoice", {}).get("fullnumber") if proforma_result else None,
        "proforma_email_sent": proforma_result.get("email_sent", False) if proforma_result else False,
        "proforma_error": proforma_error,
        "mail_tasks": mail_tasks,
    }


def _handle_stripe_flow(
    order_data: Dict[str, Any],
    event_config: Optional[Dict[str, Any]],
    rule: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Obsługuje flow STRIPE.
    - Tworzy sesję Stripe Checkout
    - Wysyła email z linkiem do płatności
    - Ustawia status na 'pending_payment'
    """
    from stripe_integration import create_checkout_session
    from email_sender import send_email, is_email_configured
    from email_templates import render_stripe_payment_email
    
    event_order_id = order_data["event_order_id"]
    purchaser_email = order_data["purchaser_email"]
    purchaser_first_name = order_data.get("purchaser_first_name", "")
    purchaser_last_name = order_data.get("purchaser_last_name", "")
    purchaser_phone = order_data.get("purchaser_phone", "")
    purchaser_nip = order_data.get("purchaser_nip", "")
    total = order_data.get("total", 0)
    currency = order_data.get("currency", "PLN")
    is_sandbox = order_data.get("sandbox", False)
    promo_code = order_data.get("promo_code", "")
    
    event_name = (event_config.get("event_name") if event_config else "") or "Wydarzenie"
    event_data = (event_config.get("data") if event_config else {}) or {}

    _log("INFO", "STRIPE FLOW: Rozpoczynam przetwarzanie", {
        "event_order_id": event_order_id,
        "total": total,
        "sandbox": is_sandbox,
    })

    # Aktualizuj status zamówienia
    update_order_status(event_order_id, "pending_payment")

    # URLs dla Stripe
    success_url = event_data.get("url_success") or event_data.get("url_event") or "https://medidesk.com"
    cancel_url = event_data.get("url_cancel") or event_data.get("url_event") or "https://medidesk.com"

    mail_tasks = []
    stripe_url = None
    stripe_session_id = None
    stripe_error = None

    # Przygotuj line_items do Stripe z biletów (ładny widok w Checkout)
    event_id_for_tickets = order_data.get("event_id", "")
    raw_tickets_for_stripe = order_data.get("tickets", []) or []
    enriched_tickets_for_stripe, _unknown_ids_for_stripe = _enrich_tickets_with_names(raw_tickets_for_stripe, event_id_for_tickets)

    def _build_stripe_line_items_from_tickets(tickets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for t in tickets:
            try:
                name = (t.get("name") or "Bilet").strip()
                qty = t.get("quantity", 1)
                try:
                    qty_i = int(qty) if qty is not None else 1
                except (ValueError, TypeError):
                    qty_i = 1
                if qty_i <= 0:
                    qty_i = 1

                unit_gross = t.get("unit_price_gross")
                try:
                    unit_gross_f = float(unit_gross) if unit_gross is not None else 0.0
                except (ValueError, TypeError):
                    unit_gross_f = 0.0

                unit_amount = int(round(unit_gross_f * 100))
                if unit_amount <= 0:
                    # fallback: jeśli brak ceny na bilecie, nie buduj tej pozycji (zostanie korekta)
                    continue

                discount_amount = t.get("discount_amount", 0) or 0
                try:
                    discount_f = float(discount_amount)
                except (ValueError, TypeError):
                    discount_f = 0.0

                desc_parts = [event_name]
                if promo_code:
                    desc_parts.append(f"Kod: {promo_code}")
                if discount_f > 0:
                    desc_parts.append(f"Rabat: {discount_f:.2f} zł")
                description_txt = " | ".join(desc_parts)[:500]

                items.append({
                    "price_data": {
                        "currency": currency.lower(),
                        "unit_amount": unit_amount,
                        "product_data": {
                            "name": name[:120],
                            "description": description_txt,
                            "metadata": {
                                "event_order_id": event_order_id,
                                "event_id": event_id_for_tickets,
                                "ticket_class_id": str(t.get("ticket_class_id", "")),
                            },
                        },
                    },
                    "quantity": qty_i,
                })
            except Exception:
                continue
        return items

    stripe_line_items = _build_stripe_line_items_from_tickets(enriched_tickets_for_stripe)

    # Korekta groszy (zaokrąglenia) - dopasuj sumę line_items do total
    amount_cents = int(round(float(total or 0) * 100))
    if stripe_line_items:
        try:
            sum_cents = 0
            for it in stripe_line_items:
                qa = int(it.get("quantity", 1) or 1)
                ua = int(it.get("price_data", {}).get("unit_amount", 0) or 0)
                sum_cents += qa * ua
            delta = amount_cents - sum_cents
            if delta != 0:
                # najprościej: skoryguj ostatnią pozycję o deltę (zwykle kilka groszy)
                last = stripe_line_items[-1]
                ua_last = int(last.get("price_data", {}).get("unit_amount", 0) or 0)
                ua_new = ua_last + delta
                if ua_new > 0:
                    last["price_data"]["unit_amount"] = ua_new
                    _log("DEBUG", "STRIPE line_items: korekta zaokrągleń", {"sum_cents": sum_cents, "amount_cents": amount_cents, "delta": delta})
                else:
                    _log("WARNING", "STRIPE line_items: nie udało się zastosować korekty (ujemna cena)", {"sum_cents": sum_cents, "amount_cents": amount_cents, "delta": delta, "ua_last": ua_last})
        except Exception as e:
            _log("WARNING", "STRIPE line_items: błąd korekty sumy", {"error": str(e)})

    if stripe_line_items:
        _log("INFO", "STRIPE FLOW: Checkout będzie miał pozycje biletów", {
            "items_count": len(stripe_line_items),
            "first_item_name": stripe_line_items[0].get("price_data", {}).get("product_data", {}).get("name") if stripe_line_items else None,
        })
    else:
        _log("WARNING", "STRIPE FLOW: brak line_items z biletów - fallback do jednej pozycji", {"tickets_count": len(enriched_tickets_for_stripe)})

    # 1. Utwórz sesję Stripe Checkout
    _log("INFO", "STRIPE FLOW: Tworzę sesję Stripe Checkout...", {"sandbox": is_sandbox})
    
    session_data, error = create_checkout_session(
        event_order_id=event_order_id,
        amount_cents=amount_cents,
        currency=currency.lower(),
        customer_email=purchaser_email,
        description=event_name,
        success_url=success_url + (f"?order_id={event_order_id}" if "?" not in success_url else f"&order_id={event_order_id}"),
        cancel_url=cancel_url + (f"?order_id={event_order_id}" if "?" not in cancel_url else f"&order_id={event_order_id}"),
        metadata={
            "event_order_id": event_order_id,
            "event_id": order_data.get("event_id", ""),
            "event_name": event_name,
        },
        line_items=stripe_line_items if stripe_line_items else None,
        sandbox=is_sandbox,
    )
    
    if error:
        _log("ERROR", f"STRIPE FLOW: Błąd tworzenia sesji: {error}")
        stripe_error = error
        
        # Wyślij powiadomienie o błędzie Stripe
        _send_error_notification(
            error_type="STRIPE_SESSION_ERROR",
            error_message=f"Nie udało się utworzyć sesji płatności Stripe.\nBłąd: {error}",
            event_order_id=event_order_id,
            event_id=order_data.get("event_id", ""),
            extra_data={
                "purchaser_email": purchaser_email,
                "event_name": event_name,
                "total": total,
                "sandbox": is_sandbox,
            },
        )
    elif session_data:
        stripe_url = session_data.get("url")
        stripe_session_id = session_data.get("checkout_session_id")
        _log("INFO", "STRIPE FLOW: Sesja utworzona", {
            "checkout_session_id": stripe_session_id,
            "url": stripe_url[:50] + "..." if stripe_url else None,
        })

    # 2. Wyślij email z linkiem do płatności
    email_sent = False
    email_error = None
    email_method = None
    
    if stripe_url and purchaser_email:
        _log("INFO", "STRIPE FLOW: Wysyłam email z linkiem płatności...")
        
        # Wzbogać bilety o nazwy z bazy
        raw_tickets = order_data.get("tickets", [])
        event_id = order_data.get("event_id", "")
        enriched_tickets, unknown_ticket_ids = _enrich_tickets_with_names(raw_tickets, event_id)
        
        _log("DEBUG", "STRIPE FLOW: Bilety do emaila", {
            "raw_count": len(raw_tickets),
            "enriched_count": len(enriched_tickets),
            "unknown_count": len(unknown_ticket_ids),
        })
        
        # Powiadomienie o nierozpoznanych biletach
        if unknown_ticket_ids:
            _send_error_notification(
                error_type="UNKNOWN_TICKET_CLASS",
                error_message=f"Wykryto bilety o nieznanych ticket_class_id.\n\nNieznane ID ({len(unknown_ticket_ids)}):\n" + "\n".join(f"- {tid}" for tid in unknown_ticket_ids[:10]),
                event_order_id=event_order_id,
                event_name=event_name,
                extra_context={
                    "event_id": event_id,
                    "unknown_ticket_ids": unknown_ticket_ids,
                    "purchaser": f"{purchaser_first_name} {purchaser_last_name}".strip(),
                    "email": purchaser_email,
                    "total": f"{total} {currency}",
                    "uwaga": "Bilety z nieznanymi ID zostały oznaczone jako 'nierozpoznany' w emailu do klienta. Sprawdź konfigurację event_ticket_classes w admin panelu.",
                }
            )
        
        # Określ typ szablonu (personal / nip_valid / nip_invalid)
        template_type = "personal"
        gus_data = None
        
        if purchaser_nip:
            # Weryfikacja NIP przez GUS
            _log("INFO", "STRIPE FLOW: Weryfikuję NIP przez GUS...", {"nip": purchaser_nip})
            
            try:
                # Import wewnątrz funkcji aby uniknąć circular import
                from app import gus_lookup_nip
                
                # Wyczyść NIP (tylko cyfry)
                clean_nip = ''.join(c for c in purchaser_nip if c.isdigit())
                
                if len(clean_nip) == 10:
                    gus_records, gus_error = gus_lookup_nip(clean_nip)
                    
                    if gus_error:
                        # Błąd GUS (timeout, niedostępny) - użyj szablonu nip_invalid z ostrzeżeniem
                        _log("WARNING", "STRIPE FLOW: Błąd GUS, używam nip_invalid", {"error": gus_error})
                        template_type = "nip_invalid"
                        gus_data = None
                        
                        # Powiadomienie wewnętrzne o błędzie GUS
                        _send_error_notification(
                            error_type="GUS_ERROR",
                            error_message=f"Błąd komunikacji z GUS podczas weryfikacji NIP.\n\nBłąd: {gus_error}",
                            event_order_id=event_order_id,
                            event_name=event_name,
                            extra_context={
                                "nip": purchaser_nip,
                                "purchaser": f"{purchaser_first_name} {purchaser_last_name}".strip(),
                                "email": purchaser_email,
                                "total": f"{total} {currency}",
                                "uwaga": "Klient otrzymał email z informacją o błędnym NIP. Może zapłacić (faktura na osobę fizyczną) lub zarejestrować się ponownie.",
                            }
                        )
                    elif gus_records and len(gus_records) > 0:
                        # NIP znaleziony - pobierz dane firmy
                        rec = gus_records[0]
                        
                        # Zbuduj adres ulicy
                        street_parts = []
                        if rec.get('ulica'):
                            street_parts.append(rec['ulica'])
                        if rec.get('nrNieruchomosci'):
                            street_parts.append(rec['nrNieruchomosci'])
                        if rec.get('nrLokalu'):
                            street_parts.append(f"/{rec['nrLokalu']}")
                        street = ' '.join(street_parts).replace(' /', '/')
                        
                        template_type = "nip_valid"
                        gus_data = {
                            "name": rec.get('nazwa') or "Firma",
                            "street": street,
                            "zip": rec.get('kodPocztowy') or "",
                            "city": rec.get('miejscowosc') or "",
                            "regon": rec.get('regon') or "",
                        }
                        _log("INFO", "STRIPE FLOW: NIP poprawny, dane z GUS", {
                            "nazwa": gus_data["name"][:50] if gus_data["name"] else None,
                            "regon": gus_data["regon"],
                        })
                    else:
                        # NIP nie znaleziony w GUS - niepoprawny
                        _log("WARNING", "STRIPE FLOW: NIP nie znaleziony w GUS", {"nip": purchaser_nip})
                        template_type = "nip_invalid"
                        gus_data = None
                        
                        # Powiadomienie wewnętrzne o niepoprawnym NIP
                        _send_error_notification(
                            error_type="GUS_NIP_INVALID",
                            error_message=f"Klient podał NIP, który nie istnieje w rejestrze GUS.\n\nNIP: {purchaser_nip}",
                            event_order_id=event_order_id,
                            event_name=event_name,
                            extra_context={
                                "nip": purchaser_nip,
                                "purchaser": f"{purchaser_first_name} {purchaser_last_name}".strip(),
                                "email": purchaser_email,
                                "total": f"{total} {currency}",
                                "uwaga": "Klient otrzymał email z informacją o błędnym NIP. Może zapłacić (faktura na osobę fizyczną) lub zarejestrować się ponownie z poprawnym NIP.",
                            }
                        )
                else:
                    # NIP ma niepoprawną długość
                    _log("WARNING", "STRIPE FLOW: NIP ma niepoprawną długość", {
                        "nip": purchaser_nip, 
                        "clean_length": len(clean_nip)
                    })
                    template_type = "nip_invalid"
                    gus_data = None
                    
                    # Powiadomienie wewnętrzne o NIP z błędną długością
                    _send_error_notification(
                        error_type="GUS_NIP_WRONG_FORMAT",
                        error_message=f"Klient podał NIP o niepoprawnej długości ({len(clean_nip)} cyfr zamiast 10).\n\nPodany NIP: {purchaser_nip}",
                        event_order_id=event_order_id,
                        event_name=event_name,
                        extra_context={
                            "nip_podany": purchaser_nip,
                            "nip_oczyszczony": clean_nip,
                            "liczba_cyfr": len(clean_nip),
                            "purchaser": f"{purchaser_first_name} {purchaser_last_name}".strip(),
                            "email": purchaser_email,
                            "total": f"{total} {currency}",
                            "uwaga": "Klient otrzymał email z informacją o błędnym NIP. Może zapłacić (faktura na osobę fizyczną) lub zarejestrować się ponownie.",
                        }
                    )
                    
            except Exception as e:
                # Wyjątek podczas weryfikacji GUS - fallback do nip_invalid
                _log("ERROR", "STRIPE FLOW: Wyjątek podczas weryfikacji GUS", {"error": str(e)})
                template_type = "nip_invalid"
                gus_data = None
                
                # Powiadomienie wewnętrzne o wyjątku GUS
                import traceback
                tb = traceback.format_exc()
                _send_error_notification(
                    error_type="GUS_EXCEPTION",
                    error_message=f"Wyjątek podczas weryfikacji NIP w GUS.\n\nBłąd: {str(e)}\n\nTraceback:\n{tb[:500]}",
                    event_order_id=event_order_id,
                    event_name=event_name,
                    extra_context={
                        "nip": purchaser_nip,
                        "purchaser": f"{purchaser_first_name} {purchaser_last_name}".strip(),
                        "email": purchaser_email,
                        "total": f"{total} {currency}",
                        "uwaga": "Klient otrzymał email z informacją o błędnym NIP (fallback). Może zapłacić (faktura na osobę fizyczną) lub zarejestrować się ponownie.",
                    }
                )
        
        # Renderuj HTML
        body_html = render_stripe_payment_email(
            template_type=template_type,
            event_name=event_name,
            purchaser_first_name=purchaser_first_name,
            purchaser_last_name=purchaser_last_name,
            purchaser_email=purchaser_email,
            purchaser_phone=purchaser_phone,
            purchaser_nip=purchaser_nip,
            total_gross=total,
            stripe_payment_url=stripe_url,
            event_config=event_data,
            tickets=enriched_tickets,
            gus_data=gus_data,
        )
        
        subject = f"Link do płatności – {event_name}"
        
        # Próbuj wysłać przez Make webhook (preferowane)
        if _is_make_email_configured():
            _log("INFO", "STRIPE FLOW: Używam Make webhook do wysyłki email")
            result = _send_email_via_make(
                to_email=purchaser_email,
                subject=subject,
                body_html=body_html,
                event_order_id=event_order_id,
                template_type=template_type,
                stripe_url=stripe_url,
                extra_data={
                    "event_name": event_name,
                    "purchaser_name": f"{purchaser_first_name} {purchaser_last_name}".strip(),
                    "total": total,
                    "currency": currency,
                    "purchaser_nip": purchaser_nip,
                },
            )
            email_method = "make_webhook"
        # Fallback na SMTP jeśli Make nie skonfigurowany
        elif is_email_configured():
            _log("INFO", "STRIPE FLOW: Make nie skonfigurowany, używam SMTP")
            result = send_email(
                to_email=purchaser_email,
                subject=subject,
                body_html=body_html,
            )
            email_method = "smtp"
        else:
            _log("WARN", "STRIPE FLOW: Brak konfiguracji email (ani Make ani SMTP)")
            result = {"success": False, "error": "Brak konfiguracji email"}
            email_method = None
        
        if result.get("success"):
            email_sent = True
            _log("INFO", f"STRIPE FLOW: Email wysłany pomyślnie przez {email_method}!", {"to": purchaser_email})
        else:
            email_error = result.get("error")
            _log("ERROR", f"STRIPE FLOW: Błąd wysyłki email ({email_method}): {email_error}")
            
            # Wyślij powiadomienie o błędzie wysyłki
            _send_error_notification(
                error_type="EMAIL_SEND_ERROR",
                error_message=f"Nie udało się wysłać emaila z linkiem do płatności Stripe.\nMetoda: {email_method}\nBłąd: {email_error}",
                event_order_id=event_order_id,
                event_id=event_id,
                extra_data={
                    "purchaser_email": purchaser_email,
                    "event_name": event_name,
                    "stripe_url": stripe_url or "(brak)",
                    "total": total,
                },
            )
    elif not stripe_url:
        _log("WARN", "STRIPE FLOW: Brak URL Stripe - email nie wysłany")
    elif not purchaser_email:
        _log("WARN", "STRIPE FLOW: Brak email kupującego - email nie wysłany")

    # Mail task do zapisania w bazie (dla historii)
    if purchaser_email:
        mail_tasks.append(_build_mail_task(
            template_key=TEMPLATE_STRIPE_PAYMENT_LINK,
            to_email=purchaser_email,
            subject=f"Link do płatności – {event_name}",
            data={
                "event_order_id": event_order_id,
                "event_name": event_name,
                "purchaser_name": f"{purchaser_first_name} {purchaser_last_name}".strip(),
                "purchaser_email": purchaser_email,
                "total": total,
                "currency": currency,
                "purchaser_nip": purchaser_nip,
                "stripe_url": stripe_url or "",
                "email_sent": email_sent,
                "email_error": email_error,
                **event_data,
            },
            direction="purchaser",
        ))

    # Mail wewnętrzny (info o zamówieniu, nie error)
    internal_email = event_data.get("md_email_techniczny") or event_data.get("md_email_kontakt") or BACKSTAGE_EVENT_INFO_EMAIL
    if internal_email:
        mail_tasks.append(_build_mail_task(
            template_key=TEMPLATE_INTERNAL_ORDER_RECEIVED,
            to_email=internal_email,
            subject=f"[STRIPE] Nowe zamówienie – {event_name}",
            data={
                "event_order_id": event_order_id,
                "event_name": event_name,
                "flow": FLOW_STRIPE,
                "total": total,
                "currency": currency,
                "purchaser_email": purchaser_email,
                "purchaser_name": f"{purchaser_first_name} {purchaser_last_name}".strip(),
                "purchaser_nip": purchaser_nip,
                "stripe_url": stripe_url or "",
                "stripe_session_id": stripe_session_id or "",
            },
            direction="internal",
        ))

    return {
        "flow": FLOW_STRIPE,
        "status": "ok" if stripe_url else "stripe_error",
        "order_status": "pending_payment",
        "stripe_url": stripe_url,
        "stripe_session_id": stripe_session_id,
        "stripe_error": stripe_error,
        "email_sent": email_sent,
        "email_error": email_error,
        "mail_tasks": mail_tasks,
    }


# ---------------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------------


def process_backstage_order(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Główna funkcja przetwarzająca webhook z Backstage.
    
    Zwraca dict z:
    - status: "ok" / "error" / "duplicate"
    - order_id: event_order_id
    - flow: FOC / PROFORMA / STRIPE
    - mail_tasks: lista maili do wysłania przez Make
    - wfirma_action: (opcjonalnie) akcja do wykonania w wFirma
    - stripe_action: (opcjonalnie) akcja do wykonania w Stripe
    - error: (opcjonalnie) komunikat błędu
    """
    _log("INFO", "========== NOWY WEBHOOK BACKSTAGE ==========")
    _log("DEBUG", "Otrzymano payload", {"payload_keys": list(payload.keys()) if isinstance(payload, dict) else "not_dict"})
    
    # Loguj pełny payload (do debugowania)
    try:
        payload_str = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        print(f"[BACKSTAGE] [RAW_PAYLOAD] >>>")
        print(payload_str)
        print(f"[BACKSTAGE] [RAW_PAYLOAD] <<<")
    except Exception as e:
        _log("WARN", f"Nie udało się zserializować payload: {e}")
    
    try:
        # 1. Wyciągnij dane zamówienia
        _log("INFO", "Krok 1: Ekstrakcja danych zamówienia...")
        order_data = _extract_order_data(payload)
        event_order_id = order_data["event_order_id"]
        event_id = order_data["event_id"]
        
        _log("INFO", "Wyekstrahowane dane", {
            "event_order_id": event_order_id,
            "event_id": event_id,
            "purchaser_email": order_data.get("purchaser_email"),
            "purchaser_name": f"{order_data.get('purchaser_first_name', '')} {order_data.get('purchaser_last_name', '')}".strip(),
            "total": order_data.get("total"),
            "currency": order_data.get("currency"),
            "payment_option_name": order_data.get("payment_option_name"),
            "payment_type": order_data.get("payment_type"),
        })

        if not event_order_id:
            _log("ERROR", "Brak event_order_id w payload!")
            _send_error_notification(
                error_type="MISSING_ORDER_ID",
                error_message="Webhook Backstage nie zawiera event_order_id. Nie można przetworzyć zamówienia.",
                extra_data={
                    "purchaser_email": order_data.get("purchaser_email", ""),
                    "event_id": order_data.get("event_id", ""),
                },
            )
            return {
                "status": "error",
                "error": "Brak event_order_id w payload",
            }

        if not event_id:
            _log("ERROR", "Brak event_id w payload!")
            _send_error_notification(
                error_type="MISSING_EVENT_ID",
                error_message="Webhook Backstage nie zawiera event_id. Nie można zidentyfikować wydarzenia.",
                event_order_id=event_order_id,
                extra_data={
                    "purchaser_email": order_data.get("purchaser_email", ""),
                },
            )
            return {
                "status": "error",
                "error": "Brak event_id w payload",
            }

        # 2. Sprawdź idempotencję (deduplikacja)
        # W SANDBOX MODE - pozwól na ponowne przetworzenie!
        is_sandbox = order_data.get("sandbox", False)
        _log("INFO", "Krok 2: Sprawdzanie idempotencji...", {"sandbox": is_sandbox})
        
        dedupe_key = _generate_dedupe_key(event_order_id, event_id)
        _log("DEBUG", "Wygenerowany dedupe_key", {"dedupe_key": dedupe_key})
        
        is_new, webhook_record = save_backstage_webhook(
            dedupe_key=dedupe_key,
            event_order_id=event_order_id,
            event_id=event_id,
            payload=payload,
        )

        if not is_new:
            if is_sandbox:
                # SANDBOX: pozwól na ponowne przetworzenie
                _log("INFO", "SANDBOX MODE: Pozwalam na ponowne przetworzenie duplikatu", {"event_order_id": event_order_id})
            else:
                # PRODUKCJA: blokuj duplikaty
                _log("WARN", "Webhook już był przetworzony (duplikat)", {"event_order_id": event_order_id})
                existing_order = get_order(event_order_id)
                return {
                    "status": "duplicate",
                    "order_id": event_order_id,
                    "message": "Webhook już został przetworzony",
                    "existing_status": existing_order.get("status") if existing_order else None,
                }
        
        _log("INFO", "Webhook zapisany do bazy" + (" (sandbox reprocess)" if not is_new and is_sandbox else " (nowy)"))

        # 3. Pobierz konfigurację eventu
        _log("INFO", "Krok 3: Pobieranie konfiguracji eventu...", {"event_id": event_id})
        event_config = _get_event_config(event_id)
        if not event_config:
            # Event nie jest skonfigurowany - zwróć błąd ale zapisz webhook
            _log("ERROR", f"Event {event_id} NIE ZNALEZIONY w bazie!", {"event_id": event_id})
            mark_backstage_webhook_processed(dedupe_key, "failed", f"Event {event_id} nie znaleziony w konfiguracji")
            
            # Wyślij powiadomienie o błędzie
            _send_error_notification(
                error_type="EVENT_NOT_FOUND",
                error_message=f"Event o ID '{event_id}' nie jest skonfigurowany w systemie. Zamówienie nie może być przetworzone.",
                event_order_id=event_order_id,
                event_id=event_id,
                extra_data={
                    "purchaser_email": order_data.get("purchaser_email", ""),
                    "total": order_data.get("total", 0),
                },
            )
            
            return {
                "status": "error",
                "order_id": event_order_id,
                "error": f"Event {event_id} nie jest skonfigurowany w systemie",
            }
        
        _log("INFO", "Event znaleziony", {"event_name": event_config.get("event_name")})

        # 4. Utwórz/zaktualizuj zamówienie w bazie
        _log("INFO", "Krok 4: Tworzenie/aktualizacja zamówienia w bazie...")
        upsert_order(
            event_order_id=event_order_id,
            event_id=event_id,
            purchaser_email=order_data["purchaser_email"],
            purchaser_first_name=order_data["purchaser_first_name"],
            purchaser_last_name=order_data["purchaser_last_name"],
            purchaser_phone=order_data["purchaser_phone"],
            purchaser_nip=order_data["purchaser_nip"],
            payment_option_name=order_data["payment_option_name"],
            payment_type=order_data["payment_type"],
            promo_code=order_data["promo_code"],
            total=order_data["total"],
            currency=order_data["currency"],
            status="received",
            raw=payload,
        )
        _log("INFO", "Zamówienie zapisane w bazie", {"event_order_id": event_order_id, "status": "received"})

        # 4b. Zapisz uczestników (sloty biletów)
        try:
            individual_tickets = _extract_individual_tickets_for_participants(payload)
            attendees = _extract_attendees_from_payload(payload)
            
            if individual_tickets:
                participant_stats = _save_participants_for_order(
                    event_order_id=event_order_id,
                    purchaser_data={
                        "purchaser_email": order_data["purchaser_email"],
                        "purchaser_first_name": order_data["purchaser_first_name"],
                        "purchaser_last_name": order_data["purchaser_last_name"],
                        "purchaser_phone": order_data["purchaser_phone"],
                    },
                    individual_tickets=individual_tickets,
                    attendees=attendees,
                )
                _log("INFO", "Uczestnicy zapisani", {
                    "event_order_id": event_order_id,
                    "tickets_count": len(individual_tickets),
                    "attendees_from_payload": len(attendees),
                    "saved": participant_stats.get("saved", 0),
                    "registered": participant_stats.get("registered", 0),
                    "pending": participant_stats.get("pending", 0),
                })
            else:
                _log("DEBUG", "Brak indywidualnych biletów do zapisania uczestników", {"event_order_id": event_order_id})
        except Exception as e:
            _log("WARNING", "Błąd zapisywania uczestników", {"event_order_id": event_order_id, "error": str(e)})

        # 5. Określ flow
        _log("INFO", "Krok 5: Określanie flow płatności...")
        flow, rule = _determine_flow(order_data)
        _log("INFO", "Flow określony", {
            "flow": flow,
            "rule_id": rule.get("id") if rule else None,
            "rule_pattern": rule.get("payment_option_name_pattern") if rule else None,
            "total": order_data.get("total"),
            "payment_option_name": order_data.get("payment_option_name"),
        })
        # Dodatkowy log pod debug PROFORMA: pokaż „wejście” które decyduje
        _log("INFO", "FLOW DECISION SUMMARY", {
            "event_order_id": event_order_id,
            "event_id": event_id,
            "flow": flow,
            "payment_option_name": order_data.get("payment_option_name"),
            "payment_type": order_data.get("payment_type"),
            "total": order_data.get("total"),
            "rule_matched": bool(rule),
            "rule_flow": rule.get("flow") if rule else None,
        })

        # 6. Wykonaj odpowiedni handler
        _log("INFO", f"Krok 6: Wykonywanie handlera dla flow={flow}...")
        if flow == FLOW_FOC:
            result = _handle_foc_flow(order_data, event_config)
        elif flow == FLOW_PROFORMA:
            result = _handle_proforma_flow(order_data, event_config, rule)
        elif flow == FLOW_STRIPE:
            result = _handle_stripe_flow(order_data, event_config, rule)
        else:
            _log("ERROR", f"Nieznany flow: {flow}")
            
            # Wyślij powiadomienie o błędzie
            _send_error_notification(
                error_type="UNKNOWN_FLOW",
                error_message=f"Nieznany flow płatności: '{flow}'. Sprawdź konfigurację reguł płatności.",
                event_order_id=event_order_id,
                event_id=event_id,
                extra_data={
                    "flow": flow,
                    "event_name": event_config.get("event_name", ""),
                    "payment_option_name": order_data.get("payment_option_name", ""),
                    "total": order_data.get("total", 0),
                },
            )
            
            result = {
                "flow": flow,
                "status": "error",
                "error": f"Nieznany flow: {flow}",
            }
        
        _log("INFO", "Handler zakończony", {
            "flow": flow,
            "order_status": result.get("order_status"),
            "mail_tasks_count": len(result.get("mail_tasks", [])),
        })

        # 7. Zapisz mail tasks do logu
        _log("INFO", "Krok 7: Zapisywanie mail tasks...")
        for i, mt in enumerate(result.get("mail_tasks", [])):
            save_mail_log(
                event_order_id=event_order_id,
                direction=mt.get("direction", "purchaser"),
                template_key=mt.get("template", ""),
                to_email=mt.get("to", ""),
                subject=mt.get("subject", ""),
                data=mt.get("data", {}),
            )
            _log("DEBUG", f"Mail task {i+1} zapisany", {
                "template": mt.get("template"),
                "to": mt.get("to"),
                "direction": mt.get("direction"),
            })

        # 8. Oznacz webhook jako przetworzony
        mark_backstage_webhook_processed(dedupe_key, "processed")
        _log("INFO", "Krok 8: Webhook oznaczony jako przetworzony")
        
        _log("INFO", "========== WEBHOOK PRZETWORZONY POMYŚLNIE ==========", {
            "event_order_id": event_order_id,
            "flow": flow,
            "status": "ok",
        })

        return {
            "status": "ok",
            "order_id": event_order_id,
            **result,
        }

    except Exception as e:
        _log("ERROR", f"WYJĄTEK podczas przetwarzania: {str(e)}", {"exception": str(e)})
        import traceback
        tb = traceback.format_exc()
        _log("ERROR", f"Traceback: {tb}")
        
        # Wyślij powiadomienie o wyjątku
        _send_error_notification(
            error_type="EXCEPTION",
            error_message=f"Wyjątek podczas przetwarzania webhooka Backstage:\n{str(e)}\n\nTraceback:\n{tb[:1000]}",
            event_order_id=order_data.get("event_order_id", "") if 'order_data' in dir() else "",
            event_id=order_data.get("event_id", "") if 'order_data' in dir() else "",
        )
        
        return {
            "status": "error",
            "error": str(e),
        }
