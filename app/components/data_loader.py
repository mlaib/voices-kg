"""Data loader — reads precomputed JSON caches, falls back to SPARQL.

All accessors return plain Python types (dict / list). Missing caches are
logged once via ``st.warning`` and trigger a live SPARQL fallback where the
code paths make that possible.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from components.sparql_client import (
    VOICES_PREFIXES,
    fuseki_available,
    run_sparql,
    run_sparql_dropdown,
)

CACHES_DIR = Path(os.environ.get("CACHES_DIR", "/output/caches"))

G_META = "urn:voices:graph:metadata"
G_TRANS = "urn:voices:graph:transcripts"
G_EVENTS = "urn:voices:graph:events"
G_ANNOT = "urn:voices:graph:annotations"
G_EMBED = "urn:voices:graph:embeddings"
G_ALIGN = "urn:voices:graph:alignment"


def _read_json(name: str) -> Any:
    path = CACHES_DIR / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        st.warning(f"Could not parse cache {name}: {e}")
        return None


def _warn_missing(name: str) -> None:
    key = f"_cache_warned_{name}"
    if st.session_state.get(key):
        return
    st.session_state[key] = True
    st.warning(f"Cache {name} missing — falling back to live SPARQL.")


# ---------------------------------------------------------------------------
# Summary totals
# ---------------------------------------------------------------------------
def load_summary() -> dict[str, int]:
    data = _read_json("summary.json")
    if data:
        return data
    _warn_missing("summary.json")
    if not fuseki_available():
        return {}
    sparql = VOICES_PREFIXES + f"""
SELECT (COUNT(DISTINCT ?interview) AS ?interviews)
       (COUNT(DISTINCT ?event) AS ?events)
       (COUNT(DISTINCT ?segment) AS ?segments)
WHERE {{
  OPTIONAL {{ GRAPH <{G_META}> {{ ?interview a voices:Interview . }} }}
  OPTIONAL {{ GRAPH <{G_EVENTS}> {{ ?event a voices:NarratedEvent . }} }}
  OPTIONAL {{ GRAPH <{G_TRANS}> {{ ?segment a voices:Segment . }} }}
}}"""
    df = run_sparql(sparql)
    if df.empty:
        return {}
    row = df.iloc[0].to_dict()
    return {k: int(v) if str(v).isdigit() else 0 for k, v in row.items()}


# ---------------------------------------------------------------------------
# Activities, emotions, places, interviews, historical events
# ---------------------------------------------------------------------------
def load_activities() -> list[dict]:
    data = _read_json("activities.json")
    if data:
        return data
    _warn_missing("activities.json")
    if not fuseki_available():
        return []
    sparql = VOICES_PREFIXES + f"""
SELECT ?label (COUNT(?event) AS ?count) WHERE {{
  GRAPH <{G_EVENTS}> {{
    ?event voices:hasActivity ?a .
    ?a rdfs:label ?label .
  }}
}} GROUP BY ?label ORDER BY DESC(?count) LIMIT 50"""
    df = run_sparql_dropdown(sparql)
    return df.to_dict("records") if not df.empty else []


def load_emotions() -> list[dict]:
    data = _read_json("emotions.json")
    if data:
        return data
    _warn_missing("emotions.json")
    if not fuseki_available():
        return []
    sparql = VOICES_PREFIXES + f"""
SELECT ?label (COUNT(?emo) AS ?count) WHERE {{
  GRAPH <{G_ANNOT}> {{
    ?emo a voices:EmotionAnnotation ; rdfs:label ?label .
  }}
}} GROUP BY ?label ORDER BY DESC(?count) LIMIT 50"""
    df = run_sparql_dropdown(sparql)
    return df.to_dict("records") if not df.empty else []


def load_places() -> list[dict]:
    data = _read_json("places.json")
    if data:
        return data
    _warn_missing("places.json")
    if not fuseki_available():
        return []
    sparql = VOICES_PREFIXES + f"""
