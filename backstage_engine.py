"""
Backstage Engine - obsługa webhooków z Zoho Backstage.
Odpowiada za routing płatności (FOC / PROFORMA / STRIPE) i generowanie mail_tasks.
"""
import hashlib
import json
import datetime
import os
import requests
import traceback
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
    mail_id: Optional[int] = None,
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
        mail_id: ID rekordu w mail_log (do callbacku mark-sent)
    
    Returns:
        Dict z status, error, etc.
    """
    if not _is_make_email_configured():
        _log("ERROR", "Make webhook nie skonfigurowany (brak MAKE_WEBHOOK_SEND_EMAIL_REQUEST lub RENDER_EMAIL_KEY_SEND_REQUEST)")
        return {
            "success": False,
            "error": "Make webhook nie skonfigurowany",
        }
    
    _log("INFO", "Wysyłam email przez Make webhook", {"to": to_email, "subject": subject, "mail_id": mail_id})
    
    # Callback URL dla Make.com do potwierdzenia wysyłki (używamy istniejącego endpointu)
    base_url = os.environ.get("RENDER_EXTERNAL_URL", "https://wfirma-api.onrender.com")
    callback_url = f"{base_url}/api/email/confirm-sent"
    
    try:
        payload = {
            "to": to_email,
            "subject": subject,
            "body_html": body_html,
            "event_order_id": event_order_id,
            "template_type": template_type,
            "stripe_url": stripe_url,
            "mail_id": mail_id,  # Make przekaże to w callbacku
            "callback_url": callback_url,
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
            
            # Aktualizuj status maila na "sent" (nie czekając na callback)
            if mail_id:
                try:
                    from pg_storage import update_mail_task_status
                    update_mail_task_status(mail_id, "sent", None)
                    _log("DEBUG", f"Status maila {mail_id} zaktualizowany na 'sent'")
                except Exception as upd_err:
                    _log("WARNING", f"Nie udało się zaktualizować statusu maila: {upd_err}")
            
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
    # Nowe parametry dla Work Queue
    severity: str = "error",
    category: str = "backstage",
    can_retry: bool = False,
) -> None:
    """
    Wysyła email wewnętrzny o błędzie i zapisuje do Work Queue.
    
    Args:
        error_type: Typ błędu (np. "EVENT_NOT_FOUND", "TICKET_NOT_FOUND", "EMAIL_ERROR")
        error_message: Szczegółowy opis błędu
        event_order_id: ID zamówienia
        event_id: ID wydarzenia
        extra_data: Dodatkowe dane do wyświetlenia
        severity: Poziom ważności (critical, error, warning)
        category: Kategoria błędu (backstage, wfirma, stripe, make, etc.)
        can_retry: Czy można ponowić operację
    """
    # Zapisz do Work Queue (error_queue)
    try:
        from pg_storage import save_error_task
        error_data_for_queue = {
            "error_type": error_type,
            "error_message": error_message[:1000] if error_message else "",
            **(extra_data or {}),
        }
        save_error_task(
            category=category,
            severity=severity,
            title=f"{error_type}: {error_message[:100]}" if error_message else error_type,
            description=error_message,
            event_order_id=event_order_id or None,
            event_id=event_id or None,
            error_data=error_data_for_queue,
            can_retry=can_retry,
            max_retries=3 if can_retry else 0,
        )
        _log("INFO", f"Błąd zapisany do Work Queue: {error_type}")
    except Exception as eq_error:
        _log("ERROR", f"Nie udało się zapisać błędu do Work Queue: {eq_error}")
    
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
    event_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Wysyła emaile z biletami do WSZYSTKICH uczestników zamówienia.
    
    Każdy uczestnik dostaje swój indywidualny email z informacją o swoim bilecie:
    - nazwa/typ biletu
    - cena
    - ewentualne zniżki
    - szczegóły wydarzenia
    - link do kalendarza (.ics)
    
    Args:
        event_order_id: ID zamówienia
        event_name: Nazwa wydarzenia
        event_config: Konfiguracja wydarzenia (kolory, banery, etc.)
        event_id: ID wydarzenia (do linku kalendarza)
    
    Returns:
        Dict z statystykami: {"sent": X, "failed": Y, "skipped": Z, "details": [...]}
    """
    from pg_storage import get_participants_for_order, get_ticket_classes, update_participant_status
    from email_templates import render_participant_ticket_email
    
    stats = {"sent": 0, "failed": 0, "skipped": 0, "details": []}

    # #region agent log
    print(f"[DEBUG-PARTICIPANT-EMAIL] ENTRY | order_id={event_order_id}, event_name={event_name[:30] if event_name else None}")
    # #endregion

    # Guard: wysyłka biletów dopiero gdy mamy komplet attendee-webhooków per ticket_id
    complete_info = is_attendee_webhooks_complete(event_order_id)
    # #region agent log
    print(f"[DEBUG-PARTICIPANT-EMAIL] COMPLETE_CHECK | order_id={event_order_id}, complete={complete_info.get('complete')}, expected={complete_info.get('expected',0)}, received={complete_info.get('received',0)}, missing={complete_info.get('missing_ticket_ids',[])[:3]}")
    # #endregion
    if not complete_info.get("complete"):
        _log("INFO", "Nie wysyłam maili do uczestników - brak kompletu attendee-webhooków", {
            "event_order_id": event_order_id,
            "expected": complete_info.get("expected", 0),
            "received": complete_info.get("received", 0),
        })
        stats["skipped"] = 0
        stats["details"].append({
            "status": "skipped_all",
            "reason": "attendee_webhooks_incomplete",
            "expected": complete_info.get("expected", 0),
            "received": complete_info.get("received", 0),
            "missing_ticket_ids": complete_info.get("missing_ticket_ids", [])[:10],
        })
        return stats

    # Guard: uczestnik dostaje email dopiero po opłaceniu zamówienia
    try:
        order = get_order(event_order_id)
    except Exception:
        order = None
    order_status = (order or {}).get("status", "") if isinstance(order, dict) else ""
    # #region agent log
    print(f"[DEBUG-PARTICIPANT-EMAIL] STATUS_CHECK | order_id={event_order_id}, order_status={order_status}, is_paid={order_status.strip().lower()=='paid'}")
    # #endregion
    if (order_status or "").strip().lower() != "paid":
        _log("INFO", "Nie wysyłam maili do uczestników - zamówienie nieopłacone", {
            "event_order_id": event_order_id,
            "status": order_status,
        })
        stats["skipped"] = 0
        stats["details"].append({
            "status": "skipped_all",
            "reason": "order_not_paid",
            "order_status": order_status,
        })
        return stats
    
    # Pobierz uczestników
    participants = get_participants_for_order(event_order_id)
    # #region agent log
    _p_preview = [{"email": p.get("email","")[:15], "status": p.get("status","")} for p in (participants or [])[:3]]
    print(f"[DEBUG-PARTICIPANT-EMAIL] PARTICIPANTS | order_id={event_order_id}, count={len(participants) if participants else 0}, preview={_p_preview}")
    # #endregion
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
        participant_phone = p.get("phone", "")
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
            or "Rezerwacja"
        )
        # Usuń słowo "Bilet" z nazwy jeśli jest
        if ticket_name and isinstance(ticket_name, str):
            ticket_name = ticket_name.replace("Bilet ", "").replace("bilet ", "")
        ticket_price = participant_data.get("price_gross", 0)
        discount_amount = participant_data.get("discount_amount", 0)
        
        # Renderuj email
        try:
            body_html = render_participant_ticket_email(
                event_name=event_name,
                participant_first_name=participant_first_name,
                participant_last_name=participant_last_name,
                participant_email=participant_email,
                participant_phone=participant_phone,
                participant_company=participant_data.get("company") or participant_data.get("company_name") or "",
                participant_badge_name=participant_data.get("badge_name") or "",
                ticket_name=ticket_name,
                ticket_id=ticket_id,
                ticket_price=float(ticket_price) if ticket_price else 0.0,
                discount_amount=float(discount_amount) if discount_amount else 0.0,
                event_config=event_config,
                event_id=event_id,
            )
        except Exception as e:
            _log("ERROR", f"Błąd renderowania emaila uczestnika: {e}", {"ticket_id": ticket_id})
            stats["failed"] += 1
            stats["details"].append({"ticket_id": ticket_id, "email": participant_email, "status": "failed", "error": str(e)})
            continue
        
        # Wyślij email
        subject = f"Już jest! Twoje potwierdzenie rezerwacji na {event_name}!"
        
        _log("INFO", "Wysyłam email do uczestnika", {
            "to": participant_email,
            "ticket_name": ticket_name,
            "ticket_id": ticket_id[:20] + "..." if len(ticket_id) > 20 else ticket_id,
        })
        
        # NAJPIERW zapisz do mail_log żeby mieć mail_id
        from pg_storage import save_mail_log
        mail_log_result = save_mail_log(
            event_order_id=event_order_id,
            direction="participant",
            template_key="participant_ticket",
            to_email=participant_email,
            subject=subject,
        )
        mail_id = mail_log_result.get("id") if mail_log_result else None
        
        # POTEM wyślij z mail_id dla callbacka
        result = _send_email_via_make(
            to_email=participant_email,
            subject=subject,
            body_html=body_html,
            event_order_id=event_order_id,
            template_type="participant_ticket",
            mail_id=mail_id,
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


def attendee_webhooks_status(event_order_id: str) -> Dict[str, Any]:
    """
    Kompletność danych wg Twojej definicji:
    - dla każdego biletu (ticket_id) musi przyjść unikalny webhook /api/backstage/attendee
    - nie weryfikujemy zawartości, tylko obecność webhooka per ticket_id
    """
    from pg_storage import get_participants_for_order

    participants = get_participants_for_order(event_order_id)
    expected_ticket_ids = []
    received_ticket_ids = []

    for p in participants:
        tid = (p.get("ticket_id") or "").strip()
        if not tid:
            continue
        expected_ticket_ids.append(tid)
        data = p.get("data") or {}
        try:
            if data.get("attendee_webhook_received") is True:
                received_ticket_ids.append(tid)
        except Exception:
            pass

    expected_set = list(dict.fromkeys(expected_ticket_ids))
    received_set = set(received_ticket_ids)
    missing = [tid for tid in expected_set if tid not in received_set]

    return {
        "expected": len(expected_set),
        "received": len(received_set),
        "missing_ticket_ids": missing,
        "complete": (len(expected_set) > 0 and len(missing) == 0),
    }


def is_attendee_webhooks_complete(event_order_id: str) -> Dict[str, Any]:
    """Alias pomocniczy."""
    return attendee_webhooks_status(event_order_id)


def maybe_send_backstage_emails_when_complete(event_order_id: str) -> Dict[str, Any]:
    """
    Wywoływane po każdym attendee-webhooku (oraz po paid), żeby sprawdzić kompletność
    i dopiero wtedy wysłać maile, które mają czekać na komplet:
    - FOC purchaser confirmation (po kompletności)
    - PROFORMA purchaser reservation (po kompletności)
    - participant ticket emails (tylko jeśli order.status == paid)
    """
    from pg_storage import get_order, get_event, mail_log_exists, save_mail_log
    from email_templates import render_foc_confirmation_email, render_proforma_reservation_email

    order = get_order(event_order_id)
    if not order:
        return {"ok": False, "error": "order_not_found"}

    status = (order.get("status") or "").strip().lower()
    purchaser_email = (order.get("purchaser_email") or "").strip()
    total = order.get("total", 0) or 0
    payment_option_name = (order.get("payment_option_name") or "")
    payment_option_lower = payment_option_name.lower()

    # event config (kolory/banery)
    event_name = "Wydarzenie"
    event_data = {}
    try:
        ev = get_event(order.get("event_id", ""))
        if ev:
            event_name = ev.get("event_name", event_name)
            event_data = ev.get("data") or {}
    except Exception:
        pass

    # Przygotuj bilety do emaili z RAW payloadu (spójnie z innymi flow)
    raw_payload = order.get("raw") or {}
    tickets_for_email = []
    try:
        if isinstance(raw_payload, dict):
            raw_tickets = _extract_tickets_from_payload(raw_payload)
            if raw_tickets:
                tickets_for_email, _unknown = _enrich_tickets_with_names(raw_tickets, order.get("event_id", "") or "")
            else:
                tickets_for_email = []
    except Exception:
        tickets_for_email = []
    
    # Fallback: jeśli brak biletów, utwórz wpis na podstawie wartości zamówienia
    if not tickets_for_email and total:
        try:
            total_f = float(total or 0)
            if total_f > 0:
                from pg_storage import get_participants_for_order
                participants = get_participants_for_order(event_order_id) or []
                qty = len(participants) if participants else 1
                unit_price = total_f / qty
                tickets_for_email = [{
                    "name": "Udział w wydarzeniu",
                    "quantity": qty,
                    "price": unit_price,
                    "total_gross": total_f,
                }]
        except Exception:
            pass

    comp = attendee_webhooks_status(event_order_id)
    if not comp.get("complete"):
        return {"ok": True, "complete": False, **comp}

    sent = {"purchaser": False, "participants": {"sent": 0, "failed": 0, "skipped": 0}}

    # Flow inference (bez trzymania osobnej kolumny flow)
    flow = None
    try:
        total_f = float(total or 0)
    except Exception:
        total_f = 0.0
    if total_f == 0:
        flow = FLOW_FOC
    elif ("pro-forma" in payment_option_lower) or ("proforma" in payment_option_lower) or ("pro forma" in payment_option_lower):
        flow = FLOW_PROFORMA
    else:
        flow = FLOW_STRIPE

    # Purchaser mail (FOC/PROFORMA) dopiero po komplecie
    if purchaser_email:
        if flow == FLOW_FOC:
            # dedupe: jeśli już kiedykolwiek logowaliśmy ten template jako purchaser, nie ponawiaj
            if not mail_log_exists(event_order_id, TEMPLATE_REGISTRATION_CONFIRMATION, direction="purchaser"):
                subject = f"Już jest! Twoja rezerwacja na {event_name} jest potwierdzona!"
                body_html = render_foc_confirmation_email(
                    event_name=event_name,
                    purchaser_first_name=order.get("purchaser_first_name", "") or "",
                    purchaser_last_name=order.get("purchaser_last_name", "") or "",
                    purchaser_email=purchaser_email,
                    purchaser_phone=order.get("purchaser_phone", "") or "",
                    event_config=event_data,
                    tickets=tickets_for_email,
                )
                # 1. Najpierw zapisz do mail_log żeby mieć mail_id
                mail_record = save_mail_log(
                    event_order_id=event_order_id,
                    direction="purchaser",
                    template_key=TEMPLATE_REGISTRATION_CONFIRMATION,
                    to_email=purchaser_email,
                    subject=subject,
                    data={"event_name": event_name, "flow": FLOW_FOC},
                )
                mail_id = mail_record.get("id") if mail_record else None
                # 2. Wyślij z mail_id
                res = _send_email_via_make(
                    to_email=purchaser_email,
                    subject=subject,
                    body_html=body_html,
                    event_order_id=event_order_id,
                    template_type="foc_confirmation",
                    mail_id=mail_id,
                )
                sent["purchaser"] = bool(res.get("success"))
        elif flow == FLOW_PROFORMA:
            if not mail_log_exists(event_order_id, TEMPLATE_PROFORMA_SENT, direction="purchaser"):
                # Oblicz datę płatności (jeśli order ma payment_due_date)
                payment_due_str = None
                if order.get("payment_due_date"):
                    try:
                        from datetime import datetime
                        due_date = order["payment_due_date"]
                        if isinstance(due_date, str):
                            due_date = datetime.fromisoformat(due_date.replace('Z', '+00:00'))
                        payment_due_str = due_date.strftime("%d.%m.%Y")
                    except:
                        pass
                
                subject = f"Twoja rejestracja na {event_name} - płatność pro forma"
                body_html = render_proforma_reservation_email(
                    event_name=event_name,
                    purchaser_first_name=order.get("purchaser_first_name", "") or "",
                    purchaser_last_name=order.get("purchaser_last_name", "") or "",
                    purchaser_email=purchaser_email,
                    purchaser_phone=order.get("purchaser_phone", "") or "",
                    event_config=event_data,
                    tickets=tickets_for_email,
                    proforma_number=None,
                    payment_due_date=payment_due_str,
                )
                # 1. Najpierw zapisz do mail_log żeby mieć mail_id
                mail_record = save_mail_log(
                    event_order_id=event_order_id,
                    direction="purchaser",
                    template_key=TEMPLATE_PROFORMA_SENT,
                    to_email=purchaser_email,
                    subject=subject,
                    data={"event_name": event_name, "flow": FLOW_PROFORMA},
                )
                mail_id = mail_record.get("id") if mail_record else None
                # 2. Wyślij z mail_id
                res = _send_email_via_make(
                    to_email=purchaser_email,
                    subject=subject,
                    body_html=body_html,
                    event_order_id=event_order_id,
                    template_type="proforma_reservation",
                    mail_id=mail_id,
                )
                sent["purchaser"] = bool(res.get("success"))

    # Participant mail: tylko po paid i komplecie
    if status == "paid":
        try:
            sent["participants"] = send_participant_ticket_emails(
                event_order_id=event_order_id,
                event_name=event_name,
                event_config=event_data,
                event_id=order.get("event_id", ""),
            )
        except Exception as e:
            _log("ERROR", f"Błąd wysyłki maili do uczestników po kompletności: {e}", {"event_order_id": event_order_id})

    return {"ok": True, "complete": True, "flow": flow, "sent": sent, **comp}


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
        ticket_name = t.get("ticketName") or t.get("ticket_name") or f"Rezerwacja ({ticket_class_id[:8]}...)" if ticket_class_id else "Rezerwacja"
        # Usuń słowo "Bilet" z nazwy jeśli jest
        if ticket_name and isinstance(ticket_name, str):
            ticket_name = ticket_name.replace("Bilet ", "").replace("bilet ", "")
        
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


def _process_pending_attendees_for_order(event_order_id: str) -> Dict[str, Any]:
    """
    Przetwarza osieroconych uczestników z bufora pending_attendees.
    
    Wywoływane gdy order webhook przetwarza zamówienie - sprawdza czy
    są jakieś "zaparkowane" uczestniki (z attendee webhook który przyszedł
    przed order webhook) i aktualizuje ich dane w tabeli participants.
    """
    from pg_storage import (
        get_pending_attendees_for_order,
        mark_pending_attendee_processed,
        update_participant_details,
        get_participant_by_ticket,
        save_participant,
    )
    
    pending = get_pending_attendees_for_order(event_order_id)
    
    if not pending:
        return {"processed": 0, "skipped": 0}
    
    _log("INFO", "Przetwarzanie pending_attendees z bufora", {
        "event_order_id": event_order_id,
        "pending_count": len(pending),
    })
    
    processed = 0
    skipped = 0
    
    for att in pending:
        try:
            ticket_id = att.get("ticket_id", "")
            email = att.get("email", "")
            first_name = att.get("first_name", "")
            last_name = att.get("last_name", "")
            phone = att.get("phone", "")
            company = att.get("company", "")
            position = att.get("position", "")
            badge_name = att.get("badge_name", "")
            attendee_id = att.get("attendee_id", "")
            
            # Sprawdź czy uczestnik istnieje
            existing = get_participant_by_ticket(event_order_id, ticket_id)
            
            import time
            extra_data = {
                "attendee_id": attendee_id,
                "source": "pending_attendee_buffer",
                "attendee_webhook_received": True,
                "attendee_webhook_received_at": int(time.time()),
                "company": company,
                "position": position,
                "badge_name": badge_name,
                "pending_attendee_id": att.get("id"),
            }
            
            if existing:
                # Aktualizuj istniejącego uczestnika
                existing_status = existing.get("status", "")
                new_status = "emailed" if existing_status.lower() == "emailed" else "registered"
                effective_email = email or existing.get("email", "") or ""
                effective_first_name = first_name or existing.get("first_name", "") or ""
                effective_last_name = last_name or existing.get("last_name", "") or ""
                effective_phone = phone or existing.get("phone", "") or ""
                
                success = update_participant_details(
                    event_order_id=event_order_id,
                    ticket_id=ticket_id,
                    email=effective_email,
                    first_name=effective_first_name,
                    last_name=effective_last_name,
                    phone=effective_phone,
                    status=new_status,
                    extra_data=extra_data,
                )
                
                if success:
                    mark_pending_attendee_processed(att["id"])
                    processed += 1
                    _log("DEBUG", "Pending attendee przetworzony (update)", {
                        "pending_id": att["id"],
                        "ticket_id": ticket_id,
                        "email": email,
                    })
                else:
                    skipped += 1
                    _log("WARNING", "Nie udało się zaktualizować uczestnika z bufora", {
                        "pending_id": att["id"],
                        "ticket_id": ticket_id,
                    })
            else:
                # Utwórz nowego uczestnika (rzadki przypadek - brak slotu)
                participant_id = save_participant(
                    event_order_id=event_order_id,
                    ticket_id=ticket_id,
                    ticket_class_id="",
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    phone=phone,
                    status="registered",
                    data=extra_data,
                )
                
                if participant_id:
                    mark_pending_attendee_processed(att["id"])
                    processed += 1
                    _log("DEBUG", "Pending attendee przetworzony (nowy)", {
                        "pending_id": att["id"],
                        "ticket_id": ticket_id,
                        "participant_id": participant_id,
                    })
                else:
                    skipped += 1
                    _log("WARNING", "Nie udało się utworzyć uczestnika z bufora", {
                        "pending_id": att["id"],
                        "ticket_id": ticket_id,
                    })
                    
        except Exception as e:
            skipped += 1
            _log("WARNING", "Błąd przetwarzania pending_attendee", {
                "pending_id": att.get("id"),
                "error": str(e),
            })
    
    if processed > 0:
        _log("INFO", "Pending attendees przetworzone", {
            "event_order_id": event_order_id,
            "processed": processed,
            "skipped": skipped,
        })
    
    return {"processed": processed, "skipped": skipped}


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
            if enriched_ticket.get("name", "").startswith("Rezerwacja ("):
                enriched_ticket["name"] = f"Nierozpoznany ({ticket_class_id[:12]}...)"
        
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
            "quantity": 1,
            "unit_price_net": 0,  # Zostanie uzupełnione z total
            "vat_rate": "23",
        }]
    
    positions = []
    for t in tickets:
        name = t.get("name") or "Rezerwacja"
        # Usuń słowo "Bilet" z nazwy jeśli jest
        if name and isinstance(name, str):
            name = name.replace("Bilet ", "").replace("bilet ", "")
        if event_name:
            name = f"{name} - {event_name}"
        
        vat_rate = t.get("vat_rate", 23)
        # wFirma akceptuje stawki jako string: "23", "8", "5", "0", "zw", "np"
        vat_str = str(vat_rate) if vat_rate in (23, 8, 5, 0) else "23"
        
        positions.append({
            "name": name,
            "unit": "szt.",
            "quantity": t.get("quantity", 1),
            "unit_price_net": t.get("unit_price_net", 0),  # Cena netto jednostkowa
            "vat_rate": vat_str,
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
# Serie produkcyjne
WFIRMA_SERIES_NAME = os.environ.get("WFIRMA_SERIES_NAME", "Eventy Faktura VAT")  # Seria dla faktur VAT
WFIRMA_SERIES_PROFORMA = os.environ.get("WFIRMA_SERIES_PROFORMA", "Eventy Pro forma")  # Seria dla proform
WFIRMA_SERIES_CORRECTION = os.environ.get("WFIRMA_SERIES_CORRECTION", "Eventy Korekta")  # Seria dla korekt
# Serie testowe (używane gdy WFIRMA_COMPANY in ['test', 'md_test'])
WFIRMA_SERIES_NAME_TEST = os.environ.get("WFIRMA_SERIES_NAME_TEST", "Eventy Faktura VAT TEST")
WFIRMA_SERIES_PROFORMA_TEST = os.environ.get("WFIRMA_SERIES_PROFORMA_TEST", "Eventy Pro forma TEST")
WFIRMA_API_KEY = os.environ.get("MAKE_RENDER_API_KEY", "")  # Ten sam klucz co dla innych API


def _create_wfirma_invoice(
    order_data: Dict[str, Any],
    event_name: str,
    document_type: str = "normal",  # "normal" (VAT) lub "proforma"
    payment_status: str = "paid",   # "paid" lub "unpaid"
    send_email: bool = True,
    proforma_reference: str = None,  # Numer proformy do referencji (tylko dla document_type="normal")
    existing_contractor_id: str = None,  # ID kontrahenta z wFirma (np. z proformy)
    is_sandbox: bool = None,  # Tryb sandbox - jeśli True, używa serii testowych
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Tworzy fakturę w wFirma przez wewnętrzne wywołanie API.
    
    Args:
        order_data: Dane zamówienia z _extract_order_data
        event_name: Nazwa wydarzenia
        document_type: "normal" (faktura VAT) lub "proforma"
        payment_status: "paid" (opłacona) lub "unpaid" (nieopłacona)
        send_email: Czy wysłać fakturę emailem
        proforma_reference: Numer proformy do referencji w opisie (np. "W nawiązaniu do proformy: X")
        existing_contractor_id: ID kontrahenta z wFirma - jeśli podany, użyje tego samego kontrahenta
        is_sandbox: Tryb sandbox - jeśli True, używa serii testowych (Eventy Faktura VAT TEST, itp.)
    
    Returns:
        (success, invoice_data, error_message)
    """
    event_order_id = order_data.get("event_order_id", "")
    
    # Określ czy to tryb testowy:
    # 1. Najpierw parametr is_sandbox z funkcji
    # 2. Fallback do order_data.sandbox (z payloadu webhooka)
    # 3. Fallback do WFIRMA_COMPANY (zmienna ENV)
    if is_sandbox is None:
        is_sandbox = order_data.get("sandbox", False)
    use_test_series = is_sandbox or WFIRMA_COMPANY in ('test', 'md_test')
    
    # Wybierz odpowiednią serię w zależności od typu dokumentu i trybu (test/prod)
    if use_test_series:
        # Serie testowe
        if document_type == "proforma":
            series_name = WFIRMA_SERIES_PROFORMA_TEST
        else:
            series_name = WFIRMA_SERIES_NAME_TEST
    else:
        # Serie produkcyjne
        if document_type == "proforma":
            series_name = WFIRMA_SERIES_PROFORMA
        else:
            series_name = WFIRMA_SERIES_NAME
    
    _log("INFO", "WFIRMA: START tworzenia dokumentu", {
        "document_type": document_type,
        "event_order_id": event_order_id,
        "payment_status": payment_status,
        "company": WFIRMA_COMPANY,
        "is_sandbox": is_sandbox,
        "use_test_series": use_test_series,
        "series_name": series_name,
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
    if not positions or (len(positions) == 1 and positions[0].get("unit_price_net", 0) == 0):
        # Oblicz cenę netto z brutto (VAT 23%)
        price_net = round(total / 1.23, 2)
        positions = [{
            "name": f"Udział w wydarzeniu: {event_name}" if event_name else "Udział w wydarzeniu",
            "unit": "szt.",
            "quantity": 1,
            "unit_price_net": price_net,
            "vat_rate": "23",
        }]

    # Preview pozycji (max 5) - żeby było widać co idzie do wFirma
    try:
        positions_preview = []
        for p in positions[:5]:
            positions_preview.append({
                "name": (p.get("name") or "")[:80],
                "quantity": p.get("quantity"),
                "unit_price_net": p.get("unit_price_net"),
                "vat_rate": p.get("vat_rate"),
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
    
    # Opis faktury - zawiera nazwę wydarzenia i opcjonalnie referencję do proformy
    invoice_description = event_name
    if proforma_reference and document_type == "normal":
        invoice_description = f"W nawiązaniu do proformy: {proforma_reference}\n{event_name}"
    
    # Payload do workflow endpoint
    invoice_payload = {
        "company": WFIRMA_COMPANY,
        "series_name": series_name,
        "payment_status": payment_status,
        "payment_due_days": 0 if payment_status == "paid" else 7,
        "description": invoice_description,
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
    
    # Jeśli mamy existing_contractor_id (np. z proformy) - użyj tego samego kontrahenta
    if existing_contractor_id:
        invoice_payload["existing_contractor_id"] = existing_contractor_id
    
    # Jeśli mamy proforma_invoice_id - powiąż fakturę końcową z proformą (systemowo)
    if proforma_reference and document_type == "normal":
        # Wyciągnij ID proformy z order_data (jeśli przekazane)
        proforma_id = order_data.get("proforma_invoice_id")
        if proforma_id:
            invoice_payload["parent_invoice_id"] = proforma_id
    
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
            # Wyciągnij contractor_id z odpowiedzi (do użycia przy fakturze końcowej)
            contractor_data = result.get("contractor", {})
            contractor_id = contractor_data.get("id") if isinstance(contractor_data, dict) else None
            
            _log("INFO", "WFIRMA: SUCCESS dokument utworzony", {
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "contractor_id": contractor_id,
                "email_sent": result.get("email_sent", False),
                "document_type": document_type,
                "payment_status": payment_status,
                "duration_ms": dt_ms,
            })
            
            # Zapisz do bazy (z contractor_id dla późniejszego użycia przy fakturze końcowej)
            try:
                from pg_storage import save_wfirma_document
                save_wfirma_document(
                    event_order_id=event_order_id,
                    wfirma_invoice_id=str(invoice_id) if invoice_id else "",
                    wfirma_number=invoice_number or "",
                    document_type=document_type,
                    email_to=purchaser_email,
                    raw=result,
                    wfirma_contractor_id=str(contractor_id) if contractor_id else None,
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
    proforma_reference: str = None,  # Numer proformy do referencji w opisie faktury
    existing_contractor_id: str = None,  # ID kontrahenta z wFirma (z proformy)
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Tworzy opłaconą fakturę VAT po płatności Stripe.
    
    Args:
        proforma_reference: Numer proformy (np. "PROF/EV/TEST/1/01/2026") - 
                           jeśli podany, zostanie dodany do opisu faktury
        existing_contractor_id: ID kontrahenta z wFirma (np. z proformy) -
                               jeśli podany, użyje tego samego kontrahenta
    """
    # #region agent log
    import traceback
    _caller = ''.join(traceback.format_stack()[-4:-1])
    print(f"[DEBUG-PAID-INVOICE] CALLED | order_id={order_data.get('event_order_id','')}, proforma_ref={proforma_reference}, contractor_id={existing_contractor_id}, caller_snippet={_caller[:300]}")
    # #endregion
    _log("INFO", "WFIRMA: Wywołanie _create_paid_invoice", {
        "event_order_id": order_data.get("event_order_id", ""),
        "event_name": event_name[:30] if event_name else None,
        "proforma_reference": proforma_reference,
        "existing_contractor_id": existing_contractor_id,
    })
    return _create_wfirma_invoice(
        order_data=order_data,
        event_name=event_name,
        document_type="normal",
        payment_status="paid",
        send_email=send_email,
        proforma_reference=proforma_reference,
        existing_contractor_id=existing_contractor_id,
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
    email_sent = False  # zostanie wysłany dopiero po komplecie attendee-webhooków

    # Wzbogać bilety o nazwy z bazy
    raw_tickets = order_data.get("tickets", [])
    if raw_tickets and event_id:
        enriched_tickets, unknown_ids = _enrich_tickets_with_names(raw_tickets, event_id)
        if unknown_ids:
            _log("DEBUG", "FOC FLOW: Nierozpoznane ticket_class_id", {"unknown_ids": unknown_ids[:5]})
    else:
        enriched_tickets = raw_tickets

    _log("INFO", "FOC FLOW: Czekam na komplet attendee-webhooków przed wysyłką maili", {
        "event_order_id": event_order_id,
        "purchaser_email_present": bool(purchaser_email),
    })

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

    participant_email_stats = {"sent": 0, "failed": 0, "skipped": 0}

    _log("INFO", "FOC FLOW: Zakończono", {
        "event_order_id": event_order_id,
        "email_sent": email_sent,
        "participant_emails_sent": 0,
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

    # ZABEZPIECZENIE: Sprawdź czy proforma już istnieje dla tego zamówienia
    try:
        from pg_storage import get_wfirma_documents
        existing_docs = get_wfirma_documents(event_order_id)
        existing_proforma = next((d for d in existing_docs if d.get("document_type") == "proforma"), None)
        if existing_proforma:
            # Jeśli brak terminu płatności w zamówieniu, ustaw 7 dni od utworzenia
            try:
                from datetime import datetime, timedelta, timezone
                from pg_storage import get_order
                current_order = get_order(event_order_id) or {}
                if not current_order.get("payment_due_date"):
                    created_at = current_order.get("created_at")
                    if isinstance(created_at, str):
                        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    if not created_at:
                        created_at = datetime.now(timezone.utc)
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    payment_due_ts = int((created_at + timedelta(days=7)).timestamp())
                    update_order_status(event_order_id, "pending_payment", payment_due_date=payment_due_ts)
            except Exception:
                pass

            _log("WARN", "PROFORMA FLOW: Proforma już istnieje - pomijam tworzenie duplikatu", {
                "event_order_id": event_order_id,
                "existing_proforma_id": existing_proforma.get("wfirma_invoice_id"),
                "existing_proforma_number": existing_proforma.get("wfirma_number"),
            })
            # Zwróć informację o istniejącej proformie zamiast tworzyć duplikat
            return {
                "flow": FLOW_PROFORMA,
                "status": "already_exists",
                "order_status": "pending_payment",
                "mail_tasks": [],
                "wfirma_action": {
                    "type": "proforma_already_exists",
                    "invoice_id": existing_proforma.get("wfirma_invoice_id"),
                    "invoice_number": existing_proforma.get("wfirma_number"),
                },
                "message": f"Proforma już istnieje: {existing_proforma.get('wfirma_number')}",
            }
    except Exception as check_err:
        _log("WARNING", "PROFORMA FLOW: Błąd sprawdzania istniejącej proformy - kontynuuję", {"error": str(check_err)})

    # Aktualizuj status zamówienia i ustaw termin płatności (7 dni)
    import time
    payment_due_timestamp = int(time.time() + 7 * 24 * 60 * 60)  # +7 dni
    update_order_status(event_order_id, "pending_payment", payment_due_date=payment_due_timestamp)

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

    _log("INFO", "PROFORMA FLOW: Czekam na komplet attendee-webhooków przed wysyłką maila rezerwacyjnego", {
        "event_order_id": event_order_id,
        "purchaser_email_present": bool(purchaser_email),
        "proforma_created": bool(proforma_result),
    })

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

    # Aktualizuj status zamówienia i ustaw termin płatności (24h dla Stripe)
    import time
    payment_due_timestamp = int(time.time() + 24 * 60 * 60)  # +24h (Stripe session TTL)
    update_order_status(event_order_id, "pending_payment", payment_due_date=payment_due_timestamp)

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
                name = (t.get("name") or "Rezerwacja").strip()
                # Usuń słowo "Bilet" z nazwy jeśli jest
                if name:
                    name = name.replace("Bilet ", "").replace("bilet ", "")
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
        
        # 1. Najpierw zapisz do mail_log żeby mieć mail_id
        mail_record = save_mail_log(
            event_order_id=event_order_id,
            direction="purchaser",
            template_key=TEMPLATE_STRIPE_PAYMENT_LINK,
            to_email=purchaser_email,
            subject=subject,
            data={
                "event_name": event_name,
                "flow": FLOW_STRIPE,
                "total": total,
                "currency": currency,
                "stripe_url": stripe_url or "",
            },
        )
        mail_id = mail_record.get("id") if mail_record else None
        _log("DEBUG", "STRIPE FLOW: Mail log zapisany", {"mail_id": mail_id})
        
        # 2. Wyślij przez Make webhook z mail_id (preferowane)
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
                mail_id=mail_id,  # Przekaż mail_id do callbacku
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

    # UWAGA: Mail purchaser już zapisany do mail_log przed wysyłką (z mail_id)
    # Nie dodajemy do mail_tasks żeby uniknąć duplikatu

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
# ASYNC WEBHOOK PROCESSING (queue + worker)
# ---------------------------------------------------------------------------


def queue_webhook_processing(webhook_id: int, event_order_id: str) -> bool:
    """
    Dodaje webhook do kolejki do przetworzenia.
    Używamy prostego mechanizmu przez UPDATE status w DB.
    
    Args:
        webhook_id: ID webhooka w tabeli backstage_webhook_events
        event_order_id: ID zamówienia
    
    Returns:
        True jeśli sukces
    """
    from pg_storage import _with_conn, _put_conn
    
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE backstage_webhook_events
            SET processed_status = 'queued'
            WHERE id = %s
        """, (int(webhook_id),))
        success = cur.rowcount > 0
        _log("INFO", f"Webhook queued for processing: webhook_id={webhook_id}, order_id={event_order_id}, success={success}")
        return success
    except Exception as e:
        _log("ERROR", f"Error queueing webhook: {e}")
        return False
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def process_queued_webhooks(limit: int = 10) -> Dict[str, Any]:
    """
    Przetwarza webhooки z kolejki (status='queued').
    Można uruchomić jako cron job co 1 minutę lub background task.
    
    Args:
        limit: Maksymalna liczba webhooków do przetworzenia w jednym wywołaniu
    
    Returns:
        Dict z processed, failed, errors
    """
    from pg_storage import _with_conn, _put_conn, _dict_cursor, save_error_task
    
    pool = None
    conn = None
    processed = 0
    failed = 0
    errors = []
    
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        
        # Pobierz webhooки do przetworzenia
        cur.execute("""
            SELECT id, event_order_id, payload
            FROM backstage_webhook_events
            WHERE processed_status = 'queued'
            ORDER BY received_at ASC
            LIMIT %s
        """, (int(limit),))
        
        webhooks = cur.fetchall()
        _log("INFO", f"Found {len(webhooks)} webhooks to process")
        
        for webhook in webhooks:
            webhook_id = webhook['id']
            event_order_id = webhook.get('event_order_id', '')
            
            try:
                # Zmień status na 'processing'
                cur.execute("""
                    UPDATE backstage_webhook_events
                    SET processed_status = 'processing'
                    WHERE id = %s
                """, (webhook_id,))
                
                _log("INFO", f"Processing webhook {webhook_id} for order {event_order_id}")
                
                # Przetwórz webhook (wywołaj istniejącą logikę)
                payload = webhook.get('payload') or {}
                if isinstance(payload, str):
                    import json
                    payload = json.loads(payload)
                
                result = process_backstage_order(payload)
                
                if result.get("status") == "ok":
                    # Oznacz jako przetworzone
                    cur.execute("""
                        UPDATE backstage_webhook_events
                        SET processed_status = 'processed',
                            processed_at = NOW()
                        WHERE id = %s
                    """, (webhook_id,))
                    processed += 1
                    _log("INFO", f"Webhook {webhook_id} processed successfully")
                else:
                    # Oznacz jako failed
                    error_msg = result.get("error", "Unknown error")
                    cur.execute("""
                        UPDATE backstage_webhook_events
                        SET processed_status = 'failed',
                            error = %s,
                            processed_at = NOW()
                        WHERE id = %s
                    """, (error_msg, webhook_id))
                    failed += 1
                    errors.append(f"Webhook {webhook_id}: {error_msg}")
                    _log("ERROR", f"Webhook {webhook_id} failed: {error_msg}")
                    
            except Exception as e:
                error_msg = str(e)
                # Zapisz błąd
                cur.execute("""
                    UPDATE backstage_webhook_events
                    SET processed_status = 'failed',
                        error = %s,
                        processed_at = NOW()
                    WHERE id = %s
                """, (error_msg, webhook_id))
                failed += 1
                errors.append(f"Webhook {webhook_id}: {error_msg}")
                
                # Loguj do error_queue
                try:
                    save_error_task(
                        category="backstage",
                        severity="error",
                        title=f"Błąd przetwarzania webhooka {webhook_id}",
                        description=error_msg,
                        event_order_id=event_order_id,
                        error_data={"webhook_id": webhook_id, "stack": traceback.format_exc()},
                        can_retry=True,
                    )
                except Exception:
                    pass
                
                _log("ERROR", f"Exception processing webhook {webhook_id}: {e}")
        
        return {
            "processed": processed,
            "failed": failed,
            "errors": errors[:10],  # Ogranicz liczbę błędów
            "total_found": len(webhooks),
        }
        
    except Exception as e:
        _log("ERROR", f"Error in process_queued_webhooks: {e}")
        return {
            "processed": processed,
            "failed": failed,
            "errors": [str(e)],
            "total_found": 0,
        }
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def get_webhook_queue_stats() -> Dict[str, int]:
    """
    Zwraca statystyki kolejki webhooków.
    
    Returns:
        Dict z queued, processing, processed, failed
    """
    from pg_storage import _with_conn, _put_conn
    
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        
        stats = {}
        for status in ['queued', 'processing', 'processed', 'failed', 'received']:
            cur.execute("""
                SELECT COUNT(*) FROM backstage_webhook_events
                WHERE processed_status = %s
            """, (status,))
            stats[status] = cur.fetchone()[0] or 0
        
        return stats
    except Exception as e:
        _log("ERROR", f"Error getting webhook queue stats: {e}")
        return {"queued": 0, "processing": 0, "processed": 0, "failed": 0, "received": 0}
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


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

    # Bezpieczeństwo: NIE loguj pełnego payloadu (PII). Zostaw fingerprint do korelacji.
    try:
        payload_str_compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        payload_hash = hashlib.sha256(payload_str_compact.encode("utf-8")).hexdigest()[:16]
        _log("DEBUG", "Payload fingerprint", {"sha256_16": payload_hash, "bytes": len(payload_str_compact)})
    except Exception as e:
        _log("WARN", f"Nie udało się zrobić fingerprint payload: {e}")
    
    try:
        # 1. Wyciągnij dane zamówienia
        _log("INFO", "Krok 1: Ekstrakcja danych zamówienia...")
        order_data = _extract_order_data(payload)
        event_order_id = order_data["event_order_id"]
        event_id = order_data["event_id"]
        
        # Minimalne maskowanie PII w logach
        purchaser_email = (order_data.get("purchaser_email") or "").strip()
        masked_email = purchaser_email
        if "@" in purchaser_email and len(purchaser_email) > 3:
            local, _, domain = purchaser_email.partition("@")
            masked_email = (local[:2] + "***@" + domain) if domain else (purchaser_email[:2] + "***")

        _log("INFO", "Wyekstrahowane dane", {
            "event_order_id": event_order_id,
            "event_id": event_id,
            "purchaser_email": masked_email,
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
                # PRODUKCJA: blokuj duplikaty TYLKO gdy poprzednie przetwarzanie się udało.
                # Jeśli poprzednio było failed/received, pozwól na retry (np. po deployu / braku ENV).
                existing_processed_status = (webhook_record or {}).get("processed_status")
                if existing_processed_status == "processed":
                    _log("WARN", "Webhook już był przetworzony (duplikat)", {"event_order_id": event_order_id})
                    existing_order = get_order(event_order_id)
                    return {
                        "status": "duplicate",
                        "order_id": event_order_id,
                        "message": "Webhook już został przetworzony",
                        "existing_status": existing_order.get("status") if existing_order else None,
                    }
                _log("WARNING", "Webhook duplikat, ale poprzednio nie był 'processed' — retry", {
                    "event_order_id": event_order_id,
                    "previous_processed_status": existing_processed_status,
                })
        
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
            sandbox=order_data.get("sandbox", False),  # Zapisz tryb testowy
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

        # 4c. Przetwórz bufor pending_attendees (race condition: attendee webhook przed order webhook)
        try:
            _process_pending_attendees_for_order(event_order_id)
        except Exception as e:
            _log("WARNING", "Błąd przetwarzania pending_attendees", {"event_order_id": event_order_id, "error": str(e)})

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

        # 6b. FALLBACK: Jeśli flow=FOC (status=paid od razu), sprawdź kompletność i wyślij maile
        # To obsługuje przypadek gdy attendee webhook przyszedł PRZED order webhook (bufor pending_attendees)
        if flow == FLOW_FOC:
            try:
                _log("INFO", "Krok 6b: FOC fallback - sprawdzam kompletność i wysyłam maile...")
                foc_send_result = maybe_send_backstage_emails_when_complete(event_order_id)
                _log("INFO", "FOC fallback zakończony", {
                    "event_order_id": event_order_id,
                    "complete": foc_send_result.get("complete"),
                    "purchaser_sent": foc_send_result.get("sent", {}).get("purchaser"),
                    "participants_sent": foc_send_result.get("sent", {}).get("participants", {}).get("sent", 0),
                })
            except Exception as e:
                _log("WARNING", f"Błąd FOC fallback wysyłki maili: {e}", {"event_order_id": event_order_id})

        # 7. Zapisz mail tasks do logu (tylko purchaser/participant - internal nie są wysyłane)
        _log("INFO", "Krok 7: Zapisywanie mail tasks...")
        for i, mt in enumerate(result.get("mail_tasks", [])):
            direction = mt.get("direction", "purchaser")
            # Pomijaj internal - te maile nie są wysyłane, więc nie loguj jako "queued"
            if direction == "internal":
                _log("DEBUG", f"Mail task {i+1} pominięty (internal - nie wysyłany)", {
                    "template": mt.get("template"),
                    "to": mt.get("to"),
                })
                continue
            save_mail_log(
                event_order_id=event_order_id,
                direction=direction,
                template_key=mt.get("template", ""),
                to_email=mt.get("to", ""),
                subject=mt.get("subject", ""),
                data=mt.get("data", {}),
            )
            _log("DEBUG", f"Mail task {i+1} zapisany", {
                "template": mt.get("template"),
                "to": mt.get("to"),
                "direction": direction,
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


# ---------------------------------------------------------------------------
# BACKSTAGE EVENT WEBHOOK - tworzenie wydarzeń jako "draft" do zatwierdzenia
# ---------------------------------------------------------------------------

# Mapowanie kodów krajów na nazwy
COUNTRY_CODE_TO_NAME = {
    "PL": "Polska",
    "DE": "Niemcy",
    "GB": "Wielka Brytania",
    "US": "Stany Zjednoczone",
    "FR": "Francja",
    "CZ": "Czechy",
    "SK": "Słowacja",
}

# Mapowanie miesięcy na teksty polskie
MONTH_NAMES_PL = {
    1: ("styczeń", "stycznia"),
    2: ("luty", "lutego"),
    3: ("marzec", "marca"),
    4: ("kwiecień", "kwietnia"),
    5: ("maj", "maja"),
    6: ("czerwiec", "czerwca"),
    7: ("lipiec", "lipca"),
    8: ("sierpień", "sierpnia"),
    9: ("wrzesień", "września"),
    10: ("październik", "października"),
    11: ("listopad", "listopada"),
    12: ("grudzień", "grudnia"),
}


def _build_backstage_image_url(resource_id: str, portal_id: str) -> str:
    """
    Buduje URL do obrazu Backstage z resourceId i portalId.
    
    Wzorzec: https://previewengine-accl.zohopublic.eu/image/BACKSTAGE/{resourceId}?cli-msg={base64}
    """
    import base64
    
    if not resource_id or not portal_id:
        return ""
    
    cli_msg_data = {
        "id": str(resource_id),
        "module": "EventImageResource",
        "subResourceId": int(portal_id) if portal_id.isdigit() else portal_id,
        "type": "0",
        "portalId": str(portal_id),
    }
    
    cli_msg_json = json.dumps(cli_msg_data, separators=(',', ':'))
    cli_msg_b64 = base64.b64encode(cli_msg_json.encode('utf-8')).decode('utf-8')
    
    return f"https://previewengine-accl.zohopublic.eu/image/BACKSTAGE/{resource_id}?cli-msg={cli_msg_b64}"


def _country_code_to_name(code: str) -> str:
    """Mapuje kod kraju (PL, DE, ...) na pełną nazwę."""
    if not code:
        return ""
    return COUNTRY_CODE_TO_NAME.get(code.upper(), code)


def _parse_iso_datetime(dt_str: str) -> Optional[datetime.datetime]:
    """Parsuje datę ISO 8601 do obiektu datetime."""
    if not dt_str:
        return None
    try:
        # Usuń 'Z' i zamień na +00:00 dla kompatybilności
        dt_str = dt_str.replace('Z', '+00:00')
        # Obsłuż format z milisekundami
        if '.' in dt_str:
            # Python 3.6+ obsługuje fromisoformat z timezone
            return datetime.datetime.fromisoformat(dt_str.split('.')[0])
        return datetime.datetime.fromisoformat(dt_str.replace('+00:00', ''))
    except (ValueError, AttributeError):
        return None


def _calculate_date_fields(start_dt: Optional[datetime.datetime], end_dt: Optional[datetime.datetime]) -> Dict[str, Any]:
    """
    Wylicza pola pomocnicze z dat start/end.
    
    Zwraca dict z polami:
    - event_day: dzień (liczba)
    - event_month_number: miesiąc (liczba)
    - event_month_text: nazwa miesiąca (styczeń, luty, ...)
    - event_month_text_odmiana: odmiana (stycznia, lutego, ...)
    - event_year: rok
    - event_days_count: liczba dni wydarzenia
    - event_time_text: godzina startu (HH:MM)
    - event_day_text_1: pełna data (np. "6 lutego 2026")
    """
    result: Dict[str, Any] = {}
    
    if start_dt:
        result["event_day"] = str(start_dt.day)
        result["event_month_number"] = str(start_dt.month)
        
        month_names = MONTH_NAMES_PL.get(start_dt.month, ("", ""))
        result["event_month_text"] = month_names[0]
        result["event_month_text_odmiana"] = month_names[1]
        result["event_year"] = str(start_dt.year)
        result["event_time_text"] = start_dt.strftime("%H:%M")
        result["event_day_text_1"] = f"{start_dt.day} {month_names[1]} {start_dt.year}"
    
    if start_dt and end_dt:
        delta = end_dt.date() - start_dt.date()
        result["event_days_count"] = str(delta.days + 1)  # +1 bo włącznie z dniem końcowym
    elif start_dt:
        result["event_days_count"] = "1"
    
    return result


def _strip_html_tags(html: str) -> str:
    """Usuwa tagi HTML z tekstu, zostawiając czysty tekst."""
    import re
    if not html:
        return ""
    # Usuń tagi HTML
    clean = re.sub(r'<[^>]+>', ' ', html)
    # Zamień wielokrotne spacje na pojedyncze
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()


def _send_new_event_notification(event_id: str, event_name: str, event_data: Dict[str, Any]) -> None:
    """
    Wysyła email powiadomienie o nowym wydarzeniu wymagającym konfiguracji.
    
    Email do: halo@medidesk.com
    """
    import os
    
    notification_email = os.environ.get("BACKSTAGE_EVENT_INFO_EMAIL", "halo@medidesk.com")
    panel_url = os.environ.get("PANEL_BASE_URL", "https://wfirma-api.onrender.com")
    edit_url = f"{panel_url}/admin-v2/events/{event_id}/edit"
    
    # Data wydarzenia
    event_date = event_data.get("event_date_time", "")[:10] if event_data.get("event_date_time") else "nie podano"
    event_city = event_data.get("event_location_city", "") or "nie podano"
    
    subject = f"🆕 Nowe wydarzenie: {event_name}"
    
    body_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #2563eb;">Utworzono nowe wydarzenie</h2>
        
        <div style="background: #f8fafc; padding: 1rem; border-radius: 8px; margin: 1rem 0;">
            <p style="margin: 0.5rem 0;"><strong>Nazwa:</strong> {event_name}</p>
            <p style="margin: 0.5rem 0;"><strong>ID:</strong> {event_id}</p>
            <p style="margin: 0.5rem 0;"><strong>Data:</strong> {event_date}</p>
            <p style="margin: 0.5rem 0;"><strong>Miasto:</strong> {event_city}</p>
        </div>
        
        <div style="background: #fef3c7; padding: 1rem; border-radius: 8px; margin: 1rem 0; border-left: 4px solid #f59e0b;">
            <p style="margin: 0; color: #92400e;"><strong>⚠️ Wydarzenie wymaga uzupełnienia konfiguracji:</strong></p>
            <ul style="margin: 0.5rem 0; color: #92400e;">
                <li>Kolory brandingowe</li>
                <li>Banner email</li>
                <li>URL wydarzenia</li>
                <li>Typy biletów</li>
            </ul>
        </div>
        
        <p style="margin: 1.5rem 0;">
            <a href="{edit_url}" style="display: inline-block; background: #2563eb; color: white; padding: 0.75rem 1.5rem; text-decoration: none; border-radius: 6px; font-weight: 600;">
                Uzupełnij konfigurację →
            </a>
        </p>
        
        <p style="color: #64748b; font-size: 0.875rem;">
            Ten email został wysłany automatycznie po utworzeniu wydarzenia z Zoho Backstage.
        </p>
    </div>
    """
    
    try:
        result = _send_email_via_make(
            to_email=notification_email,
            subject=subject,
            body_html=body_html,
            template_type="new_event_notification",
            extra_data={
                "event_id": event_id,
                "event_name": event_name,
            }
        )
        _log("INFO", f"Wysłano powiadomienie o nowym wydarzeniu do {notification_email}", {
            "event_id": event_id,
            "result": result.get("success", False),
        })
    except Exception as e:
        _log("ERROR", f"Błąd wysyłania powiadomienia o nowym wydarzeniu: {e}")
        raise


def _parse_event_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parsuje payload webhooka wydarzenia z Zoho Backstage.
    
    Zwraca dict z polami:
    - event_id: ID wydarzenia
    - event_name: nazwa wydarzenia
    - data: dict z polami do zapisania w JSONB
    - mapped_fields: lista zmapowanych pól (do informacji)
    """
    mapped_fields: List[str] = []
    data: Dict[str, Any] = {}
    
    # --- Podstawowe pola ---
    event_id = str(payload.get("id") or "").strip()
    event_name = str(payload.get("name") or "").strip()
    
    if not event_id:
        raise ValueError("Brak wymaganego pola 'id' w payload")
    
    # eventId i eventName do data (dla spójności z panelem admina)
    data["eventId"] = event_id
    mapped_fields.append("eventId")
    
    if event_name:
        data["eventName"] = event_name
        mapped_fields.append("eventName")
    
    # --- Opis i podsumowanie ---
    description = payload.get("description") or ""
    if description:
        data["event_description"] = _strip_html_tags(description)
        mapped_fields.append("event_description")
    
    summary = payload.get("summary") or ""
    if summary:
        data["event_summary"] = summary
        mapped_fields.append("event_summary")
    
    # --- Kategoria ---
    category = payload.get("category") or ""
    if category:
        data["event_category"] = category
        mapped_fields.append("event_category")
    
    # --- Lokalizacja ---
    venue_name = payload.get("venue_name") or ""
    if venue_name:
        data["event_location_place"] = venue_name
        mapped_fields.append("event_location_place")
    
    # venueTranslations[0] - miasto, adres
    venue_translations = payload.get("venueTranslations") or []
    if venue_translations and len(venue_translations) > 0:
        vt = venue_translations[0]
        
        city = vt.get("townOrCity") or ""
        if city:
            data["event_location_city"] = city
            mapped_fields.append("event_location_city")
        
        street = vt.get("street") or ""
        if street:
            data["event_location_address"] = street
            mapped_fields.append("event_location_address")
        
        state = vt.get("state") or ""
        if state:
            data["event_location_state"] = state
            mapped_fields.append("event_location_state")
    
    # venues[0] - kod pocztowy, kraj, współrzędne
    venues = payload.get("venues") or []
    if venues and len(venues) > 0:
        v = venues[0]
        
        zipcode = v.get("zipcode") or ""
        if zipcode:
            data["event_location_zip"] = zipcode
            mapped_fields.append("event_location_zip")
        
        country_code = v.get("country") or ""
        if country_code:
            data["event_country"] = _country_code_to_name(country_code)
            mapped_fields.append("event_country")
        
        # Współrzędne (opcjonalne)
        lat = v.get("latitude") or ""
        lng = v.get("longitude") or ""
        if lat and lng:
            data["event_location_lat"] = lat
            data["event_location_lng"] = lng
            mapped_fields.extend(["event_location_lat", "event_location_lng"])
        
        # Google Maps link z placeId
        place_id = v.get("placeId") or ""
        if place_id:
            data["event_location_google_link"] = f"https://www.google.com/maps/place/?q=place_id:{place_id}"
            mapped_fields.append("event_location_google_link")
    
    # --- Daty ---
    portal_id = str(payload.get("portal") or "")
    timezone = payload.get("timezone") or "Europe/Warsaw"
    data["event_timezone"] = timezone
    mapped_fields.append("event_timezone")
    
    # Preferuj event.startDateTime.local jeśli dostępne
    event_obj = payload.get("event") or {}
    start_dt_obj = event_obj.get("startDateTime") or {}
    end_dt_obj = event_obj.get("endDateTime") or {}
    
    start_local = start_dt_obj.get("local") or payload.get("startDate") or ""
    end_local = end_dt_obj.get("local") or payload.get("endDate") or ""
    
    if start_local:
        data["event_date_time"] = start_local
        mapped_fields.append("event_date_time")
    
    if end_local:
        data["event_end_date_time"] = end_local
        mapped_fields.append("event_end_date_time")
    
    # Wylicz pola pomocnicze z dat
    start_dt = _parse_iso_datetime(start_local)
    end_dt = _parse_iso_datetime(end_local)
    
    date_fields = _calculate_date_fields(start_dt, end_dt)
    for key, value in date_fields.items():
        data[key] = value
        mapped_fields.append(key)
    
    # --- Obrazy ---
    cover_photo_id = payload.get("coverPhotoResourceId") or ""
    if cover_photo_id and portal_id:
        url = _build_backstage_image_url(cover_photo_id, portal_id)
        if url:
            data["event_mail_link_top_banner"] = url
            mapped_fields.append("event_mail_link_top_banner")
    
    # Logo z eventMetas[0]
    event_metas = payload.get("eventMetas") or []
    if event_metas and len(event_metas) > 0:
        logo_id = event_metas[0].get("logoResourceId") or ""
        if logo_id and portal_id:
            url = _build_backstage_image_url(logo_id, portal_id)
            if url:
                data["event_logo_link"] = url
                mapped_fields.append("event_logo_link")
    
    # --- Linki Backstage ---
    # Pobierz brand_id z payloadu (różne możliwe nazwy pola)
    brand_id = str(payload.get("brand") or payload.get("brandId") or payload.get("brand_id") or "").strip()
    data["_backstage_brand_id"] = brand_id
    
    if event_id and portal_id:
        # Nowy format URL Backstage (z home# i brand)
        if brand_id:
            data["event_config_link"] = f"https://backstage.zoho.eu/home#/portal/{portal_id}/brand/{brand_id}/event/{event_id}/details"
            data["event_orders_link"] = f"https://backstage.zoho.eu/home#/portal/{portal_id}/brand/{brand_id}/event/{event_id}/orders"
            data["event_attendees_link"] = f"https://backstage.zoho.eu/home#/portal/{portal_id}/brand/{brand_id}/event/{event_id}/attendees"
        else:
            # Fallback bez brand_id (stary format)
            data["event_config_link"] = f"https://backstage.zoho.eu/home#/portal/{portal_id}/event/{event_id}/details"
            data["event_orders_link"] = f"https://backstage.zoho.eu/home#/portal/{portal_id}/event/{event_id}/orders"
            data["event_attendees_link"] = f"https://backstage.zoho.eu/home#/portal/{portal_id}/event/{event_id}/attendees"
        mapped_fields.extend(["event_config_link", "event_orders_link", "event_attendees_link"])
    
    # --- Surowe dane (do debugowania) ---
    data["_backstage_raw_event_id"] = event_id
    data["_backstage_portal_id"] = portal_id
    data["_backstage_webhook_received"] = datetime.datetime.utcnow().isoformat() + "Z"
    
    return {
        "event_id": event_id,
        "event_name": event_name or f"Event {event_id}",
        "data": data,
        "mapped_fields": mapped_fields,
    }


def process_backstage_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Przetwarza webhook wydarzenia z Zoho Backstage.
    
    Tworzy lub aktualizuje wydarzenie w bazie danych ze statusem "draft" (do zatwierdzenia).
    
    Args:
        payload: dane z webhooka Zoho Backstage
        
    Returns:
        dict z wynikiem:
        {
            "status": "ok" | "error",
            "event_id": "...",
            "event_name": "...",
            "action": "created" | "updated",
            "message": "...",
            "mapped_fields": [...],
            "error": "..."  // tylko gdy status=error
        }
    """
    _log("INFO", "========== BACKSTAGE EVENT WEBHOOK ==========")
    _log("DEBUG", "Otrzymano payload wydarzenia", {"keys": list(payload.keys())[:20]})
    
    try:
        # 1. Parsuj payload
        parsed = _parse_event_webhook(payload)
        event_id = parsed["event_id"]
        event_name = parsed["event_name"]
        data = parsed["data"]
        mapped_fields = parsed["mapped_fields"]
        
        _log("INFO", f"Sparsowano wydarzenie: {event_id} - {event_name}", {
            "mapped_fields_count": len(mapped_fields),
        })
        
        # 2. Sprawdź czy wydarzenie już istnieje
        from pg_storage import get_event, upsert_event
        
        existing = get_event(event_id)
        action = "updated" if existing else "created"
        
        # 3. Zapisz/zaktualizuj wydarzenie ze statusem "pending_config" (wymaga uzupełnienia)
        event_status = "pending_config" if not existing else (existing.get("status") or "pending_config")
        
        upsert_event(
            event_id=event_id,
            event_name=event_name,
            status=event_status,
            notes=f"Utworzono automatycznie z webhooka Backstage ({datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC)",
            data=data,
            is_active=True,
        )
        
        _log("INFO", f"Wydarzenie {action}: {event_id}", {
            "event_name": event_name,
            "status": event_status,
        })
        
        # 4. Wyślij email powiadomienie dla NOWYCH wydarzeń
        if action == "created":
            try:
                _send_new_event_notification(event_id, event_name, data)
            except Exception as notify_err:
                _log("WARNING", f"Nie udało się wysłać powiadomienia o nowym wydarzeniu: {notify_err}")
        
        message = "Wydarzenie utworzone - wymaga uzupełnienia konfiguracji" if action == "created" else "Wydarzenie zaktualizowane"
        
        return {
            "status": "ok",
            "event_id": event_id,
            "event_name": event_name,
            "action": action,
            "message": message,
            "mapped_fields": mapped_fields,
        }
        
    except ValueError as e:
        _log("ERROR", f"Błąd walidacji: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
        }
    except Exception as e:
        _log("ERROR", f"Wyjątek podczas przetwarzania wydarzenia: {str(e)}")
        import traceback
        _log("ERROR", f"Traceback: {traceback.format_exc()}")
        return {
            "status": "error",
            "error": str(e),
        }
