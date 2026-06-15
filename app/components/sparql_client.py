"""SPARQL client — talks to Fuseki, caches through Redis where possible."""
from __future__ import annotations

import os
from typing import Optional

import pandas as pd
import requests
import streamlit as st

from components.redis_cache import cached_dataframe, DEFAULT_TTL, DROPDOWN_TTL

FUSEKI_URL = os.environ.get("FUSEKI_URL", "http://fuseki:3030/voices")
DEFAULT_TIMEOUT = 120


def _sparql_endpoint() -> str:
    url = FUSEKI_URL.rstrip("/")
    if url.endswith("/sparql") or url.endswith("/query"):
        return url
    return f"{url}/sparql"


@st.cache_data(ttl=30, show_spinner=False)
def _fuseki_available_cached(endpoint: str) -> bool:
    try:
        resp = requests.post(
            endpoint,
            data={"query": "ASK { ?s ?p ?o }"},
            headers={"Accept": "application/sparql-results+json"},
            timeout=5,
        )
        return resp.status_code == 200
    except Exception:
        return False


def fuseki_available(endpoint: Optional[str] = None) -> bool:
    # Cached for 30s so the status badge doesn't cost a round-trip per rerun.
    return _fuseki_available_cached(endpoint or _sparql_endpoint())


def _run_sparql_raw(query: str, timeout: int = DEFAULT_TIMEOUT) -> pd.DataFrame:
    """Actual POST + parse — uncached."""
    resp = requests.post(
        _sparql_endpoint(),
        data={"query": query},
        headers={"Accept": "application/sparql-results+json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        return pd.DataFrame()
    rows = [{k: v.get("value", "") for k, v in b.items()} for b in bindings]
    return pd.DataFrame(rows)


def run_sparql(
    query: str,
    timeout: int = DEFAULT_TIMEOUT,
    ttl: int = DEFAULT_TTL,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Run SPARQL. Errors saved to ``st.session_state['sparql_error']``.

    When cache is hit, ``st.session_state['sparql_cached']`` is set to True
    so pages can show a "Cached" badge next to results.
    """
    st.session_state["sparql_error"] = None
    st.session_state["sparql_cached"] = False

    def _compute() -> pd.DataFrame:
        return _run_sparql_raw(query, timeout=timeout)

    try:
        if use_cache:
            df, cached = cached_dataframe(query, _compute, ttl=ttl, prefix="sparql")
            st.session_state["sparql_cached"] = cached
            return df
        return _compute()
    except requests.exceptions.Timeout:
        st.session_state["sparql_error"] = (
            f"Query timed out after {timeout}s. Try adding LIMIT or simplifying."
        )
    except requests.exceptions.ConnectionError:
        st.session_state["sparql_error"] = (
            f"Cannot reach Fuseki at {_sparql_endpoint()}. Is the service running?"
        )
    except Exception as e:
        st.session_state["sparql_error"] = str(e)
    return pd.DataFrame()


def run_sparql_dropdown(query: str) -> pd.DataFrame:
    """Same as ``run_sparql`` but with the long dropdown TTL."""
    return run_sparql(query, ttl=DROPDOWN_TTL)


def show_sparql_error() -> None:
    err = st.session_state.get("sparql_error")
    if err:
        st.error(f"SPARQL error: {err}")


def cached_badge() -> None:
    if st.session_state.get("sparql_cached"):
        st.caption("Cached result from Redis.")


def fuseki_status_badge() -> None:
    if fuseki_available():
        st.sidebar.success("Triplestore: connected")
    else:
        st.sidebar.error("Triplestore: offline")


VOICES_PREFIXES = """\
PREFIX voices: <https://w3id.org/voices/ontology#>
PREFIX rdfs:   <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX owl:    <http://www.w3.org/2002/07/owl#>
PREFIX skos:   <http://www.w3.org/2004/02/skos/core#>
PREFIX xsd:    <http://www.w3.org/2001/XMLSchema#>
PREFIX time:   <http://www.w3.org/2006/time#>
PREFIX prov:   <http://www.w3.org/ns/prov#>
"""