SELECT ?label (COUNT(?event) AS ?count) WHERE {{
  GRAPH <{G_EVENTS}> {{
    ?event voices:hasLocation ?place .
    ?place rdfs:label ?label .
  }}
}} GROUP BY ?label ORDER BY DESC(?count) LIMIT 200"""
    df = run_sparql_dropdown(sparql)
    return df.to_dict("records") if not df.empty else []


def load_interviews() -> list[dict]:
    """Return list of {id: <IRI>, label: <survivor>} dicts.

    The cache stores entries as {iri, survivor, id} where ``id`` is the bare
    numeric ID, not the IRI. Normalize here so callers can rely on a single
    shape regardless of cache vintage.
    """
    data = _read_json("interviews.json")
    if data:
        normalized = []
        for r in data:
            iri = r.get("iri") or r.get("id") or ""
            label = r.get("survivor") or r.get("label") or iri
            if iri.startswith("urn:") or iri.startswith("http"):
                normalized.append({"id": iri, "label": label})
            else:
                # Cache predates the urn: scheme; rebuild the IRI from numeric id.
                normalized.append({"id": f"urn:voices:interview:{iri}", "label": label})
        return normalized
    _warn_missing("interviews.json")
    if not fuseki_available():
        return []
    sparql = VOICES_PREFIXES + f"""
SELECT ?id ?label WHERE {{
  GRAPH <{G_META}> {{
    ?id a voices:Interview ; rdfs:label ?label .
  }}
}} ORDER BY ?label"""
    df = run_sparql_dropdown(sparql)
    return df.to_dict("records") if not df.empty else []


@st.cache_data(ttl=3600, persist="disk", show_spinner=False)
def load_interviews_meta() -> list[dict]:
    """Same as load_interviews() but enriched with recordingYear and gender.

    Issues a single batch query to the metadata graph (≈982 rows, sub-second)
    and merges the result onto the cache list. Result is cached by Streamlit
    so we run the query at most once per app session.
    """
    base = load_interviews()
    if not base:
        return []
    if not fuseki_available():
        return base
    sparql = VOICES_PREFIXES + f"""
SELECT ?id ?year ?gender WHERE {{
  GRAPH <{G_META}> {{
    ?id a voices:Interview .
    OPTIONAL {{ ?id voices:recordingYear ?year }}
    OPTIONAL {{ ?id voices:gender ?gender }}
  }}
}}"""
    df = run_sparql(sparql)
    if df.empty:
        return base
    extra = {str(row.get("id", "")): row for _, row in df.iterrows()}
    out = []
    for r in base:
        iri = r.get("id", "")
        meta = extra.get(iri)
        out.append({
            "id": iri,
            "label": r.get("label", ""),
            "year": str(meta.get("year", "")) if meta is not None else "",
            "gender": str(meta.get("gender", "")) if meta is not None else "",
        })
    return out


def load_sankey_flow() -> list[dict]:
    """3-col flow rows for the home Sankey: period → activity → category."""
    data = _read_json("sankey_flow.json")
    return data or []


def period_counts_for_activity(activity_label: str) -> dict[str, int]:
    """Period → event-count for a chosen activity. Pure cache lookup."""
    out: dict[str, int] = {}
    for r in load_sankey_flow():
        if r.get("activity") == activity_label:
            p = r.get("period")
            if p:
                out[p] = out.get(p, 0) + int(r.get("count", 0) or 0)
    return out


def period_counts_for_word(word: str, max_hits: int = 1500) -> dict[str, int]:
    """Period → segment-count for transcript matches of ``word``.

    Uses Meilisearch to find matching segments fast, then bucket them by
    period via the segment → event → temporalBucket join in SPARQL.
    """
    if not word or not word.strip():
        return {}
    from components.search_client import meilisearch_available, search as meili_search
    if not meilisearch_available():
        return {}
    res = meili_search(word, limit=max_hits)
    hits = res.get("hits", [])
    seg_iris = [h.get("iri") for h in hits if h.get("iri")]
    if not seg_iris:
        return {}
    iri_block = " ".join(f"<{i}>" for i in seg_iris)
    q = VOICES_PREFIXES + f"""
