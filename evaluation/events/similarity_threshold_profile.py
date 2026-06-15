#!/usr/bin/env python3
"""similarity_threshold_profile.py — characterise the intra-interview
cosine-similarity distribution and locate the `similarTo` threshold within it.

This produces the post-hoc justification for the 0.82 cut-off quoted in the
paper (Section 4.4): the percentile at which 0.82 sits and the fraction of
intra-interview event pairs it retains. It does NOT claim the threshold was
tuned; it describes the threshold's selectivity on the corpus.

Input: per-interview event-embedding parquet files (one interview per file),
each with a 1536-d `embedding` column. These are gated (derived from VHA
transcripts) and are not shipped here — point --embeddings-dir at your copy.

Usage:
    python similarity_threshold_profile.py \
        --embeddings-dir /path/to/event_embeddings/openai \
        --threshold 0.82 --sample 40
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--embeddings-dir", type=Path,
                    default=Path(os.environ.get("EMBEDDINGS_DIR", "data/processed/event_embeddings/openai")))
    ap.add_argument("--pattern", default="interview_*_embeddings_openai.parquet")
    ap.add_argument("--threshold", type=float, default=0.82)
    ap.add_argument("--sample", type=int, default=40, help="number of interviews to profile (0 = all)")
    args = ap.parse_args()

    files = sorted(glob.glob(str(args.embeddings_dir / args.pattern)))
    if not files:
        print(f"No embedding parquet files under {args.embeddings_dir}", file=sys.stderr)
        return 2
    if args.sample:
        files = files[: args.sample]

    scores, n_events = [], 0
    for f in files:
        X = np.vstack(pd.read_parquet(f, columns=["embedding"])["embedding"].values).astype("float32")
        n = len(X)
        n_events += n
        if n < 2:
            continue
        X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
        S = X @ X.T
        scores.append(S[np.triu_indices(n, k=1)])

    s = np.concatenate(scores)
    print(f"interviews profiled: {len(files)} | events: {n_events:,} | intra-interview pairs: {len(s):,}")
    print(f"mean={s.mean():.3f}  median={np.median(s):.3f}")
    for p in (50, 75, 90, 95, 99):
        print(f"  {p}th percentile cosine = {np.percentile(s, p):.3f}")
    pct = 100.0 * (s < args.threshold).mean()
    frac = 100.0 * (s >= args.threshold).mean()
    print(f"threshold {args.threshold}: {pct:.1f}th percentile; retains {frac:.2f}% of intra-interview pairs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
