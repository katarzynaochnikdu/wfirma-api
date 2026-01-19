"""
Email Sender - wysyłka maili przez SMTP (Microsoft Office 365).
"""
import os
import smtplib
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any

# Konfiguracja SMTP Microsoft
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")


def _log(level: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
    """Loguje wiadomość z timestampem."""
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[{ts}] [EMAIL] [{level}]"
    if data:
        import json
        safe_data = {k: (v[:100] + "..." if isinstance(v, str) and len(v) > 100 else v) for k, v in data.items()}
        print(f"{prefix} {message} | {json.dumps(safe_data, ensure_ascii=False, default=str)}")
    else:
        print(f"{prefix} {message}")


def is_email_configured() -> bool:
    """Sprawdza czy email jest skonfigurowany."""
    return bool(EMAIL_ADDRESS and EMAIL_PASSWORD)


def get_email_status() -> Dict[str, Any]:
    """Zwraca status konfiguracji email."""
    return {
        "configured": is_email_configured(),
        "smtp_host": SMTP_HOST,
        "smtp_port": SMTP_PORT,
        "email_address": EMAIL_ADDRESS[:3] + "***" if EMAIL_ADDRESS else None,
        "password_set": bool(EMAIL_PASSWORD),
    }


def send_email(
    to_email: str,
    subject: str,
    body_html: str,
    body_text: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Wysyła email przez SMTP.
    
    Args:
        to_email: Adres odbiorcy
        subject: Temat
        body_html: Treść HTML
        body_text: Treść tekstowa (opcjonalna, generowana z HTML jeśli brak)
        reply_to: Adres do odpowiedzi (opcjonalny)
    
    Returns:
        Dict z status, message, etc.
    """
    if not is_email_configured():
        _log("ERROR", "Email nie skonfigurowany!")
        return {
            "success": False,
            "error": "Email nie skonfigurowany - brak EMAIL_ADDRESS lub EMAIL_PASSWORD",
        }
    
    _log("INFO", "Wysyłam email", {"to": to_email, "subject": subject})
    
    try:
        # Utwórz wiadomość
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = to_email
        if reply_to:
            msg["Reply-To"] = reply_to
        
        # Dodaj treść tekstową
        if not body_text:
            # Prosta konwersja HTML -> text (usuń tagi)
            import re
            body_text = re.sub(r'<[^>]+>', '', body_html)
            body_text = re.sub(r'\s+', ' ', body_text).strip()
        
        part_text = MIMEText(body_text, "plain", "utf-8")
        part_html = MIMEText(body_html, "html", "utf-8")
        
        msg.attach(part_text)
        msg.attach(part_html)
        
        # Połącz i wyślij
        _log("DEBUG", f"Łączę z {SMTP_HOST}:{SMTP_PORT}")
        
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.set_debuglevel(0)  # Ustaw 1 dla debug
            server.ehlo()
            server.starttls()
            server.ehlo()
            
            _log("DEBUG", "Loguję się...")
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            
            _log("DEBUG", "Wysyłam...")
            server.sendmail(EMAIL_ADDRESS, [to_email], msg.as_string())
        
        _log("INFO", "Email wysłany pomyślnie!", {"to": to_email})
        
        return {
            "success": True,
            "message": f"Email wysłany do {to_email}",
            "to": to_email,
            "subject": subject,
        }
        
    except smtplib.SMTPAuthenticationError as e:
        _log("ERROR", f"Błąd autentykacji SMTP: {e}")
        return {
            "success": False,
            "error": f"Błąd autentykacji SMTP - sprawdź EMAIL_ADDRESS i EMAIL_PASSWORD: {str(e)}",
        }
    except smtplib.SMTPException as e:
        _log("ERROR", f"Błąd SMTP: {e}")
        return {
            "success": False,
            "error": f"Błąd SMTP: {str(e)}",
        }
    except Exception as e:
        _log("ERROR", f"Nieoczekiwany błąd: {e}")
        return {
            "success": False,
            "error": f"Nieoczekiwany błąd: {str(e)}",
        }


def send_test_email(to_email: Optional[str] = None) -> Dict[str, Any]:
    """
    Wysyła testowy email.
    
    Args:
        to_email: Adres odbiorcy (domyślnie EMAIL_ADDRESS - do siebie)
    """
    if not to_email:
        to_email = EMAIL_ADDRESS
    
    subject = "🧪 Test wysyłki z Render - wFirma API"
    body_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color: #2563eb;">✅ Test wysyłki email</h2>
        <p>Ten email został wysłany z aplikacji <strong>wFirma API</strong> na Render.</p>
        <hr style="border: 1px solid #e5e7eb; margin: 20px 0;">
        <p><strong>Data wysłania:</strong> {datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC</p>
        <p><strong>SMTP Host:</strong> {SMTP_HOST}</p>
        <p><strong>From:</strong> {EMAIL_ADDRESS}</p>
        <hr style="border: 1px solid #e5e7eb; margin: 20px 0;">
        <p style="color: #6b7280; font-size: 12px;">
            Jeśli widzisz tę wiadomość, konfiguracja email działa poprawnie! 🎉
        </p>
    </body>
    </html>
    """
    
    return send_email(to_email, subject, body_html)
