"""
Stripe Integration - tworzenie Checkout Sessions i obsługa webhooków.
Używa STRIPE_RENDER_API_KEY z ENV (produkcyjny klucz Stripe).
"""
import os
import hmac
import hashlib
from typing import Any, Dict, Optional, Tuple

try:
    import stripe
except ImportError:
    stripe = None  # type: ignore

from pg_storage import (
    get_order,
    update_order_status,
    save_stripe_session,
    get_stripe_session_by_checkout_id,
    update_stripe_session_paid,
    save_wfirma_document,
    save_mail_log,
    get_event,
)


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

STRIPE_API_KEY = os.environ.get("STRIPE_RENDER_API_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")  # Do weryfikacji podpisu webhooka

# Inicjalizacja Stripe
if stripe and STRIPE_API_KEY:
    stripe.api_key = STRIPE_API_KEY


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------


def is_stripe_configured() -> bool:
    """Sprawdza czy Stripe jest poprawnie skonfigurowany."""
    return bool(stripe and STRIPE_API_KEY)


def _get_stripe_status() -> Dict[str, Any]:
    """Zwraca status konfiguracji Stripe."""
    return {
        "stripe_library_available": stripe is not None,
        "stripe_api_key_present": bool(STRIPE_API_KEY),
        "stripe_webhook_secret_present": bool(STRIPE_WEBHOOK_SECRET),
        "configured": is_stripe_configured(),
    }


# ---------------------------------------------------------------------------
# CHECKOUT SESSION
# ---------------------------------------------------------------------------


