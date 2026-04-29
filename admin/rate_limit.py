"""Simple Redis sliding-window rate limiter (60 req/min per IP by default)."""
from __future__ import annotations

import logging
import time
from typing import Optional

import redis

from .config import get_settings

logger = logging.getLogger(__name__)

_client: Optional[redis.Redis] = None


def get_redis(db: Optional[int] = None) -> redis.Redis:
    """Return a redis client for the configured URL.

    Pass ``db`` to override the database index encoded in REDIS_URL.
    """
    settings = get_settings()
    url = settings.redis_url
    if db is not None:
        # naive swap of trailing db index
        if "/" in url.rsplit(":", 1)[-1]:
            base, _ = url.rsplit("/", 1)
            url = f"{base}/{db}"
        else:
            url = f"{url.rstrip('/')}/{db}"
    return redis.from_url(url, decode_responses=True, socket_timeout=2)


def _default_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = get_redis()
    return _client


def check_rate_limit(
    ip: str,
    limit: Optional[int] = None,
    window_seconds: int = 60,
) -> tuple[bool, int]:
    """Return (allowed, remaining). Fail-open if Redis unreachable."""
    settings = get_settings()
    max_hits = limit if limit is not None else settings.rate_limit_per_minute
    bucket = int(time.time() // window_seconds)
    key = f"ratelimit:{ip}:{bucket}"
    try:
        client = _default_client()
        pipe = client.pipeline()
        pipe.incr(key, 1)
        pipe.expire(key, window_seconds + 5)
        count, _ = pipe.execute()
        count = int(count)
        remaining = max(0, max_hits - count)
        return count <= max_hits, remaining
    except Exception as exc:
        logger.warning("rate limit failed (fail-open): %s", exc)
        return True, max_hits
