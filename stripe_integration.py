"""
Stripe Integration - tworzenie Checkout Sessions i obsługa webhooków.
Używa STRIPE_RENDER_API_KEY z ENV (produkcyjny klucz Stripe).
"""
import os
import hmac
import hashlib
import requests
import time
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

# Email wewnętrzny - info techniczne (błędy)
BACKSTAGE_TECHNICAL_INFO_EMAIL = os.environ.get("BACKSTAGE_TECHNICAL_INFO_EMAIL", "")
# Email wewnętrzny - powiadomienia o zamówieniach/płatnościach (nie błędy)
BACKSTAGE_EVENT_INFO_EMAIL = os.environ.get("BACKSTAGE_EVENT_INFO_EMAIL", "")

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

CHECKOUT_SESSION_TTL_SECONDS = 24 * 60 * 60  # 24h - ważność linku do płatności


def create_checkout_session(
    event_order_id: str,
    amount_cents: int,
    currency: str = "pln",
    customer_email: Optional[str] = None,
    description: Optional[str] = None,
    success_url: str = "",
    cancel_url: str = "",
    metadata: Optional[Dict[str, str]] = None,
    line_items: Optional[list] = None,
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
        
        # Przygotuj line_items (jeśli nie podano - fallback do jednej pozycji)
        final_line_items = line_items
        if not final_line_items:
            final_line_items = [{
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
            "line_items": final_line_items,
            "mode": "payment",
            "metadata": meta,
            "client_reference_id": event_order_id,
            # Link do płatności ważny 24h od utworzenia (Stripe Checkout Session expiry)
            # Dajemy minimalny margines -60s, żeby nie wyjść poza limit po stronie Stripe.
            "expires_at": int(time.time()) + CHECKOUT_SESSION_TTL_SECONDS - 60,
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
    # Bezpieczeństwo: fail-closed na brak konfiguracji.
    if stripe is None:
        return False, "Stripe library not available (missing dependency)"

    webhook_secret = _get_webhook_secret(sandbox)
    if not webhook_secret:
        return False, "Missing Stripe webhook secret (server misconfigured)"
    
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
    stripe_mode = (metadata.get("stripe_mode") or "").lower().strip()
    is_sandbox = stripe_mode == "sandbox"
    recovery_mode = False
    recovery_reason = ""
    skip_purchaser_email = False

    print(f"[STRIPE] handle_checkout_completed | session={checkout_session_id}, payment_intent={payment_intent_id}, order={event_order_id}")
    
    if not checkout_session_id:
        print("[STRIPE] ERROR: Brak checkout_session_id w session_data")
        return {"status": "error", "error": "Brak checkout_session_id"}
    
    if not event_order_id:
        print(f"[STRIPE] ERROR: Brak event_order_id w metadata/client_reference_id | metadata_keys={list(metadata.keys())}")
        return {"status": "error", "error": "Brak event_order_id w metadata/client_reference_id"}
    
    # Sprawdź czy sesja istnieje w bazie
    existing = get_stripe_session_by_checkout_id(checkout_session_id)
    try:
        print(f"[STRIPE] existing stripe_session | found={bool(existing)}, status={(existing or {}).get('status')}, order_id={(existing or {}).get('event_order_id')}")
    except Exception:
        pass
    if existing and existing.get("status") == "paid":
        # Jeśli sesja jest paid, ale nie mamy jeszcze faktury, to dokończ proces (recovery).
        try:
            from pg_storage import get_wfirma_documents
            docs = get_wfirma_documents(event_order_id)
            docs_preview = []
            for d in (docs or [])[:3]:
                docs_preview.append({
                    "id": d.get("id"),
                    "wfirma_number": d.get("wfirma_number"),
                    "document_type": d.get("document_type"),
                    "status": d.get("status"),
                    "created_at": str(d.get("created_at"))[:19] if d.get("created_at") else None,
                })
            has_normal_invoice = any((d or {}).get("document_type") == "normal" for d in (docs or []))
            print(f"[STRIPE] paid session detected | wfirma_docs_count={len(docs or [])}, has_normal_invoice={has_normal_invoice}, docs_preview={docs_preview}")

            if has_normal_invoice:
                return {
                    "status": "duplicate",
                    "message": "Płatność już została przetworzona (faktura istnieje)",
                    "order_id": event_order_id,
                }

            # Recovery: brak faktury mimo paid
            recovery_mode = True
            recovery_reason = "paid_session_but_no_normal_invoice"
            # nie wysyłaj ponownie maila do klienta w recovery (żeby nie dublować)
            skip_purchaser_email = True
            print(f"[STRIPE] RECOVERY MODE enabled | reason={recovery_reason}, sandbox={is_sandbox}")

        except Exception as e:
            # Jeśli nie umiemy sprawdzić faktur, zachowaj ostrożność: nie twórz nowych
            print(f"[STRIPE] DUPLICATE: nie udało się pobrać wfirma_documents: {e}")
            return {
                "status": "duplicate",
                "message": "Płatność już została przetworzona (brak weryfikacji faktury)",
                "order_id": event_order_id,
            }
    
    # Oznacz sesję jako opłaconą
    if not recovery_mode:
        print(f"[STRIPE] update_stripe_session_paid | session={checkout_session_id}, payment_intent={payment_intent_id}")
        update_stripe_session_paid(checkout_session_id, payment_intent_id)
    else:
        print(f"[STRIPE] skip update_stripe_session_paid (already paid) | session={checkout_session_id}")
    
    # Aktualizuj status zamówienia
    print(f"[STRIPE] update_order_status -> paid | order={event_order_id}")
    update_order_status(event_order_id, "paid")
    
    # Pobierz dane zamówienia i eventu do mail tasks
    order = get_order(event_order_id)
    if not order:
        print(f"[STRIPE] WARN: brak order w DB dla event_order_id={event_order_id}")
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
    # total z DB bywa Decimal -> rzutuj na float, bo to wraca w JSON (webhook response)
    total_raw = order.get("total", 0) if order else 0
    try:
        total_value = float(total_raw or 0)
    except Exception:
        total_value = 0.0
    currency_value = order.get("currency", "PLN") if order else "PLN"
    # internal_email_target jest określany niżej, zależnie od wyniku wysyłki

    try:
        print(f"[STRIPE] order summary | event_id={order.get('event_id') if order else None}, total={total_value} ({type(total_raw).__name__}=>float), currency={currency_value}, purchaser_email={purchaser_email}")
    except Exception:
        pass
    
    # Wyciągnij i wzbogać bilety do emaila
    enriched_tickets = []
    try:
        from backstage_engine import _extract_tickets_from_payload, _enrich_tickets_with_names
        
        raw_payload = order.get("raw", {}) if order else {}
        raw_tickets = _extract_tickets_from_payload(raw_payload) if raw_payload else []
        event_id_for_tickets = order.get("event_id", "") if order else ""
        
        if raw_tickets:
            enriched_tickets, unknown_ids = _enrich_tickets_with_names(raw_tickets, event_id_for_tickets)
            print(f"[STRIPE] Wygenerowano bilety do emaila ({len(enriched_tickets)} pozycji)")
    except Exception as e:
        print(f"[STRIPE] Błąd pobierania biletów: {e}")
    
    # Wyciągnij dane kupującego
    purchaser_first_name = ""
    purchaser_last_name = ""
    purchaser_phone = ""
    try:
        if order:
            raw_payload = order.get("raw", {})
            # Spróbuj wyciągnąć z buyer_details
            buyer_details = raw_payload.get("buyer_details", {})
            if not buyer_details:
                # Spróbuj z customFormData
                custom_forms = raw_payload.get("customFormData", [])
                if custom_forms:
                    form_entries = custom_forms[0].get("formEntries", {})
                    purchaser_first_name = form_entries.get("purchaser_first_name", "")
                    purchaser_last_name = form_entries.get("purchaser_last_name", "")
                    purchaser_phone = form_entries.get("purchaser_mobile_no", "")
            else:
                purchaser_first_name = buyer_details.get("purchaser_first_name", "")
                purchaser_last_name = buyer_details.get("purchaser_last_name", "")
                purchaser_phone = buyer_details.get("purchaser_mobile_no", "")
    except Exception:
        pass
    
    # 1. Mail do kupującego: potwierdzenie płatności
    purchaser_email_sent = False
    purchaser_email_error = None
    
    if purchaser_email and not skip_purchaser_email:
        purchaser_subject = f"Płatność potwierdzona! Twoja rezerwacja na {event_name}"
        
        # Użyj stylizowanego szablonu
        try:
            from email_templates import render_payment_confirmation_email
            
            purchaser_body_html = render_payment_confirmation_email(
                event_name=event_name,
                purchaser_first_name=purchaser_first_name or purchaser_name.split()[0] if purchaser_name else "Uczestnik",
                purchaser_last_name=purchaser_last_name or (purchaser_name.split()[-1] if purchaser_name and len(purchaser_name.split()) > 1 else ""),
                purchaser_email=purchaser_email,
                purchaser_phone=purchaser_phone,
                total_gross=total_value,
                event_config=event_data,
                tickets=enriched_tickets,
            )
            print(f"[STRIPE] Wygenerowano stylizowany email potwierdzenia płatności")
        except Exception as e:
            print(f"[STRIPE] Błąd renderowania szablonu, używam podstawowego: {e}")
            # Fallback do podstawowego emaila
            purchaser_body_html = f"""
            <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2 style="color: #28a745;">Dziękujemy za dokonanie płatności!</h2>
                <p>Szanowny/a <strong>{purchaser_name}</strong>,</p>
                <p>Potwierdzamy otrzymanie płatności za zamówienie.</p>
                <hr>
                <p><strong>Wydarzenie:</strong> {event_name}</p>
                <p><strong>Numer zamówienia:</strong> {event_order_id}</p>
                <p><strong>Kwota:</strong> {total_value} {currency_value}</p>
                <hr>
                <p>W przypadku pytań prosimy o kontakt.</p>
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

        try:
            print(f"[STRIPE] mail_task purchaser queued | to={purchaser_email}, total={total_value}")
        except Exception:
            pass
        
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
    elif purchaser_email and skip_purchaser_email:
        print(f"[STRIPE] skip purchaser email (recovery_mode) | to={purchaser_email}")
    
    # 2. Mail wewnętrzny - zależny od wyniku wysyłki do kupującego
    # Dla sukcesu: BACKSTAGE_EVENT_INFO_EMAIL, dla błędów: BACKSTAGE_TECHNICAL_INFO_EMAIL
    if purchaser_email_sent:
        # SUKCES - klient poinformowany → email eventowy
        internal_email_target = BACKSTAGE_EVENT_INFO_EMAIL or event_data.get("md_email_techniczny") or event_data.get("md_email_kontakt")
    else:
        # BŁĄD lub brak emaila → email techniczny
        internal_email_target = BACKSTAGE_TECHNICAL_INFO_EMAIL or event_data.get("md_email_techniczny") or event_data.get("md_email_kontakt")
    
    if internal_email_target:
        if purchaser_email_sent:
            # SUKCES - klient poinformowany
            internal_subject = f"[PAID OK] Płatność dokonana, klient poinformowany – {event_name}"
            def _format_paid_dt(dt_value) -> Tuple[str, str]:
                if not dt_value:
                    return "—", ""
                try:
                    if hasattr(dt_value, "strftime"):
                        return dt_value.strftime("%Y-%m-%d"), dt_value.strftime("%H:%M")
                except Exception:
                    pass
                s = str(dt_value)
                if "T" in s:
                    date_part, time_part = s.split("T", 1)
                elif " " in s:
                    date_part, time_part = s.split(" ", 1)
                else:
                    return s[:10], ""
                time_part = time_part.replace("Z", "")
                time_part = time_part.split("+")[0].split(".")[0]
                return date_part[:10], time_part[:5]

            paid_dt = None
            if order:
                paid_dt = order.get("updated_at") or order.get("created_at")
            paid_day, paid_time = _format_paid_dt(paid_dt)

            purchaser_full_name = (
                purchaser_name
                or f"{purchaser_first_name} {purchaser_last_name}".strip()
                or "(brak danych)"
            )
            purchaser_email_display = purchaser_email or "(brak)"
            total_formatted = f"{total_value:.2f} {currency_value}"

            banner_url = (
                event_data.get("event_mail_link_top_banner")
                or event_data.get("event_mail_link_bottom_banner")
                or "https://via.placeholder.com/600x200/2563eb/ffffff?text=Event"
            )
            event_config_link = event_data.get("event_config_link") or ""
            color_primary = event_data.get("color_gradient_1") or "#0065D7"
            color_secondary = event_data.get("color_gradient_2") or color_primary
            md_email_kontakt = event_data.get("md_email_kontakt") or "konferencje@medidesk.com"

            backstage_btn_html = ""
            if event_config_link:
                backstage_btn_html = f'''
                <tr>
                  <td style="padding: 16px 20px; text-align: center;">
                    <!--[if mso]>
                    <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{event_config_link}" style="v-text-anchor:middle; height:40px; width:320px;" arcsize="10%" stroke="false" fillcolor="{color_primary}">
                      <w:anchorlock/>
                      <center style="color:#ffffff; font-size:14px; font-weight:bold;">Otwórz Konfigurację w Backstage</center>
                    </v:roundrect>
                    <![endif]-->
                    <!--[if !mso]><!-->
                    <a href="{event_config_link}" target="_blank" style="display: inline-block; padding: 12px 24px; background-color: {color_primary}; color: #fff; text-decoration: none; border-radius: 6px; font-size: 14px; font-weight: bold;">Otwórz Konfigurację w Backstage</a>
                    <!--<![endif]-->
                  </td>
                </tr>
                '''

            internal_body_html = f"""
            <!doctype html>
            <html lang="pl">
            <head>
              <meta charset="UTF-8" />
              <title>Nowe zamówienie – {event_name}</title>
              <!--[if mso]>
              <style type="text/css">
                body, table, td {{font-family: Arial, Helvetica, sans-serif !important;}}
              </style>
              <![endif]-->
              <style type="text/css">
                p, h1, h2, h3, h4, h5, h6, ul {{margin: 0;}}
                @media screen and (max-width: 620px) {{
                  .main-table {{ width: 100% !important; }}
                }}
              </style>
            </head>
            <body>
              <div style="display: none; max-height: 0; overflow: hidden; mso-hide: all;">
                PAID: {purchaser_full_name} | {total_formatted} | {event_name}
              </div>
              <table border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f5f5f5;" bgcolor="#f5f5f5">
                <tr>
                  <td style="padding: 16px">
                    <table border="0" width="600" cellpadding="0" cellspacing="0" class="main-table" style="width: 600px; margin: auto; max-width: 600px; font-family: Arial, sans-serif; font-size: 14px; background-color: #fff; border: 1px solid #ddd;" bgcolor="#ffffff">
                      <tr>
                        <td style="padding: 0; line-height: 0; background-color: {color_primary};" bgcolor="{color_primary}">
                          <img src="{banner_url}" alt="{event_name}" width="600" style="width: 100%; max-width: 100%; display: block;">
                        </td>
                      </tr>
                      <tr>
                        <td style="padding: 12px 20px; background-color: {color_primary}; text-align: center;" bgcolor="{color_primary}">
                          <p style="color: #fff; font-size: 16px; font-weight: bold; margin: 0;">✓ PAID – Nowe opłacone zamówienie</p>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding: 0;">
                          <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse; background-color: #fff;" bgcolor="#fff">
                            <tr>
                              <td width="45%" style="padding: 14px 20px; border-bottom: 1px solid #e5e7eb; font-size: 13px; color: #64748b; font-weight: 500;">Purchased By ◇</td>
                              <td width="30%" style="padding: 14px 20px; border-bottom: 1px solid #e5e7eb; font-size: 13px; color: #64748b; font-weight: 500;">Date &amp; Time ◇</td>
                              <td width="25%" style="padding: 14px 20px; border-bottom: 1px solid #e5e7eb; font-size: 13px; color: #64748b; font-weight: 500; text-align: right;">Amount ◇</td>
                            </tr>
                            <tr style="background-color: #fffbeb;" bgcolor="#fffbeb">
                              <td style="padding: 16px 20px; border-bottom: 1px solid #fde68a; vertical-align: top;">
                                <p style="font-size: 15px; font-weight: 600; color: #1e293b; margin: 0;">{purchaser_full_name}</p>
                                <p style="font-size: 13px; color: #64748b; margin: 4px 0 0 0;">{purchaser_email_display}</p>
                              </td>
                              <td style="padding: 16px 20px; border-bottom: 1px solid #fde68a; vertical-align: top;">
                                <p style="font-size: 15px; font-weight: 600; color: #1e293b; margin: 0;">{paid_day}</p>
                                <p style="font-size: 13px; color: #64748b; margin: 4px 0 0 0;">{paid_time}</p>
                              </td>
                              <td style="padding: 16px 20px; border-bottom: 1px solid #fde68a; vertical-align: top; text-align: right;">
                                <p style="font-size: 17px; font-weight: 700; color: #1e293b; margin: 0;">{total_formatted}</p>
                              </td>
                            </tr>
                          </table>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding: 14px 20px; background-color: #f8f9fa;" bgcolor="#f8f9fa">
                          <table width="100%" cellpadding="0" cellspacing="0">
                            <tr>
                              <td width="70%" style="vertical-align: top;">
                                <p style="font-size: 11px; color: #888; margin: 0 0 2px 0;">Wydarzenie</p>
                                <p style="font-size: 14px; font-weight: bold; color: #000; margin: 0;">{event_name}</p>
                              </td>
                              <td width="30%" style="vertical-align: top; text-align: right;">
                                <p style="font-size: 11px; color: #888; margin: 0 0 2px 0;">Order ID</p>
                                <p style="font-size: 12px; font-weight: bold; color: #666; margin: 0; font-family: monospace;">#{event_order_id}</p>
                              </td>
                            </tr>
                          </table>
                        </td>
                      </tr>
                      {backstage_btn_html}
                      <tr>
                        <td style="padding: 10px 20px; background-color: {color_secondary}; text-align: center;" bgcolor="{color_secondary}">
                          <p style="color: #e2e8f0; font-size: 11px; margin: 0;">Powiadomienie wewnętrzne | {md_email_kontakt}</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
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
            "to": internal_email_target,
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
            to_email=internal_email_target,
            subject=internal_subject,
            data=internal_task["data"],
        )
        
        # Wysyłka emaila wewnętrznego przez Make
        _send_email_via_make_stripe(
            to_email=internal_email_target,
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
        
        print(f"[STRIPE] Tworzę fakturę VAT (wFirma) | order={event_order_id}, send_email={bool(purchaser_email)}")
        
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
            print(f"[STRIPE] Faktura utworzona: {invoice_number} (ID: {invoice_id}), email_sent={invoice_email_sent}")
        else:
            invoice_error = error
            print(f"[STRIPE] BŁĄD tworzenia faktury: {error}")
            
            # Wyślij powiadomienie wewnętrzne o błędzie faktury
            # internal_email_target jest wyliczony wyżej (event/technical zależnie od przebiegu)
            if internal_email_target:
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
                    to_email=internal_email_target,
                    subject=error_subject,
                    body_html=error_body_html,
                    event_order_id=event_order_id,
                    template_type="internal_invoice_error",
                )
                
    except Exception as e:
        invoice_error = str(e)
        print(f"[STRIPE] WYJĄTEK podczas tworzenia faktury: {e}")
    
    # 4. Wyślij indywidualne emaile z biletami do WSZYSTKICH uczestników
    participant_email_stats = {"sent": 0, "failed": 0, "skipped": 0}
    try:
        from backstage_engine import send_participant_ticket_emails
        from backstage_engine import attendee_webhooks_status

        comp = attendee_webhooks_status(event_order_id)
        if not comp.get("complete"):
            print(f"[STRIPE] Pomijam emaile do uczestników - brak kompletu attendee-webhooków | expected={comp.get('expected')}, received={comp.get('received')}")
            participant_email_stats = {"sent": 0, "failed": 0, "skipped": 0, "details": [{"status": "skipped_all", "reason": "attendee_webhooks_incomplete", **comp}]}
        else:
        
            participant_email_stats = send_participant_ticket_emails(
                event_order_id=event_order_id,
                event_name=event_name,
                event_config=event_data,
            )
            print(f"[STRIPE] Emaile do uczestników: sent={participant_email_stats.get('sent', 0)}, failed={participant_email_stats.get('failed', 0)}, skipped={participant_email_stats.get('skipped', 0)}")
    except Exception as e:
        print(f"[STRIPE] Błąd wysyłki emaili do uczestników: {e}")
    
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
        "recovery_mode": recovery_mode,
        "recovery_reason": recovery_reason or None,
        "participant_emails": participant_email_stats,
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
