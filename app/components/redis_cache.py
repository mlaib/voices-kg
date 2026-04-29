"""Redis-backed cache with a graceful st.cache_data fallback.

Key scheme: ``q:<sha1(query)>`` — works for SPARQL or any stable string key.
Value: JSON-serialised DataFrame records.

If Redis is unreachable we fall back to Streamlit's in-process cache. Never
raise: callers treat every path as a best-effort cache.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Callable, Optional

import pandas as pd
import streamlit as st

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover - redis not installed
    redis = None  # type: ignore

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/1")
DEFAULT_TTL = 3600
DROPDOWN_TTL = 86400


def _key_for(raw: str, prefix: str = "q") -> str:
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


@st.cache_resource(show_spinner=False)
def _redis_client() -> Optional["redis.Redis"]:
    """Return a Redis client if reachable, else None.

    Cached as a resource but with a live PING check before returning.
    """
    if redis is None:
        return None
    try:
        client = redis.Redis.from_url(REDIS_URL, socket_timeout=2, socket_connect_timeout=2)
        client.ping()
        return client
    except Exception:
        return None


def _fallback_get(key: str) -> Optional[str]:
    store = st.session_state.setdefault("_redis_fallback_store", {})
    return store.get(key)


def _fallback_set(key: str, value: str) -> None:
    store = st.session_state.setdefault("_redis_fallback_store", {})
    store[key] = value


def cache_get(key: str) -> Optional[str]:
    """Fetch raw string value from cache. Never raises."""
    client = _redis_client()
    if client is not None:
        try:
            v = client.get(key)
            if v is None:
                return None
            return v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
        except Exception:
            pass
    return _fallback_get(key)


def cache_set(key: str, value: str, ttl: int = DEFAULT_TTL) -> None:
    """Store raw string value. Never raises."""
    client = _redis_client()
    if client is not None:
        try:
            client.setex(key, ttl, value)
            return
        except Exception:
            pass
    _fallback_set(key, value)


def cached_dataframe(
    key_source: str,
    compute: Callable[[], pd.DataFrame],
    ttl: int = DEFAULT_TTL,
    prefix: str = "q",
) -> tuple[pd.DataFrame, bool]:
    """Return (df, cached). ``cached`` indicates hit vs miss.

    The DataFrame round-trips through JSON records — callers must tolerate
    columns being reordered and complex dtypes being coerced to str/number.
    """
    key = _key_for(key_source, prefix=prefix)
    raw = cache_get(key)
    if raw is not None:
        try:
            records = json.loads(raw)
            return pd.DataFrame.from_records(records), True
        except Exception:
            pass
    df = compute()
    try:
        payload = df.to_json(orient="records", date_format="iso", default_handler=str)
        if payload is not None:
            cache_set(key, payload, ttl=ttl)
    except Exception:
        pass
    return df, False


def cached_json(
    key_source: str,
    compute: Callable[[], Any],
    ttl: int = DEFAULT_TTL,
    prefix: str = "j",
) -> tuple[Any, bool]:
    key = _key_for(key_source, prefix=prefix)
    raw = cache_get(key)
    if raw is not None:
        try:
            return json.loads(raw), True
        except Exception:
            pass
    value = compute()
    try:
        cache_set(key, json.dumps(value, default=str), ttl=ttl)
    except Exception:
        pass
    return value, False


def redis_status() -> bool:
    return _redis_client() is not None
