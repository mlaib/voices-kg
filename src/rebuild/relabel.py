"""Ensure every newly-minted ``urn:voices:place:<slug>`` has a label + type
in the ``urn:voices:graph:metadata`` graph.

After ``filter.py`` runs, the rewritten output inherits labels from the
former events graph (they survive the rewrite because the subject just
changes from an SFI IRI to our new place IRI). But some places may have
had no English label in v1 (those slug as ``term-<N>``), and no place has
an ``rdf:type voices:Place`` triple in the metadata graph yet.

This script is idempotent: it scans the output once to collect existing
labels/types in the metadata graph, then appends only what is missing.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PLACE_IRI_RE = re.compile(r"<(urn:voices:place:[^>]+)>")

RDFS_LABEL = "<http://www.w3.org/2000/01/rdf-schema#label>"
RDF_TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
VOICES_PLACE = "<http://voices.uni.lu/ontology#Place>"
METADATA_GRAPH = "<urn:voices:graph:metadata>"

# Strict N-Quads line that declares a place label in the metadata graph.
META_LABEL_RE = re.compile(
    r"^<(urn:voices:place:[^>]+)>\s+"
    r"<http://www\.w3\.org/2000/01/rdf-schema#label>\s+"
    r'"(?:[^"\\]|\\.)*"(?:@[A-Za-z-]+|\^\^<[^>]+>)?\s+'
    r"<urn:voices:graph:metadata>\s*\.\s*$"
)
META_TYPE_RE = re.compile(
    r"^<(urn:voices:place:[^>]+)>\s+"
    r"<http://www\.w3\.org/1999/02/22-rdf-syntax-ns#type>\s+"
    r"<http://voices\.uni\.lu/ontology#Place>\s+"
    r"<urn:voices:graph:metadata>\s*\.\s*$"
)


def humanise_slug(slug: str) -> str:
    """Convert ``miskolc-hungary`` → ``Miskolc Hungary``.

    Falls back to the raw slug when it is a ``term-<N>`` placeholder that
    we don't have a better name for.
    """
    if slug.startswith("term-"):
        return slug
    parts = [p for p in slug.split("-") if p]
    return " ".join(p.capitalize() for p in parts) if parts else slug


def _nt_escape(s: str) -> str:
    return (
        s.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace('"', '\\"')
    )


def scan(path: Path) -> tuple[set[str], set[str], set[str]]:
    """Return (all_place_iris, places_with_meta_label, places_with_meta_type)."""
    all_places: set[str] = set()
    labelled: set[str] = set()
    typed: set[str] = set()

    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if "urn:voices:place:" not in line:
                continue
            for m in PLACE_IRI_RE.finditer(line):
                all_places.add(m.group(1))
            lm = META_LABEL_RE.match(line)
            if lm is not None:
                labelled.add(lm.group(1))
                continue
            tm = META_TYPE_RE.match(line)
            if tm is not None:
                typed.add(tm.group(1))

    return all_places, labelled, typed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append metadata-graph labels and type triples for places.")
    parser.add_argument("--input", type=Path, required=True,
                        help="The kg2026_v2.nq produced by filter.py. Triples are appended in place.")
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 2

    all_places, labelled, typed = scan(args.input)
    missing_labels = sorted(all_places - labelled)
    missing_types = sorted(all_places - typed)

    print(
        f"[relabel] {len(all_places):,} places, "
        f"{len(missing_labels):,} need labels, {len(missing_types):,} need types",
        flush=True,
    )

    if not missing_labels and not missing_types:
        print("[relabel] nothing to append; already idempotent.")
        return 0

    with args.input.open("a", encoding="utf-8") as fh:
        for iri in missing_labels:
            # slug = IRI minus the prefix.
            slug = iri[len("urn:voices:place:"):]
            label = _nt_escape(humanise_slug(slug))
            fh.write(
                f"<{iri}> {RDFS_LABEL} \"{label}\"@en {METADATA_GRAPH} .\n"
            )
        for iri in missing_types:
            fh.write(
                f"<{iri}> {RDF_TYPE} {VOICES_PLACE} {METADATA_GRAPH} .\n"
            )

    print(
        f"[relabel] appended {len(missing_labels):,} labels and "
        f"{len(missing_types):,} type triples."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
