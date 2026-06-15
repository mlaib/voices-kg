#!/usr/bin/env python3
"""compute_recall.py — dimension-presence recall of the extraction pipeline.

Recall here is deliberately simple and honest (a pilot metric, not a full
study): for a set of utterances an annotator marks, per utterance, which of
the five dimensions are ACTUALLY PRESENT in the source text (gold). Recall for
a dimension = fraction of utterances where the dimension is gold-present AND
the pipeline produced a non-empty value for it.

Inputs (CSV, one row per utterance, keyed by segment_iri):
  gold.csv      columns: segment_iri, gold_participants, gold_activity,
                gold_location, gold_temporal, gold_emotion   (1 = present, 0/blank = absent)
  pipeline.csv  columns: segment_iri, participants, activity, location,
                temporal, emotion   (non-empty = the pipeline produced a value)

Usage:
    python compute_recall.py gold.csv pipeline.csv
"""
from __future__ import annotations

import csv
import sys

DIMENSIONS = ["participants", "activity", "location", "temporal", "emotion"]


def _load(path: str) -> dict[str, dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        return {r["segment_iri"]: r for r in csv.DictReader(f)}


def _present(v: str) -> bool:
    return bool((v or "").strip()) and (v or "").strip().lower() not in ("0", "no", "none", "not stated")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python compute_recall.py gold.csv pipeline.csv", file=sys.stderr)
        return 2
    gold, pipe = _load(argv[1]), _load(argv[2])
    seg_ids = [s for s in gold if s in pipe]
    print(f"Utterances with gold + pipeline: {len(seg_ids)}\n")
    print("Per-dimension recall (gold-present dimensions recovered by the pipeline):\n")
    recalls = []
    for d in DIMENSIONS:
        present = recovered = 0
        for s in seg_ids:
            if _present(gold[s].get(f"gold_{d}", "")):
                present += 1
                if _present(pipe[s].get(d, "")):
                    recovered += 1
        r = (recovered / present) if present else None
        recalls.append(r)
        rs = f"{r * 100:.1f}%" if r is not None else "N/A"
        print(f"  {d:14} {recovered}/{present:<4} {rs:>7}")
    valid = [r for r in recalls if r is not None]
    if valid:
        print(f"\nMacro-averaged recall: {sum(valid) / len(valid) * 100:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
