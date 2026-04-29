"""Public REST API wrapping the knowledge graph.

All routes public, rate-limited by IP (60 req/min by default).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from ..config import get_settings
from ..rate_limit import check_rate_limit, get_redis
from ..sparql_client import FusekiError, ping as fuseki_ping, run_select

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["api"])


# ---------------------------------------------------------------------------
# Rate-limit helper (dependency-free so we can use request.client.host)
# ---------------------------------------------------------------------------
def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(request: Request) -> None:
    ip = _client_ip(request)
    allowed, remaining = check_rate_limit(ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "rate_limited", "remaining": remaining},
        )


# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------
def _output_path(*parts: str) -> Path:
    settings = get_settings()
    return Path(settings.output_dir).joinpath(*parts)


def _load_cached_json(relpath: str) -> Optional[list | dict]:
    p = _output_path(*relpath.split("/"))
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.warning("Could not load cache %s: %s", p, exc)
        return None


def _redis_cache_get(key: str) -> Optional[str]:
    try:
        return get_redis(db=1).get(key)
    except Exception:
        return None


def _redis_cache_set(key: str, value: str, ttl: int = 300) -> None:
    try:
        get_redis(db=1).set(key, value, ex=ttl)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------
@router.get("/interviews")
async def list_interviews(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    _enforce_rate_limit(request)
    query = f"""
    SELECT ?id ?survivor_label WHERE {{
      GRAPH ?g {{
        ?id a voices:Interview .
        OPTIONAL {{ ?id voices:survivorLabel ?survivor_label }}
      }}
    }}
    ORDER BY ?id
    LIMIT {limit} OFFSET {offset}
    """
    try:
        rows = await run_select(query)
    except FusekiError as exc:
        return JSONResponse(
            {"error": "fuseki_unavailable", "detail": str(exc)},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return {"items": rows, "limit": limit, "offset": offset, "count": len(rows)}


@router.get("/interviews/{interview_id:path}")
async def get_interview(interview_id: str, request: Request):
    _enforce_rate_limit(request)
    # accept either a full IRI or a short id
    iri = interview_id if interview_id.startswith("http") else f"<{interview_id}>"
    if iri.startswith("<"):
        subject = iri
    else:
        subject = f"<{iri}>"

    meta_q = f"""
    SELECT ?p ?o WHERE {{
      GRAPH ?g {{ {subject} ?p ?o }}
    }}
    """
    count_q = f"""
    SELECT (COUNT(?e) AS ?events) WHERE {{
      GRAPH ?g {{ ?e voices:interview {subject} }}
    }}
    """
    try:
        meta_rows = await run_select(meta_q)
        count_rows = await run_select(count_q)
    except FusekiError as exc:
        return JSONResponse(
            {"error": "fuseki_unavailable", "detail": str(exc)},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if not meta_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found"
        )
    metadata = {row["p"]: row["o"] for row in meta_rows if "p" in row}
    event_count = int(count_rows[0].get("events", 0)) if count_rows else 0
    return {
        "id": interview_id,
        "metadata": metadata,
        "counts": {"events": event_count},
    }


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
@router.get("/events")
async def list_events(
    request: Request,
    activity: Optional[str] = None,
    emotion: Optional[str] = None,
    place: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    _enforce_rate_limit(request)
    filters = []
    if activity:
        filters.append(f"?id voices:hasActivity <{activity}> .")
    if place:
        filters.append(f"?id voices:hasLocation <{place}> .")
    # emotion filter omitted: emotions live on separate annotation nodes that
    # reference segments, not events directly, so a cheap join isn't possible.
    flt = "\n      ".join(filters)
    query = f"""
    SELECT ?id ?whatText ?activity ?place WHERE {{
      GRAPH <urn:voices:graph:events> {{
        ?id a voices:NarratedEvent .
        {flt}
        OPTIONAL {{ ?id voices:whatText ?whatText }}
        OPTIONAL {{ ?id voices:hasActivity ?activity }}
        OPTIONAL {{ ?id voices:hasLocation ?place }}
      }}
    }}
    LIMIT {limit} OFFSET {offset}
    """
    try:
        rows = await run_select(query)
    except FusekiError as exc:
        return JSONResponse(
            {"error": "fuseki_unavailable", "detail": str(exc)},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return {"items": rows, "limit": limit, "offset": offset, "count": len(rows)}


@router.get("/events/{event_id:path}")
async def get_event(event_id: str, request: Request):
    _enforce_rate_limit(request)
    subject = f"<{event_id}>"
    props_q = f"""
    SELECT ?p ?o WHERE {{
      GRAPH ?g {{ {subject} ?p ?o }}
    }}
    """
    annot_q = f"""
    SELECT ?annotation ?p ?o WHERE {{
      GRAPH ?g {{
        << {subject} ?ap ?ao >> ?p ?o .
        BIND(CONCAT(STR(?ap), "|", STR(?ao)) AS ?annotation)
      }}
    }}
    """
    try:
        prop_rows = await run_select(props_q)
        annot_rows = await run_select(annot_q)
    except FusekiError as exc:
        return JSONResponse(
            {"error": "fuseki_unavailable", "detail": str(exc)},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if not prop_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found"
        )
    return {
        "id": event_id,
        "properties": {row["p"]: row["o"] for row in prop_rows if "p" in row},
        "annotations": annot_rows,
    }


# ---------------------------------------------------------------------------
# Places / activities / emotions — small reference lists, cached to disk
# ---------------------------------------------------------------------------
@router.get("/places")
async def list_places(request: Request, limit: int = Query(200, ge=1, le=5000)):
    _enforce_rate_limit(request)
    cached = _load_cached_json("caches/places.json")
    if cached is not None:
        items = cached[:limit] if isinstance(cached, list) else cached
        return {"items": items, "source": "cache"}
    query = f"""
    SELECT ?id ?label ?lat ?lon WHERE {{
      GRAPH ?g {{
        ?id a voices:Place .
        OPTIONAL {{ ?id rdfs:label ?label }}
        OPTIONAL {{ ?id geo:lat ?lat }}
        OPTIONAL {{ ?id geo:long ?lon }}
      }}
    }}
    LIMIT {limit}
    """
    try:
        rows = await run_select(query)
    except FusekiError as exc:
        return JSONResponse(
            {"error": "fuseki_unavailable", "detail": str(exc)},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return {"items": rows, "source": "sparql"}


@router.get("/activities")
async def list_activities(request: Request, limit: int = Query(500, ge=1, le=5000)):
    _enforce_rate_limit(request)
    cached = _load_cached_json("caches/activities.json")
    if cached is not None:
        items = cached[:limit] if isinstance(cached, list) else cached
        return {"items": items, "source": "cache"}
    query = f"""
    SELECT DISTINCT ?id ?label WHERE {{
      GRAPH ?g {{
        ?id a voices:Activity .
        OPTIONAL {{ ?id rdfs:label ?label }}
      }}
    }}
    ORDER BY ?label
    LIMIT {limit}
    """
    try:
        rows = await run_select(query)
    except FusekiError as exc:
        return JSONResponse(
            {"error": "fuseki_unavailable", "detail": str(exc)},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return {"items": rows, "source": "sparql"}


@router.get("/emotions")
async def list_emotions(request: Request, limit: int = Query(500, ge=1, le=5000)):
    _enforce_rate_limit(request)
    cached = _load_cached_json("caches/emotions.json")
    if cached is not None:
        items = cached[:limit] if isinstance(cached, list) else cached
        return {"items": items, "source": "cache"}
    query = f"""
    SELECT DISTINCT ?id ?label WHERE {{
      GRAPH ?g {{
        ?id a voices:Emotion .
        OPTIONAL {{ ?id rdfs:label ?label }}
      }}
    }}
    ORDER BY ?label
    LIMIT {limit}
    """
    try:
        rows = await run_select(query)
    except FusekiError as exc:
        return JSONResponse(
            {"error": "fuseki_unavailable", "detail": str(exc)},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return {"items": rows, "source": "sparql"}


# ---------------------------------------------------------------------------
# Search (Meilisearch)
# ---------------------------------------------------------------------------
@router.get("/search")
async def search(
    request: Request,
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
):
    _enforce_rate_limit(request)
    settings = get_settings()
    url = f"{settings.meilisearch_url.rstrip('/')}/indexes/voices-segments/search"
    headers = {"Content-Type": "application/json"}
    if settings.meilisearch_key:
        headers["Authorization"] = f"Bearer {settings.meilisearch_key}"
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                url, json={"q": q, "limit": limit}, headers=headers
            )
    except httpx.HTTPError as exc:
        return JSONResponse(
            {"error": "meilisearch_unavailable", "detail": str(exc)},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if resp.status_code != 200:
        return JSONResponse(
            {"error": "meilisearch_error", "status": resp.status_code,
             "detail": resp.text[:300]},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    data = resp.json()
    return {
        "items": data.get("hits", []),
        "query": q,
        "total": data.get("estimatedTotalHits", len(data.get("hits", []))),
    }


# ---------------------------------------------------------------------------
# Similar events (FAISS nearest neighbors)
# ---------------------------------------------------------------------------
_FAISS_INDEX = None
_FAISS_IDS: Optional[list[str]] = None


def _load_faiss() -> tuple[object, list[str]] | tuple[None, None]:
    global _FAISS_INDEX, _FAISS_IDS
    if _FAISS_INDEX is not None and _FAISS_IDS is not None:
        return _FAISS_INDEX, _FAISS_IDS
    index_path = _output_path("similarity.faiss")
    ids_path = _output_path("similarity.ids.json")
    if not index_path.exists() or not ids_path.exists():
        return None, None
    try:
        import faiss  # type: ignore
    except ImportError:
        logger.info("faiss not installed; /api/similar disabled")
        return None, None
    try:
        _FAISS_INDEX = faiss.read_index(str(index_path))
        with open(ids_path, "r", encoding="utf-8") as fh:
            _FAISS_IDS = json.load(fh)
        return _FAISS_INDEX, _FAISS_IDS
    except Exception as exc:
        logger.warning("Failed to load faiss index: %s", exc)
        return None, None


@router.get("/similar/{event_id:path}")
async def similar_events(
    event_id: str,
    request: Request,
    k: int = Query(10, ge=1, le=100),
):
    _enforce_rate_limit(request)
    index, ids = _load_faiss()
    if index is None or ids is None:
        return JSONResponse(
            {"error": "not_implemented",
             "detail": "similarity.faiss or similarity.ids.json not available"},
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
        )
    try:
        idx = ids.index(event_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not present in similarity index",
        )
    try:
        import numpy as np  # type: ignore
        vec = index.reconstruct(idx).reshape(1, -1).astype("float32")
        distances, indices = index.search(vec, k + 1)  # +1 because first = self
    except Exception as exc:
        logger.warning("FAISS search failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    hits = []
    for dist, i in zip(distances[0], indices[0]):
        if i < 0 or i >= len(ids):
            continue
        candidate = ids[i]
        if candidate == event_id:
            continue
        hits.append({"id": candidate, "score": float(dist)})
        if len(hits) >= k:
            break
    return {"items": hits, "source": event_id, "k": k}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@router.get("/healthz")
async def api_healthz(request: Request):
    _enforce_rate_limit(request)
    status_out = {"status": "ok"}

    # Fuseki
    try:
        status_out["fuseki"] = "ok" if await fuseki_ping() else "down"
    except Exception:
        status_out["fuseki"] = "down"

    # Redis
    try:
        get_redis().ping()
        status_out["redis"] = "ok"
    except Exception:
        status_out["redis"] = "down"

    # Meilisearch
    settings = get_settings()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(
                f"{settings.meilisearch_url.rstrip('/')}/health"
            )
            status_out["meilisearch"] = "ok" if r.status_code == 200 else "down"
    except Exception:
        status_out["meilisearch"] = "down"

    if any(v == "down" for v in status_out.values() if isinstance(v, str) and v in ("ok", "down")):
        status_out["status"] = "degraded"
    return status_out
