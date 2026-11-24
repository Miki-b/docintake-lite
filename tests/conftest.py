from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402


def _db_available() -> bool:
    if not config.DATABASE_URL or not config.ADMIN_DATABASE_URL:
        return False
    try:
        import psycopg

        with psycopg.connect(config.ADMIN_DATABASE_URL, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()
requires_db = pytest.mark.skipif(not DB_AVAILABLE, reason="no reachable DATABASE_URL")


@pytest.fixture()
def clean_db():
    """Apply schema and truncate data tables (as admin, bypassing RLS)."""
    import psycopg

    from app import db

    db.apply_schema()
    with psycopg.connect(config.ADMIN_DATABASE_URL, autocommit=True) as conn:
        conn.execute("TRUNCATE observations, documents, patients RESTART IDENTITY CASCADE")
    yield
