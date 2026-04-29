"""Tiny async Fuseki SPARQL client with graceful degradation."""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)


VOICES_PREFIXES = """
PREFIX voices: <http://voices.uni.lu/ontology#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX geo: <http://www.w3.org/2003/01/geo/wgs84_pos#>
PREFIX prov: <http://www.w3.org/ns/prov#>
"""


class FusekiError(RuntimeError):
    """Raised when the downstream Fuseki service is unreachable or errors."""


async def run_select(
    query: str,
    *,
    timeout: float = 15.0,
    endpoint: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Run a SPARQL SELECT against Fuseki and return list of binding dicts.

    Each binding is ``{var: literal_value}`` (unwrapped).
    """
    settings = get_settings()
    base = endpoint or settings.fuseki_url
    url = base.rstrip("/") + "/sparql"
    full_query = VOICES_PREFIXES + "\n" + query

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url,
                data={"query": full_query},
                headers={"Accept": "application/sparql-results+json"},
            )
    except httpx.HTTPError as exc:
        logger.warning("Fuseki unreachable: %s", exc)
        raise FusekiError(f"Fuseki unreachable: {exc}") from exc

    if resp.status_code != 200:
        logger.warning(
            "Fuseki returned %s: %s", resp.status_code, resp.text[:300]
        )
        raise FusekiError(f"Fuseki status {resp.status_code}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise FusekiError(f"Fuseki returned invalid JSON: {exc}") from exc

    results = data.get("results", {}).get("bindings", [])
    out: list[dict[str, Any]] = []
    for row in results:
        out.append({k: v.get("value") for k, v in row.items()})
    return out


async def ping() -> bool:
    """Return True if Fuseki /$/ping responds."""
    settings = get_settings()
    base = settings.fuseki_url.rstrip("/")
    # ping endpoint is at dataset root's server "$/ping"
    server = base.rsplit("/", 1)[0] if "/" in base else base
    url = f"{server}/$/ping"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
            return resp.status_code == 200
    except httpx.HTTPError:
        return False