SELECT ?period (COUNT(DISTINCT ?seg) AS ?n) WHERE {{
  VALUES ?seg {{ {iri_block} }}
  GRAPH <{G_EVENTS}> {{
    ?seg voices:segmentRefersToEvent ?ev .
    ?ev voices:temporalBucket ?period .
  }}
}} GROUP BY ?period"""
    df = run_sparql_dropdown(q)
    if df.empty:
        return {}
    out: dict[str, int] = {}
    for _, row in df.iterrows():
        p = str(row.get("period", "") or "")
        try:
            n = int(row.get("n", 0) or 0)
        except (TypeError, ValueError):
            n = 0
        if p:
            out[p] = n
    return out


def load_surprise_terms() -> dict[str, list[dict]]:
    """Top over-represented terms per life period. Cache-only."""
    data = _read_json("surprise_terms.json")
    return data or {}


def load_surprise_terms_by_emotion() -> dict[str, dict[str, list[dict]]]:
    """Top over-represented terms per (life period, emotion category).

    Within-period contrast: for each (period, emotion), the score reflects how
    over-represented the term is in that emotion's segments compared to other
    emotions in the same period — i.e. "what makes a moment in this period
    feel this way".
    """
    data = _read_json("surprise_terms_by_emotion.json")
    return data or {}


def _word_seg_iris(word: str, max_hits: int = 1500) -> list[str]:
    """Helper: Meilisearch IRIs for transcripts containing ``word``."""
    from components.search_client import meilisearch_available, search as meili_search
    if not word or not word.strip() or not meilisearch_available():
        return []
    res = meili_search(word, limit=max_hits)
    hits = res.get("hits", [])
    return [h.get("iri") for h in hits if h.get("iri")]


def _values_block(iris: list[str]) -> str:
    return " ".join(f"<{i}>" for i in iris)


def activity_counts_for_word(word: str, max_hits: int = 1500) -> dict[str, int]:
    """Activity-label → segment-count for transcripts containing ``word``."""
    iris = _word_seg_iris(word, max_hits)
    if not iris:
        return {}
    q = VOICES_PREFIXES + f"""
SELECT ?label (COUNT(DISTINCT ?seg) AS ?n) WHERE {{
  VALUES ?seg {{ {_values_block(iris)} }}
  GRAPH <{G_EVENTS}> {{
    ?seg voices:segmentRefersToEvent ?ev .
    ?ev voices:hasActivity ?act .
    ?act rdfs:label ?label .
  }}
}} GROUP BY ?label"""
    df = run_sparql_dropdown(q)
    if df.empty:
        return {}
    return {str(r.get("label", "")): int(r.get("n", 0) or 0)
            for _, r in df.iterrows() if r.get("label")}


def place_counts_for_word(word: str, top_n: int = 15, max_hits: int = 1500) -> dict[str, int]:
    """Place-label → segment-count, capped to top_n places by hit count."""
    iris = _word_seg_iris(word, max_hits)
    if not iris:
        return {}
    q = VOICES_PREFIXES + f"""
SELECT ?label (COUNT(DISTINCT ?seg) AS ?n) WHERE {{
  VALUES ?seg {{ {_values_block(iris)} }}
  GRAPH <{G_EVENTS}> {{
    ?seg voices:segmentRefersToEvent ?ev .
    ?ev voices:hasLocation ?p .
    ?p rdfs:label ?label .
  }}
}} GROUP BY ?label ORDER BY DESC(?n) LIMIT {top_n}"""
    df = run_sparql_dropdown(q)
    if df.empty:
        return {}
    return {str(r.get("label", "")): int(r.get("n", 0) or 0)
            for _, r in df.iterrows() if r.get("label")}


def period_emotion_counts_for_activity(activity_label: str) -> list[dict]:
    """Per-period × emotion-category counts for one activity (cache lookup)."""
    out: list[dict] = []
    for r in load_sankey_flow():
        if r.get("activity") == activity_label:
            out.append({
                "period":   r.get("period"),
                "category": r.get("category"),
                "count":    int(r.get("count", 0) or 0),
            })
    return out


def load_historical_events() -> list[dict]:
    data = _read_json("historical_events.json")
    if data:
        return data
    _warn_missing("historical_events.json")
    if not fuseki_available():
        return []
    sparql = VOICES_PREFIXES + f"""
