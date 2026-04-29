"""Password hashing, JWT encoding/decoding, cookie helpers."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Request, Response
from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import get_settings
from .models import Role

logger = logging.getLogger(__name__)

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed)
    except Exception as exc:  # pragma: no cover
        logger.warning("bcrypt verify failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def create_access_token(
    email: str,
    role: Role | str,
    expires_minutes: Optional[int] = None,
) -> str:
    settings = get_settings()
    exp_minutes = expires_minutes or settings.jwt_expire_minutes
    now = datetime.now(tz=timezone.utc)
    payload: dict[str, Any] = {
        "sub": email,
        "role": role.value if isinstance(role, Role) else str(role),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=exp_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[dict]:
    settings = get_settings()
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        logger.debug("JWT decode failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Cookies
# ---------------------------------------------------------------------------
def _is_secure_request(request: Optional[Request]) -> bool:
    if request is None:
        return True
    # If behind Caddy terminating TLS, the request scheme may be http.
    # Respect X-Forwarded-Proto if present.
    xfp = request.headers.get("x-forwarded-proto")
    if xfp:
        return xfp.lower() == "https"
    return request.url.scheme == "https"


def set_session_cookie(
    response: Response,
    token: str,
    request: Optional[Request] = None,
) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,
        secure=_is_secure_request(request),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, request: Optional[Request] = None) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.cookie_name,
        path="/",
        httponly=True,
        secure=_is_secure_request(request),
        samesite="lax",
    )


def read_session_cookie(request: Request) -> Optional[str]:
    settings = get_settings()
    return request.cookies.get(settings.cookie_name)
