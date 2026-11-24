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
    require_database_url,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = ROOT / "db" / "schema.sql"


def apply_schema(admin_url: str | None = None) -> None:
    """Create extension, tables, role, RLS policies and seed clinics."""
    url = admin_url or ADMIN_DATABASE_URL
    if not url:
        raise RuntimeError("ADMIN_DATABASE_URL is not set (see .env.example)")
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql)


@contextlib.contextmanager
def clinic_session(clinic_id: int, url: str | None = None) -> Iterator[psycopg.Cursor]:
    """Yield a cursor in a transaction scoped to one clinic via RLS.

    Commits on success, rolls back on error.
    """
    dsn = url or require_database_url()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # transaction-local; cleared at commit/rollback.
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
