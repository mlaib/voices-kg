"""Auth routes: /auth/login, /auth/logout, /auth/verify, /auth/me."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from ..config import get_settings
from ..deps import db_session, get_current_user_optional
from ..models import Role, User
from ..security import (
    clear_session_cookie,
    create_access_token,
    hash_password,
    set_session_cookie,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _templates() -> Jinja2Templates:
    # imported locally so main.py can share; kept simple
    from ..main import templates as _t  # type: ignore

    return _t


@router.get("/login", response_class=HTMLResponse)
async def login_get(
    request: Request,
    next: Optional[str] = None,
    error: Optional[str] = None,
):
    return _templates().TemplateResponse(
        "login.html",
        {
            "request": request,
            "next": next or "/",
            "error": error,
            "user": None,
        },
    )


@router.post("/login")
async def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    session: Session = Depends(db_session),
):
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None or not user.active or not verify_password(password, user.password_hash):
        logger.info("Failed login for %s", email)
        return _templates().TemplateResponse(
            "login.html",
            {
                "request": request,
                "next": next,
                "error": "Invalid email or password.",
                "user": None,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    user.last_login = datetime.utcnow()
    session.add(user)
    session.commit()

    token = create_access_token(user.email, user.role)
    # Only accept path-only `next` values — prevents open-redirect and
    # the http/https scheme confusion from pre-fix browser history.
    safe_next = next if (next and next.startswith("/") and not next.startswith("//")) else "/"
    redirect = RedirectResponse(
        url=safe_next, status_code=status.HTTP_302_FOUND
    )
    set_session_cookie(redirect, token, request=request)
    logger.info("Login OK for %s (role=%s)", user.email, user.role.value)
    return redirect


@router.api_route("/logout", methods=["GET", "POST"])
async def logout(request: Request):
    """Sign out — accept both GET (sidebar link) and POST (form)."""
    redirect = RedirectResponse(
        url="/auth/login", status_code=status.HTTP_302_FOUND
    )
    clear_session_cookie(redirect, request=request)
    return redirect


@router.get("/password", response_class=HTMLResponse)
async def password_get(request: Request, error: Optional[str] = None,
                       success: Optional[str] = None):
    """Self-service password change form. Requires a valid session cookie."""
    user = get_current_user_optional(request)
    if user is None:
        return RedirectResponse(
            url="/auth/login?next=/auth/password",
            status_code=status.HTTP_302_FOUND,
        )
    return _templates().TemplateResponse(
        "change_password.html",
        {
            "request": request,
            "user_email": user.email,
            "error": error,
            "success": success,
        },
    )


@router.post("/password")
async def password_post(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    session: Session = Depends(db_session),
):
    user = get_current_user_optional(request)
    if user is None:
        return RedirectResponse(
            url="/auth/login?next=/auth/password",
            status_code=status.HTTP_302_FOUND,
        )

    db_user = session.exec(select(User).where(User.email == user.email)).first()
    if db_user is None:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)

    error: Optional[str] = None
    if not verify_password(current_password, db_user.password_hash):
        error = "Current password is incorrect."
    elif new_password != confirm_password:
        error = "The two new-password entries don't match."
    elif len(new_password) < 8:
        error = "New password must be at least 8 characters."
    elif new_password == current_password:
        error = "New password must differ from the current one."

    if error:
        return _templates().TemplateResponse(
            "change_password.html",
            {
                "request": request,
                "user_email": user.email,
                "error": error,
                "success": None,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    db_user.password_hash = hash_password(new_password)
    session.add(db_user)
    session.commit()
    logger.info("Password changed for %s", db_user.email)

    return _templates().TemplateResponse(
        "change_password.html",
        {
            "request": request,
            "user_email": user.email,
            "error": None,
            "success": "Password updated. Use the new password next time you sign in.",
        },
    )


@router.get("/me")
async def me(request: Request):
    user = get_current_user_optional(request)
    if user is None:
        return JSONResponse(
            {"authenticated": False}, status_code=status.HTTP_401_UNAUTHORIZED
        )
    return {
        "authenticated": True,
        "email": user.email,
        "role": user.role.value,
    }


@router.get("/verify")
async def verify(request: Request):
    """Subrequest endpoint used by both Caddy's ``forward_auth`` and nginx's
    ``auth_request``.

    nginx's auth_request module *does not follow* a 302 from the subrequest,
    so we must return 401 (which nginx maps via ``error_page 401 = @login``
    in the site config). Caddy's forward_auth handles either, so 401 is the
    safe choice for both fronts.

    * Valid cookie                   -> 200 with X-User / X-Role headers
    * No cookie, REQUIRE_AUTH=true   -> 401 (front redirects to /auth/login)
    * No cookie, REQUIRE_AUTH=false  -> 200 as anonymous/guest
    """
    settings = get_settings()
    user = get_current_user_optional(request)
    if user is not None:
        resp = Response(status_code=status.HTTP_200_OK)
        resp.headers["X-User"] = user.email
        resp.headers["X-Role"] = user.role.value
        return resp

    if settings.require_auth:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    resp = Response(status_code=status.HTTP_200_OK)
    resp.headers["X-User"] = "anonymous"
    resp.headers["X-Role"] = "guest"
    return resp
