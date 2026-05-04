"""
compute_precision.py — read a filled-in judgments.csv and print the
alignment precision summary that goes into Section 5.3 of the paper.

Usage
-----
    python compute_precision.py [judgments.csv]

Default path is `judgments.csv` in the current working directory.

Each row in the input must have a `judgment` value that is one of:

    correct | incorrect | unsure

Empty / blank judgments are reported separately (treated as "not yet
reviewed", not as wrong).

Output
------
A short text summary suitable for direct quotation in the paper:

    Total reviewed:     N out of M
    Overall precision:  P% (X/Y excluding `unsure`)
    GeoNames precision: ...
    Wikidata precision: ...
    Unsure rate:        Z%
    Incorrect rows: <one-per-line listing>

The script exits non-zero if more than 5% of rows are still blank
(treated as incomplete review).
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path


VALID_JUDGMENTS = {"correct", "incorrect", "unsure"}


def normalise(judgment: str) -> str:
    return (judgment or "").strip().lower()


def main(argv: list[str]) -> int:
    in_path = Path(argv[1]) if len(argv) > 1 else Path("judgments.csv")
    if not in_path.exists():
        print(f"ERROR: file not found: {in_path}", file=sys.stderr)
        return 2

    rows: list[dict] = []
    with in_path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            r["judgment_norm"] = normalise(r.get("judgment", ""))
            rows.append(r)

    total = len(rows)
    by_j = Counter(r["judgment_norm"] for r in rows)
    blank = by_j.get("", 0)
    invalid = sum(1 for r in rows
                  if r["judgment_norm"] not in (VALID_JUDGMENTS | {""}))
    reviewed = total - blank - invalid

    print(f"Sample size:        {total}")
    print(f"Reviewed:           {reviewed} ({reviewed / total * 100:.1f}%)")
    if blank:
        print(f"Blank / not reviewed: {blank}")
    if invalid:
        print(f"Invalid judgment:    {invalid}")

    if reviewed == 0:
        print("Nothing to score yet.", file=sys.stderr)
        return 1

    # Overall precision excludes blank and unsure.
    decided = [r for r in rows if r["judgment_norm"] in {"correct", "incorrect"}]
    correct = sum(1 for r in decided if r["judgment_norm"] == "correct")
    if decided:
        overall = correct / len(decided) * 100.0
        print(f"\nOverall precision:  {overall:.1f}% ({correct}/{len(decided)} excluding `unsure`)")

    # Per authority.
    print("")
    for auth in ("geonames", "wikidata"):
        sub = [r for r in decided if r.get("target_authority") == auth]
        if not sub:
            continue
        c = sum(1 for r in sub if r["judgment_norm"] == "correct")
        print(f"{auth.capitalize():9} precision: {c / len(sub) * 100:.1f}% "
              f"({c}/{len(sub)})")

    unsure = sum(1 for r in rows if r["judgment_norm"] == "unsure")
    if unsure:
        print(f"\nUnsure rate:        {unsure / reviewed * 100:.1f}% ({unsure}/{reviewed})")

    incorrects = [r for r in rows if r["judgment_norm"] == "incorrect"]
    if incorrects:
        print(f"\nIncorrect rows ({len(incorrects)}):")
        for r in incorrects:
            note = f"  --  {r.get('notes', '').strip()}" if r.get("notes", "").strip() else ""
            print(f"  {r.get('place_iri', '?')} -> {r.get('target_iri', '?')}{note}")

    if blank > total * 0.05:
        print(f"\nWARN: more than 5% of rows are blank ({blank}/{total}). "
              "Review is incomplete.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
