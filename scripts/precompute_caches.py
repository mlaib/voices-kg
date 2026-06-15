#!/usr/bin/env python3
"""precompute_caches.py — run once, materialise static JSON caches for the app.

Runs a small suite of SPARQL queries against Fuseki and writes their results
as JSON files into output/caches/. The Streamlit app reads these instead of
hammering Fuseki for every dropdown.

Outputs
-------
  output/caches/summary.json
  output/caches/activities.json
  output/caches/emotions.json
  output/caches/places.json
  output/caches/interviews.json
  output/caches/historical_events.json
  output/caches/periods.json

Environment
-----------
  FUSEKI_URL   default http://localhost:3032/voices
  CACHE_DIR    default <project>/output/caches

Usage
-----
  python scripts/precompute_caches.py          # all caches
  python scripts/precompute_caches.py --only summary places
  python scripts/precompute_caches.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent

FUSEKI_URL = os.environ.get("FUSEKI_URL", "http://localhost:3032/voices").rstrip("/")
DEFAULT_CACHE_DIR = Path(os.environ.get("CACHE_DIR", str(PROJECT_DIR / "output" / "caches")))

PREFIXES = """
PREFIX voices: <https://w3id.org/voices/ontology#>
PREFIX rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:   <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos:   <http://www.w3.org/2004/02/skos/core#>
"""


def log(msg: str) -> None:
    print(f"[precompute] {msg}", file=sys.stderr, flush=True)


# ───────────────────────── SPARQL helper ─────────────────────────

def sparql(query: str, *, timeout: float = 300.0) -> list[dict[str, Any]]:
    data = urllib.parse.urlencode({"query": PREFIXES + query}).encode("utf-8")
    req = urllib.request.Request(
        f"{FUSEKI_URL}/sparql",
        data=data,
        headers={
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    return payload.get("results", {}).get("bindings", [])


def val(row: dict[str, Any], key: str, default: Any = None) -> Any:
    node = row.get(key)
    if not node:
        return default
    return node.get("value", default)


def to_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


# ───────────────────────── cache builders ─────────────────────────

def build_summary() -> dict[str, int]:
    # Each sub-count is cheap individually; doing them separately is clearer
    # and sidesteps UNION+COUNT DISTINCT cross-talk that zeroed buckets in v2.
    def count_one(query: str) -> int:
        rows = sparql(query)
        return to_int(val(rows[0], "n")) if rows else 0

    interviews = count_one("SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE { GRAPH <urn:voices:graph:metadata> { ?x a voices:Interview } }")
    events     = count_one("SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE { GRAPH <urn:voices:graph:events> { ?x a voices:NarratedEvent } }")
    segments   = count_one("SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE { GRAPH <urn:voices:graph:transcripts> { ?x voices:transcriptText [] } }")
    activities = count_one("SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE { GRAPH <urn:voices:graph:events> { ?x a voices:Activity } }")
    emotions   = count_one("SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE { GRAPH <urn:voices:graph:annotations> { ?x a voices:EmotionAnnotation } }")
    places     = count_one("SELECT (COUNT(DISTINCT ?x) AS ?n) WHERE { GRAPH <urn:voices:graph:metadata> { ?x a voices:Place } }")
    row = {}  # unused — kept to minimise diff below
    quads_rows = sparql("SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } }")
    return {
        "interviews":  interviews,
        "events":      events,
        "segments":    segments,
        "activities":  activities,
        "emotions":    emotions,
        "places":      places,
        "quads":       to_int(val(quads_rows[0], "n")) if quads_rows else 0,
    }


def build_activities() -> list[dict[str, Any]]:
    # Activities are controlled-vocabulary terms (urn:voices:activity:*) in the
    # events graph. Count = number of narrated events tagged with each.
    Q = """
    SELECT ?label (COUNT(?ev) AS ?count)
    WHERE {
      GRAPH <urn:voices:graph:events> {
        ?ev voices:hasActivity ?act .
        ?act rdfs:label ?label .
      }
    }
    GROUP BY ?label
    ORDER BY DESC(?count)
    """
    return [{"label": val(r, "label"),
             "count": to_int(val(r, "count"))} for r in sparql(Q)]


def build_emotions() -> list[dict[str, Any]]:
    Q = """
    SELECT ?label (COUNT(?emo) AS ?count)
    WHERE {
      GRAPH <urn:voices:graph:annotations> {
        ?emo a voices:EmotionAnnotation ;
             rdfs:label ?label .
      }
    }
    GROUP BY ?label
    ORDER BY DESC(?count)
    """
    return [{"label": val(r, "label"),
             "count": to_int(val(r, "count"))} for r in sparql(Q)]


def build_places() -> list[dict[str, Any]]:
    Q = """
    SELECT ?place ?label (COUNT(?event) AS ?event_count) ?wikidata ?geonames
    WHERE {
      GRAPH <urn:voices:graph:events> {
        ?event voices:hasLocation ?place .
        ?place rdfs:label ?label .
      }
      OPTIONAL {
        GRAPH <urn:voices:graph:alignment> {
          ?place skos:exactMatch ?wikidata .
          FILTER(CONTAINS(STR(?wikidata), "wikidata.org"))
        }
      }
      OPTIONAL {
        GRAPH <urn:voices:graph:alignment> {
          ?place skos:exactMatch ?geonames .
          FILTER(CONTAINS(STR(?geonames), "geonames.org"))
        }
      }
    }
    GROUP BY ?place ?label ?wikidata ?geonames
    ORDER BY DESC(?event_count)
    LIMIT 500
    """
    return [{
        "iri": val(r, "place"),
        "label": val(r, "label"),
        "event_count": to_int(val(r, "event_count")),
        "wikidata": val(r, "wikidata"),
        "geonames": val(r, "geonames"),
    } for r in sparql(Q)]


def build_interviews() -> list[dict[str, Any]]:
    Q = """
    SELECT ?iv ?survivor ?id
    WHERE {
      GRAPH <urn:voices:graph:metadata> {
        ?iv a voices:Interview .
        OPTIONAL { ?iv rdfs:label ?survivor . }
        OPTIONAL { ?iv voices:interviewId ?id . }
      }
    }
    ORDER BY ?survivor
    """
    return [{
        "iri": val(r, "iv"),
        "survivor": val(r, "survivor"),
        "id": val(r, "id"),
    } for r in sparql(Q)]


def build_historical_events() -> list[dict[str, Any]]:
    Q = """
    SELECT ?label (COUNT(?event) AS ?count)
    WHERE {
      GRAPH <urn:voices:graph:events> {
        ?event voices:alignsWithHistoricalEvent ?he .
        ?he rdfs:label ?label .
      }
    }
    GROUP BY ?label
    ORDER BY DESC(?count)
    """
    return [{"label": val(r, "label"),
             "count": to_int(val(r, "count"))} for r in sparql(Q)]


def build_periods() -> list[dict[str, Any]]:
    Q = """
    SELECT ?period (COUNT(?event) AS ?count)
    WHERE {
      GRAPH <urn:voices:graph:events> {
        ?event voices:temporalBucket ?period .
      }
    }
    GROUP BY ?period
    ORDER BY ?period
    """
    return [{"period": val(r, "period"),
             "count": to_int(val(r, "count"))} for r in sparql(Q)]


def build_sankey_flow() -> list[dict[str, Any]]:
    # 3-column flow data for the home Sankey: period → activity → emotion
    # category. Bounded to 5*14*4 = 280 combinations, so a few KB of JSON.
    Q = """
    SELECT ?period ?activity ?category (COUNT(?ev) AS ?n) WHERE {
      GRAPH <urn:voices:graph:events> {
        ?ev voices:temporalBucket ?period .
        ?ev voices:hasActivity ?act . ?act rdfs:label ?activity .
      }
      GRAPH <urn:voices:graph:annotations> {
        ?ev voices:hasEmotion ?ann .
        ?ann voices:emotionCategory ?category .
      }
    }
    GROUP BY ?period ?activity ?category
    """
    return [{
        "period":   val(r, "period"),
        "activity": val(r, "activity"),
        "category": val(r, "category"),
        "count":    to_int(val(r, "n")),
    } for r in sparql(Q)]


BUILDERS: dict[str, Callable[[], Any]] = {
    "summary":           build_summary,
    "activities":        build_activities,
    "emotions":          build_emotions,
    "places":            build_places,
    "interviews":        build_interviews,
    "historical_events": build_historical_events,
    "periods":           build_periods,
    "sankey_flow":       build_sankey_flow,
}


# ───────────────────────── main ─────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR,
                        help="output directory (default: %(default)s)")
    parser.add_argument("--only", nargs="+", choices=sorted(BUILDERS.keys()),
                        help="build only these caches")
    parser.add_argument("--dry-run", action="store_true",
                        help="run queries but don't write files")
    args = parser.parse_args(argv)

    targets = args.only or sorted(BUILDERS.keys())
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    log(f"Fuseki: {FUSEKI_URL}")
    log(f"Targets: {', '.join(targets)}")

    results: dict[str, Any] = {}
    t0 = time.time()
    try:
        for name in targets:
            log(f"Building {name} ...")
            t = time.time()
            data = BUILDERS[name]()
            dt = time.time() - t
            size = len(data) if isinstance(data, list) else 1
            log(f"  {name}: {size} row(s) in {dt:.2f}s")
            results[name] = data
            if not args.dry_run:
                path = args.cache_dir / f"{name}.json"
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
                log(f"  wrote {path}")
    except KeyboardInterrupt:
        log("Interrupted.")
        return 130
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR while building {name!r}: {exc}")
        return 1

    log(f"Done in {time.time()-t0:.1f}s")
    print(json.dumps({"built": list(results.keys()),
                      "cache_dir": str(args.cache_dir)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