SELECT ?label WHERE {{
  GRAPH <{G_EVENTS}> {{
    ?h a voices:HistoricalEvent ; rdfs:label ?label .
  }}
}} ORDER BY ?label"""
    df = run_sparql_dropdown(sparql)
    return df.to_dict("records") if not df.empty else []


def as_label_list(records: list[dict], key: str = "label") -> list[str]:
    """Flatten a list of {label, count} dicts into a sorted label list."""
    if not records:
        return []
    seen: list[str] = []
    out: list[str] = []
    for r in records:
        v = r.get(key)
        if v is None:
            continue
        s = str(v)
        if s and s not in seen:
            seen.append(s)
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# Per-interview details (always live — too granular to precompute all)
# ---------------------------------------------------------------------------
def load_interview_detail(interview_iri: str) -> dict:
    """Return {metadata, events, emotions, places} for a single interview."""
    if not fuseki_available():
        return {"metadata": {}, "events": pd.DataFrame(), "emotions": pd.DataFrame(), "places": pd.DataFrame()}
    safe_iri = interview_iri.replace(">", "")
    meta_q = VOICES_PREFIXES + f"""
SELECT ?label ?year ?gender WHERE {{
  GRAPH <{G_META}> {{
    <{safe_iri}> rdfs:label ?label .
    OPTIONAL {{ <{safe_iri}> voices:recordingYear ?year . }}
    OPTIONAL {{ <{safe_iri}> voices:gender ?gender . }}
  }}
}} LIMIT 1"""
    events_q = VOICES_PREFIXES + f"""
SELECT ?event ?what ?where ?when ?activity ?emotion ?valence ?start WHERE {{
  GRAPH <{G_TRANS}> {{ <{safe_iri}> voices:hasSegment ?seg . }}
  GRAPH <{G_EVENTS}> {{
    ?seg voices:segmentRefersToEvent ?event .
    OPTIONAL {{ ?event voices:whatText ?what . }}
    OPTIONAL {{ ?event voices:hasLocation ?p . ?p rdfs:label ?where . }}
    OPTIONAL {{ ?event voices:whenText ?when . }}
    OPTIONAL {{ ?event voices:hasActivity ?a . ?a rdfs:label ?activity . }}
    OPTIONAL {{ ?seg voices:startTimestamp ?start . }}
  }}
  OPTIONAL {{
    GRAPH <{G_ANNOT}> {{
      ?event voices:hasEmotion ?emo .
      ?emo rdfs:label ?emotion .
      OPTIONAL {{ ?emo voices:hasValence ?valence . }}
    }}
  }}
}} ORDER BY ?start LIMIT 500"""
    meta_df = run_sparql(meta_q)
    events_df = run_sparql(events_q)
    metadata = meta_df.iloc[0].to_dict() if not meta_df.empty else {}
    emotions_df = pd.DataFrame()
    places_df = pd.DataFrame()
    if not events_df.empty:
        if "emotion" in events_df.columns:
            emotions_df = (
                events_df[events_df["emotion"].astype(str) != ""]
                .groupby("emotion")
                .size()
                .reset_index(name="count")
                .sort_values("count", ascending=False)
            )
        if "where" in events_df.columns:
            places_df = (
                events_df[events_df["where"].astype(str) != ""]
                .groupby("where")
                .size()
                .reset_index(name="count")
                .sort_values("count", ascending=False)
            )
    return {
        "metadata": metadata,
        "events": events_df,
        "emotions": emotions_df,
        "places": places_df,
    }
