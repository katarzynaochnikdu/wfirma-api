import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

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
-- Twarda ochrona przed podwójną fakturą VAT (normal) dla tego samego zamówienia
CREATE UNIQUE INDEX IF NOT EXISTS uniq_wfirma_normal_per_order
ON wfirma_documents(event_order_id)
WHERE document_type = 'normal';
-- Twarda ochrona przed podwójną proformą dla tego samego zamówienia
CREATE UNIQUE INDEX IF NOT EXISTS uniq_wfirma_proforma_per_order
ON wfirma_documents(event_order_id)
WHERE document_type = 'proforma';

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

-- ---------------------------------------------------------------------------
-- TOKEN MONITOR (wFirma refresh token expiry notifications)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS token_monitor_state (
  company TEXT PRIMARY KEY,
  last_check_at TIMESTAMPTZ,
  last_email_at TIMESTAMPTZ,
  last_email_kind TEXT, -- daily / urgent / expired
  last_days_remaining NUMERIC(10,3),
  last_status TEXT, -- ok / warn / expired / missing
  last_error TEXT
);

-- ---------------------------------------------------------------------------
-- WFIRMA TOKENS (bezpieczne przechowywanie tokenów OAuth2)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wfirma_tokens (
  company TEXT PRIMARY KEY,
  access_token TEXT NOT NULL,
  access_token_expires_at BIGINT NOT NULL,        -- Unix timestamp
  refresh_token TEXT NOT NULL,
  refresh_token_expires_at BIGINT,                 -- Unix timestamp (30 dni od utworzenia)
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),   -- Kiedy pierwszy raz zapisano
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()    -- Kiedy ostatnio zaktualizowano
);
-- ---------------------------------------------------------------------------
-- OAUTH STATE (dla ręcznego /auth -> /callback)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS oauth_states (
  state TEXT PRIMARY KEY,
  company TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  used_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_oauth_states_company ON oauth_states(company);

-- ---------------------------------------------------------------------------
-- ADMIN USERS (logowanie do panelu /admin)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin_users (
  id BIGSERIAL PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  first_name TEXT,
  last_name TEXT,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'admin',
  allowed_pages JSONB NOT NULL DEFAULT '[]'::jsonb,
  must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  failed_login_count INTEGER NOT NULL DEFAULT 0,
  locked_until TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_login_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_admin_users_email ON admin_users(email);

-- ---------------------------------------------------------------------------
-- ADMIN AUDIT LOG (kto/co/kiedy w panelu admin)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin_audit_log (
  id BIGSERIAL PRIMARY KEY,
  admin_user_id BIGINT REFERENCES admin_users(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  target_email TEXT,
  ip TEXT,
  user_agent TEXT,
  data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_log_user_id ON admin_audit_log(admin_user_id);
CREATE INDEX IF NOT EXISTS idx_admin_audit_log_action ON admin_audit_log(action);
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

        # 1b) Dodatkowe kolumny (idempotentne ALTER) - bezpieczne dla istniejących baz
        cur.execute("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS first_name TEXT")
        cur.execute("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS last_name TEXT")
        cur.execute("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'admin'")
        cur.execute("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS allowed_pages JSONB NOT NULL DEFAULT '[]'::jsonb")
        cur.execute("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE")

        # 1c) Backfill dla istniejących rekordów (żeby nie blokować dostępu)
        cur.execute("UPDATE admin_users SET role = 'admin' WHERE role IS NULL OR role = ''")
        cur.execute("UPDATE admin_users SET allowed_pages = '[]'::jsonb WHERE allowed_pages IS NULL")
        cur.execute("UPDATE admin_users SET must_change_password = FALSE WHERE must_change_password IS NULL")

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


def _dict_cursor(conn: Any):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)  # type: ignore[attr-defined]


def list_events(limit: int = 200) -> List[Dict[str, Any]]:
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            "SELECT event_id, event_name, status, notes, data, created_at, updated_at "
            "FROM events ORDER BY updated_at DESC LIMIT %s",
            (int(limit),),
        )
        return [dict(r) for r in (cur.fetchall() or [])]
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def get_event(event_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            "SELECT event_id, event_name, status, notes, data, created_at, updated_at "
            "FROM events WHERE event_id=%s",
            (str(event_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def upsert_event(event_id: str, event_name: str, status: str, notes: str, data: Dict[str, Any]) -> Dict[str, Any]:
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO events(event_id, event_name, status, notes, data)
            VALUES(%s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO UPDATE SET
              event_name=EXCLUDED.event_name,
              status=EXCLUDED.status,
              notes=EXCLUDED.notes,
              data=EXCLUDED.data,
              updated_at=NOW()
            """,
            (
                str(event_id),
                str(event_name),
                (status or None),
                (notes or None),
                psycopg2.extras.Json(data),  # type: ignore[attr-defined]
            ),
        )
        ev = get_event(event_id)
        return ev or {"event_id": event_id, "event_name": event_name, "status": status, "notes": notes, "data": data}
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def delete_event(event_id: str) -> None:
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM events WHERE event_id=%s", (str(event_id),))
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def get_ticket_classes(event_id: str) -> List[Dict[str, Any]]:
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            "SELECT event_id, ticket_class_id, ticket_name, data, created_at, updated_at "
            "FROM event_ticket_classes WHERE event_id=%s ORDER BY ticket_class_id ASC",
            (str(event_id),),
        )
        return [dict(r) for r in (cur.fetchall() or [])]
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def replace_ticket_classes(event_id: str, classes: List[Dict[str, Any]]) -> None:
    """
    Najprostszy model edycji: replace-all dla danego eventu.
    `classes` to lista obiektów z kluczami: ticket_class_id, ticket_name, data (opcjonalnie).
    """
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM event_ticket_classes WHERE event_id=%s", (str(event_id),))
        for item in classes or []:
            tci = str(item.get("ticket_class_id") or "").strip()
            if not tci:
                continue
            ticket_name = item.get("ticket_name")
            data = item.get("data") or {}
            cur.execute(
                """
                INSERT INTO event_ticket_classes(event_id, ticket_class_id, ticket_name, data)
                VALUES(%s, %s, %s, %s)
                """,
                (
                    str(event_id),
                    tci,
                    (str(ticket_name) if ticket_name is not None else None),
                    psycopg2.extras.Json(data),  # type: ignore[attr-defined]
                ),
            )
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


# ---------------------------------------------------------------------------
# PAYMENT RULES CRUD
# ---------------------------------------------------------------------------


def list_payment_rules(event_id: str) -> List[Dict[str, Any]]:
    """Pobiera reguły płatności dla danego eventu."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT id, event_id, payment_option_id, payment_type, payment_option_name_pattern,
                   flow, is_default, wfirma_company, wfirma_series_name, wfirma_document_type,
                   wfirma_payment_due_days, data, created_at, updated_at
            FROM payment_rules
            WHERE event_id = %s
            ORDER BY is_default ASC, id ASC
            """,
            (str(event_id),),
        )
        return [dict(r) for r in (cur.fetchall() or [])]
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def get_payment_rule(rule_id: int) -> Optional[Dict[str, Any]]:
    """Pobiera pojedynczą regułę płatności po ID."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT id, event_id, payment_option_id, payment_type, payment_option_name_pattern,
                   flow, is_default, wfirma_company, wfirma_series_name, wfirma_document_type,
                   wfirma_payment_due_days, data, created_at, updated_at
            FROM payment_rules
            WHERE id = %s
            """,
            (int(rule_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def upsert_payment_rule(
    event_id: str,
    flow: str,
    rule_id: Optional[int] = None,
    payment_option_id: Optional[str] = None,
    payment_type: Optional[int] = None,
    payment_option_name_pattern: Optional[str] = None,
    is_default: bool = False,
    wfirma_company: Optional[str] = None,
    wfirma_series_name: Optional[str] = None,
    wfirma_document_type: Optional[str] = None,
    wfirma_payment_due_days: Optional[int] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Tworzy lub aktualizuje regułę płatności."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()

        if rule_id:
            # UPDATE
            cur.execute(
                """
                UPDATE payment_rules SET
                    event_id = %s,
                    payment_option_id = %s,
                    payment_type = %s,
                    payment_option_name_pattern = %s,
                    flow = %s,
                    is_default = %s,
                    wfirma_company = %s,
                    wfirma_series_name = %s,
                    wfirma_document_type = %s,
                    wfirma_payment_due_days = %s,
                    data = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id
                """,
                (
                    str(event_id),
                    payment_option_id or None,
                    payment_type,
                    payment_option_name_pattern or None,
                    str(flow),
                    bool(is_default),
                    wfirma_company or None,
                    wfirma_series_name or None,
                    wfirma_document_type or None,
                    wfirma_payment_due_days,
                    psycopg2.extras.Json(data or {}),  # type: ignore[attr-defined]
                    int(rule_id),
                ),
            )
            row = cur.fetchone()
            return get_payment_rule(int(rule_id)) or {"id": rule_id}
        else:
            # INSERT
            cur.execute(
                """
                INSERT INTO payment_rules (
                    event_id, payment_option_id, payment_type, payment_option_name_pattern,
                    flow, is_default, wfirma_company, wfirma_series_name, wfirma_document_type,
                    wfirma_payment_due_days, data
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    str(event_id),
                    payment_option_id or None,
                    payment_type,
                    payment_option_name_pattern or None,
                    str(flow),
                    bool(is_default),
                    wfirma_company or None,
                    wfirma_series_name or None,
                    wfirma_document_type or None,
                    wfirma_payment_due_days,
                    psycopg2.extras.Json(data or {}),  # type: ignore[attr-defined]
                ),
            )
            row = cur.fetchone()
            new_id = row[0] if row else None
            return get_payment_rule(new_id) or {"id": new_id}
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def delete_payment_rule(rule_id: int) -> None:
    """Usuwa regułę płatności."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM payment_rules WHERE id = %s", (int(rule_id),))
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def match_payment_rule(event_id: str, payment_option_name: Optional[str], payment_type: Optional[int]) -> Optional[Dict[str, Any]]:
    """
    Dopasowuje regułę płatności dla danego zamówienia.
    Kolejność matchowania:
    1. Dokładne dopasowanie payment_option_name_pattern (ILIKE/contains)
    2. Dokładne dopasowanie payment_type
    3. Reguła domyślna (is_default=True)
    """
    rules = list_payment_rules(event_id)
    if not rules:
        return None

    payment_option_name_lower = (payment_option_name or "").lower()

    # 1. Szukaj po payment_option_name_pattern
    for rule in rules:
        pattern = (rule.get("payment_option_name_pattern") or "").strip().lower()
        if pattern and pattern in payment_option_name_lower:
            return rule

    # 2. Szukaj po payment_type
    for rule in rules:
        rule_payment_type = rule.get("payment_type")
        if rule_payment_type is not None and rule_payment_type == payment_type:
            return rule

    # 3. Szukaj domyślnej reguły
    for rule in rules:
        if rule.get("is_default"):
            return rule

    return None


# ---------------------------------------------------------------------------
# ORDERS CRUD
# ---------------------------------------------------------------------------


def get_order(event_order_id: str) -> Optional[Dict[str, Any]]:
    """Pobiera zamówienie po event_order_id."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT event_order_id, event_id, purchaser_email, purchaser_first_name, purchaser_last_name,
                   purchaser_phone, purchaser_nip, payment_option_name, payment_type, promo_code,
                   total, currency, status, raw, created_at, updated_at
            FROM orders
            WHERE event_order_id = %s
            """,
            (str(event_order_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def list_orders(
    event_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Lista zamówień z filtrowaniem."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)

        where_clauses = []
        params: List[Any] = []

        if event_id:
            where_clauses.append("event_id = %s")
            params.append(str(event_id))
        if status:
            where_clauses.append("status = %s")
            params.append(str(status))

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        params.extend([int(limit), int(offset)])

        cur.execute(
            f"""
            SELECT event_order_id, event_id, purchaser_email, purchaser_first_name, purchaser_last_name,
                   purchaser_phone, purchaser_nip, payment_option_name, payment_type, promo_code,
                   total, currency, status, created_at, updated_at
            FROM orders
            {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        return [dict(r) for r in (cur.fetchall() or [])]
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def list_orders_older_than_minutes(
    min_age_minutes: int,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """
    Zwraca zamówienia starsze niż min_age_minutes (po created_at).
    Używane przez monitory (np. kompletność attendee-webhooków).
    """
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT event_order_id, event_id, purchaser_email, total, currency, status, payment_option_name,
                   created_at, updated_at
            FROM orders
            WHERE created_at <= (NOW() - (%s || ' minutes')::interval)
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (int(min_age_minutes), int(limit)),
        )
        return [dict(r) for r in (cur.fetchall() or [])]
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def upsert_order(
    event_order_id: str,
    event_id: str,
    purchaser_email: Optional[str] = None,
    purchaser_first_name: Optional[str] = None,
    purchaser_last_name: Optional[str] = None,
    purchaser_phone: Optional[str] = None,
    purchaser_nip: Optional[str] = None,
    payment_option_name: Optional[str] = None,
    payment_type: Optional[int] = None,
    promo_code: Optional[str] = None,
    total: Optional[float] = None,
    currency: str = "PLN",
    status: str = "received",
    raw: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Tworzy lub aktualizuje zamówienie (idempotentne po event_order_id)."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO orders (
                event_order_id, event_id, purchaser_email, purchaser_first_name, purchaser_last_name,
                purchaser_phone, purchaser_nip, payment_option_name, payment_type, promo_code,
                total, currency, status, raw
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_order_id) DO UPDATE SET
                purchaser_email = COALESCE(EXCLUDED.purchaser_email, orders.purchaser_email),
                purchaser_first_name = COALESCE(EXCLUDED.purchaser_first_name, orders.purchaser_first_name),
                purchaser_last_name = COALESCE(EXCLUDED.purchaser_last_name, orders.purchaser_last_name),
                purchaser_phone = COALESCE(EXCLUDED.purchaser_phone, orders.purchaser_phone),
                purchaser_nip = COALESCE(EXCLUDED.purchaser_nip, orders.purchaser_nip),
                payment_option_name = COALESCE(EXCLUDED.payment_option_name, orders.payment_option_name),
                payment_type = COALESCE(EXCLUDED.payment_type, orders.payment_type),
                promo_code = COALESCE(EXCLUDED.promo_code, orders.promo_code),
                total = COALESCE(EXCLUDED.total, orders.total),
                currency = COALESCE(EXCLUDED.currency, orders.currency),
                raw = EXCLUDED.raw,
                updated_at = NOW()
            """,
            (
                str(event_order_id),
                str(event_id),
                purchaser_email,
                purchaser_first_name,
                purchaser_last_name,
                purchaser_phone,
                purchaser_nip,
                payment_option_name,
                payment_type,
                promo_code,
                total,
                currency,
                status,
                psycopg2.extras.Json(raw or {}),  # type: ignore[attr-defined]
            ),
        )
        return get_order(event_order_id) or {"event_order_id": event_order_id}
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def update_order_status(event_order_id: str, status: str) -> Optional[Dict[str, Any]]:
    """Aktualizuje status zamówienia."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE orders SET status = %s, updated_at = NOW() WHERE event_order_id = %s",
            (str(status), str(event_order_id)),
        )
        return get_order(event_order_id)
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


# ---------------------------------------------------------------------------
# BACKSTAGE WEBHOOK EVENTS (idempotency)
# ---------------------------------------------------------------------------


def save_backstage_webhook(
    dedupe_key: str,
    event_order_id: str,
    event_id: str,
    payload: Dict[str, Any],
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Zapisuje raw webhook z Backstage. Zwraca (is_new, record).
    Jeśli dedupe_key już istnieje, zwraca (False, istniejący_rekord).
    """
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)

        # Sprawdź czy już istnieje
        cur.execute(
            "SELECT id, dedupe_key, event_order_id, event_id, processed_status FROM backstage_webhook_events WHERE dedupe_key = %s",
            (str(dedupe_key),),
        )
        existing = cur.fetchone()
        if existing:
            return False, dict(existing)

        # Wstaw nowy
        cur.execute(
            """
            INSERT INTO backstage_webhook_events (dedupe_key, event_order_id, event_id, payload)
            VALUES (%s, %s, %s, %s)
            RETURNING id, dedupe_key, event_order_id, event_id, processed_status
            """,
            (
                str(dedupe_key),
                str(event_order_id),
                str(event_id),
                psycopg2.extras.Json(payload),  # type: ignore[attr-defined]
            ),
        )
        row = cur.fetchone()
        return True, dict(row) if row else None
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def mark_backstage_webhook_processed(dedupe_key: str, status: str = "processed", error: Optional[str] = None) -> None:
    """Oznacza webhook jako przetworzony."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE backstage_webhook_events
            SET processed_status = %s, processed_at = NOW(), error = %s
            WHERE dedupe_key = %s
            """,
            (str(status), error, str(dedupe_key)),
        )
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


# ---------------------------------------------------------------------------
# STRIPE SESSIONS
# ---------------------------------------------------------------------------


def save_stripe_session(
    event_order_id: str,
    checkout_session_id: str,
    url: str,
    amount_total: Optional[float] = None,
    currency: str = "PLN",
    raw: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Zapisuje Stripe checkout session."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            INSERT INTO stripe_sessions (event_order_id, checkout_session_id, url, amount_total, currency, raw)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_order_id) DO UPDATE SET
                checkout_session_id = EXCLUDED.checkout_session_id,
                url = EXCLUDED.url,
                amount_total = EXCLUDED.amount_total,
                currency = EXCLUDED.currency,
                raw = EXCLUDED.raw,
                updated_at = NOW()
            RETURNING id, event_order_id, checkout_session_id, status, url
            """,
            (
                str(event_order_id),
                str(checkout_session_id),
                str(url),
                amount_total,
                str(currency),
                psycopg2.extras.Json(raw or {}),  # type: ignore[attr-defined]
            ),
        )
        row = cur.fetchone()
        return dict(row) if row else {"event_order_id": event_order_id}
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def get_stripe_session_by_checkout_id(checkout_session_id: str) -> Optional[Dict[str, Any]]:
    """Pobiera Stripe session po checkout_session_id."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT id, event_order_id, checkout_session_id, payment_intent_id, status,
                   amount_total, currency, url, raw, created_at, updated_at
            FROM stripe_sessions
            WHERE checkout_session_id = %s
            """,
            (str(checkout_session_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def update_stripe_session_paid(checkout_session_id: str, payment_intent_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Oznacza Stripe session jako opłaconą."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE stripe_sessions
            SET status = 'paid', payment_intent_id = COALESCE(%s, payment_intent_id), updated_at = NOW()
            WHERE checkout_session_id = %s
            """,
            (payment_intent_id, str(checkout_session_id)),
        )
        return get_stripe_session_by_checkout_id(checkout_session_id)
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


# ---------------------------------------------------------------------------
# WFIRMA DOCUMENTS
# ---------------------------------------------------------------------------


def save_wfirma_document(
    event_order_id: str,
    wfirma_invoice_id: str,
    wfirma_number: str,
    document_type: str,
    pdf_path: Optional[str] = None,
    email_to: Optional[str] = None,
    email_cc: Optional[str] = None,
    raw: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Zapisuje informacje o dokumencie wFirma."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            INSERT INTO wfirma_documents (
                event_order_id, wfirma_invoice_id, wfirma_number, document_type,
                pdf_path, email_to, email_cc, raw
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, event_order_id, wfirma_invoice_id, wfirma_number, document_type, status
            """,
            (
                str(event_order_id),
                str(wfirma_invoice_id),
                str(wfirma_number),
                str(document_type),
                pdf_path,
                email_to,
                email_cc,
                psycopg2.extras.Json(raw or {}),  # type: ignore[attr-defined]
            ),
        )
        row = cur.fetchone()
        return dict(row) if row else {"event_order_id": event_order_id}
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def get_wfirma_documents(event_order_id: str) -> List[Dict[str, Any]]:
    """Pobiera dokumenty wFirma dla zamówienia."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT id, event_order_id, wfirma_invoice_id, wfirma_number, document_type,
                   status, pdf_path, email_to, email_cc, raw, created_at, updated_at
            FROM wfirma_documents
            WHERE event_order_id = %s
            ORDER BY created_at DESC
            """,
            (str(event_order_id),),
        )
        return [dict(r) for r in (cur.fetchall() or [])]
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


# ---------------------------------------------------------------------------
# MAIL LOG
# ---------------------------------------------------------------------------


def save_mail_log(
    event_order_id: Optional[str],
    direction: str,
    template_key: str,
    to_email: str,
    subject: str,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Zapisuje log wysyłki maila."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            INSERT INTO mail_log (event_order_id, direction, template_key, to_email, subject, data)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, event_order_id, direction, template_key, to_email, subject, status
            """,
            (
                event_order_id,
                str(direction),
                str(template_key),
                str(to_email),
                str(subject),
                psycopg2.extras.Json(data or {}),  # type: ignore[attr-defined]
            ),
        )
        row = cur.fetchone()
        return dict(row) if row else {}
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def list_pending_mail_tasks(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Pobiera listę oczekujących maili do wysłania (status='queued').
    Make.com może pollować ten endpoint żeby pobierać nowe taski.
    """
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT id, event_order_id, direction, template_key, to_email, subject, status, data, created_at
            FROM mail_log
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (int(limit),),
        )
        return [dict(r) for r in (cur.fetchall() or [])]
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


# ---------------------------------------------------------------------------
# TOKEN MONITOR STATE + ADVISORY LOCK
# ---------------------------------------------------------------------------


def try_advisory_lock(lock_id: int) -> bool:
    """Próbuje przejąć globalny lock w Postgres (dla wielu workerów)."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute("SELECT pg_try_advisory_lock(%s)", (int(lock_id),))
        row = cur.fetchone()
        return bool(row and row[0])
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def advisory_lock(lock_id: int) -> None:
    """
    Blokujący lock w Postgres (dla wielu workerów).
    Uwaga: to jest mechanizm kontroli współbieżności, nie "sleep" – blokuje do czasu przejęcia locka.
    """
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute("SELECT pg_advisory_lock(%s)", (int(lock_id),))
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def advisory_unlock(lock_id: int) -> None:
    """Zwalnia globalny lock w Postgres."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute("SELECT pg_advisory_unlock(%s)", (int(lock_id),))
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def get_token_monitor_state(company: str) -> Dict[str, Any]:
    """Pobiera stan token monitor dla firmy."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT company, last_check_at, last_email_at, last_email_kind,
                   last_days_remaining, last_status, last_error
            FROM token_monitor_state
            WHERE company = %s
            """,
            (str(company),),
        )
        row = cur.fetchone()
        return dict(row) if row else {"company": company}
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def upsert_token_monitor_state(
    company: str,
    last_check_at: Optional[str] = None,
    last_email_at: Optional[str] = None,
    last_email_kind: Optional[str] = None,
    last_days_remaining: Optional[float] = None,
    last_status: Optional[str] = None,
    last_error: Optional[str] = None,
) -> Dict[str, Any]:
    """Upsert stanu token monitor (idempotentnie)."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO token_monitor_state
              (company, last_check_at, last_email_at, last_email_kind, last_days_remaining, last_status, last_error)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (company) DO UPDATE SET
              last_check_at = COALESCE(EXCLUDED.last_check_at, token_monitor_state.last_check_at),
              last_email_at = COALESCE(EXCLUDED.last_email_at, token_monitor_state.last_email_at),
              last_email_kind = COALESCE(EXCLUDED.last_email_kind, token_monitor_state.last_email_kind),
              last_days_remaining = COALESCE(EXCLUDED.last_days_remaining, token_monitor_state.last_days_remaining),
              last_status = COALESCE(EXCLUDED.last_status, token_monitor_state.last_status),
              last_error = COALESCE(EXCLUDED.last_error, token_monitor_state.last_error)
            """,
            (
                str(company),
                last_check_at,
                last_email_at,
                last_email_kind,
                last_days_remaining,
                last_status,
                last_error,
            ),
        )
        return {"company": company, "ok": True}
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


# ---------------------------------------------------------------------------
# WFIRMA TOKENS (bezpieczne przechowywanie tokenów OAuth2 w Postgres)
# ---------------------------------------------------------------------------


def save_wfirma_token(
    company: str,
    access_token: str,
    access_token_expires_at: int,
    refresh_token: str,
    refresh_token_expires_at: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Zapisuje tokeny wFirma do Postgres (upsert).
    Zwraca dict z info o zapisie i timestampami.
    """
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            INSERT INTO wfirma_tokens
              (company, access_token, access_token_expires_at, refresh_token, refresh_token_expires_at, created_at, updated_at)
            VALUES
              (%s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (company) DO UPDATE SET
              access_token = EXCLUDED.access_token,
              access_token_expires_at = EXCLUDED.access_token_expires_at,
              refresh_token = EXCLUDED.refresh_token,
              refresh_token_expires_at = COALESCE(EXCLUDED.refresh_token_expires_at, wfirma_tokens.refresh_token_expires_at),
              updated_at = NOW()
            RETURNING company, access_token_expires_at, refresh_token_expires_at, created_at, updated_at
            """,
            (
                str(company),
                str(access_token),
                int(access_token_expires_at),
                str(refresh_token),
                int(refresh_token_expires_at) if refresh_token_expires_at else None,
            ),
        )
        row = cur.fetchone()
        result = dict(row) if row else {}
        result["ok"] = True
        print(f"[PG] save_wfirma_token: {company} | access_expires={access_token_expires_at} | refresh_expires={refresh_token_expires_at}")
        return result
    except Exception as e:
        print(f"[PG] save_wfirma_token ERROR: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def save_oauth_state(state: str, company: str) -> Dict[str, Any]:
    """Zapisz stan OAuth (state) dla ręcznego /auth -> /callback."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO oauth_states (state, company, created_at, used_at)
            VALUES (%s, %s, NOW(), NULL)
            ON CONFLICT (state) DO UPDATE SET
              company = EXCLUDED.company,
              created_at = NOW(),
              used_at = NULL
            """,
            (str(state), str(company)),
        )
        return {"ok": True}
    except Exception as e:
        print(f"[PG] save_oauth_state ERROR: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def consume_oauth_state(state: str, max_age_seconds: int = 900) -> Dict[str, Any]:
    """
    Pobierz i oznacz jako użyty state OAuth.
    Zwraca {"ok": True, "company": "..."} lub {"ok": False, "error": "..."}.
    """
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT company
            FROM oauth_states
            WHERE state = %s
              AND used_at IS NULL
              AND created_at >= NOW() - (%s * INTERVAL '1 second')
            """,
            (str(state), int(max_age_seconds)),
        )
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "state_not_found_or_expired"}

        company = row[0]
        cur.execute(
            "UPDATE oauth_states SET used_at = NOW() WHERE state = %s",
            (str(state),),
        )
        return {"ok": True, "company": company}
    except Exception as e:
        print(f"[PG] consume_oauth_state ERROR: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def get_wfirma_token(company: str) -> Optional[Dict[str, Any]]:
    """
    Pobiera tokeny wFirma z Postgres.
    Zwraca dict z access_token, refresh_token, expires i timestampami lub None.
    """
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT company, access_token, access_token_expires_at, 
                   refresh_token, refresh_token_expires_at,
                   created_at, updated_at
            FROM wfirma_tokens
            WHERE company = %s
            """,
            (str(company),),
        )
        row = cur.fetchone()
        if row:
            result = dict(row)
            print(f"[PG] get_wfirma_token: {company} | found, updated_at={result.get('updated_at')}")
            return result
        print(f"[PG] get_wfirma_token: {company} | not found")
        return None
    except Exception as e:
        print(f"[PG] get_wfirma_token ERROR: {e}")
        return None
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def mark_mail_sent(mail_id: int, error: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Oznacza mail jako wysłany (status='sent') lub nieudany (status='failed').
    """
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        new_status = "failed" if error else "sent"
        cur.execute(
            """
            UPDATE mail_log
            SET status = %s, error = %s
            WHERE id = %s
            RETURNING id, event_order_id, direction, template_key, to_email, subject, status, error
            """,
            (new_status, error, int(mail_id)),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def get_mail_task(mail_id: int) -> Optional[Dict[str, Any]]:
    """Pobiera szczegóły mail taska po ID."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT id, event_order_id, direction, template_key, to_email, subject, status, data, error, created_at
            FROM mail_log
            WHERE id = %s
            """,
            (int(mail_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def mail_log_exists(event_order_id: str, template_key: str, direction: Optional[str] = None) -> bool:
    """
    Sprawdza czy istnieje wpis mail_log dla danego zamówienia i template_key.
    Używane do deduplikacji (żeby nie wysyłać kilka razy tego samego maila).
    """
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        if direction:
            cur.execute(
                """
                SELECT 1
                FROM mail_log
                WHERE event_order_id = %s AND template_key = %s AND direction = %s
                LIMIT 1
                """,
                (str(event_order_id), str(template_key), str(direction)),
            )
        else:
            cur.execute(
                """
                SELECT 1
                FROM mail_log
                WHERE event_order_id = %s AND template_key = %s
                LIMIT 1
                """,
                (str(event_order_id), str(template_key)),
            )
        row = cur.fetchone()
        return bool(row)
    except Exception as e:
        print(f"[DB] mail_log_exists error: {e}")
        return False
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------


def parse_kv_lines(text: str) -> Dict[str, Any]:
    """
    Parser do wklejania z arkusza: linie typu:
      key<TAB>value
      key: value
    Zwraca dict. Nie próbuje na siłę typów – ale rozpoznaje JSON/boolean/int/float.
    """
    out: Dict[str, Any] = {}
    if not text:
        return out
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        key = None
        value = None
        if "\t" in line:
            key, value = line.split("\t", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        elif ";" in line:
            key, value = line.split(";", 1)
        else:
            continue

        k = (key or "").strip()
        v = (value or "").strip()
        if not k:
            continue

        # Typy podstawowe
        low = v.lower()
        if low in ("true", "false"):
            out[k] = (low == "true")
            continue

        # Liczby
        try:
            if "." in v:
                out[k] = float(v)
            else:
                out[k] = int(v)
            continue
        except Exception:
            pass

        # JSON (obiekt/array) jeśli wygląda sensownie
        if (v.startswith("{") and v.endswith("}")) or (v.startswith("[") and v.endswith("]")):
            try:
                out[k] = json.loads(v)
                continue
            except Exception:
                pass

        out[k] = v
    return out


# ---------------------------------------------------------------------------
# PARTICIPANTS (uczestnicy wydarzeń - osoby przypisane do biletów)
# ---------------------------------------------------------------------------

def save_participant(
    event_order_id: str,
    ticket_id: str,
    ticket_class_id: str = "",
    email: str = "",
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    status: str = "pending",  # pending/registered/emailed/failed/cancelled
    data: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """
    Zapisuje uczestnika (slot biletu) do bazy.
    Zwraca ID rekordu lub None przy błędzie.
    
    Status:
    - pending: bilet zarezerwowany, dane uczestnika nie wypełnione
    - registered: dane uczestnika uzupełnione
    - emailed: wysłano email do uczestnika
    - cancelled: anulowany
    """
    pool, conn = _with_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO participants (
                event_order_id, ticket_id, ticket_class_id,
                email, first_name, last_name, phone, status, data
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_order_id, email, ticket_id) DO UPDATE SET
                ticket_class_id = EXCLUDED.ticket_class_id,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                phone = EXCLUDED.phone,
                status = EXCLUDED.status,
                data = participants.data || EXCLUDED.data,
                updated_at = NOW()
            RETURNING id
        """, (
            event_order_id, ticket_id, ticket_class_id,
            email or "", first_name or "", last_name or "", phone or "",
            status, json.dumps(data or {})
        ))
        result = cur.fetchone()
        conn.commit()
        return result[0] if result else None
    except Exception as e:
        conn.rollback()
        print(f"[DB] save_participant error: {e}")
        return None
    finally:
        _put_conn(pool, conn)


def get_participants_for_order(event_order_id: str) -> List[Dict[str, Any]]:
    """Pobiera wszystkich uczestników dla zamówienia."""
    pool, conn = _with_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, event_order_id, ticket_id, ticket_class_id,
                   email, first_name, last_name, phone, status, data,
                   created_at, updated_at
            FROM participants
            WHERE event_order_id = %s
            ORDER BY id
        """, (event_order_id,))
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        print(f"[DB] get_participants_for_order error: {e}")
        return []
    finally:
        _put_conn(pool, conn)


def get_participant_by_ticket(event_order_id: str, ticket_id: str) -> Optional[Dict[str, Any]]:
    """Pobiera uczestnika przypisanego do konkretnego biletu."""
    pool, conn = _with_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, event_order_id, ticket_id, ticket_class_id,
                   email, first_name, last_name, phone, status, data,
                   created_at, updated_at
            FROM participants
            WHERE event_order_id = %s AND ticket_id = %s
        """, (event_order_id, ticket_id))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    except Exception as e:
        print(f"[DB] get_participant_by_ticket error: {e}")
        return None
    finally:
        _put_conn(pool, conn)


def update_participant_status(participant_id: int, status: str) -> bool:
    """Aktualizuje status uczestnika."""
    pool, conn = _with_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE participants SET status = %s, updated_at = NOW()
            WHERE id = %s
        """, (status, participant_id))
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        print(f"[DB] update_participant_status error: {e}")
        return False
    finally:
        _put_conn(pool, conn)


def update_participant_details(
    event_order_id: str,
    ticket_id: str,
    email: str,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    status: str = "registered",
    extra_data: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Aktualizuje dane uczestnika przypisanego do biletu.
    Używane gdy uczestnik wypełnia swoje dane przez link.
    """
    pool, conn = _with_conn()
    try:
        cur = conn.cursor()
        
        # Jeśli jest extra_data, merguj z istniejącymi
        data_update = ""
        params = [email, first_name, last_name, phone, status, event_order_id, ticket_id]
        if extra_data:
            data_update = ", data = data || %s::jsonb"
            params = [email, first_name, last_name, phone, status, json.dumps(extra_data), event_order_id, ticket_id]
        
        cur.execute(f"""
            UPDATE participants SET
                email = %s,
                first_name = %s,
                last_name = %s,
                phone = %s,
                status = %s,
                updated_at = NOW()
                {data_update}
            WHERE event_order_id = %s AND ticket_id = %s
        """, params)
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        print(f"[DB] update_participant_details error: {e}")
        return False
    finally:
        _put_conn(pool, conn)


def get_pending_participants(event_order_id: str) -> List[Dict[str, Any]]:
    """Pobiera uczestników ze statusem 'pending' (do wypełnienia)."""
    pool, conn = _with_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, event_order_id, ticket_id, ticket_class_id,
                   email, first_name, last_name, phone, status, data,
                   created_at, updated_at
            FROM participants
            WHERE event_order_id = %s AND status = 'pending'
            ORDER BY id
        """, (event_order_id,))
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        print(f"[DB] get_pending_participants error: {e}")
        return []
    finally:
        _put_conn(pool, conn)


def count_participants_by_status(event_order_id: str) -> Dict[str, int]:
    """Zlicza uczestników wg statusu dla zamówienia."""
    pool, conn = _with_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT status, COUNT(*) as cnt
            FROM participants
            WHERE event_order_id = %s
            GROUP BY status
        """, (event_order_id,))
        rows = cur.fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception as e:
        print(f"[DB] count_participants_by_status error: {e}")
        return {}
    finally:
        _put_conn(pool, conn)


# ---------------------------------------------------------------------------
# ADMIN USERS CRUD (logowanie do panelu /admin)
# ---------------------------------------------------------------------------


def admin_user_count() -> int:
    """Zwraca liczbę kont admin (do sprawdzenia czy można bootstrap)."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM admin_users")
        row = cur.fetchone()
        return row[0] if row else 0
    except Exception as e:
        print(f"[DB] admin_user_count error: {e}")
        return 0
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def get_admin_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Pobiera admina po email."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT id, email, first_name, last_name, password_hash, role, allowed_pages,
                   must_change_password, is_active, failed_login_count, locked_until,
                   created_at, updated_at, last_login_at
            FROM admin_users
            WHERE LOWER(email) = LOWER(%s)
            """,
            (str(email).strip(),),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def get_admin_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Pobiera admina po id."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT id, email, first_name, last_name, password_hash, role, allowed_pages,
                   must_change_password, is_active, failed_login_count, locked_until,
                   created_at, updated_at, last_login_at
            FROM admin_users
            WHERE id = %s
            """,
            (int(user_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def list_admin_users() -> List[Dict[str, Any]]:
    """Lista wszystkich adminów."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT id, email, first_name, last_name, role, allowed_pages, must_change_password,
                   is_active, failed_login_count, locked_until, created_at, updated_at, last_login_at
            FROM admin_users
            ORDER BY created_at ASC
            """
        )
        return [dict(r) for r in (cur.fetchall() or [])]
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def create_admin_user(
    email: str,
    password_hash: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    role: str = "admin",
    allowed_pages: Optional[List[str]] = None,
    must_change_password: bool = False,
) -> Optional[Dict[str, Any]]:
    """Tworzy nowego admina. Zwraca utworzony rekord (bez password_hash)."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            INSERT INTO admin_users (email, first_name, last_name, password_hash, role, allowed_pages, must_change_password)
            VALUES (LOWER(%s), %s, %s, %s, %s, %s, %s)
            RETURNING id, email, first_name, last_name, role, allowed_pages, must_change_password, is_active, created_at
            """,
            (
                str(email).strip(),
                (str(first_name).strip() if first_name else None),
                (str(last_name).strip() if last_name else None),
                str(password_hash),
                str(role or "admin"),
                psycopg2.extras.Json(allowed_pages or []),  # type: ignore[attr-defined]
                bool(must_change_password),
            ),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB] create_admin_user error: {e}")
        return None
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def update_admin_user_password(user_id: int, password_hash: str, must_change_password: Optional[bool] = None) -> bool:
    """Aktualizuje hasło admina."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE admin_users
            SET password_hash = %s,
                must_change_password = COALESCE(%s, must_change_password),
                updated_at = NOW()
            WHERE id = %s
            """,
            (str(password_hash), must_change_password, int(user_id)),
        )
        return cur.rowcount > 0
    except Exception as e:
        print(f"[DB] update_admin_user_password error: {e}")
        return False
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def update_admin_user_active(user_id: int, is_active: bool) -> bool:
    """Aktywuje lub dezaktywuje admina."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE admin_users
            SET is_active = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (bool(is_active), int(user_id)),
        )
        return cur.rowcount > 0
    except Exception as e:
        print(f"[DB] update_admin_user_active error: {e}")
        return False
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def update_admin_user_access(
    user_id: int,
    first_name: Optional[str],
    last_name: Optional[str],
    role: str,
    allowed_pages: Optional[List[str]],
) -> bool:
    """Aktualizuje imię/nazwisko, rolę i uprawnienia użytkownika."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE admin_users
            SET first_name = %s,
                last_name = %s,
                role = %s,
                allowed_pages = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                (str(first_name).strip() if first_name else None),
                (str(last_name).strip() if last_name else None),
                str(role or "admin"),
                psycopg2.extras.Json(allowed_pages or []),  # type: ignore[attr-defined]
                int(user_id),
            ),
        )
        return cur.rowcount > 0
    except Exception as e:
        print(f"[DB] update_admin_user_access error: {e}")
        return False
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def update_admin_user_last_login(user_id: int) -> bool:
    """Aktualizuje last_login_at i resetuje failed_login_count."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE admin_users
            SET last_login_at = NOW(), failed_login_count = 0, locked_until = NULL, updated_at = NOW()
            WHERE id = %s
            """,
            (int(user_id),),
        )
        return cur.rowcount > 0
    except Exception as e:
        print(f"[DB] update_admin_user_last_login error: {e}")
        return False
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def increment_admin_user_failed_login(user_id: int, lock_minutes: int = 15) -> int:
    """
    Zwiększa failed_login_count. Po 5 próbach ustawia locked_until.
    Zwraca nową wartość failed_login_count.
    """
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        # Inkrementuj licznik
        cur.execute(
            """
            UPDATE admin_users
            SET failed_login_count = failed_login_count + 1, updated_at = NOW()
            WHERE id = %s
            RETURNING failed_login_count
            """,
            (int(user_id),),
        )
        row = cur.fetchone()
        count = row[0] if row else 0

        # Po 5 nieudanych próbach zablokuj konto
        if count >= 5:
            cur.execute(
                """
                UPDATE admin_users
                SET locked_until = NOW() + INTERVAL '%s minutes'
                WHERE id = %s
                """,
                (int(lock_minutes), int(user_id)),
            )
        return count
    except Exception as e:
        print(f"[DB] increment_admin_user_failed_login error: {e}")
        return 0
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def delete_admin_user(user_id: int) -> bool:
    """Usuwa admina (hard delete)."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM admin_users WHERE id = %s", (int(user_id),))
        return cur.rowcount > 0
    except Exception as e:
        print(f"[DB] delete_admin_user error: {e}")
        return False
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


