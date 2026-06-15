#!/usr/bin/env python3
"""compute_iaa.py — inter-annotator agreement (Cohen's kappa) between two
filled judgment files, per dimension.

Each input is a judgments.csv (same row order / event_iri) with the five
judgment columns filled with correct | incorrect | unsure | <blank>.
For each dimension we compute Cohen's kappa over the events both annotators
labelled (non-blank in both), treating {correct, incorrect, unsure} as the
category set.

Usage:
    python compute_iaa.py judgments_A.csv judgments_B.csv
"""
from __future__ import annotations

import csv
import sys
from collections import Counter

DIMENSIONS = ["participants", "activity", "location", "temporal", "emotion"]
CATS = ["correct", "incorrect", "unsure"]


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _load(path: str) -> dict[str, dict[str, str]]:
    rows = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows[r["event_iri"]] = r
    return rows


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """pairs: list of (label_A, label_B) over the category set CATS."""
    n = len(pairs)
    if n == 0:
        return None
    po = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in CATS)
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python compute_iaa.py judgments_A.csv judgments_B.csv", file=sys.stderr)
        return 2
    A, B = _load(argv[1]), _load(argv[2])
    common = [e for e in A if e in B]
    print(f"Shared events: {len(common)}\n")
    print("Per-dimension Cohen's kappa (events both annotators labelled):\n")
    kappas = []
    for d in DIMENSIONS:
        col = f"judgment_{d}"
        pairs = []
        for e in common:
            a, b = _norm(A[e].get(col, "")), _norm(B[e].get(col, ""))
            if a in CATS and b in CATS:
                pairs.append((a, b))
        k = cohen_kappa(pairs)
        kappas.append(k)
        ks = f"{k:.3f}" if k is not None else "N/A"
        print(f"  {d:14} kappa={ks:>6}  (n={len(pairs)})")
    valid = [k for k in kappas if k is not None]
    if valid:
        print(f"\nMean kappa across dimensions: {sum(valid) / len(valid):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
