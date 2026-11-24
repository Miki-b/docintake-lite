"""Load configuration from .env. Never logs secret values."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
# Admin/owner URL for schema setup (extensions, roles, DDL). On Neon the owner
# role has BYPASSRLS, so it is used only for setup, never for app queries. Falls
# back to DATABASE_URL (which on Neon is the owner role).
ADMIN_DATABASE_URL = os.getenv("ADMIN_DATABASE_URL") or DATABASE_URL
PHI_ENCRYPTION_KEY = os.getenv("PHI_ENCRYPTION_KEY", "")
MRN_HMAC_KEY = os.getenv("MRN_HMAC_KEY", "")

# The app connects as this role, which must NOT have BYPASSRLS (RLS enforcement
# depends on it). Created by db/schema.sql.
APP_DB_USER = os.getenv("APP_DB_USER", "app_user")
APP_DB_PASSWORD = os.getenv("APP_DB_PASSWORD", "Dev_AppUser_7f3a!")


def require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set (see .env.example)")
    return DATABASE_URL


def app_database_url() -> str:
    """DSN the app uses for queries: the same host/db as DATABASE_URL but as the
    NOBYPASSRLS app role, so Row-Level Security is actually enforced. If
    APP_DATABASE_URL is set explicitly, use it verbatim."""
    explicit = os.getenv("APP_DATABASE_URL")
    if explicit:
        return explicit
    base = require_database_url()
    p = urlsplit(base)
    hostport = p.netloc.split("@")[-1]
    netloc = f"{APP_DB_USER}:{quote(APP_DB_PASSWORD, safe='')}@{hostport}"
    return urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))
