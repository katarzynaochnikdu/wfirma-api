import os
import time
from typing import Any, Dict, Optional, Tuple

try:
    import psycopg2
    import psycopg2.extras
    from psycopg2.pool import SimpleConnectionPool
except Exception:  # pragma: no cover
    psycopg2 = None  # type: ignore
    SimpleConnectionPool = None  # type: ignore


# NOTE:
# - Render Postgres udostępnia DATABASE_URL (internal) w formacie postgresql://...
# - Trzymamy inicjalizację schematu w kodzie (małe kroki, bez zewn. narzędzi migracyjnych na start).


SCHEMA_VERSION = "001_init"


SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  event_name TEXT NOT NULL,
  status TEXT,
  notes TEXT,
  data JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS event_ticket_classes (
  event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
  ticket_class_id TEXT NOT NULL,
  ticket_name TEXT,
  data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (event_id, ticket_class_id)
);

CREATE TABLE IF NOT EXISTS payment_rules (
  id BIGSERIAL PRIMARY KEY,
  event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
  payment_option_id TEXT,
  payment_type INTEGER,
  payment_option_name_pattern TEXT,
  flow TEXT NOT NULL, -- FOC | PROFORMA | STRIPE
  is_default BOOLEAN NOT NULL DEFAULT FALSE,
  wfirma_company TEXT, -- md/test/md_test (jeśli potrzebne)
  wfirma_series_name TEXT,
  wfirma_document_type TEXT, -- proforma / normal / ...
  wfirma_payment_due_days INTEGER,
  data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payment_rules_event_id ON payment_rules(event_id);

CREATE TABLE IF NOT EXISTS orders (
  event_order_id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL REFERENCES events(event_id),
  purchaser_email TEXT,
  purchaser_first_name TEXT,
  purchaser_last_name TEXT,
  purchaser_phone TEXT,
  purchaser_nip TEXT,
  payment_option_name TEXT,
  payment_type INTEGER,
  promo_code TEXT,
  total NUMERIC(12,2),
  currency TEXT NOT NULL DEFAULT 'PLN',
  status TEXT NOT NULL DEFAULT 'received', -- received/pending_payment/paid/failed/cancelled
  raw JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_event_id ON orders(event_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

CREATE TABLE IF NOT EXISTS order_tickets (
  id BIGSERIAL PRIMARY KEY,
  event_order_id TEXT NOT NULL REFERENCES orders(event_order_id) ON DELETE CASCADE,
  ticket_class_id TEXT,
  ticket_id TEXT,
  quantity INTEGER NOT NULL DEFAULT 1,
  price_per_unit NUMERIC(12,2),
  total_amount NUMERIC(12,2),
  discount_amount NUMERIC(12,2),
  tax_percent NUMERIC(6,3),
  is_tax_inclusive BOOLEAN,
  data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_order_tickets_order_id ON order_tickets(event_order_id);

CREATE TABLE IF NOT EXISTS participants (
  id BIGSERIAL PRIMARY KEY,
  event_order_id TEXT NOT NULL REFERENCES orders(event_order_id) ON DELETE CASCADE,
  email TEXT,
  first_name TEXT,
  last_name TEXT,
  phone TEXT,
  ticket_id TEXT,
  ticket_class_id TEXT,
  status TEXT NOT NULL DEFAULT 'registered', -- registered/emailed/failed/cancelled
  data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (event_order_id, email, ticket_id)
);

CREATE INDEX IF NOT EXISTS idx_participants_order_id ON participants(event_order_id);

CREATE TABLE IF NOT EXISTS stripe_sessions (
  id BIGSERIAL PRIMARY KEY,
  event_order_id TEXT NOT NULL REFERENCES orders(event_order_id) ON DELETE CASCADE,
  checkout_session_id TEXT UNIQUE,
  payment_intent_id TEXT UNIQUE,
  status TEXT NOT NULL DEFAULT 'created', -- created/paid/failed/expired
  amount_total NUMERIC(12,2),
  currency TEXT,
  url TEXT,
  raw JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (event_order_id)
);

CREATE TABLE IF NOT EXISTS wfirma_documents (
  id BIGSERIAL PRIMARY KEY,
  event_order_id TEXT NOT NULL REFERENCES orders(event_order_id) ON DELETE CASCADE,
  wfirma_invoice_id TEXT,
  wfirma_number TEXT,
  document_type TEXT, -- proforma/normal/...
  status TEXT NOT NULL DEFAULT 'created', -- created/sent/failed
  pdf_path TEXT,
  email_to TEXT,
  email_cc TEXT,
  raw JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wfirma_docs_order_id ON wfirma_documents(event_order_id);

CREATE TABLE IF NOT EXISTS mail_log (
  id BIGSERIAL PRIMARY KEY,
  event_order_id TEXT,
  direction TEXT, -- purchaser/internal/participant
  template_key TEXT,
  to_email TEXT,
  subject TEXT,
  status TEXT NOT NULL DEFAULT 'queued', -- queued/sent/failed
  error TEXT,
  data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mail_log_order_id ON mail_log(event_order_id);

CREATE TABLE IF NOT EXISTS backstage_webhook_events (
  id BIGSERIAL PRIMARY KEY,
  dedupe_key TEXT UNIQUE,
  event_order_id TEXT,
  event_id TEXT,
  payload JSONB NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  processed_at TIMESTAMPTZ,
  processed_status TEXT NOT NULL DEFAULT 'received', -- received/processed/failed
  error TEXT
);

CREATE INDEX IF NOT EXISTS idx_backstage_events_order_id ON backstage_webhook_events(event_order_id);
"""


_pool: Optional["SimpleConnectionPool"] = None
_schema_checked_at: float = 0.0


def _get_database_url() -> Optional[str]:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        return None
    return url


def _get_pool() -> "SimpleConnectionPool":
    global _pool
    if psycopg2 is None or SimpleConnectionPool is None:
        raise RuntimeError("Brak psycopg2. Sprawdź requirements.txt i redeploy.")

    if _pool is not None:
        return _pool

    url = _get_database_url()
    if not url:
        raise RuntimeError("Brak DATABASE_URL w ENV (Render Postgres niepodpięty).")

    # Minimalny pool; Render ma limity połączeń zależne od planu.
    _pool = SimpleConnectionPool(minconn=1, maxconn=4, dsn=url)
    return _pool


def _with_conn() -> Tuple[Any, Any]:
    pool = _get_pool()
    conn = pool.getconn()
    try:
        # Autocommit ułatwia DDL bez dodatkowych commitów
        conn.autocommit = True
    except Exception:
        pass
    return pool, conn


def _put_conn(pool: Any, conn: Any) -> None:
    try:
        pool.putconn(conn)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def ensure_schema(force: bool = False) -> Dict[str, Any]:
    """
    Zapewnia, że schemat istnieje.
    Zwraca dict diagnostyczny (bez sekretów).
    """
    global _schema_checked_at
    now = time.time()
    # Limituj częstotliwość sprawdzania (przy wielu requestach)
    if not force and _schema_checked_at and (now - _schema_checked_at) < 30:
        return {"ok": True, "skipped": True, "reason": "recent_check"}

    _schema_checked_at = now

    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()

        # 1) Schemat (idempotentne CREATE IF NOT EXISTS)
        cur.execute(SCHEMA_SQL)

        # 2) Wersja migracji
        cur.execute("SELECT 1 FROM schema_migrations WHERE version=%s", (SCHEMA_VERSION,))
        exists = cur.fetchone() is not None
        if not exists:
            cur.execute("INSERT INTO schema_migrations(version) VALUES(%s)", (SCHEMA_VERSION,))

        return {"ok": True, "schema_version": SCHEMA_VERSION, "applied": (not exists)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def get_db_status() -> Dict[str, Any]:
    """
    Diagnostyka DB: czy jest DATABASE_URL, czy da się połączyć, czy schemat jest gotowy.
    """
    url = _get_database_url()
    if not url:
        return {"ok": False, "db_configured": False, "error": "Brak DATABASE_URL w ENV"}

    # Nie zwracamy pełnego URL (sekrety). Zwróć tylko informację, że jest.
    base = {"db_configured": True, "db_url_present": True}

    if psycopg2 is None:
        return {**base, "ok": False, "error": "Brak psycopg2 (dependency)"}

    # Spróbuj init schematu
    schema = ensure_schema(force=True)
    if not schema.get("ok"):
        return {**base, "ok": False, "schema": schema}

    # Prosty ping
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute("SELECT NOW()")
        now = cur.fetchone()[0]
        return {**base, "ok": True, "schema": schema, "db_time": str(now)}
    except Exception as e:
        return {**base, "ok": False, "error": str(e), "schema": schema}
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)