# ---------------------------------------------------------------------------
# ADMIN AUDIT LOG
# ---------------------------------------------------------------------------


def insert_admin_audit_log(
    action: str,
    admin_user_id: Optional[int] = None,
    target_email: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Dodaje wpis do logu audytu. Zwraca id wpisu."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO admin_audit_log (admin_user_id, action, target_email, ip, user_agent, data)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                admin_user_id,
                str(action),
                target_email,
                ip,
                user_agent,
                psycopg2.extras.Json(data or {}),  # type: ignore[attr-defined]
            ),
        )
        row = cur.fetchone()
        return row[0] if row else None
    except Exception as e:
        print(f"[DB] insert_admin_audit_log error: {e}")
        return None
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)


def list_admin_audit_log(limit: int = 100) -> List[Dict[str, Any]]:
    """Lista ostatnich wpisów audytu."""
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT al.id, al.admin_user_id, au.email as admin_email, al.action,
                   al.target_email, al.ip, al.user_agent, al.data, al.created_at
            FROM admin_audit_log al
            LEFT JOIN admin_users au ON al.admin_user_id = au.id
            ORDER BY al.created_at DESC, al.id DESC
            LIMIT %s
            """,
            (int(limit),),
        )
        return [dict(r) for r in (cur.fetchall() or [])]
    finally:
        if pool is not None and conn is not None:
            _put_conn(pool, conn)

