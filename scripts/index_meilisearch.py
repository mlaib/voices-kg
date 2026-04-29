#!/usr/bin/env python3
"""index_meilisearch.py — feed transcript segments into Meilisearch.

Source
------
Queries Fuseki ($FUSEKI_URL) for every segment carrying a voices:transcriptText,
optionally joined with its parent interview + survivor label.

Target
------
Meilisearch index ``voices-segments`` at $MEILISEARCH_URL. The index is
created on first run with:
  primary key       = id
  searchable attrs  = [text, survivor]
  filterable attrs  = [interview_id, survivor]
  sortable attrs    = [start_ms]

Document schema
---------------
  { "id": sha1(iri)[:24],
    "iri": "<urn:voices:segment:...>",
    "interview_id": "<iri>",
    "survivor": "Erika Jacoby",
    "text": "...",
    "start_ms": 12340,
    "end_ms": 19570 }

Running
-------
Meilisearch in the v2 stack is not exposed to the host. Either:
  (a) run this script inside the Docker network, e.g.
        docker compose exec admin python /app/scripts/index_meilisearch.py
  (b) temporarily expose port 7700 on the meilisearch service.

Environment
-----------
  FUSEKI_URL       default http://localhost:3032/voices
  MEILISEARCH_URL  default http://localhost:7700   (host-unreachable in stack)
  MEILISEARCH_KEY  required — set via environment or .env
  BATCH_SIZE       default 1000
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable, Iterator


# ───────────────────────── config ─────────────────────────

FUSEKI_URL = os.environ.get("FUSEKI_URL", "http://localhost:3032/voices")
MEILI_URL = os.environ.get("MEILISEARCH_URL", "http://localhost:7700").rstrip("/")
MEILI_KEY = os.environ.get("MEILISEARCH_KEY") or ""
INDEX_NAME = os.environ.get("MEILI_INDEX", "voices-segments")
DEFAULT_BATCH = int(os.environ.get("BATCH_SIZE", "1000"))

TRANSCRIPT_GRAPH = "urn:voices:graph:transcripts"
METADATA_GRAPH = "urn:voices:graph:metadata"
VOICES_NS = "http://voices.uni.lu/ontology#"

SPARQL_SEGMENTS = f"""
PREFIX voices: <{VOICES_NS}>
PREFIX rdfs:   <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?seg ?text ?interview ?survivor ?start ?end
WHERE {{
  GRAPH <{TRANSCRIPT_GRAPH}> {{
    ?seg voices:transcriptText ?text .
    OPTIONAL {{ ?seg voices:startTimeMs ?start . }}
    OPTIONAL {{ ?seg voices:endTimeMs   ?end . }}
  }}
  OPTIONAL {{ GRAPH <{TRANSCRIPT_GRAPH}> {{ ?interview voices:hasSegment ?seg . }} }}
  OPTIONAL {{ GRAPH <{METADATA_GRAPH}>   {{ ?interview rdfs:label ?survivor . }} }}
}}
"""


def log(msg: str) -> None:
    print(f"[index_meilisearch] {msg}", file=sys.stderr, flush=True)


# ───────────────────────── HTTP helpers ─────────────────────────

def _request(method: str, url: str, *, data: bytes | None = None,
             headers: dict[str, str] | None = None, timeout: float = 120.0
             ) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def meili_request(method: str, path: str, payload: Any | None = None) -> tuple[int, Any]:
    url = f"{MEILI_URL}{path}"
    body = None
    headers = {"Authorization": f"Bearer {MEILI_KEY}"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    status, raw = _request(method, url, data=body, headers=headers)
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        parsed = raw.decode("utf-8", errors="replace")
    return status, parsed


# ───────────────────────── SPARQL streaming ─────────────────────────

def sparql_select(query: str) -> list[dict[str, Any]]:
    data = urllib.parse.urlencode({"query": query}).encode("utf-8")
    headers = {
        "Accept": "application/sparql-results+json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    status, raw = _request("POST", f"{FUSEKI_URL}/sparql",
                           data=data, headers=headers, timeout=600.0)
    if status != 200:
        raise RuntimeError(f"SPARQL query failed ({status}): {raw[:500]!r}")
    payload = json.loads(raw)
    return payload.get("results", {}).get("bindings", [])


def _binding_val(row: dict[str, Any], key: str, default: Any = None) -> Any:
    node = row.get(key)
    if not node:
        return default
    return node.get("value", default)


def stream_segments() -> Iterator[dict[str, Any]]:
    log(f"Querying Fuseki at {FUSEKI_URL} ...")
    rows = sparql_select(SPARQL_SEGMENTS)
    log(f"  got {len(rows):,} binding rows")
    for row in rows:
        iri = _binding_val(row, "seg")
        text = _binding_val(row, "text")
        if not iri or not text:
            continue
        doc_id = hashlib.sha1(iri.encode("utf-8")).hexdigest()[:24]
        start_raw = _binding_val(row, "start")
        end_raw = _binding_val(row, "end")
        try:
            start_ms = int(float(start_raw)) if start_raw is not None else None
        except (TypeError, ValueError):
            start_ms = None
        try:
            end_ms = int(float(end_raw)) if end_raw is not None else None
        except (TypeError, ValueError):
            end_ms = None

        doc = {
            "id": doc_id,
            "iri": iri,
            "text": text,
            "interview_id": _binding_val(row, "interview"),
            "survivor": _binding_val(row, "survivor"),
            "start_ms": start_ms,
            "end_ms": end_ms,
        }
        yield doc


# ───────────────────────── Meilisearch bootstrap ─────────────────────────

def ensure_index() -> None:
    log(f"Ensuring index '{INDEX_NAME}' ...")
    status, body = meili_request("GET", f"/indexes/{INDEX_NAME}")
    if status == 404:
        log("  index missing, creating ...")
        status, body = meili_request("POST", "/indexes",
                                     {"uid": INDEX_NAME, "primaryKey": "id"})
        if status >= 300:
            raise RuntimeError(f"Failed to create index: {status} {body!r}")
    elif status >= 300:
        raise RuntimeError(f"Failed to GET index: {status} {body!r}")

    settings = {
        "searchableAttributes": ["text", "survivor"],
        "filterableAttributes": ["interview_id", "survivor"],
        "sortableAttributes": ["start_ms"],
    }
    status, body = meili_request("PATCH", f"/indexes/{INDEX_NAME}/settings", settings)
    if status >= 300:
        raise RuntimeError(f"Failed to PATCH settings: {status} {body!r}")
    log("  index ready.")


def index_batches(docs: Iterable[dict[str, Any]], batch_size: int) -> int:
    buf: list[dict[str, Any]] = []
    total = 0
    last_log = time.time()
    for doc in docs:
        buf.append(doc)
        if len(buf) >= batch_size:
            _post_batch(buf)
            total += len(buf)
            buf = []
            if time.time() - last_log > 2.0:
                log(f"  indexed {total:,} docs ...")
                last_log = time.time()
    if buf:
        _post_batch(buf)
        total += len(buf)
    return total


def _post_batch(docs: list[dict[str, Any]]) -> None:
    status, body = meili_request("POST", f"/indexes/{INDEX_NAME}/documents", docs)
    if status >= 300:
        raise RuntimeError(f"Batch upload failed: {status} {body!r}")


# ───────────────────────── main ─────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH,
                        help="documents per Meilisearch POST (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true",
                        help="query Fuseki, count segments, do not write to Meilisearch")
    parser.add_argument("--limit", type=int, default=0,
                        help="only index N documents (0 = all) — useful for smoke tests")
    args = parser.parse_args(argv)

    try:
        docs_iter = stream_segments()
        if args.limit > 0:
            docs_iter = (d for i, d in enumerate(docs_iter) if i < args.limit)

        if args.dry_run:
            count = sum(1 for _ in docs_iter)
            print(json.dumps({"would_index": count}))
            return 0

        # Peek one doc to decide whether to bother creating the index
        first = next(docs_iter, None)
        if first is None:
            log("Fuseki returned 0 transcript segments — nothing to index. Skipping.")
            return 0

        def _chain(head: dict[str, Any], tail: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
            yield head
            yield from tail

        ensure_index()
        total = index_batches(_chain(first, docs_iter), args.batch_size)
        log(f"Done. Uploaded {total:,} documents to '{INDEX_NAME}'.")
        print(json.dumps({"indexed": total, "index": INDEX_NAME}))
        return 0
    except KeyboardInterrupt:
        log("Interrupted.")
        return 130
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
