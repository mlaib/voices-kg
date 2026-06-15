"""Materialise utterance-level embedding triples into a separate N-Quads file.

Reads:
  data/processed/utterance_embeddings/openai/interview_*_utterances_openai.parquet

Emits (graph urn:voices:graph:embeddings):
  <urn:voices:segment:{uid}> voices:hasTextEmbedding <urn:voices:utt_embedding:{uid}>
  <urn:voices:utt_embedding:{uid}> a voices:UtteranceEmbedding
  <urn:voices:utt_embedding:{uid}> voices:embeddingModel "text-embedding-3-small"
  <urn:voices:utt_embedding:{uid}> voices:embeddingDim 1536

Vectors themselves stay in the parquet sidecar files (too bulky for N-Quads).
Output: KG2026.paper/output/utterance_embeddings.nq (load alongside kg2026_paper.nq).
"""
from __future__ import annotations
import os

import sys
import time
from pathlib import Path

import pandas as pd

WS = Path(os.environ.get("VOICES_WS", "."))
EMB_DIR = WS / "data/processed/utterance_embeddings/openai"
OUT_NQ = WS / "KG2026.paper/output/utterance_embeddings.nq"

VOICES = "http://voices.uni.lu/ontology#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
XSD_INT = "http://www.w3.org/2001/XMLSchema#integer"
G_EMBED = "urn:voices:graph:embeddings"

MODEL = "text-embedding-3-small"
DIM = 1536


def _iri(s: str) -> str:
    return f"<{s}>"


def _lit(value: str, datatype: str | None = None) -> str:
    esc = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    if datatype:
        return f'"{esc}"^^<{datatype}>'
    return f'"{esc}"'


def main() -> int:
    OUT_NQ.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(EMB_DIR.glob("interview_*_utterances_openai.parquet"))
    if not files:
        print(f"ERROR: no parquet files in {EMB_DIR}", file=sys.stderr)
        return 1
    print(f"Found {len(files)} interview embedding files")

    has_emb = _iri(f"{VOICES}hasTextEmbedding")
    rdf_type = _iri(RDF_TYPE)
    cls = _iri(f"{VOICES}UtteranceEmbedding")
    p_model = _iri(f"{VOICES}embeddingModel")
    p_dim = _iri(f"{VOICES}embeddingDim")
    g = _iri(G_EMBED)
    model_lit = _lit(MODEL)
    dim_lit = _lit(str(DIM), datatype=XSD_INT)

    total = 0
    t0 = time.time()
    with OUT_NQ.open("w", encoding="utf-8") as out:
        for i, f in enumerate(files, 1):
            df = pd.read_parquet(f, columns=["utterance_id"])
            for uid in df["utterance_id"].astype(str):
                seg = _iri(f"urn:voices:segment:{uid}")
                emb = _iri(f"urn:voices:utt_embedding:{uid}")
                out.write(f"{seg} {has_emb} {emb} {g} .\n")
                out.write(f"{emb} {rdf_type} {cls} {g} .\n")
                out.write(f"{emb} {p_model} {model_lit} {g} .\n")
                out.write(f"{emb} {p_dim} {dim_lit} {g} .\n")
                total += 4
            if i % 100 == 0 or i == len(files):
                print(f"  [{i:4d}/{len(files)}] quads={total:,}", flush=True)

    dt = time.time() - t0
    print(f"\nWrote {total:,} quads in {dt:.1f}s → {OUT_NQ}")
    print(f"  size: {OUT_NQ.stat().st_size / (1024*1024):.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
