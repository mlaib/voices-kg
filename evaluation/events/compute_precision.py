"""
compute_precision.py - read a filled-in judgments.csv and print
per-dimension precision for the event-extraction quality evaluation.

Each row in judgments.csv has up to five judgment columns, one per
extracted dimension:

    judgment_participants
    judgment_activity
    judgment_location
    judgment_temporal
    judgment_emotion

Each cell holds one of:

    correct | incorrect | unsure | <blank>

Empty cells are treated as "not yet reviewed" and reported separately.
Per-dimension precision excludes unsure and blank rows.

Usage:
    python compute_precision.py [judgments.csv]

Default path is `judgments.csv` in the current working directory.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path


VALID = {"correct", "incorrect", "unsure"}
DIMENSIONS = ["participants", "activity", "location", "temporal", "emotion"]


def normalise(s: str) -> str:
    return (s or "").strip().lower()


def main(argv: list[str]) -> int:
    in_path = Path(argv[1]) if len(argv) > 1 else Path("judgments.csv")
    if not in_path.exists():
        print(f"ERROR: file not found: {in_path}", file=sys.stderr)
        return 2

    rows = list(csv.DictReader(in_path.open(encoding="utf-8")))
    print(f"Sample size:   {len(rows)} events\n")

    summary = {}
    for d in DIMENSIONS:
        col = f"judgment_{d}"
        c = Counter(normalise(r.get(col, "")) for r in rows)
        decided = c["correct"] + c["incorrect"]
        summary[d] = {
            "correct":   c["correct"],
            "incorrect": c["incorrect"],
            "unsure":    c["unsure"],
            "blank":     c[""],
            "decided":   decided,
            "precision": (c["correct"] / decided * 100.0) if decided else None,
        }

    fmt = "{dim:14}  {correct:>4}/{decided:<4}  {prec:>6}  unsure={unsure:<3}  blank={blank}"
    print("Per-dimension precision (correct / (correct+incorrect)):\n")
    for d in DIMENSIONS:
        s = summary[d]
        prec = f"{s['precision']:.1f}%" if s["precision"] is not None else "N/A"
        print(fmt.format(dim=d, correct=s["correct"], decided=s["decided"],
                         prec=prec, unsure=s["unsure"], blank=s["blank"]))

    # Overall precision macro-averaged across dimensions where any decisions exist.
    valid_precs = [s["precision"] for s in summary.values() if s["precision"] is not None]
    if valid_precs:
        macro = sum(valid_precs) / len(valid_precs)
        print(f"\nMacro-averaged precision across dimensions: {macro:.1f}%")

    total_blank = sum(s["blank"] for s in summary.values())
    total_cells = len(rows) * len(DIMENSIONS)
    if total_blank > total_cells * 0.10:
        print(f"\nWARN: {total_blank}/{total_cells} judgment cells still blank "
              f"({total_blank / total_cells * 100:.1f}%). Review is incomplete.",
              file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
