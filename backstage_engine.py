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

    return {
        "event_order_id": str(event_order_id).strip(),
        "event_id": str(event_id).strip(),
        "purchaser_email": str(purchaser_email).strip(),
        "purchaser_first_name": str(purchaser_first_name).strip(),
        "purchaser_last_name": str(purchaser_last_name).strip(),
        "purchaser_phone": str(purchaser_phone).strip(),
        "purchaser_nip": str(purchaser_nip).strip(),
        "payment_option_name": str(payment_option_name).strip(),
        "payment_type": payment_type,
        "total": total,
        "promo_code": str(promo_code).strip(),
        "currency": str(currency).strip().upper() or "PLN",
        "sandbox": sandbox,
    }


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

    # 1. Jeśli total = 0 → zawsze FOC
    if total == 0 or total is None:
        return FLOW_FOC, None

    # 2. Spróbuj dopasować regułę z bazy
    rule = match_payment_rule(event_id, payment_option_name, payment_type)
    if rule:
        return rule.get("flow", FLOW_STRIPE), rule

    # 3. Fallback: heurystyka na podstawie nazwy opcji płatności
    payment_option_lower = payment_option_name.lower()
    if "pro-forma" in payment_option_lower or "proforma" in payment_option_lower:
        return FLOW_PROFORMA, None
    if "online" in payment_option_lower or "karta" in payment_option_lower:
        return FLOW_STRIPE, None

    # 4. Domyślnie: STRIPE
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
# FLOW HANDLERS
# ---------------------------------------------------------------------------


