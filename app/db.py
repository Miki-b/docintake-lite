"""Postgres access with per-request clinic isolation (RLS) and PHI encryption.

Every data operation runs inside a transaction that sets the transaction-local
GUC app.clinic_id (via set_config(..., is_local=true)); the RLS policies key off
it. Patient name + MRN are encrypted in SQL with pgcrypto; plaintext PHI is
never logged.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

import psycopg

from app.config import (
    ADMIN_DATABASE_URL,
    MRN_HMAC_KEY,
    PHI_ENCRYPTION_KEY,
    app_database_url,
    require_database_url,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = ROOT / "db" / "schema.sql"

# Pass timeouts as startup options so they hold even on a PgBouncer pooler
# (where a per-statement SET would not persist across autocommit statements).
_TIMEOUT_OPTS = "-c statement_timeout=30000 -c lock_timeout=10000"


def _direct_url(url: str) -> str:
    """Neon's pooled (PgBouncer) endpoint hangs on DDL; the direct endpoint is
    the same host without the '-pooler' suffix. No-op for non-Neon URLs."""
    return url.replace("-pooler.", ".", 1)


def admin_connect() -> psycopg.Connection:
    """Autocommit admin connection on the direct endpoint, with timeouts.
    Used for schema setup and test teardown (TRUNCATE)."""
    url = _direct_url(ADMIN_DATABASE_URL or require_database_url())
    return psycopg.connect(url, autocommit=True, options=_TIMEOUT_OPTS)


def _split_sql(sql: str) -> list[str]:
    """Split a SQL script into statements, respecting $$ dollar-quoting and
    '...' string literals. Simple-minded but sufficient for schema.sql; keeps
    DO $$ ... $$ blocks intact so we can run statements one at a time (needed
    for poolers that choke on a single multi-statement send)."""
    stmts: list[str] = []
    buf: list[str] = []
    in_dollar = False
    in_squote = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        two = sql[i:i + 2]
        if not in_dollar and not in_squote and two == "--":
            # Skip a line comment (its apostrophes must not toggle quoting).
            j = sql.find("\n", i)
            i = n if j == -1 else j
            continue
        if not in_squote and two == "$$":
            in_dollar = not in_dollar
            buf.append(two)
            i += 2
            continue
        if not in_dollar and ch == "'":
            in_squote = not in_squote
            buf.append(ch)
            i += 1
            continue
        if ch == ";" and not in_dollar and not in_squote:
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def apply_schema(admin_url: str | None = None) -> None:
    """Create extension, tables, role, RLS policies and seed clinics.

    Runs each statement individually with autocommit and a statement timeout,
    which is more robust on pooled/managed Postgres (e.g. Neon's PgBouncer
    endpoint) than one large multi-statement send.
    """
    url = _direct_url(admin_url or ADMIN_DATABASE_URL or "")
    if not url:
        raise RuntimeError("ADMIN_DATABASE_URL is not set (see .env.example)")
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    with psycopg.connect(url, autocommit=True, options=_TIMEOUT_OPTS) as conn:
        for stmt in _split_sql(sql):
            conn.execute(stmt)


@contextlib.contextmanager
def clinic_session(clinic_id: int, url: str | None = None) -> Iterator[psycopg.Cursor]:
    """Yield a cursor in a transaction scoped to one clinic via RLS.

    Commits on success, rolls back on error.
    """
    dsn = url or app_database_url()
    # No startup 'options' here: the Neon pooler rejects statement_timeout in the
    # startup packet. Set timeouts transaction-locally instead (pooler-safe).
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # transaction-local; cleared at commit/rollback.
            cur.execute("SET LOCAL statement_timeout = '30000'")
            cur.execute("SET LOCAL lock_timeout = '10000'")
            cur.execute("SELECT set_config('app.clinic_id', %s, true)", [str(clinic_id)])
            try:
                yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise


def upsert_patient(cur: psycopg.Cursor, clinic_id: int, name: str, mrn: str) -> int:
    cur.execute(
        """
        INSERT INTO patients (clinic_id, name_enc, mrn_enc, mrn_hash)
        VALUES (%(c)s,
                pgp_sym_encrypt(%(name)s, %(key)s),
                pgp_sym_encrypt(%(mrn)s, %(key)s),
                hmac(%(mrn)s, %(hkey)s, 'sha256'))
        ON CONFLICT (clinic_id, mrn_hash)
        DO UPDATE SET name_enc = EXCLUDED.name_enc
        RETURNING id
        """,
        {"c": clinic_id, "name": name, "mrn": mrn,
         "key": PHI_ENCRYPTION_KEY, "hkey": MRN_HMAC_KEY},
    )
    return cur.fetchone()[0]


def insert_document(cur: psycopg.Cursor, clinic_id: int, patient_id: int | None,
                    filename: str | None, ocr_engine: str | None) -> int:
    cur.execute(
        """
        INSERT INTO documents (clinic_id, patient_id, filename, ocr_engine)
        VALUES (%s, %s, %s, %s) RETURNING id
        """,
        [clinic_id, patient_id, filename, ocr_engine],
    )
    return cur.fetchone()[0]


def insert_observation(cur: psycopg.Cursor, clinic_id: int, patient_id: int,
                       document_id: int | None, fhir: dict, verified: bool) -> int:
    from psycopg.types.json import Jsonb

    cur.execute(
        """
        INSERT INTO observations (clinic_id, patient_id, document_id, fhir, verified)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
        """,
        [clinic_id, patient_id, document_id, Jsonb(fhir), verified],
    )
    return cur.fetchone()[0]


def fetch_observations(cur: psycopg.Cursor, patient_id: int) -> list[dict]:
    cur.execute(
        "SELECT fhir, verified FROM observations WHERE patient_id = %s ORDER BY id",
        [patient_id],
    )
    return [{"fhir": row[0], "verified": row[1]} for row in cur.fetchall()]


def decrypt_patient(cur: psycopg.Cursor, patient_id: int) -> dict | None:
    """Decrypt a patient's name + MRN (used for round-trip checks)."""
    cur.execute(
        """
        SELECT pgp_sym_decrypt(name_enc, %(key)s),
               pgp_sym_decrypt(mrn_enc, %(key)s)
        FROM patients WHERE id = %(id)s
        """,
        {"key": PHI_ENCRYPTION_KEY, "id": patient_id},
    )
    row = cur.fetchone()
    if not row:
        return None
    return {"name": row[0], "mrn": row[1]}
