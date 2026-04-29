"""Admin dashboard and user management routes."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, func, select

from ..config import get_settings
from ..deps import CurrentUser, db_session, require_admin
from ..models import Role, User
from ..rate_limit import get_redis
from ..security import hash_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# Track boot time for uptime display
_BOOT_TIME = time.time()


def _templates() -> Jinja2Templates:
    from ..main import templates as _t  # type: ignore

    return _t


def _read_stats_json() -> dict:
    settings = get_settings()
    path = Path(settings.output_dir) / "stats.json"
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.warning("Could not read stats.json: %s", exc)
        return {}


def _cache_stats() -> dict:
    try:
        client = get_redis(db=1)
        size = client.dbsize()
        info = client.info(section="memory")
        return {
            "size": size,
            "used_memory_human": info.get("used_memory_human", "?"),
            "ok": True,
        }
    except Exception as exc:
        logger.warning("Redis cache stats failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def _uptime() -> str:
    seconds = int(time.time() - _BOOT_TIME)
    hours, rem = divmod(seconds, 3600)
    mins, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {mins}m {secs}s"
    if mins:
        return f"{mins}m {secs}s"
    return f"{secs}s"


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: CurrentUser = Depends(require_admin),
    session: Session = Depends(db_session),
):
    user_count = session.exec(select(func.count(User.id))).one()
    # sqlmodel returns either int or tuple depending on version — normalize
    if isinstance(user_count, tuple):
        user_count = user_count[0]

    return _templates().TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user": user,
            "page": "dashboard",
            "user_count": user_count,
            "cache": _cache_stats(),
            "build": _read_stats_json(),
            "uptime": _uptime(),
            "users": None,
            "flash": request.query_params.get("flash"),
            "flash_error": request.query_params.get("error"),
        },
    )


@router.get("/users", response_class=HTMLResponse)
async def list_users(
    request: Request,
    user: CurrentUser = Depends(require_admin),
    session: Session = Depends(db_session),
):
    users = session.exec(select(User).order_by(User.created_at)).all()
    return _templates().TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user": user,
            "page": "users",
            "users": users,
            "roles": [r.value for r in Role],
            "flash": request.query_params.get("flash"),
            "flash_error": request.query_params.get("error"),
        },
    )


@router.post("/users")
async def create_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("reviewer"),
    user: CurrentUser = Depends(require_admin),
    session: Session = Depends(db_session),
):
    email = email.strip().lower()
    if not email or not password:
        return RedirectResponse(
            url="/admin/users?error=Email+and+password+required",
            status_code=status.HTTP_302_FOUND,
        )
    if len(password) < 6:
        return RedirectResponse(
            url="/admin/users?error=Password+must+be+at+least+6+chars",
            status_code=status.HTTP_302_FOUND,
        )

    existing = session.exec(select(User).where(User.email == email)).first()
    if existing is not None:
        return RedirectResponse(
            url="/admin/users?error=User+already+exists",
            status_code=status.HTTP_302_FOUND,
        )

    try:
        role_enum = Role(role)
    except ValueError:
        role_enum = Role.reviewer

    new_user = User(
        email=email,
        password_hash=hash_password(password),
        role=role_enum,
        created_at=datetime.utcnow(),
        active=True,
    )
    session.add(new_user)
    session.commit()
    logger.info("Admin %s created user %s (%s)", user.email, email, role_enum.value)
    return RedirectResponse(
        url=f"/admin/users?flash=Created+{email}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/users/{user_id}/delete")
async def delete_user(
    user_id: int,
    request: Request,
    user: CurrentUser = Depends(require_admin),
    session: Session = Depends(db_session),
):
    target = session.get(User, user_id)
    if target is None:
        return RedirectResponse(
            url="/admin/users?error=User+not+found",
            status_code=status.HTTP_302_FOUND,
        )
    if target.email == user.email:
        return RedirectResponse(
            url="/admin/users?error=Cannot+delete+yourself",
            status_code=status.HTTP_302_FOUND,
        )
    session.delete(target)
    session.commit()
    logger.info("Admin %s deleted user %s", user.email, target.email)
    return RedirectResponse(
        url=f"/admin/users?flash=Deleted+{target.email}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/users/{user_id}/reset")
async def reset_password(
    user_id: int,
    request: Request,
    new_password: str = Form(...),
    user: CurrentUser = Depends(require_admin),
    session: Session = Depends(db_session),
):
    if len(new_password) < 6:
        return RedirectResponse(
            url="/admin/users?error=Password+too+short",
            status_code=status.HTTP_302_FOUND,
        )
    target = session.get(User, user_id)
    if target is None:
        return RedirectResponse(
            url="/admin/users?error=User+not+found",
            status_code=status.HTTP_302_FOUND,
        )
    target.password_hash = hash_password(new_password)
    session.add(target)
    session.commit()
    logger.info("Admin %s reset password for %s", user.email, target.email)
    return RedirectResponse(
        url=f"/admin/users?flash=Reset+password+for+{target.email}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/cache/flush")
async def flush_cache(
    request: Request,
    user: CurrentUser = Depends(require_admin),
):
    try:
        client = get_redis(db=1)
        client.flushdb()
        logger.info("Admin %s flushed cache db 1", user.email)
        flash = "Cache+flushed"
        err = ""
    except Exception as exc:
        logger.warning("Cache flush failed: %s", exc)
        flash = ""
        err = f"Flush+failed%3A+{exc}"
    url = f"/admin/?flash={flash}" if flash else f"/admin/?error={err}"
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
