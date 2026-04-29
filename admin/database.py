"""Database engine and session plumbing."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterator

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

logger = logging.getLogger(__name__)

_engine: Engine | None = None


def _ensure_sqlite_dir(database_url: str) -> None:
    """Ensure the SQLite parent directory exists when using a sqlite URL."""
    if not database_url.startswith("sqlite"):
        return
    # sqlite:////data/voices.db -> path part is /data/voices.db
    # strip scheme
    path_part = database_url.split("sqlite:///", 1)[-1]
    # absolute (four slashes) or relative (three slashes) — both work after strip
    if not path_part:
        return
    db_path = Path("/" + path_part) if database_url.startswith("sqlite:////") else Path(path_part)
    parent = db_path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("Could not create sqlite dir %s: %s", parent, exc)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _ensure_sqlite_dir(settings.database_url)
        connect_args = {}
        if settings.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(
            settings.database_url,
            echo=False,
            connect_args=connect_args,
        )
    return _engine


def init_db() -> None:
    """Create tables if they don't exist."""
    from . import models  # noqa: F401  (import to register models)

    engine = get_engine()
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
