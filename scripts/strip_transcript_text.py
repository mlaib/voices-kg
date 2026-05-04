"""Strip voices:transcriptText quads from a VOICES N-Quads dump.

Produces a "public" variant of the KG dump in which the literal transcript
text derived from copyrighted USC SFI VHA testimonies has been removed.
All other quads (events, places, emotions, embeddings, alignments, ...)
are kept untouched, so SPARQL queries that reference segment IRIs still
resolve.

Usage:
    python scripts/strip_transcript_text.py \
        --input  output/kg2026_v2.nq \
        --output output/kg2026_v2_public.nq
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PREDICATE_IRI = "<http://voices.uni.lu/ontology#transcriptText>"


def strip(in_path: Path, out_path: Path) -> tuple[int, int]:
    kept = dropped = 0
    with in_path.open("r", encoding="utf-8") as fin, \
         out_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            if PREDICATE_IRI in line:
                dropped += 1
                continue
            fout.write(line)
            kept += 1
    return kept, dropped


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()

    if not args.input.exists():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 1

    print(f"reading  {args.input}  ({args.input.stat().st_size / 1e9:.2f} GB)")
    print(f"writing  {args.output}")
    kept, dropped = strip(args.input, args.output)
    out_size = args.output.stat().st_size / 1e9
    print(f"done: kept {kept:,} quads, dropped {dropped:,} transcript-text quads")
    print(f"output size: {out_size:.2f} GB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
