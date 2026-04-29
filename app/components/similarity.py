"""FAISS similarity wrapper with lazy, memory-mapped load."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import streamlit as st

try:
    import faiss  # type: ignore
except Exception:  # pragma: no cover
    faiss = None  # type: ignore

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/output"))
INDEX_PATH = OUTPUT_DIR / "similarity.faiss"
IDS_PATH = OUTPUT_DIR / "similarity.ids.json"

_state: dict = {"loaded": False, "index": None, "ids": [], "warned": False}


def _load() -> None:
    if _state["loaded"]:
        return
    _state["loaded"] = True
    if faiss is None:
        return
    try:
        if not INDEX_PATH.exists() or not IDS_PATH.exists():
            return
        _state["index"] = faiss.read_index(str(INDEX_PATH), faiss.IO_FLAG_MMAP)
        _state["ids"] = json.loads(IDS_PATH.read_text())
    except Exception:
        _state["index"] = None
        _state["ids"] = []


def _warn_once() -> None:
    if _state["warned"]:
        return
    _state["warned"] = True
    st.warning(
        "Similarity index not available in this release. "
        "Related-event lookups will return no results."
    )


def similar_to(event_iri: str, k: int = 10) -> list[tuple[str, float]]:
    """Return up to k nearest neighbours (iri, score) for the event IRI.

    Returns [] and shows a one-time warning if the index is missing.
    """
    _load()
    index = _state["index"]
    ids: list[str] = _state["ids"]
    if index is None or not ids:
        _warn_once()
        return []
    try:
        position = ids.index(event_iri)
    except ValueError:
        return []
    try:
        vec = index.reconstruct(position).reshape(1, -1)
        distances, indices = index.search(vec, k + 1)
    except Exception:
        return []
    out: list[tuple[str, float]] = []
    for idx, dist in zip(indices[0], distances[0]):
        if idx < 0 or idx >= len(ids):
            continue
        if idx == position:
            continue
        out.append((ids[idx], float(dist)))
        if len(out) >= k:
            break
    return out


def similarity_available() -> bool:
    _load()
    return _state["index"] is not None
