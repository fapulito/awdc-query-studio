"""
Billing module: freemium subscription management backed by Postgres (YugabyteDB).

Exposes:
    billing_enabled  – bool; False when YUGABYTE_RW_HOST is unset
    PLAN_LIMITS      – dict mapping tier → monthly question cap
    get_or_create_user(email)  → row dict
    record_question(email)     → None
    check_limit(email)         → (allowed: bool, questions_used: int, limit: int)
    set_tier(email, tier)      → None
"""

import os
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

PLAN_LIMITS = {"free": 10, "pro": 250}

_YUGABYTE_HOST = os.getenv("YUGABYTE_RW_HOST", "")
billing_enabled: bool = bool(_YUGABYTE_HOST)

if not billing_enabled:
    logger.warning(
        "YUGABYTE_RW_HOST is not set — billing is disabled. "
        "All users will be allowed unlimited questions."
    )

# ---------------------------------------------------------------------------
# Lazy DB connection
# ---------------------------------------------------------------------------

_conn = None


def _get_conn():
    """Return a live psycopg connection, reconnecting if needed."""
    global _conn
    try:
        import psycopg  # noqa: F401 (psycopg3)
    except ImportError:
        logger.error("psycopg is not installed; billing is non-functional.")
        raise

    dsn = (
        f"host={os.getenv('YUGABYTE_RW_HOST')} "
        f"port={os.getenv('YUGABYTE_RW_PORT', '5433')} "
        f"dbname={os.getenv('YUGABYTE_RW_DBNAME', 'yugabyte')} "
        f"user={os.getenv('YUGABYTE_RW_USER', 'yugabyte')} "
        f"password={os.getenv('YUGABYTE_RW_PASSWORD', '')} "
        f"sslmode={os.getenv('YUGABYTE_RW_SSLMODE', 'require')}"
    )

    if _conn is None or _conn.closed:
        _conn = psycopg.connect(dsn, autocommit=False)
        _ensure_schema(_conn)
    else:
        try:
            _conn.execute("SELECT 1")
        except Exception:
            _conn = psycopg.connect(dsn, autocommit=False)
            _ensure_schema(_conn)
    return _conn


def _ensure_schema(conn) -> None:
    """Create awdc_app schema and subscriptions table if they don't exist."""
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS awdc_app")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS awdc_app.subscriptions (
                email          TEXT PRIMARY KEY,
                tier           TEXT NOT NULL DEFAULT 'free',
                period_start   TIMESTAMPTZ,
                questions_used INT NOT NULL DEFAULT 0
            )
            """
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Rolling-period reset helper
# ---------------------------------------------------------------------------

def _maybe_reset(row: dict, cur) -> dict:
    """If period_start is >30 days ago, reset counter in DB and return updated row."""
    now = datetime.now(tz=timezone.utc)
    period_start = row.get("period_start")
    if period_start is None or (now - period_start) > timedelta(days=30):
        cur.execute(
            "UPDATE awdc_app.subscriptions "
            "SET questions_used = 0, period_start = NOW() "
            "WHERE email = %s",
            (row["email"],),
        )
        row = dict(row)
        row["questions_used"] = 0
        row["period_start"] = now
    return row


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_or_create_user(email: str) -> dict:
    """Return the subscription row for *email*, creating it if absent."""
    if not billing_enabled:
        return {"email": email, "tier": "free", "period_start": None, "questions_used": 0}
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO awdc_app.subscriptions (email, tier, period_start, questions_used)
            VALUES (%s, 'free', NOW(), 0)
            ON CONFLICT (email) DO NOTHING
            """,
            (email,),
        )
        cur.execute(
            "SELECT email, tier, period_start, questions_used "
            "FROM awdc_app.subscriptions WHERE email = %s",
            (email,),
        )
        row_raw = cur.fetchone()
        conn.commit()
    cols = ["email", "tier", "period_start", "questions_used"]
    return dict(zip(cols, row_raw))


def check_limit(email: str) -> tuple:
    """
    Returns (allowed: bool, questions_used: int, limit: int).
    Performs rolling 30-day reset if needed.
    """
    if not billing_enabled:
        return (True, 0, PLAN_LIMITS["free"])
    conn = _get_conn()
    with conn.cursor() as cur:
        row = get_or_create_user(email)
        row = _maybe_reset(row, cur)
        conn.commit()
    tier = row.get("tier", "free")
    limit = PLAN_LIMITS.get(tier, PLAN_LIMITS["free"])
    used = row.get("questions_used", 0)
    return (used < limit, used, limit)


def record_question(email: str) -> None:
    """Increment questions_used, applying reset if the period has rolled over."""
    if not billing_enabled:
        return
    conn = _get_conn()
    with conn.cursor() as cur:
        row = get_or_create_user(email)
        row = _maybe_reset(row, cur)
        cur.execute(
            "UPDATE awdc_app.subscriptions SET questions_used = questions_used + 1 "
            "WHERE email = %s",
            (email,),
        )
        conn.commit()


def set_tier(email: str, tier: str) -> None:
    """Upsert *tier* for *email*. Resets usage counter when upgrading."""
    if not billing_enabled:
        return
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO awdc_app.subscriptions (email, tier, period_start, questions_used)
            VALUES (%s, %s, NOW(), 0)
            ON CONFLICT (email) DO UPDATE
                SET tier           = EXCLUDED.tier,
                    questions_used = 0,
                    period_start   = NOW()
            """,
            (email, tier),
        )
        conn.commit()
