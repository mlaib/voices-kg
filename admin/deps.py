"""Shared FastAPI dependencies."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session, select

from .database import get_session
from .models import Role, User
from .security import decode_token, read_session_cookie

logger = logging.getLogger(__name__)


class CurrentUser:
    """Lightweight user representation derived from the JWT."""

    def __init__(self, email: str, role: Role, authenticated: bool = True):
        self.email = email
        self.role = role
        self.authenticated = authenticated

    @property
    def is_admin(self) -> bool:
        return self.role == Role.admin

    def __repr__(self) -> str:  # pragma: no cover
        return f"CurrentUser(email={self.email!r}, role={self.role!r})"


def _user_from_request(request: Request) -> Optional[CurrentUser]:
    token = read_session_cookie(request)
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    email = payload.get("sub")
    role_raw = payload.get("role", "reviewer")
    if not email:
        return None
    try:
        role = Role(role_raw)
    except ValueError:
        role = Role.reviewer
    return CurrentUser(email=email, role=role, authenticated=True)


def get_current_user_optional(request: Request) -> Optional[CurrentUser]:
    """Return CurrentUser if cookie is valid, else None. Never raises."""
    return _user_from_request(request)


def get_current_user(request: Request) -> CurrentUser:
    """Require an authenticated user (401 otherwise)."""
    user = _user_from_request(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Require an admin role. 403 if authenticated but not admin."""
    if user.role != Role.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user


def db_session() -> Session:
    """FastAPI-friendly session dependency."""
    yield from get_session()


def load_db_user(email: str, session: Session) -> Optional[User]:
    return session.exec(select(User).where(User.email == email)).first()