def _handle_foc_flow(
    order_data: Dict[str, Any],
    event_config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Obsługuje flow FOC (Free of Charge).
    - Ustawia status na 'paid' (darmowe)
    - Generuje mail z potwierdzeniem rejestracji
    """
    event_order_id = order_data["event_order_id"]
    purchaser_email = order_data["purchaser_email"]
    event_name = (event_config.get("event_name") if event_config else "") or "Wydarzenie"
    event_data = (event_config.get("data") if event_config else {}) or {}

    # Aktualizuj status zamówienia na 'paid' (darmowe = od razu opłacone)
    update_order_status(event_order_id, "paid")

    mail_tasks = []

    # Mail do kupującego: potwierdzenie rejestracji
    if purchaser_email:
        mail_tasks.append(_build_mail_task(
            template_key=TEMPLATE_REGISTRATION_CONFIRMATION,
            to_email=purchaser_email,
            subject=f"Potwierdzenie rejestracji – {event_name}",
            data={
                "event_order_id": event_order_id,
                "event_name": event_name,
                "purchaser_name": f"{order_data.get('purchaser_first_name', '')} {order_data.get('purchaser_last_name', '')}".strip(),
                "purchaser_email": purchaser_email,
                **event_data,  # Dodaj wszystkie dane eventu (banery, linki, etc.)
            },
            direction="purchaser",
        ))

    # Mail wewnętrzny: powiadomienie o zamówieniu
    internal_email = event_data.get("md_email_techniczny") or event_data.get("md_email_kontakt")
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
                "purchaser_name": f"{order_data.get('purchaser_first_name', '')} {order_data.get('purchaser_last_name', '')}".strip(),
            },
            direction="internal",
        ))

    return {
        "flow": FLOW_FOC,
        "status": "completed",
        "order_status": "paid",
        "mail_tasks": mail_tasks,
    }


def _handle_proforma_flow(
    order_data: Dict[str, Any],
    event_config: Optional[Dict[str, Any]],
    rule: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Obsługuje flow PROFORMA.
    - Ustawia status na 'pending_payment'
    - Zwraca dane do wystawienia proformy w wFirma (Make wywołuje osobno)
    - Generuje mail z proformą (po wystawieniu przez Make/wFirma)
    """
    event_order_id = order_data["event_order_id"]
    purchaser_email = order_data["purchaser_email"]
    event_name = (event_config.get("event_name") if event_config else "") or "Wydarzenie"
    event_data = (event_config.get("data") if event_config else {}) or {}

    # Aktualizuj status zamówienia
    update_order_status(event_order_id, "pending_payment")

    # Konfiguracja wFirma z reguły
    wfirma_config = {
        "company": (rule.get("wfirma_company") if rule else None) or "md",
        "document_type": (rule.get("wfirma_document_type") if rule else None) or "proforma",
        "series_name": (rule.get("wfirma_series_name") if rule else None),
        "payment_due_days": (rule.get("wfirma_payment_due_days") if rule else None) or 14,
    }

    mail_tasks = []

    # Mail do kupującego będzie wysłany PO wystawieniu proformy
    # Na razie zwracamy placeholder - Make wywoła endpoint wFirma i doda PDF
    if purchaser_email:
        mail_tasks.append(_build_mail_task(
            template_key=TEMPLATE_PROFORMA_SENT,
            to_email=purchaser_email,
            subject=f"Faktura pro-forma – {event_name}",
            data={
                "event_order_id": event_order_id,
                "event_name": event_name,
                "purchaser_name": f"{order_data.get('purchaser_first_name', '')} {order_data.get('purchaser_last_name', '')}".strip(),
                "purchaser_email": purchaser_email,
                "total": order_data.get("total", 0),
                "currency": order_data.get("currency", "PLN"),
                "purchaser_nip": order_data.get("purchaser_nip", ""),
                # Placeholder - Make doda po wystawieniu proformy:
                # "proforma_number": "...",
                # "proforma_pdf_url": "...",
                **event_data,
            },
            direction="purchaser",
        ))

    # Mail wewnętrzny
    internal_email = event_data.get("md_email_techniczny") or event_data.get("md_email_kontakt")
    if internal_email:
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
            },
            direction="internal",
        ))

    return {
        "flow": FLOW_PROFORMA,
        "status": "pending_wfirma",
        "order_status": "pending_payment",
        "wfirma_action": {
            "action": "create_proforma",
            "config": wfirma_config,
            "invoice_data": {
                "purchaser_email": purchaser_email,
                "purchaser_first_name": order_data.get("purchaser_first_name", ""),
                "purchaser_last_name": order_data.get("purchaser_last_name", ""),
                "purchaser_nip": order_data.get("purchaser_nip", ""),
                "total": order_data.get("total", 0),
                "currency": order_data.get("currency", "PLN"),
                "event_name": event_name,
                "event_order_id": event_order_id,
            },
        },
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

    # 1. Utwórz sesję Stripe Checkout
    _log("INFO", "STRIPE FLOW: Tworzę sesję Stripe Checkout...", {"sandbox": is_sandbox})
    
    session_data, error = create_checkout_session(
        event_order_id=event_order_id,
        amount_cents=int(total * 100),
        currency=currency.lower(),
        customer_email=purchaser_email,
        description=f"{event_name} - {event_order_id}",
        success_url=success_url + (f"?order_id={event_order_id}" if "?" not in success_url else f"&order_id={event_order_id}"),
        cancel_url=cancel_url + (f"?order_id={event_order_id}" if "?" not in cancel_url else f"&order_id={event_order_id}"),
        metadata={
            "event_order_id": event_order_id,
            "event_id": order_data.get("event_id", ""),
            "event_name": event_name,
        },
        sandbox=is_sandbox,
    )
    
    if error:
        _log("ERROR", f"STRIPE FLOW: Błąd tworzenia sesji: {error}")
        stripe_error = error
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
        
        # Określ typ szablonu (personal / nip_valid / nip_invalid)
        template_type = "personal"
        gus_data = None
        
        if purchaser_nip:
            # TODO: Można tu dodać weryfikację NIP przez GUS
            # Na razie zakładamy że NIP jest poprawny jeśli podany
            template_type = "nip_valid"
            gus_data = {
                "name": f"{purchaser_first_name} {purchaser_last_name}".strip() or "Firma",
                "street": "",
                "zip": "",
                "city": "",
                "regon": "",
            }
        
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
            tickets=[],  # TODO: Ekstrakcja biletów z payload
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

    # Mail wewnętrzny
    internal_email = event_data.get("md_email_techniczny") or event_data.get("md_email_kontakt")
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
            return {
                "status": "error",
                "error": "Brak event_order_id w payload",
            }

        if not event_id:
            _log("ERROR", "Brak event_id w payload!")
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
        _log("ERROR", f"Traceback: {traceback.format_exc()}")
        return {
            "status": "error",
            "error": str(e),
        }
