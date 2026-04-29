"""Seed script — idempotent, safe to run on every container boot.

Run as: ``python -m admin.seed``
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime

from sqlmodel import Session, select

from .config import get_settings
from .database import get_engine, init_db
from .models import Role, User
from .security import hash_password


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def ensure_admin() -> None:
    settings = get_settings()
    engine = get_engine()
    with Session(engine) as session:
        existing = session.exec(
            select(User).where(User.email == settings.admin_email)
        ).first()
        if existing is not None:
            print(f"[seed] Admin user already present: {settings.admin_email}")
            return
        user = User(
            email=settings.admin_email,
            password_hash=hash_password(settings.admin_password),
            role=Role.admin,
            created_at=datetime.utcnow(),
            active=True,
        )
        session.add(user)
        session.commit()
        print(f"[seed] Created admin user: {settings.admin_email}")


def main() -> int:
    _configure_logging()
    logger = logging.getLogger("admin.seed")
    settings = get_settings()
    logger.info("Seeding DB at %s", settings.database_url)
    init_db()
    print("[seed] Tables ensured")
    ensure_admin()
    print("[seed] Done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
