"""Load configuration from .env. Never logs secret values."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_DATABASE_URL = os.getenv("ADMIN_DATABASE_URL")
PHI_ENCRYPTION_KEY = os.getenv("PHI_ENCRYPTION_KEY", "")
MRN_HMAC_KEY = os.getenv("MRN_HMAC_KEY", "")


def require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set (see .env.example)")
    return DATABASE_URL
