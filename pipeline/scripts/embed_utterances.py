"""Embed utterance text from utterances.parquet using OpenAI text-embedding-3-small.

Output layout mirrors event embeddings:
  data/processed/utterance_embeddings/openai/interview_{IntCode}_utterances_openai.parquet
  columns: utterance_id, interview_id, part_number, text, embedding (1536-dim float32)

utterance_id format = f"{interview_id}_{global_row_index}" — matches events_v6/v7.
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
UTTERANCES = WS / "data/processed/utterances.parquet"
OUT_DIR = WS / "data/processed/utterance_embeddings/openai"

MODEL = "text-embedding-3-small"
BATCH_SIZE = 256
MAX_RETRIES = 5
PROGRESS_EVERY = 20  # interviews


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
    return s if s else " "  # never send empty string to OpenAI


def main() -> int:
    load_dotenv(WS / ".env", override=True)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        return 1

    client = OpenAI(api_key=api_key)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading {UTTERANCES}", flush=True)
    u = pd.read_parquet(UTTERANCES)
    # global row index is the utterance_id suffix, matches events_v6/v7
    u = u.reset_index().rename(columns={"index": "_row"})
    u["utterance_id"] = u["interview_id"].astype(str) + "_" + u["_row"].astype(str)
    print(f"  {len(u):,} utterances across {u['interview_id'].nunique()} interviews", flush=True)

    grouped = u.groupby("interview_id", sort=True)
    total_iv = len(grouped)
    total_done = 0
    t0 = time.time()

    for i, (iv_id, g) in enumerate(grouped, 1):
        out_path = OUT_DIR / f"interview_{iv_id}_utterances_openai.parquet"
        if out_path.exists():
            continue

        texts = [_clean(t) for t in g["text"].tolist()]
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            chunk = texts[start : start + BATCH_SIZE]
            embeddings.extend(embed_batch(client, chunk))

        df_out = pd.DataFrame({
            "utterance_id": g["utterance_id"].values,
            "interview_id": g["interview_id"].values,
            "part_number": g["part_number"].values,
            "text": texts,
            "embedding": [np.asarray(e, dtype=np.float32) for e in embeddings],
        })
        df_out.to_parquet(out_path, index=False)
        total_done += len(texts)

        if i % PROGRESS_EVERY == 0 or i == total_iv:
            dt = time.time() - t0
            rate = total_done / dt if dt else 0
            print(f"  [{i:4d}/{total_iv}] iv={iv_id} ut={len(texts):4d} "
                  f"total={total_done:,} rate={rate:.0f} ut/s", flush=True)

    print(f"\nDone. {total_done:,} utterances embedded in {time.time()-t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
