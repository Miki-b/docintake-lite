"""Apply db/schema.sql (extensions, tables, app_user role, RLS, seed clinics).

Run:  python -m scripts.init_db
Uses ADMIN_DATABASE_URL from .env.
"""
from __future__ import annotations

from app.db import apply_schema


def main() -> None:
    apply_schema()
    print("schema applied (extensions, tables, RLS, app_user, 2 clinics)")


if __name__ == "__main__":
    main()
