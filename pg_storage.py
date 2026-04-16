import json
import os
import time
from contextlib import contextmanager
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

CREATE TABLE IF NOT EXISTS token_monitor_state (
  company TEXT PRIMARY KEY,
  last_check_at TIMESTAMPTZ,
  last_email_at TIMESTAMPTZ,
  last_email_kind TEXT, -- daily / urgent / expired
  last_days_remaining NUMERIC(10,3),
  last_status TEXT, -- ok / warn / expired / missing
  last_error TEXT
);

CREATE TABLE IF NOT EXISTS wfirma_tokens (
  company TEXT PRIMARY KEY,
  access_token TEXT NOT NULL,
  access_token_expires_at BIGINT NOT NULL,        -- Unix timestamp
  refresh_token TEXT NOT NULL,
  refresh_token_expires_at BIGINT,                 -- Unix timestamp (30 dni od utworzenia)
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),   -- Kiedy pierwszy raz zapisano
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()    -- Kiedy ostatnio zaktualizowano
);

CREATE TABLE IF NOT EXISTS oauth_states (
  state TEXT PRIMARY KEY,
  company TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  used_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_oauth_states_company ON oauth_states(company);
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
    global _schema_checked_at
    import time
    now = time.time()
    if not force and _schema_checked_at and (now - _schema_checked_at) < 30:
        return {"ok": True, "skipped": True, "reason": "recent_check"}
    _schema_checked_at = now

    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute(SCHEMA_SQL)
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



# --- DEPRECATED: te funkcje mają bug - lock/unlock na różnych połączeniach z puli ---
# Użyj advisory_lock_ctx() / try_advisory_lock_ctx() zamiast nich.

def try_advisory_lock(lock_id: int) -> bool:
    """DEPRECATED: Użyj try_advisory_lock_ctx(). Lock może nie działać poprawnie z connection pool."""
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
    """DEPRECATED: Użyj advisory_lock_ctx(). Lock może nie działać poprawnie z connection pool."""
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
    """DEPRECATED: Użyj advisory_lock_ctx(). Unlock może trafić na inne połączenie niż lock."""
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


# --- NOWE: Context managery utrzymujące jedno połączenie dla lock+unlock ---

@contextmanager
def advisory_lock_ctx(lock_id: int):
    """
    Blokujący advisory lock w Postgres jako context manager.
    Lock i unlock operują na TYM SAMYM połączeniu (wymagane przez PostgreSQL).
    Użycie: with advisory_lock_ctx(lock_id): ...
    """
    ensure_schema()
    pool = None
    conn = None
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute("SELECT pg_advisory_lock(%s)", (int(lock_id),))
        yield conn
    finally:
        if pool is not None and conn is not None:
            try:
                cur2 = conn.cursor()
                cur2.execute("SELECT pg_advisory_unlock(%s)", (int(lock_id),))
            except Exception:
                pass
            _put_conn(pool, conn)


@contextmanager
def try_advisory_lock_ctx(lock_id: int):
    """
    Non-blocking advisory lock jako context manager.
    Yield: (conn, acquired: bool). Lock i unlock na tym samym połączeniu.
    Użycie: with try_advisory_lock_ctx(lock_id) as (conn, acquired): ...
    """
    ensure_schema()
    pool = None
    conn = None
    acquired = False
    try:
        pool, conn = _with_conn()
        cur = conn.cursor()
        cur.execute("SELECT pg_try_advisory_lock(%s)", (int(lock_id),))
        row = cur.fetchone()
        acquired = bool(row and row[0])
        yield conn, acquired
    finally:
        if pool is not None and conn is not None:
            if acquired:
                try:
                    cur2 = conn.cursor()
                    cur2.execute("SELECT pg_advisory_unlock(%s)", (int(lock_id),))
                except Exception:
                    pass
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


