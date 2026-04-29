"""Auth integration with the admin service.

Caddy already gates the app with ``forward_auth``; by the time Streamlit
renders, the user is authenticated (or REQUIRE_AUTH is off). We still want
to *display* who's logged in, so we call ``ADMIN_URL/auth/me`` with the
incoming cookie forwarded from ``st.context.headers``.
"""
from __future__ import annotations

import os
from typing import Optional

import requests
import streamlit as st

ADMIN_URL = os.environ.get("ADMIN_URL", "http://admin:8000")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")


def _incoming_cookie_header() -> str:
    """Read the raw Cookie header from the incoming request.

    Streamlit exposes request headers via ``st.context.headers`` (>= 1.37).
    Returns an empty string if unavailable.
    """
    try:
        ctx = getattr(st, "context", None)
        if ctx is None:
            return ""
        headers = getattr(ctx, "headers", None)
        if headers is None:
            return ""
        # ``headers`` behaves like a dict-like mapping.
        cookie = headers.get("Cookie") or headers.get("cookie") or ""
        return cookie or ""
    except Exception:
        return ""


def current_user() -> Optional[dict]:
    """Return a dict with email + role for the current user, or None.

    Cached in session_state to avoid repeat round-trips per rerun.
    """
    cached = st.session_state.get("_auth_me")
    if cached is not None:
        return cached if cached else None

    cookie = _incoming_cookie_header()
    headers = {"Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    try:
        resp = requests.get(f"{ADMIN_URL.rstrip('/')}/auth/me", headers=headers, timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            st.session_state["_auth_me"] = data
            return data
    except Exception:
        pass
    st.session_state["_auth_me"] = {}
    return None


def render_user_badge() -> None:
    """Render a sidebar badge showing the current user + role + admin link + logout.

    Uses relative URLs with ``target="_self"`` so navigation stays in the
    same browser tab (Streamlit's default link behaviour for absolute URLs
    is to open them in a new tab).
    """
    user = current_user()
    with st.sidebar:
        if user and user.get("email"):
            email = user.get("email", "")
            role = user.get("role", "user")
            st.markdown(f"**Signed in as** `{email}`  \n_Role: {role}_")
            links = []
            if role == "admin":
                links.append('<a href="/admin/" target="_self">Admin panel</a>')
            links.append('<a href="/auth/password" target="_self">Change password</a>')
            links.append('<a href="/auth/logout" target="_self">Log out</a>')
            st.markdown(
                '<div style="display:flex;flex-direction:column;gap:4px;font-size:0.9em">'
                + "".join(f"<div>{html}</div>" for html in links)
                + "</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown("**Signed in as** _Anonymous_")
            st.markdown(
                '<a href="/auth/login" target="_self">Log in</a>',
                unsafe_allow_html=True,
            )
