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


