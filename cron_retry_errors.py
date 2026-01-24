"""
Cron job do automatycznego retry błędów z error_queue.

Uruchomienie:
    python cron_retry_errors.py

Dodaj do Render cron jobs (co 5 minut):
    python cron_retry_errors.py

Exponential backoff:
    - 1. próba: po 5 minutach
    - 2. próba: po 15 minutach
    - 3. próba: po 60 minutach
"""
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, Any, List

# Dodaj katalog główny do ścieżki Python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def log(level: str, message: str, data: Dict[str, Any] = None) -> None:
    """Loguje wiadomość z timestampem."""
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[{ts}] [CRON_RETRY] [{level}]"
    if data:
        print(f"{prefix} {message} | {data}")
    else:
        print(f"{prefix} {message}")


def get_backoff_minutes(retry_count: int) -> int:
    """
    Zwraca czas oczekiwania (w minutach) przed następną próbą.
    Exponential backoff: 5min, 15min, 60min
    """
    backoff_schedule = [5, 15, 60]
    if retry_count >= len(backoff_schedule):
        return backoff_schedule[-1]
    return backoff_schedule[retry_count]


def should_retry_task(task: Dict[str, Any]) -> bool:
    """
    Sprawdza czy zadanie powinno być ponowione.
    
    Args:
        task: Zadanie z error_queue
    
    Returns:
        True jeśli można ponowić
    """
    # Sprawdź czy można ponowić
    if not task.get("can_retry"):
        return False
    
    # Sprawdź czy nie przekroczono limitu
    retry_count = task.get("retry_count", 0)
    max_retries = task.get("max_retries", 3)
    if retry_count >= max_retries:
        return False
    
    # Sprawdź czas od ostatniej próby (exponential backoff)
    last_retry = task.get("last_retry_at") or task.get("created_at")
    if not last_retry:
        return True  # Można ponowić jeśli brak daty
    
    # Oblicz wymagany czas oczekiwania
    required_wait_minutes = get_backoff_minutes(retry_count)
    
    # Porównaj z czasem teraz
    now = datetime.utcnow()
    if hasattr(last_retry, "tzinfo") and last_retry.tzinfo:
        # Jeśli last_retry ma timezone, usuń go do porównania
        from datetime import timezone
        last_retry = last_retry.replace(tzinfo=None)
    
    time_since_last = now - last_retry
    minutes_since_last = time_since_last.total_seconds() / 60
    
    return minutes_since_last >= required_wait_minutes


def retry_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """
    Próbuje ponowić zadanie.
    
    W rzeczywistości ta funkcja powinna wywołać odpowiednią logikę
    w zależności od kategorii błędu. Na razie tylko zwiększamy retry_count.
    
    Args:
        task: Zadanie z error_queue
    
    Returns:
        Dict z success, error
    """
    from pg_storage import retry_error_task
    
    task_id = task.get("id")
    category = task.get("category", "unknown")
    
    log("INFO", f"Retrying task {task_id}", {"category": category, "title": task.get("title", "")[:50]})
    
    # Zwiększ retry_count
    result = retry_error_task(task_id)
    
    if result.get("success"):
        # Tu można dodać logikę ponowienia w zależności od kategorii
        # Na przykład:
        # - category="email": wywołaj ponowną wysyłkę emaila
        # - category="stripe": wywołaj ponowne przetworzenie płatności
        # - category="wfirma": wywołaj ponowne utworzenie faktury
        
        # Na razie tylko logujemy sukces zwiększenia retry_count
        log("INFO", f"Task {task_id} retry_count increased", {"new_count": result.get("retry_count")})
        return {"success": True, "task_id": task_id}
    else:
        log("ERROR", f"Failed to retry task {task_id}", {"error": result.get("error")})
        return {"success": False, "error": result.get("error")}


def retry_failed_tasks() -> Dict[str, Any]:
    """
    Główna funkcja - próbuje ponowić nieudane zadania z error_queue.
    
    Returns:
        Dict z retried, skipped, failed, errors
    """
    from pg_storage import list_error_tasks
    
    log("INFO", "Starting retry of failed tasks...")
    
    # Pobierz zadania do retry (nie resolved, można retry)
    tasks = list_error_tasks(resolved=False, limit=100)
    
    log("INFO", f"Found {len(tasks)} unresolved tasks")
    
    retried = 0
    skipped = 0
    failed = 0
    errors = []
    
    for task in tasks:
        task_id = task.get("id")
        
        # Sprawdź czy powinniśmy ponowić
        if not should_retry_task(task):
            skipped += 1
            continue
        
        # Spróbuj ponowić
        result = retry_task(task)
        
        if result.get("success"):
            retried += 1
        else:
            failed += 1
            errors.append(f"Task {task_id}: {result.get('error', 'Unknown error')}")
    
    log("INFO", f"Retry completed: retried={retried}, skipped={skipped}, failed={failed}")
    
    return {
        "retried": retried,
        "skipped": skipped,
        "failed": failed,
        "errors": errors[:10],
        "total_tasks": len(tasks),
    }


def process_webhook_queue() -> Dict[str, Any]:
    """
    Przetwarza webhooки z kolejki (jeśli są).
    
    Returns:
        Dict z processed, failed
    """
    try:
        from backstage_engine import process_queued_webhooks
        
        log("INFO", "Processing webhook queue...")
        result = process_queued_webhooks(limit=10)
        
        log("INFO", f"Webhook queue processed: processed={result.get('processed')}, failed={result.get('failed')}")
        return result
    except ImportError:
        log("WARNING", "backstage_engine not available, skipping webhook processing")
        return {"processed": 0, "failed": 0}
    except Exception as e:
        log("ERROR", f"Error processing webhook queue: {e}")
        return {"processed": 0, "failed": 0, "error": str(e)}


def main():
    """Główna funkcja uruchamiana przez cron."""
    log("INFO", "=" * 50)
    log("INFO", "CRON RETRY ERRORS - START")
    log("INFO", "=" * 50)
    
    # 1. Retry błędów z error_queue
    retry_result = retry_failed_tasks()
    
    # 2. Przetwórz kolejkę webhooków
    webhook_result = process_webhook_queue()
    
    # Podsumowanie
    log("INFO", "-" * 50)
    log("INFO", "SUMMARY")
    log("INFO", f"  Error Queue: retried={retry_result.get('retried')}, skipped={retry_result.get('skipped')}, failed={retry_result.get('failed')}")
    log("INFO", f"  Webhooks: processed={webhook_result.get('processed')}, failed={webhook_result.get('failed')}")
    log("INFO", "=" * 50)
    log("INFO", "CRON RETRY ERRORS - END")
    log("INFO", "=" * 50)
    
    return {
        "error_queue": retry_result,
        "webhooks": webhook_result,
    }


if __name__ == "__main__":
    main()
