from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402


def _db_available() -> bool:
    if not config.DATABASE_URL:
        return False
    import time

    import psycopg

    from app.db import _direct_url

    # Direct endpoint; retry through Neon's cold-start wake-up window.
    url = _direct_url(config.ADMIN_DATABASE_URL or config.DATABASE_URL)
    deadline = time.time() + 70
    while time.time() < deadline:
        try:
            with psycopg.connect(url, connect_timeout=20) as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            time.sleep(3)
    return False


DB_AVAILABLE = _db_available()
requires_db = pytest.mark.skipif(not DB_AVAILABLE, reason="no reachable DATABASE_URL")


@pytest.fixture(scope="session")
def _schema_applied():
    """Apply the schema once per test session."""
    from app import db

    db.apply_schema()
    yield


@pytest.fixture()
def clean_db(_schema_applied):
    """Truncate data tables before each DB test (admin/direct, bypasses RLS)."""
    from app import db

    with db.admin_connect() as conn:
        conn.execute("TRUNCATE observations, documents, patients RESTART IDENTITY CASCADE")
    yield
