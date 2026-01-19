"""
Backstage Engine - obsługa webhooków z Zoho Backstage.
Odpowiada za routing płatności (FOC / PROFORMA / STRIPE) i generowanie mail_tasks.
"""
import hashlib
import json
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

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
    Obsługuje różne warianty struktury (raw/nested).
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

    # Pobierz dane z buyer_details (Backstage format)
    buyer_details = raw.get("buyer_details") or []
    buyer_form = {}
    if buyer_details and isinstance(buyer_details, list) and len(buyer_details) > 0:
        buyer_form = buyer_details[0].get("formEntries") or {}

    # purchaser info - próbuj z różnych źródeł
    purchaser_email = (
        payload.get("purchaser_email")  # Top level w webhook
        or raw.get("purchaser_email")
        or raw.get("purchaserEmail")
        or buyer_form.get("purchaser_email")
        or raw.get("eventOrder_orderBy")  # Backstage: email zamawiającego
        or ""
    )
    purchaser_first_name = (
        raw.get("purchaser_first_name")
        or raw.get("purchaserFirstName")
        or buyer_form.get("purchaser_first_name")
        or payload.get("purchaser_first_name")
        or ""
    )
    purchaser_last_name = (
        raw.get("purchaser_last_name")
        or raw.get("purchaserLastName")
        or buyer_form.get("purchaser_last_name")
        or payload.get("purchaser_last_name")
        or ""
    )
    purchaser_phone = (
        raw.get("purchaser_phone")
        or raw.get("purchaserPhone")
        or buyer_form.get("purchaser_mobile_no")  # Backstage format
        or buyer_form.get("purchaser_phone")
        or payload.get("purchaser_phone")
        or ""
    )

    # NIP - może być w custom fields lub buyer_form
    purchaser_nip = (
        raw.get("purchaser_nip")
        or raw.get("nip")
        or raw.get("NIP")
        or buyer_form.get("nip")
        or buyer_form.get("NIP")
        or buyer_form.get("purchaser_nip")
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
        or raw.get("payment_option_name")
        or raw.get("paymentOptionName")
        or ""
    )
    payment_type_raw = (
        raw.get("eventOrder_paymentType")
        or raw.get("payment_type")
        or raw.get("paymentType")
    )
    payment_type = int(payment_type_raw) if payment_type_raw is not None else None

    # total / kwota - może być na top level lub w raw
    total_raw = (
        payload.get("total")  # Top level w webhook
        or raw.get("total")
        or raw.get("orderCost_grandTotal")  # Backstage format
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
        or ""
    )

    # currency
    currency = (
        raw.get("currency")
        or raw.get("eventOrder_currency")
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
    - Ustawia status na 'pending_payment'
    - Zwraca dane do utworzenia Stripe Checkout Session
    - Generuje mail z linkiem do płatności
    """
    event_order_id = order_data["event_order_id"]
    purchaser_email = order_data["purchaser_email"]
    event_name = (event_config.get("event_name") if event_config else "") or "Wydarzenie"
    event_data = (event_config.get("data") if event_config else {}) or {}

    # Aktualizuj status zamówienia
    update_order_status(event_order_id, "pending_payment")

    # URLs dla Stripe
    success_url = event_data.get("url_success") or event_data.get("url_event") or ""
    cancel_url = event_data.get("url_cancel") or event_data.get("url_event") or ""

    mail_tasks = []

    # Mail do kupującego z linkiem do płatności
    # Placeholder - Make doda stripe_url po utworzeniu sesji
    if purchaser_email:
        mail_tasks.append(_build_mail_task(
            template_key=TEMPLATE_STRIPE_PAYMENT_LINK,
            to_email=purchaser_email,
            subject=f"Link do płatności – {event_name}",
            data={
                "event_order_id": event_order_id,
                "event_name": event_name,
                "purchaser_name": f"{order_data.get('purchaser_first_name', '')} {order_data.get('purchaser_last_name', '')}".strip(),
                "purchaser_email": purchaser_email,
                "total": order_data.get("total", 0),
                "currency": order_data.get("currency", "PLN"),
                "purchaser_nip": order_data.get("purchaser_nip", ""),
                # Placeholder - Make/Stripe doda:
                # "stripe_url": "https://checkout.stripe.com/...",
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
                "total": order_data.get("total", 0),
                "currency": order_data.get("currency", "PLN"),
                "purchaser_email": purchaser_email,
                "purchaser_name": f"{order_data.get('purchaser_first_name', '')} {order_data.get('purchaser_last_name', '')}".strip(),
                "purchaser_nip": order_data.get("purchaser_nip", ""),
            },
            direction="internal",
        ))

    return {
        "flow": FLOW_STRIPE,
        "status": "pending_stripe",
        "order_status": "pending_payment",
        "stripe_action": {
            "action": "create_checkout_session",
            "checkout_data": {
                "event_order_id": event_order_id,
                "amount": int(order_data.get("total", 0) * 100),  # grosze/cents
                "currency": order_data.get("currency", "PLN").lower(),
                "customer_email": purchaser_email,
                "description": f"{event_name} - {event_order_id}",
                "success_url": success_url + (f"?order_id={event_order_id}" if success_url else ""),
                "cancel_url": cancel_url + (f"?order_id={event_order_id}" if cancel_url else ""),
                "metadata": {
                    "event_order_id": event_order_id,
                    "event_id": order_data.get("event_id", ""),
                    "event_name": event_name,
                },
            },
        },
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
    try:
        # 1. Wyciągnij dane zamówienia
        order_data = _extract_order_data(payload)
        event_order_id = order_data["event_order_id"]
        event_id = order_data["event_id"]

        if not event_order_id:
            return {
                "status": "error",
                "error": "Brak event_order_id w payload",
            }

        if not event_id:
            return {
                "status": "error",
                "error": "Brak event_id w payload",
            }

        # 2. Sprawdź idempotencję (deduplikacja)
        dedupe_key = _generate_dedupe_key(event_order_id, event_id)
        is_new, webhook_record = save_backstage_webhook(
            dedupe_key=dedupe_key,
            event_order_id=event_order_id,
            event_id=event_id,
            payload=payload,
        )

        if not is_new:
            # Webhook już był przetworzony
            existing_order = get_order(event_order_id)
            return {
                "status": "duplicate",
                "order_id": event_order_id,
                "message": "Webhook już został przetworzony",
                "existing_status": existing_order.get("status") if existing_order else None,
            }

        # 3. Pobierz konfigurację eventu
        event_config = _get_event_config(event_id)
        if not event_config:
            # Event nie jest skonfigurowany - zwróć błąd ale zapisz webhook
            mark_backstage_webhook_processed(dedupe_key, "failed", f"Event {event_id} nie znaleziony w konfiguracji")
            return {
                "status": "error",
                "order_id": event_order_id,
                "error": f"Event {event_id} nie jest skonfigurowany w systemie",
            }

        # 4. Utwórz/zaktualizuj zamówienie w bazie
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

        # 5. Określ flow
        flow, rule = _determine_flow(order_data)

        # 6. Wykonaj odpowiedni handler
        if flow == FLOW_FOC:
            result = _handle_foc_flow(order_data, event_config)
        elif flow == FLOW_PROFORMA:
            result = _handle_proforma_flow(order_data, event_config, rule)
        elif flow == FLOW_STRIPE:
            result = _handle_stripe_flow(order_data, event_config, rule)
        else:
            result = {
                "flow": flow,
                "status": "error",
                "error": f"Nieznany flow: {flow}",
            }

        # 7. Zapisz mail tasks do logu
        for mt in result.get("mail_tasks", []):
            save_mail_log(
                event_order_id=event_order_id,
                direction=mt.get("direction", "purchaser"),
                template_key=mt.get("template", ""),
                to_email=mt.get("to", ""),
                subject=mt.get("subject", ""),
                data=mt.get("data", {}),
            )

        # 8. Oznacz webhook jako przetworzony
        mark_backstage_webhook_processed(dedupe_key, "processed")

        return {
            "status": "ok",
            "order_id": event_order_id,
            **result,
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }
