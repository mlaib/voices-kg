"""Meilisearch wrapper for full-text search over transcript segments."""
from __future__ import annotations

import os
from typing import Any, Optional

import streamlit as st

try:
    import meilisearch  # type: ignore
except Exception:  # pragma: no cover
    meilisearch = None  # type: ignore

MEILISEARCH_URL = os.environ.get("MEILISEARCH_URL", "http://meilisearch:7700")
MEILISEARCH_KEY = os.environ.get("MEILISEARCH_KEY", "")
DEFAULT_INDEX = "voices-segments"


@st.cache_resource(show_spinner=False)
def _client() -> Optional["meilisearch.Client"]:
    if meilisearch is None:
        return None
    try:
        c = meilisearch.Client(MEILISEARCH_URL, MEILISEARCH_KEY or None)
        # Health check — Meilisearch exposes .health()
        c.health()
        return c
    except Exception:
        return None


def meilisearch_available() -> bool:
    return _client() is not None


def search(
    query: str,
    index: str = DEFAULT_INDEX,
    filters: Optional[list[str]] = None,
    limit: int = 20,
    offset: int = 0,
    attributes_to_highlight: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Run a Meilisearch query. Returns Meilisearch's response dict.

    On error returns ``{"hits": [], "estimatedTotalHits": 0, "error": msg}``.
    """
    c = _client()
    if c is None:
        return {"hits": [], "estimatedTotalHits": 0, "error": "Meilisearch unreachable"}
    try:
        idx = c.index(index)
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if filters:
            params["filter"] = filters
        if attributes_to_highlight:
            params["attributesToHighlight"] = attributes_to_highlight
            params["highlightPreTag"] = "<mark>"
            params["highlightPostTag"] = "</mark>"
        return idx.search(query, params)
    except Exception as e:
        return {"hits": [], "estimatedTotalHits": 0, "error": str(e)}


def meili_status_badge() -> None:
    if meilisearch_available():
        st.sidebar.success("Search index: connected")
    else:
        st.sidebar.warning("Search index: offline")
