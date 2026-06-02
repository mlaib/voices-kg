"""Produce the public variant of a VOICES N-Quads dump.

Two transforms are applied in a single streaming pass:

1. **Strip transcript text** — drop every ``voices:transcriptText`` quad. The
   literal transcript text is derived from copyrighted USC SFI VHA testimonies
   and is not redistributable. All other quads (events, places, emotions,
   embeddings, alignments, ...) are kept untouched, so SPARQL queries that
   reference segment IRIs still resolve.

2. **Pseudonymize survivor names** — on each ``voices:Interview`` subject in the
   metadata graph, replace the survivor's full name with ``Interview <id>`` in
   both the ``rdfs:label`` and ``voices:testimonyTitle`` literals. The bare
   interview id (the VHA IntCode) is already public in the IRI
   (``urn:voices:interview:<id>``), so the analytics, dropdowns, and search all
   keep working; only the personal name is removed. The Meilisearch indexer and
   the precompute caches both derive their ``survivor`` field from this
   ``rdfs:label``, so regenerating them from this dump propagates the change to
   every app tab with no UI code changes.

   The private full dump (``output/kg2026_v2.nq``) retains the real names and is
   the internal name<->id mapping; it must not be published.

   NOTE — scope limitation: this anonymizes only the interviewee's metadata
   labels. The survivor's name still appears in the ``events`` graph as
   ``urn:voices:person:`` participant IRIs/labels (e.g. the survivor as a
   participant, and derived "<name>'s mother" entries), which remain reachable
   via the public SPARQL endpoint. Scrubbing those requires IRI re-minting and
   is intentionally out of scope here. Pass ``--keep-names`` to disable
   pseudonymization entirely.

Usage:
    python scripts/strip_transcript_text.py \
        --input  output/kg2026_v2.nq \
        --output output/kg2026_v2_public.nq
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PREDICATE_IRI = "<http://voices.uni.lu/ontology#transcriptText>"

# A survivor-name literal on a voices:Interview subject in the metadata graph,
# carried by either rdfs:label ("..."@en) or voices:testimonyTitle ("...").
# Captures: (1) subject + predicate prefix, (2) interview id, (3) closing
# predicate punctuation, (4) the literal incl. quotes and any @en tag, (5) the
# graph + trailing ". ". The literal in group 4 is what gets replaced.
NAME_LINE_RE = re.compile(
    r'^(<urn:voices:interview:(\d+)>\s+'
    r'<(?:http://www\.w3\.org/2000/01/rdf-schema#label'
    r'|http://voices\.uni\.lu/ontology#testimonyTitle)>\s+)'
    r'"(?:[^"\\]|\\.)*"(@en)?'
    r'(\s+<urn:voices:graph:metadata>\s*\.\s*)$'
)


def _pseudonymize(line: str) -> str | None:
    """Rewrite a survivor-name literal to ``"Interview <id>"``; else None."""
    m = NAME_LINE_RE.match(line)
    if not m:
        return None
    prefix, iid, lang, suffix = m.group(1), m.group(2), m.group(3), m.group(4)
    literal = f'"Interview {iid}"' + (lang or "")
    return f"{prefix}{literal}{suffix}"


def strip(in_path: Path, out_path: Path, anonymize: bool = True) -> tuple[int, int, int]:
    kept = dropped = renamed = 0
    with in_path.open("r", encoding="utf-8") as fin, \
         out_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            if PREDICATE_IRI in line:
                dropped += 1
                continue
            if anonymize and "<urn:voices:interview:" in line:
                rewritten = _pseudonymize(line)
                if rewritten is not None:
                    fout.write(rewritten)
                    kept += 1
                    renamed += 1
                    continue
            fout.write(line)
            kept += 1
    return kept, dropped, renamed


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument(
        "--keep-names",
        action="store_true",
        help="Do not pseudonymize survivor names (debug/internal use only).",
    )
    args = p.parse_args()

    if not args.input.exists():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 1

    anonymize = not args.keep_names
    print(f"reading  {args.input}  ({args.input.stat().st_size / 1e9:.2f} GB)")
    print(f"writing  {args.output}  (anonymize names: {anonymize})")
    kept, dropped, renamed = strip(args.input, args.output, anonymize=anonymize)
    out_size = args.output.stat().st_size / 1e9
    print(f"done: kept {kept:,} quads, dropped {dropped:,} transcript-text quads")
    print(f"      pseudonymized {renamed:,} survivor-name literals")
    print(f"output size: {out_size:.2f} GB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
