#!/usr/bin/env python3
"""index_faiss.py — build a FAISS index over utterance embeddings.

Background
----------
In VOICES KG v2 the embedding *vectors themselves* do not live in RDF (they are
too bulky). The N-Quads file output/utterance_embeddings_v2.nq only records
the relation:

    <urn:voices:segment:{uid}> voices:hasTextEmbedding <urn:voices:utt_embedding:{uid}>
    <urn:voices:utt_embedding:{uid}> voices:embeddingModel "text-embedding-3-small"
    <urn:voices:utt_embedding:{uid}> voices:embeddingDim 1536

The actual 1536-dim float32 vectors sit in parquet sidecars at:

    data/processed/utterance_embeddings/openai/interview_{IntCode}_utterances_openai.parquet
    columns: utterance_id, interview_id, part_number, text, embedding

This script reads those parquet files, restricts them to the set of IRIs that
Fuseki actually exposes (so we don't index vectors for segments we dropped in
src/rebuild/filter.py), builds a FAISS index and dumps it alongside an id
manifest so the app can map FAISS row -> segment IRI.

Outputs
-------
  output/similarity.faiss        — FAISS index (IndexFlatIP; IVF if >100k).
  output/similarity.ids.json     — ordered list of segment IRIs matching index rows.

If the embeddings parquet directory does not exist the script prints a friendly
message and exits 0 (non-fatal — stack still works, just without similarity).

Environment
-----------
  FUSEKI_URL        default http://localhost:3032/voices
  EMBEDDINGS_DIR    default /mnt/d/Projets/voices/workspace/data/processed/utterance_embeddings/openai
  EMBEDDINGS_NQ     default <project>/output/utterance_embeddings_v2.nq
  OUTPUT_DIR        default <project>/output
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
from typing import Iterator


# ───────────────────────── paths & config ─────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent

DEFAULT_EMB_DIR = Path(os.environ.get(
    "EMBEDDINGS_DIR",
    "/mnt/d/Projets/voices/workspace/data/processed/utterance_embeddings/openai",
))
DEFAULT_NQ = Path(os.environ.get(
    "EMBEDDINGS_NQ",
    str(PROJECT_DIR / "output" / "utterance_embeddings_v2.nq"),
))
DEFAULT_OUT = Path(os.environ.get(
    "OUTPUT_DIR",
    str(PROJECT_DIR / "output"),
))
FUSEKI_URL = os.environ.get("FUSEKI_URL", "http://localhost:3032/voices")

SEGMENT_IRI_PREFIX = "urn:voices:segment:"


def log(msg: str) -> None:
    print(f"[index_faiss] {msg}", file=sys.stderr, flush=True)


# ───────────────────────── allowed-IRI discovery ─────────────────────────

def _iter_nq_subjects(path: Path) -> Iterator[str]:
    """Stream subject IRIs from an N-Quads file (no rdflib dependency)."""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith("<"):
                continue
            end = line.find(">")
            if end <= 1:
                continue
            yield line[1:end]


def load_allowed_ids(nq_path: Path | None, fuseki_url: str | None) -> set[str] | None:
    """Return the set of segment utterance_ids we should keep.

    Prefers scanning the local .nq file (fast, zero-http). Falls back to
    SPARQL. Returns None if neither source is available — in that case we
    index every vector we find.
    """
    if nq_path and nq_path.is_file():
        log(f"Scanning allowed ids from {nq_path} ...")
        ids: set[str] = set()
        for subj in _iter_nq_subjects(nq_path):
            if subj.startswith(SEGMENT_IRI_PREFIX):
                ids.add(subj[len(SEGMENT_IRI_PREFIX):])
        log(f"  found {len(ids):,} segment ids")
        return ids or None

    if fuseki_url:
        log(f"Querying allowed ids from {fuseki_url} ...")
        query = (
            "PREFIX voices: <http://voices.uni.lu/ontology#>\n"
            "SELECT ?seg WHERE {\n"
            "  GRAPH <urn:voices:graph:embeddings> { ?seg voices:hasTextEmbedding ?e }\n"
            "}"
        )
        try:
            data = urllib.parse.urlencode({"query": query}).encode("utf-8")
            req = urllib.request.Request(
                f"{fuseki_url}/sparql",
                data=data,
                headers={
                    "Accept": "application/sparql-results+json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.load(resp)
            ids = set()
            for row in payload.get("results", {}).get("bindings", []):
                iri = row.get("seg", {}).get("value", "")
                if iri.startswith(SEGMENT_IRI_PREFIX):
                    ids.add(iri[len(SEGMENT_IRI_PREFIX):])
            log(f"  got {len(ids):,} segment ids via SPARQL")
            return ids or None
        except Exception as exc:  # noqa: BLE001
            log(f"  SPARQL lookup failed: {exc}")

    return None


# ───────────────────────── vector streaming ─────────────────────────

def iter_vectors(emb_dir: Path, allowed: set[str] | None
                 ) -> Iterator[tuple[str, "np.ndarray"]]:
    import numpy as np  # local — optional dep
    import pandas as pd  # local — optional dep

    files = sorted(emb_dir.glob("interview_*_utterances_openai.parquet"))
    log(f"Found {len(files)} parquet files in {emb_dir}")
    for i, path in enumerate(files, 1):
        try:
            df = pd.read_parquet(path, columns=["utterance_id", "embedding"])
        except Exception as exc:  # noqa: BLE001
            log(f"  skip {path.name}: {exc}")
            continue
        for uid, vec in zip(df["utterance_id"].astype(str), df["embedding"]):
            if allowed is not None and uid not in allowed:
                continue
            arr = np.asarray(vec, dtype="float32")
            if arr.ndim != 1:
                continue
            yield uid, arr
        if i % 50 == 0 or i == len(files):
            log(f"  [{i}/{len(files)}] scanned")


# ───────────────────────── FAISS build ─────────────────────────

def build_index(emb_dir: Path, out_dir: Path, allowed: set[str] | None,
                force_ivf: bool = False) -> tuple[int, int]:
    import numpy as np  # noqa: F401  (used below)
    try:
        import faiss  # type: ignore[import-not-found]
    except ImportError:
        log("ERROR: faiss is not installed. Install faiss-cpu in the indexer image.")
        raise

    ids: list[str] = []
    vectors: list = []
    dim: int | None = None
    for uid, vec in iter_vectors(emb_dir, allowed):
        if dim is None:
            dim = int(vec.shape[0])
        elif vec.shape[0] != dim:
            log(f"  dimension mismatch for {uid}: {vec.shape[0]} != {dim}, skipping")
            continue
        ids.append(uid)
        vectors.append(vec)

    if not ids or dim is None:
        log("No vectors collected — nothing to index.")
        return 0, 0

    import numpy as np
    xb = np.vstack(vectors).astype("float32")
    # Normalise so inner-product == cosine.
    norms = np.linalg.norm(xb, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    xb = xb / norms

    log(f"Building FAISS index: n={len(ids):,} dim={dim}")
    use_ivf = force_ivf or len(ids) > 100_000
    if use_ivf:
        nlist = max(4, min(4096, int(len(ids) ** 0.5)))
        quant = faiss.IndexFlatIP(dim)
        index = faiss.IndexIVFFlat(quant, dim, nlist, faiss.METRIC_INNER_PRODUCT)
        log(f"  training IVF with nlist={nlist}")
        index.train(xb)
        index.add(xb)
        index.nprobe = min(32, nlist)
    else:
        index = faiss.IndexFlatIP(dim)
        index.add(xb)

    out_dir.mkdir(parents=True, exist_ok=True)
    idx_path = out_dir / "similarity.faiss"
    ids_path = out_dir / "similarity.ids.json"
    faiss.write_index(index, str(idx_path))
    ids_path.write_text(json.dumps({
        "dim": dim,
        "count": len(ids),
        "metric": "inner_product_normalized",
        "kind": "ivf" if use_ivf else "flat",
        "ids": ids,
    }))
    log(f"Wrote {idx_path} ({idx_path.stat().st_size/1e6:.1f} MB)")
    log(f"Wrote {ids_path}")
    return len(ids), dim


# ───────────────────────── main ─────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--embeddings-dir", type=Path, default=DEFAULT_EMB_DIR,
                        help="parquet directory with utterance embeddings (default: %(default)s)")
    parser.add_argument("--embeddings-nq", type=Path, default=DEFAULT_NQ,
                        help="N-Quads file used to derive allowed ids (default: %(default)s)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT,
                        help="where to write similarity.faiss + .ids.json (default: %(default)s)")
    parser.add_argument("--ivf", action="store_true",
                        help="force IVF index even for small corpora (useful for tests)")
    parser.add_argument("--no-filter", action="store_true",
                        help="skip allowed-ids filtering, index every vector found")
    args = parser.parse_args(argv)

    try:
        if not args.embeddings_dir.is_dir():
            log(f"Embeddings directory not found: {args.embeddings_dir}")
            log("Skipping FAISS build (non-fatal). Run scripts/embed_utterances.py first "
                "if you want semantic similarity.")
            return 0

        allowed = None if args.no_filter else load_allowed_ids(
            args.embeddings_nq if args.embeddings_nq.is_file() else None,
            FUSEKI_URL,
        )

        t0 = time.time()
        n, dim = build_index(args.embeddings_dir, args.output_dir, allowed, force_ivf=args.ivf)
        log(f"Done in {time.time()-t0:.1f}s. n={n} dim={dim}")
        print(json.dumps({"count": n, "dim": dim,
                          "index": str(args.output_dir / "similarity.faiss")}))
        return 0
    except KeyboardInterrupt:
        log("Interrupted.")
        return 130
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