def create_checkout_session(
    event_order_id: str,
    amount_cents: int,
    currency: str = "pln",
    customer_email: Optional[str] = None,
    description: Optional[str] = None,
    success_url: str = "",
    cancel_url: str = "",
    metadata: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Tworzy Stripe Checkout Session.
    
    Args:
        event_order_id: ID zamówienia z Backstage
        amount_cents: Kwota w groszach/centach
        currency: Waluta (domyślnie PLN)
        customer_email: Email klienta (opcjonalnie)
        description: Opis płatności
        success_url: URL przekierowania po udanej płatności
        cancel_url: URL przekierowania po anulowaniu
        metadata: Dodatkowe dane do zapisania w Stripe
    
    Returns:
        (session_data, error) - session_data zawiera checkout_session_id, url
    """
    if not is_stripe_configured():
        return None, "Stripe nie jest skonfigurowany (brak STRIPE_RENDER_API_KEY)"
    
    if amount_cents <= 0:
        return None, "Kwota musi być większa od 0"
    
    try:
        # Przygotuj metadata
        meta = metadata or {}
        meta["event_order_id"] = event_order_id
        
        # Przygotuj line_items
        line_items = [{
            "price_data": {
                "currency": currency.lower(),
                "unit_amount": amount_cents,
                "product_data": {
                    "name": description or f"Zamówienie {event_order_id}",
                },
            },
            "quantity": 1,
        }]
        
        # Parametry sesji
        session_params = {
            "payment_method_types": ["card", "blik", "p24"],  # Karty, BLIK, Przelewy24
            "line_items": line_items,
            "mode": "payment",
            "metadata": meta,
            "client_reference_id": event_order_id,
        }
        
        # Dodaj opcjonalne parametry
        if customer_email:
            session_params["customer_email"] = customer_email
        if success_url:
            session_params["success_url"] = success_url
        if cancel_url:
            session_params["cancel_url"] = cancel_url
        
        # Utwórz sesję
        session = stripe.checkout.Session.create(**session_params)
        
        # Zapisz do bazy
        save_stripe_session(
            event_order_id=event_order_id,
            checkout_session_id=session.id,
            url=session.url,
            amount_total=amount_cents / 100.0,
            currency=currency.upper(),
            raw={"session_id": session.id, "url": session.url},
        )
        
        return {
            "checkout_session_id": session.id,
            "url": session.url,
            "amount_cents": amount_cents,
            "currency": currency.upper(),
        }, None
        
    except stripe.error.StripeError as e:
        return None, f"Stripe error: {str(e)}"
    except Exception as e:
        return None, f"Error: {str(e)}"


# ---------------------------------------------------------------------------
# WEBHOOK HANDLING
# ---------------------------------------------------------------------------


def verify_webhook_signature(payload: bytes, signature: str) -> Tuple[bool, Optional[str]]:
    """
    Weryfikuje podpis webhooka Stripe.
    
    Args:
        payload: Raw body requestu
        signature: Header Stripe-Signature
    
    Returns:
        (is_valid, error_message)
    """
    if not STRIPE_WEBHOOK_SECRET:
        # Jeśli brak sekretu - przepuść bez weryfikacji (dev mode)
        return True, None
    
    try:
        stripe.Webhook.construct_event(
            payload, signature, STRIPE_WEBHOOK_SECRET
        )
        return True, None
    except stripe.error.SignatureVerificationError as e:
        return False, f"Invalid signature: {str(e)}"
    except Exception as e:
        return False, f"Verification error: {str(e)}"


def handle_checkout_completed(session_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Obsługuje event checkout.session.completed.
    
    Args:
        session_data: Dane sesji z webhooka Stripe
    
    Returns:
        Dict z wynikiem przetwarzania
    """
    checkout_session_id = session_data.get("id")
    payment_intent_id = session_data.get("payment_intent")
    metadata = session_data.get("metadata") or {}
    event_order_id = metadata.get("event_order_id") or session_data.get("client_reference_id")
    
    if not checkout_session_id:
        return {"status": "error", "error": "Brak checkout_session_id"}
    
    if not event_order_id:
        return {"status": "error", "error": "Brak event_order_id w metadata/client_reference_id"}
    
    # Sprawdź czy sesja istnieje w bazie
    existing = get_stripe_session_by_checkout_id(checkout_session_id)
    if existing and existing.get("status") == "paid":
        return {
            "status": "duplicate",
            "message": "Płatność już została przetworzona",
            "order_id": event_order_id,
        }
    
    # Oznacz sesję jako opłaconą
    update_stripe_session_paid(checkout_session_id, payment_intent_id)
    
    # Aktualizuj status zamówienia
    update_order_status(event_order_id, "paid")
    
    # Pobierz dane zamówienia i eventu do mail tasks
    order = get_order(event_order_id)
    event_config = None
    if order:
        ev = get_event(order.get("event_id", ""))
        if ev:
            event_config = {
                "event_name": ev.get("event_name", ""),
                "data": ev.get("data") or {},
            }
    
    # Przygotuj mail tasks
    mail_tasks = []
    
    event_name = (event_config.get("event_name") if event_config else "") or "Wydarzenie"
    event_data = (event_config.get("data") if event_config else {}) or {}
    purchaser_email = order.get("purchaser_email", "") if order else ""
    purchaser_name = ""
    if order:
        purchaser_name = f"{order.get('purchaser_first_name', '')} {order.get('purchaser_last_name', '')}".strip()
    
    # Mail do kupującego: potwierdzenie płatności
    if purchaser_email:
        mail_task = {
            "template": "payment_confirmation",
            "to": purchaser_email,
            "subject": f"Potwierdzenie płatności – {event_name}",
            "direction": "purchaser",
            "data": {
                "event_order_id": event_order_id,
                "event_name": event_name,
                "purchaser_name": purchaser_name,
                "purchaser_email": purchaser_email,
                "total": order.get("total", 0) if order else 0,
                "currency": order.get("currency", "PLN") if order else "PLN",
                "payment_method": "Stripe",
                **event_data,
            },
        }
        mail_tasks.append(mail_task)
        
        # Zapisz do logu
        save_mail_log(
            event_order_id=event_order_id,
            direction="purchaser",
            template_key="payment_confirmation",
            to_email=purchaser_email,
            subject=mail_task["subject"],
            data=mail_task["data"],
        )
    
    # Mail wewnętrzny
    internal_email = event_data.get("md_email_techniczny") or event_data.get("md_email_kontakt")
    if internal_email:
        internal_task = {
            "template": "internal_order_paid",
            "to": internal_email,
            "subject": f"[PAID] Zamówienie opłacone – {event_name}",
            "direction": "internal",
            "data": {
                "event_order_id": event_order_id,
                "event_name": event_name,
                "purchaser_name": purchaser_name,
                "purchaser_email": purchaser_email,
                "total": order.get("total", 0) if order else 0,
                "currency": order.get("currency", "PLN") if order else "PLN",
                "payment_method": "Stripe",
                "checkout_session_id": checkout_session_id,
            },
        }
        mail_tasks.append(internal_task)
        
        save_mail_log(
            event_order_id=event_order_id,
            direction="internal",
            template_key="internal_order_paid",
            to_email=internal_email,
            subject=internal_task["subject"],
            data=internal_task["data"],
        )
    
    return {
        "status": "ok",
        "order_id": event_order_id,
        "order_status": "paid",
        "checkout_session_id": checkout_session_id,
        "payment_intent_id": payment_intent_id,
        "mail_tasks": mail_tasks,
        "wfirma_action": {
            "action": "create_paid_invoice",
            "invoice_data": {
                "event_order_id": event_order_id,
                "purchaser_email": purchaser_email,
                "purchaser_first_name": order.get("purchaser_first_name", "") if order else "",
                "purchaser_last_name": order.get("purchaser_last_name", "") if order else "",
                "purchaser_nip": order.get("purchaser_nip", "") if order else "",
                "total": order.get("total", 0) if order else 0,
                "currency": order.get("currency", "PLN") if order else "PLN",
                "event_name": event_name,
            },
        },
    }


def process_webhook_event(event_type: str, event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Przetwarza event z webhooka Stripe.
    
    Args:
        event_type: Typ eventu (np. checkout.session.completed)
        event_data: Dane eventu (object z webhooka)
    
    Returns:
        Dict z wynikiem przetwarzania
    """
    if event_type == "checkout.session.completed":
        return handle_checkout_completed(event_data)
    
    # Inne eventy - ignorujemy na razie
    return {
        "status": "ignored",
        "event_type": event_type,
        "message": f"Event type {event_type} nie jest obsługiwany",
    }
