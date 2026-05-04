"""
extract_sample.py - draw a deterministic random sample of NarratedEvent
instances together with their source utterance text and all extracted
dimensions, ready for per-dimension manual evaluation.

The output is a CSV with one row per sampled event and one judgment
column per dimension (participants, activity, location, time, emotion).
A reviewer fills the judgment columns with `correct` / `incorrect` /
`unsure`; the precision-computing script then summarises per-dimension
precision.

Usage
-----
    python extract_sample.py \\
        --fuseki http://localhost:3032/voices \\
        --out-sample sample.csv \\
        --out-template judgments.csv \\
        --total 100 \\
        --seed 20260504
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import urllib.parse
import urllib.request
from pathlib import Path


SPARQL_ALL_EVENTS = """
PREFIX voices: <http://voices.uni.lu/ontology#>
PREFIX rdfs:   <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?ev ?seg ?text WHERE {
  GRAPH <urn:voices:graph:events> {
    ?ev a voices:NarratedEvent .
    ?seg voices:segmentRefersToEvent ?ev .
  }
  OPTIONAL {
    GRAPH <urn:voices:graph:transcripts> { ?seg voices:transcriptText ?text }
  }
}
"""

SPARQL_EVENT_DIMENSIONS = """
PREFIX voices: <http://voices.uni.lu/ontology#>
PREFIX rdfs:   <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?ev (GROUP_CONCAT(DISTINCT ?p_label; separator="|") AS ?participants)
           (GROUP_CONCAT(DISTINCT ?act_label; separator="|") AS ?activities)
           (GROUP_CONCAT(DISTINCT ?loc_label; separator="|") AS ?locations)
           (GROUP_CONCAT(DISTINCT ?cause_label; separator="|") AS ?causes)
           (GROUP_CONCAT(DISTINCT ?mode_label; separator="|") AS ?modes)
           (GROUP_CONCAT(DISTINCT ?when_text; separator="|") AS ?temporal)
           (GROUP_CONCAT(DISTINCT ?emotion_cat; separator="|") AS ?emotions)
           (GROUP_CONCAT(DISTINCT ?hist_label; separator="|") AS ?historical)
