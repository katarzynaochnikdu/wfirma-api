"""
Stripe Integration - tworzenie Checkout Sessions i obsługa webhooków.
Używa STRIPE_RENDER_API_KEY z ENV (produkcyjny klucz Stripe).
"""
import os
import hmac
import hashlib
import requests
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

# Produkcja
STRIPE_API_KEY = os.environ.get("STRIPE_RENDER_API_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

# Sandbox (testowy)
STRIPE_SANDBOX_API_KEY = os.environ.get("STRIPE_RENDER_API_KEY_SANDBOX")
STRIPE_SANDBOX_WEBHOOK_SECRET = os.environ.get("STRIPE_SANDBOX_WEBHOOK_SECRET")

# Email wewnętrzny - info techniczne
BACKSTAGE_TECHNICAL_INFO_EMAIL = os.environ.get("BACKSTAGE_TECHNICAL_INFO_EMAIL", "")

# Make.com webhook do wysyłki emaili
MAKE_WEBHOOK_SEND_EMAIL_REQUEST = os.environ.get("MAKE_WEBHOOK_SEND_EMAIL_REQUEST", "")
RENDER_EMAIL_KEY_SEND_REQUEST = os.environ.get("RENDER_EMAIL_KEY_SEND_REQUEST", "")

# Inicjalizacja Stripe (domyślnie produkcja)
if stripe and STRIPE_API_KEY:
    stripe.api_key = STRIPE_API_KEY


def _send_email_via_make_stripe(
    to_email: str,
    subject: str,
    body_html: str,
    event_order_id: str = "",
    template_type: str = "",
) -> Dict[str, Any]:
    """
    Wysyła email przez webhook Make.com (dla Stripe webhooków).
    """
    if not MAKE_WEBHOOK_SEND_EMAIL_REQUEST or not RENDER_EMAIL_KEY_SEND_REQUEST:
        print(f"[STRIPE EMAIL] Make webhook nie skonfigurowany")
        return {"success": False, "error": "Make webhook nie skonfigurowany"}
    
    print(f"[STRIPE EMAIL] Wysyłam email przez Make | to={to_email}, template={template_type}")
    
    try:
        payload = {
            "to": to_email,
            "subject": subject,
            "body_html": body_html,
            "event_order_id": event_order_id,
            "template_type": template_type,
        }
        
        headers = {
            "Content-Type": "application/json",
            "x-make-apikey": RENDER_EMAIL_KEY_SEND_REQUEST,
        }
        
        response = requests.post(
            MAKE_WEBHOOK_SEND_EMAIL_REQUEST,
            json=payload,
            headers=headers,
            timeout=30,
        )
        
        print(f"[STRIPE EMAIL] Make response: {response.status_code} | {response.text[:200]}")
        
        return {
            "success": response.status_code in (200, 202),
            "status_code": response.status_code,
            "response": response.text[:500],
        }
        
    except Exception as e:
        print(f"[STRIPE EMAIL] Błąd wysyłki: {e}")
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------


def _get_api_key(sandbox: bool = False) -> Optional[str]:
    """Zwraca odpowiedni klucz API (sandbox lub produkcja)."""
    return STRIPE_SANDBOX_API_KEY if sandbox else STRIPE_API_KEY


def _get_webhook_secret(sandbox: bool = False) -> Optional[str]:
    """Zwraca odpowiedni sekret webhooka (sandbox lub produkcja)."""
    return STRIPE_SANDBOX_WEBHOOK_SECRET if sandbox else STRIPE_WEBHOOK_SECRET


def is_stripe_configured(sandbox: bool = False) -> bool:
    """Sprawdza czy Stripe jest poprawnie skonfigurowany."""
    api_key = _get_api_key(sandbox)
    return bool(stripe and api_key)


def _get_stripe_status(sandbox: bool = False) -> Dict[str, Any]:
    """Zwraca status konfiguracji Stripe."""
    api_key = _get_api_key(sandbox)
    webhook_secret = _get_webhook_secret(sandbox)
    mode = "sandbox" if sandbox else "live"
    return {
        "mode": mode,
        "stripe_library_available": stripe is not None,
        "stripe_api_key_present": bool(api_key),
        "stripe_webhook_secret_present": bool(webhook_secret),
        "configured": is_stripe_configured(sandbox),
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
    sandbox: bool = False,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Tworzy Stripe Checkout Session.
    
    Args:
        event_order_id: ID zamówienia z Backstage
        amount_cents: Kwota w groszach/centach
        currency: Waluta (domyślnie PLN)
        sandbox: Użyj klucza testowego (STRIPE_RENDER_API_KEY_SANDBOX)
        customer_email: Email klienta (opcjonalnie)
        description: Opis płatności
        success_url: URL przekierowania po udanej płatności
        cancel_url: URL przekierowania po anulowaniu
        metadata: Dodatkowe dane do zapisania w Stripe
    
    Returns:
        (session_data, error) - session_data zawiera checkout_session_id, url
    """
    if not is_stripe_configured(sandbox):
        mode = "sandbox" if sandbox else "produkcyjny"
        key_name = "STRIPE_RENDER_API_KEY_SANDBOX" if sandbox else "STRIPE_RENDER_API_KEY"
        return None, f"Stripe ({mode}) nie jest skonfigurowany (brak {key_name})"
    
    if amount_cents <= 0:
        return None, "Kwota musi być większa od 0"
    
    try:
        # Ustaw klucz API dla tego requestu
        api_key = _get_api_key(sandbox)
        stripe.api_key = api_key
        
        # Przygotuj metadata
        meta = metadata or {}
        meta["event_order_id"] = event_order_id
        meta["stripe_mode"] = "sandbox" if sandbox else "live"
        
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


def verify_webhook_signature(payload: bytes, signature: str, sandbox: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Weryfikuje podpis webhooka Stripe.
    
    Args:
        payload: Raw body requestu
        signature: Header Stripe-Signature
        sandbox: Czy używać sekretu sandbox
    
    Returns:
        (is_valid, error_message)
    """
    webhook_secret = _get_webhook_secret(sandbox)
    if not webhook_secret:
        # Jeśli brak sekretu - przepuść bez weryfikacji (dev mode)
        return True, None
    
    try:
        stripe.Webhook.construct_event(
            payload, signature, webhook_secret
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
    
    # Dane do emaili
    total_value = order.get("total", 0) if order else 0
    currency_value = order.get("currency", "PLN") if order else "PLN"
    internal_email = BACKSTAGE_TECHNICAL_INFO_EMAIL or event_data.get("md_email_techniczny") or event_data.get("md_email_kontakt")
    
    # Wyciągnij i wzbogać bilety do tabeli w emailu
    tickets_table_html = ""
    enriched_tickets = []
    try:
        from backstage_engine import _extract_tickets_from_payload, _enrich_tickets_with_names
        from email_templates import generate_tickets_table_rows, format_currency
        
        raw_payload = order.get("raw", {}) if order else {}
        raw_tickets = _extract_tickets_from_payload(raw_payload) if raw_payload else []
        event_id_for_tickets = order.get("event_id", "") if order else ""
        
        if raw_tickets:
            enriched_tickets, unknown_ids = _enrich_tickets_with_names(raw_tickets, event_id_for_tickets)
            
            # Przygotuj bilety do tabeli (format: name, quantity, price)
            tickets_for_table = []
            for t in enriched_tickets:
                tickets_for_table.append({
                    "name": t.get("name", "Bilet"),
                    "quantity": t.get("quantity", 1),
                    "price": t.get("unit_price_gross", 0),
                })
            
            # Generuj wiersze tabeli
            tickets_rows = generate_tickets_table_rows(tickets_for_table)
            
            if tickets_rows:
                tickets_table_html = f'''
                <table cellpadding="0" cellspacing="0" style="border-collapse: collapse; width: 100%; margin: 16px 0; border: 1px solid #DEE2E6;">
                    <tr>
                        <td colspan="3" style="font-size: 16px; font-weight: bold; padding: 10px 6px; color: #28a745;">Szczegóły zamówienia</td>
                    </tr>
                    {tickets_rows}
                    <tr>
                        <td colspan="2" style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: #28a745; color: #ffffff;">Razem zapłacono</td>
                        <td style="font-weight: bold; font-size: 16px; padding: 10px 6px; background-color: #28a745; color: #ffffff; text-align: right;">{format_currency(total_value)}</td>
                    </tr>
                </table>
                '''
                print(f"[STRIPE] Wygenerowano tabelę biletów ({len(enriched_tickets)} pozycji)")
    except Exception as e:
        print(f"[STRIPE] Błąd generowania tabeli biletów: {e}")
    
    # 1. Mail do kupującego: potwierdzenie płatności
    purchaser_email_sent = False
    purchaser_email_error = None
    
    if purchaser_email:
        purchaser_subject = f"Potwierdzenie płatności – {event_name}"
        purchaser_body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #28a745;">Dziękujemy za dokonanie płatności!</h2>
            <p>Szanowny/a <strong>{purchaser_name}</strong>,</p>
            <p>Potwierdzamy otrzymanie płatności za zamówienie.</p>
            <hr>
            <p><strong>Wydarzenie:</strong> {event_name}</p>
            <p><strong>Numer zamówienia:</strong> {event_order_id}</p>
            {tickets_table_html}
            <hr>
            <p>W przypadku pytań prosimy o kontakt.</p>
            <p style="color: #666; font-size: 12px;">Email wygenerowany automatycznie.</p>
        </body>
        </html>
        """
        
        mail_task = {
            "template": "payment_confirmation",
            "to": purchaser_email,
            "subject": purchaser_subject,
            "direction": "purchaser",
            "data": {
                "event_order_id": event_order_id,
                "event_name": event_name,
                "purchaser_name": purchaser_name,
                "purchaser_email": purchaser_email,
                "total": total_value,
                "currency": currency_value,
                "payment_method": "Stripe",
            },
        }
        mail_tasks.append(mail_task)
        
        # Zapisz do logu
        save_mail_log(
            event_order_id=event_order_id,
            direction="purchaser",
            template_key="payment_confirmation",
            to_email=purchaser_email,
            subject=purchaser_subject,
            data=mail_task["data"],
        )
        
        # Wyślij email do kupującego przez Make
        print(f"[STRIPE] Wysyłam potwierdzenie płatności do kupującego: {purchaser_email}")
        result = _send_email_via_make_stripe(
            to_email=purchaser_email,
            subject=purchaser_subject,
            body_html=purchaser_body_html,
            event_order_id=event_order_id,
            template_type="payment_confirmation",
        )
        
        if result.get("success"):
            purchaser_email_sent = True
            print(f"[STRIPE] Email do kupującego wysłany pomyślnie!")
        else:
            purchaser_email_error = result.get("error", "Nieznany błąd")
            print(f"[STRIPE] BŁĄD wysyłki emaila do kupującego: {purchaser_email_error}")
    
    # 2. Mail wewnętrzny - zależny od wyniku wysyłki do kupującego
    if internal_email:
        if purchaser_email_sent:
            # SUKCES - klient poinformowany
            internal_subject = f"[PAID OK] Płatność dokonana, klient poinformowany – {event_name}"
            internal_body_html = f"""
            <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2 style="color: #28a745;">✅ Płatność dokonana - klient poinformowany</h2>
                <p><strong>Zamówienie:</strong> {event_order_id}</p>
                <p><strong>Wydarzenie:</strong> {event_name}</p>
                <hr>
                <p><strong>Kupujący:</strong> {purchaser_name}</p>
                <p><strong>Email:</strong> {purchaser_email}</p>
                <p><strong>Kwota:</strong> {total_value} {currency_value}</p>
                <p><strong>Checkout Session:</strong> {checkout_session_id}</p>
                <hr>
                <p style="color: #28a745;"><strong>✓ Email z potwierdzeniem płatności został wysłany do klienta.</strong></p>
                <p style="color: #666; font-size: 12px;">Email wygenerowany automatycznie przez system Render.</p>
            </body>
            </html>
            """
            template_key = "internal_order_paid_ok"
        elif purchaser_email and not purchaser_email_sent:
            # BŁĄD - płatność OK ale email nie wysłany
            internal_subject = f"[PAID ERROR] Płatność OK, ALE nie wysłano emaila – {event_name}"
            internal_body_html = f"""
            <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2 style="color: #dc3545;">⚠️ Płatność dokonana - BŁĄD wysyłki emaila</h2>
                <p><strong>Zamówienie:</strong> {event_order_id}</p>
                <p><strong>Wydarzenie:</strong> {event_name}</p>
                <hr>
                <p><strong>Kupujący:</strong> {purchaser_name}</p>
                <p><strong>Email:</strong> {purchaser_email}</p>
                <p><strong>Kwota:</strong> {total_value} {currency_value}</p>
                <p><strong>Checkout Session:</strong> {checkout_session_id}</p>
                <hr>
                <p style="color: #dc3545;"><strong>❌ NIE UDAŁO SIĘ wysłać emaila z potwierdzeniem do klienta!</strong></p>
                <p><strong>Błąd:</strong> {purchaser_email_error}</p>
                <p style="color: #dc3545;"><strong>WYMAGANA AKCJA:</strong> Skontaktuj się z klientem ręcznie!</p>
                <hr>
                <p style="color: #666; font-size: 12px;">Email wygenerowany automatycznie przez system Render.</p>
            </body>
            </html>
            """
            template_key = "internal_order_paid_email_error"
        else:
            # Brak emaila kupującego
            internal_subject = f"[PAID] Płatność dokonana (brak emaila klienta) – {event_name}"
            internal_body_html = f"""
            <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2 style="color: #ffc107;">⚠️ Płatność dokonana - brak emaila klienta</h2>
                <p><strong>Zamówienie:</strong> {event_order_id}</p>
                <p><strong>Wydarzenie:</strong> {event_name}</p>
                <hr>
                <p><strong>Kupujący:</strong> {purchaser_name or "(brak danych)"}</p>
                <p><strong>Email:</strong> (brak)</p>
                <p><strong>Kwota:</strong> {total_value} {currency_value}</p>
                <p><strong>Checkout Session:</strong> {checkout_session_id}</p>
                <hr>
                <p style="color: #ffc107;"><strong>⚠️ Brak adresu email klienta - nie wysłano potwierdzenia.</strong></p>
                <p style="color: #666; font-size: 12px;">Email wygenerowany automatycznie przez system Render.</p>
            </body>
            </html>
            """
            template_key = "internal_order_paid_no_email"
        
        internal_task = {
            "template": template_key,
            "to": internal_email,
            "subject": internal_subject,
            "direction": "internal",
            "data": {
                "event_order_id": event_order_id,
                "event_name": event_name,
                "purchaser_name": purchaser_name,
                "purchaser_email": purchaser_email,
                "total": total_value,
                "currency": currency_value,
                "payment_method": "Stripe",
                "checkout_session_id": checkout_session_id,
                "purchaser_email_sent": purchaser_email_sent,
                "purchaser_email_error": purchaser_email_error,
            },
        }
        mail_tasks.append(internal_task)
        
        save_mail_log(
            event_order_id=event_order_id,
            direction="internal",
            template_key=template_key,
            to_email=internal_email,
            subject=internal_subject,
            data=internal_task["data"],
        )
        
        # Wysyłka emaila wewnętrznego przez Make
        _send_email_via_make_stripe(
            to_email=internal_email,
            subject=internal_subject,
            body_html=internal_body_html,
            event_order_id=event_order_id,
            template_type=template_key,
        )
    
    # 3. Utwórz fakturę VAT w wFirma
    invoice_created = False
    invoice_id = None
    invoice_number = None
    invoice_email_sent = False
    invoice_error = None
    
    try:
        from backstage_engine import _create_paid_invoice
        
        # Przygotuj dane zamówienia dla faktury
        # Użyj już wyciągniętych biletów (enriched_tickets) jeśli dostępne
        raw_payload = order.get("raw", {}) if order else {}
        
        # Wyciągnij dane rozliczeniowe
        billing_address = raw_payload.get("eventOrder_billingAddress", {}) if raw_payload else {}
        
        order_data_for_invoice = {
            "event_order_id": event_order_id,
            "event_id": order.get("event_id", "") if order else "",
            "purchaser_email": purchaser_email,
            "purchaser_first_name": order.get("purchaser_first_name", "") if order else "",
            "purchaser_last_name": order.get("purchaser_last_name", "") if order else "",
            "purchaser_nip": order.get("purchaser_nip", "") if order else "",
            "billing_address": billing_address.get("streetAddress1") or billing_address.get("street") or "-",
            "billing_zip": billing_address.get("zipcode") or billing_address.get("zip") or "00-000",
            "billing_city": billing_address.get("city") or "-",
            "total": total_value,
            "currency": currency_value,
            "tickets": enriched_tickets,  # Użyj wzbogaconych biletów
        }
        
        print(f"[STRIPE] Tworzę fakturę VAT dla zamówienia {event_order_id}...")
        
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
            print(f"[STRIPE] Faktura utworzona: {invoice_number} (ID: {invoice_id})")
        else:
            invoice_error = error
            print(f"[STRIPE] BŁĄD tworzenia faktury: {error}")
            
            # Wyślij powiadomienie wewnętrzne o błędzie faktury
            if internal_email:
                error_subject = f"[INVOICE ERROR] Błąd faktury – {event_name}"
                error_body_html = f"""
                <html>
                <body style="font-family: Arial, sans-serif; padding: 20px;">
                    <h2 style="color: #dc3545;">❌ Błąd tworzenia faktury</h2>
                    <p><strong>Zamówienie:</strong> {event_order_id}</p>
                    <p><strong>Wydarzenie:</strong> {event_name}</p>
                    <hr>
                    <p><strong>Kupujący:</strong> {purchaser_name}</p>
                    <p><strong>Email:</strong> {purchaser_email}</p>
                    <p><strong>NIP:</strong> {order_data_for_invoice.get('purchaser_nip') or '(brak)'}</p>
                    <p><strong>Kwota:</strong> {total_value} {currency_value}</p>
                    <hr>
                    <p style="color: #dc3545;"><strong>Błąd:</strong> {error}</p>
                    <p><strong>WYMAGANA AKCJA:</strong> Utwórz fakturę ręcznie w wFirma!</p>
                    <hr>
                    <p style="color: #666; font-size: 12px;">Email wygenerowany automatycznie przez system Render.</p>
                </body>
                </html>
                """
                _send_email_via_make_stripe(
                    to_email=internal_email,
                    subject=error_subject,
                    body_html=error_body_html,
                    event_order_id=event_order_id,
                    template_type="internal_invoice_error",
                )
                
    except Exception as e:
        invoice_error = str(e)
        print(f"[STRIPE] WYJĄTEK podczas tworzenia faktury: {e}")
    
    return {
        "status": "ok",
        "order_id": event_order_id,
        "order_status": "paid",
        "checkout_session_id": checkout_session_id,
        "payment_intent_id": payment_intent_id,
        "mail_tasks": mail_tasks,
        "invoice_created": invoice_created,
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "invoice_email_sent": invoice_email_sent,
        "invoice_error": invoice_error,
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
    
    if event_type == "checkout.session.async_payment_succeeded":
        # Płatność asynchroniczna się powiodła (np. BLIK, przelewy24)
        return handle_checkout_completed(event_data)
    
    if event_type == "checkout.session.expired":
        return handle_checkout_expired(event_data)
    
    if event_type == "checkout.session.async_payment_failed":
        return handle_checkout_payment_failed(event_data)
    
    # Inne eventy - ignorujemy
    return {
        "status": "ignored",
        "event_type": event_type,
        "message": f"Event type {event_type} nie jest obsługiwany",
    }


def handle_checkout_expired(session_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Obsługuje event checkout.session.expired.
    Klient nie zapłacił w wymaganym czasie.
    """
    checkout_session_id = session_data.get("id")
    metadata = session_data.get("metadata") or {}
    event_order_id = metadata.get("event_order_id") or session_data.get("client_reference_id")
    
    print(f"[STRIPE] checkout.session.expired | order={event_order_id}, session={checkout_session_id}")
    
    if not event_order_id:
        return {"status": "error", "error": "Brak event_order_id"}
    
    # Aktualizuj status zamówienia
    update_order_status(event_order_id, "payment_expired")
    
    # Pobierz dane zamówienia
    order = get_order(event_order_id)
    event_config = None
    event_name = "Wydarzenie"
    if order:
        ev = get_event(order.get("event_id", ""))
        if ev:
            event_name = ev.get("event_name", "Wydarzenie")
    
    purchaser_email = order.get("purchaser_email", "") if order else ""
    purchaser_name = ""
    if order:
        purchaser_name = f"{order.get('purchaser_first_name', '')} {order.get('purchaser_last_name', '')}".strip()
    
    # Aktualizuj status sesji Stripe
    if checkout_session_id:
        try:
            from pg_storage import _with_conn, _put_conn
            pool, conn = _with_conn()
            cur = conn.cursor()
            cur.execute("""
                UPDATE stripe_sessions 
                SET status = 'expired', updated_at = NOW()
                WHERE checkout_session_id = %s
            """, (checkout_session_id,))
            conn.commit()
            cur.close()
            _put_conn(pool, conn)
        except Exception as e:
            print(f"[STRIPE] Błąd aktualizacji sesji: {e}")
    
    # Wyślij email wewnętrzny o wygasłej sesji
    if BACKSTAGE_TECHNICAL_INFO_EMAIL:
        total_value = order.get("total", 0) if order else 0
        currency_value = order.get("currency", "PLN") if order else "PLN"
        
        internal_subject = f"[EXPIRED] Sesja płatności wygasła – {event_name}"
        internal_body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #ffc107;">⏰ Sesja płatności wygasła</h2>
            <p><strong>Zamówienie:</strong> {event_order_id}</p>
            <p><strong>Wydarzenie:</strong> {event_name}</p>
            <hr>
            <p><strong>Kupujący:</strong> {purchaser_name}</p>
            <p><strong>Email:</strong> {purchaser_email}</p>
            <p><strong>Kwota:</strong> {total_value} {currency_value}</p>
            <p><strong>Checkout Session:</strong> {checkout_session_id}</p>
            <hr>
            <p style="color: #666;">Klient nie dokonał płatności w wymaganym czasie. Sesja Stripe wygasła.</p>
            <p style="color: #666; font-size: 12px;">Email wygenerowany automatycznie przez system Render.</p>
        </body>
        </html>
        """
        
        save_mail_log(
            event_order_id=event_order_id,
            direction="internal",
            template_key="internal_payment_expired",
            to_email=BACKSTAGE_TECHNICAL_INFO_EMAIL,
            subject=internal_subject,
            data={"event_order_id": event_order_id, "event_name": event_name},
        )
        
        _send_email_via_make_stripe(
            to_email=BACKSTAGE_TECHNICAL_INFO_EMAIL,
            subject=internal_subject,
            body_html=internal_body_html,
            event_order_id=event_order_id,
            template_type="internal_payment_expired",
        )
    
    return {
        "status": "ok",
        "event_type": "checkout.session.expired",
        "order_id": event_order_id,
        "order_status": "payment_expired",
        "message": "Sesja płatności wygasła",
    }


def handle_checkout_payment_failed(session_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Obsługuje event checkout.session.async_payment_failed.
    Płatność asynchroniczna nie powiodła się.
    """
    checkout_session_id = session_data.get("id")
    metadata = session_data.get("metadata") or {}
    event_order_id = metadata.get("event_order_id") or session_data.get("client_reference_id")
    
    print(f"[STRIPE] checkout.session.async_payment_failed | order={event_order_id}, session={checkout_session_id}")
    
    if not event_order_id:
        return {"status": "error", "error": "Brak event_order_id"}
    
    # Aktualizuj status zamówienia
    update_order_status(event_order_id, "payment_failed")
    
    # Pobierz dane zamówienia
    order = get_order(event_order_id)
    event_name = "Wydarzenie"
    if order:
        ev = get_event(order.get("event_id", ""))
        if ev:
            event_name = ev.get("event_name", "Wydarzenie")
    
    purchaser_email = order.get("purchaser_email", "") if order else ""
    purchaser_name = ""
    if order:
        purchaser_name = f"{order.get('purchaser_first_name', '')} {order.get('purchaser_last_name', '')}".strip()
    
    # Aktualizuj status sesji Stripe
    if checkout_session_id:
        try:
            from pg_storage import _with_conn, _put_conn
            pool, conn = _with_conn()
            cur = conn.cursor()
            cur.execute("""
                UPDATE stripe_sessions 
                SET status = 'failed', updated_at = NOW()
                WHERE checkout_session_id = %s
            """, (checkout_session_id,))
            conn.commit()
            cur.close()
            _put_conn(pool, conn)
        except Exception as e:
            print(f"[STRIPE] Błąd aktualizacji sesji: {e}")
    
    # Wyślij email wewnętrzny o nieudanej płatności
    if BACKSTAGE_TECHNICAL_INFO_EMAIL:
        total_value = order.get("total", 0) if order else 0
        currency_value = order.get("currency", "PLN") if order else "PLN"
        
        internal_subject = f"[FAILED] Płatność nieudana – {event_name}"
        internal_body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #dc3545;">❌ Płatność nieudana</h2>
            <p><strong>Zamówienie:</strong> {event_order_id}</p>
            <p><strong>Wydarzenie:</strong> {event_name}</p>
            <hr>
            <p><strong>Kupujący:</strong> {purchaser_name}</p>
            <p><strong>Email:</strong> {purchaser_email}</p>
            <p><strong>Kwota:</strong> {total_value} {currency_value}</p>
            <p><strong>Checkout Session:</strong> {checkout_session_id}</p>
            <hr>
            <p style="color: #dc3545;"><strong>Płatność asynchroniczna (BLIK/P24) nie powiodła się.</strong></p>
            <p style="color: #666; font-size: 12px;">Email wygenerowany automatycznie przez system Render.</p>
        </body>
        </html>
        """
        
        save_mail_log(
            event_order_id=event_order_id,
            direction="internal",
            template_key="internal_payment_failed",
            to_email=BACKSTAGE_TECHNICAL_INFO_EMAIL,
            subject=internal_subject,
            data={"event_order_id": event_order_id, "event_name": event_name},
        )
        
        _send_email_via_make_stripe(
            to_email=BACKSTAGE_TECHNICAL_INFO_EMAIL,
            subject=internal_subject,
            body_html=internal_body_html,
            event_order_id=event_order_id,
            template_type="internal_payment_failed",
        )
    
    return {
        "status": "ok",
        "event_type": "checkout.session.async_payment_failed",
        "order_id": event_order_id,
        "order_status": "payment_failed",
        "message": "Płatność nie powiodła się",
    }
