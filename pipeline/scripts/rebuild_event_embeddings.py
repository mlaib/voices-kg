"""Rebuild per-interview event embeddings for events_v7.parquet using OpenAI.

Format matches existing data/processed/event_embeddings/openai/ layout:
  interview_{IntCode}_embeddings_openai.parquet
  columns: utterance_id, utterance_hash, combined_text, embedding  (1536-dim)

combined_text = f"{who} | {what}"

Resumable: skips interviews whose output parquet already exists.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

WS = Path(os.environ.get("VOICES_WS", "."))
EVENTS = WS / "data/processed/events_v7.parquet"
OUT_DIR = WS / "data/processed/event_embeddings/openai"

MODEL = "text-embedding-3-small"
BATCH_SIZE = 512
MAX_RETRIES = 5


def embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.embeddings.create(model=MODEL, input=texts)
            return [d.embedding for d in resp.data]
        except Exception as e:  # noqa: BLE001
            wait = 2 ** attempt
            print(f"    retry {attempt+1}/{MAX_RETRIES} in {wait}s ({e})", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries")


def _clean(s) -> str:
    if s is None:
        return ""
    s = str(s).strip()
    return s if s else ""


def main() -> int:
    load_dotenv(WS / ".env")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        return 1

    client = OpenAI(api_key=api_key)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading {EVENTS}")
    events = pd.read_parquet(EVENTS)
    events["_uid_int"] = events["utterance_id"].str.split("_").str[1].astype(int)
    events = events.sort_values(["interview_id", "_uid_int"]).reset_index(drop=True)
    events["combined_text"] = (
        events["who"].map(_clean) + " | " + events["what"].map(_clean)
    )
    print(f"  {len(events):,} events across {events['interview_id'].nunique()} interviews")

    grouped = events.groupby("interview_id", sort=True)
    total = len(grouped)
    total_events = 0
    t0 = time.time()

    for i, (iv_id, g) in enumerate(grouped, 1):
        out_path = OUT_DIR / f"interview_{iv_id}_embeddings_openai.parquet"
        if out_path.exists():
            continue

        texts = g["combined_text"].tolist()
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            chunk = texts[start : start + BATCH_SIZE]
            embeddings.extend(embed_batch(client, chunk))

        df_out = pd.DataFrame({
            "utterance_id": g["utterance_id"].values,
            "utterance_hash": g["utterance_hash"].values,
            "combined_text": texts,
            "embedding": [np.asarray(e, dtype=np.float32) for e in embeddings],
        })
        df_out.to_parquet(out_path, index=False)
        total_events += len(texts)

        if i % 20 == 0 or i == total:
            dt = time.time() - t0
            rate = total_events / dt if dt else 0
            print(f"  [{i:4d}/{total}] iv={iv_id} ev={len(texts):4d} "
                  f"total={total_events:,} rate={rate:.0f} ev/s", flush=True)

    print(f"\nDone. {total_events:,} events embedded in {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