WHERE {
  VALUES ?ev { %s }
  GRAPH <urn:voices:graph:events> {
    OPTIONAL { ?ev voices:hasParticipant ?p .
               OPTIONAL { GRAPH <urn:voices:graph:metadata> { ?p rdfs:label ?p_label_lit } }
               BIND(COALESCE(?p_label_lit, REPLACE(STR(?p), ".*[/:]", "")) AS ?p_label) }
    OPTIONAL { ?ev voices:hasActivity ?act .
               OPTIONAL { ?act rdfs:label ?act_label_lit }
               BIND(COALESCE(?act_label_lit, REPLACE(STR(?act), ".*[/:]", "")) AS ?act_label) }
    OPTIONAL { ?ev voices:hasLocation ?loc .
               OPTIONAL { GRAPH <urn:voices:graph:metadata> { ?loc rdfs:label ?loc_label_lit } }
               BIND(COALESCE(?loc_label_lit, REPLACE(STR(?loc), ".*[/:]", "")) AS ?loc_label) }
    OPTIONAL { ?ev voices:hasCause ?cause .
               OPTIONAL { ?cause rdfs:label ?cause_label_lit }
               BIND(COALESCE(?cause_label_lit, REPLACE(STR(?cause), ".*[/:]", "")) AS ?cause_label) }
    OPTIONAL { ?ev voices:hasMode ?mode .
               OPTIONAL { ?mode rdfs:label ?mode_label_lit }
               BIND(COALESCE(?mode_label_lit, REPLACE(STR(?mode), ".*[/:]", "")) AS ?mode_label) }
    OPTIONAL { ?ev voices:whenText ?when_text }
    OPTIONAL { ?ev voices:alignsWithHistoricalEvent ?hist .
               OPTIONAL { ?hist rdfs:label ?hist_label_lit }
               BIND(COALESCE(?hist_label_lit, REPLACE(STR(?hist), ".*[/:]", "")) AS ?hist_label) }
  }
  OPTIONAL {
    GRAPH <urn:voices:graph:annotations> {
      ?ev voices:hasEmotion ?em . ?em voices:emotionCategory ?emotion_cat .
    }
  }
} GROUP BY ?ev
"""


def sparql_select(fuseki_url: str, query: str) -> list[dict]:
    sparql = f"{fuseki_url.rstrip('/')}/sparql"
    data = urllib.parse.urlencode({"query": query}).encode()
    req = urllib.request.Request(
        sparql, data=data,
        headers={"Accept": "application/sparql-results+json",
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.load(resp)["results"]["bindings"]


def fetch_all_events(fuseki_url: str) -> list[dict]:
    rows = sparql_select(fuseki_url, SPARQL_ALL_EVENTS)
    out = []
    for r in rows:
        out.append({
            "event_iri": r["ev"]["value"],
            "segment_iri": r["seg"]["value"],
            "segment_text": r.get("text", {}).get("value", ""),
        })
    return out


def fetch_event_dimensions(fuseki_url: str, event_iris: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    BATCH = 25
    for i in range(0, len(event_iris), BATCH):
        chunk = event_iris[i:i + BATCH]
        values = " ".join(f"<{e}>" for e in chunk)
        q = SPARQL_EVENT_DIMENSIONS % values
        rows = sparql_select(fuseki_url, q)
        for r in rows:
            out[r["ev"]["value"]] = {
                "participants": r.get("participants", {}).get("value", ""),
                "activities":   r.get("activities", {}).get("value", ""),
                "locations":    r.get("locations", {}).get("value", ""),
                "causes":       r.get("causes", {}).get("value", ""),
                "modes":        r.get("modes", {}).get("value", ""),
                "temporal":     r.get("temporal", {}).get("value", ""),
                "emotions":     r.get("emotions", {}).get("value", ""),
                "historical":   r.get("historical", {}).get("value", ""),
            }
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fuseki", default="http://localhost:3032/voices")
    p.add_argument("--out-sample", type=Path, default=Path("sample.csv"))
    p.add_argument("--out-template", type=Path, default=Path("judgments.csv"))
    p.add_argument("--total", type=int, default=100)
    p.add_argument("--seed", type=int, default=20260504)
    args = p.parse_args(argv)

    print(f"[extract] Fetching all events from {args.fuseki} ...", file=sys.stderr)
    all_events = fetch_all_events(args.fuseki)
    print(f"[extract]   got {len(all_events):,} events.", file=sys.stderr)

    rng = random.Random(args.seed)
    pool = sorted(all_events, key=lambda r: r["event_iri"])
    sample = rng.sample(pool, k=min(args.total, len(pool)))
    sample.sort(key=lambda r: r["event_iri"])
    print(f"[extract] Sampled {len(sample)} events (seed={args.seed}).", file=sys.stderr)

    print("[extract] Fetching dimensions for sampled events ...", file=sys.stderr)
    dim_map = fetch_event_dimensions(args.fuseki, [r["event_iri"] for r in sample])
    print(f"[extract]   resolved dimensions for {len(dim_map)} events.", file=sys.stderr)

    sample_fields = ["event_iri", "segment_iri", "segment_text",
                     "participants", "activities", "locations",
                     "causes", "modes", "temporal", "emotions", "historical"]
    judgment_fields = sample_fields + [
        "judgment_participants", "judgment_activity", "judgment_location",
        "judgment_temporal", "judgment_emotion", "notes",
    ]

    with args.out_sample.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=sample_fields)
        w.writeheader()
        for r in sample:
            d = dim_map.get(r["event_iri"], {})
            w.writerow({**r, **d})

    with args.out_template.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=judgment_fields)
        w.writeheader()
        for r in sample:
            d = dim_map.get(r["event_iri"], {})
            row = {**r, **d}
            for jf in ("judgment_participants", "judgment_activity",
                       "judgment_location", "judgment_temporal",
                       "judgment_emotion", "notes"):
                row[jf] = ""
            w.writerow(row)

    print(f"[extract] Wrote {args.out_sample} and {args.out_template}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
