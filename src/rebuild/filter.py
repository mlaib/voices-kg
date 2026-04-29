"""Streaming filter that strips SFI thesaurus IRIs from a v1 N-Quads dump.

Pass 1 — scan the input and build a mapping from every
``http://voices.uni.lu/vocab/term/<N>`` IRI to a new, slug-based
``urn:voices:place:<slug>`` IRI derived from its English rdfs:label.

Pass 2 — stream the input again, drop the entire ``urn:voices:graph:concepts``
graph and any ``voices:mentionsConcept`` assertions, rewrite every SFI IRI
inline via substring replace, and write the transformed quads.

The same passes are optionally applied to an embeddings .nq file and to a
.nqs (RDF-star) companion file.

Usage::

    python -m src.rebuild.filter \\
        --input  .../kg2026_paper.nq \\
        --output output/kg2026_v2.nq \\
        [--embeddings .../utterance_embeddings.nq] \\
        [--nqs-in .../kg2026_paper.nqs --nqs-out output/kg2026_v2.nqs]

The substring rewrite is safe because SFI IRIs are uniquely prefixed with
``http://voices.uni.lu/vocab/term/`` and always appear inside ``<...>``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterable

# Match "<http://voices.uni.lu/vocab/term/NNN>" anywhere inside a quad line.
SFI_IRI_RE = re.compile(
    r"<http://voices\.uni\.lu/vocab/term/(\d+)>"
)

# Match a label quad in the events graph (single line, strict N-Quads):
#   <http://voices.uni.lu/vocab/term/N>
#   <http://www.w3.org/2000/01/rdf-schema#label>
#   "LABEL"@en
#   <urn:voices:graph:events> .
LABEL_LINE_RE = re.compile(
    r'^<http://voices\.uni\.lu/vocab/term/(\d+)>\s+'
    r'<http://www\.w3\.org/2000/01/rdf-schema#label>\s+'
    r'"((?:[^"\\]|\\.)*)"@en\s+'
    r'<urn:voices:graph:events>\s*\.\s*$'
)

CONCEPTS_GRAPH_IRI = "<urn:voices:graph:concepts>"
MENTIONS_CONCEPT_IRI = "<http://voices.uni.lu/ontology#mentionsConcept>"
SFI_PREFIX = "http://voices.uni.lu/vocab/term/"

PLACE_PREFIX = "urn:voices:place:"
MAX_SLUG = 80

_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _unescape_nt_literal(s: str) -> str:
    """Un-escape an N-Triples/N-Quads literal body.

    We only see it inside slug derivation, so a minimal decoder is fine.
    """
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "t":
                out.append("\t")
                i += 2
                continue
            if nxt == "r":
                out.append("\r")
                i += 2
                continue
            if nxt == '"':
                out.append('"')
                i += 2
                continue
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
            if nxt == "u" and i + 5 < len(s):
                try:
                    out.append(chr(int(s[i + 2 : i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            if nxt == "U" and i + 9 < len(s):
                try:
                    out.append(chr(int(s[i + 2 : i + 10], 16)))
                    i += 10
                    continue
                except ValueError:
                    pass
            out.append(nxt)
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def slugify(label: str) -> str:
    """Normalise a label to a URL-safe slug (lowercase, hyphen-separated)."""
    s = _unescape_nt_literal(label).lower()
    s = _SLUG_NON_ALNUM.sub("-", s)
    s = s.strip("-")
    if len(s) > MAX_SLUG:
        s = s[:MAX_SLUG].rstrip("-")
    return s


def _place_iri(slug: str) -> str:
    return f"<{PLACE_PREFIX}{slug}>"


def build_sfi_map(input_paths: Iterable[Path]) -> tuple[dict[str, str], int]:
    """Pass 1: scan every line of every input, returning the mapping.

    Returns ``(sfi_to_slug_iri, collisions_disambiguated)`` where
    ``sfi_to_slug_iri`` maps the full angle-bracketed SFI IRI (including
    brackets) to the full angle-bracketed new IRI.
    """
    label_by_id: dict[str, str] = {}
    seen_ids: set[str] = set()

    for path in input_paths:
        if path is None:
            continue
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                # Cheap pre-filter: only look at lines mentioning an SFI IRI.
                if SFI_PREFIX not in line:
                    continue
                for m in SFI_IRI_RE.finditer(line):
                    seen_ids.add(m.group(1))
                lm = LABEL_LINE_RE.match(line)
                if lm is not None:
                    term_id, label = lm.group(1), lm.group(2)
                    # Keep the first label we see; labels in events graph
                    # are deterministic one-per-term in v1 output.
                    if term_id not in label_by_id:
                        label_by_id[term_id] = label

    # Build slug map with collision detection.
    slug_to_id: dict[str, str] = {}
    sfi_to_new: dict[str, str] = {}
    collisions = 0
    # Iterate deterministically by numeric id for reproducible collision handling.
    for term_id in sorted(seen_ids, key=lambda x: int(x)):
        label = label_by_id.get(term_id)
        if label:
            slug = slugify(label)
            if not slug:
                slug = f"term-{term_id}"
        else:
            slug = f"term-{term_id}"

        if slug in slug_to_id and slug_to_id[slug] != term_id:
            # Collision: disambiguate by numeric id.
            slug = f"{slug}-{term_id}"
            collisions += 1
        slug_to_id.setdefault(slug, term_id)

        old_iri = f"<{SFI_PREFIX}{term_id}>"
        new_iri = _place_iri(slug)
        sfi_to_new[old_iri] = new_iri

    return sfi_to_new, collisions


def _rewrite_line(line: str, sfi_to_new: dict[str, str]) -> str:
    """Substitute every SFI IRI occurrence in a single quad line."""
    def repl(match: "re.Match[str]") -> str:
        old = match.group(0)
        return sfi_to_new.get(old, old)

    return SFI_IRI_RE.sub(repl, line)


def _graph_iri_of(line: str) -> str | None:
    """Return the 4th token (named graph IRI with brackets) of a quad line.

    We parse from the right: the line ends with ``" ."`` (or ``".\n"``) and
    the 4th component is the graph. Doing it as a right-strip + rsplit keeps
    us correct even when an object literal contains spaces.
    """
    s = line.rstrip()
    if not s.endswith("."):
        return None
    s = s[:-1].rstrip()
    # Graph IRI is either <...> or _:bnode. We want angle-bracketed IRIs.
    if not s.endswith(">"):
        return None
    # Find the matching "<" for that final ">".
    lt = s.rfind("<")
    if lt < 0:
        return None
    return s[lt:]


def process_file(
    src: Path,
    dst: Path,
    sfi_to_new: dict[str, str],
    progress_label: str,
    progress_every: int = 1_000_000,
) -> dict[str, int]:
    """Pass 2 over a single file. Returns per-file counts."""
    in_lines = 0
    out_lines = 0
    dropped_concepts = 0
    dropped_mentions = 0
    rewritten = 0

    t0 = time.time()
    dst.parent.mkdir(parents=True, exist_ok=True)

    with src.open("r", encoding="utf-8") as fin, dst.open("w", encoding="utf-8") as fout:
        for line in fin:
            in_lines += 1

            # Drop the concepts graph outright.
            if CONCEPTS_GRAPH_IRI in line:
                graph = _graph_iri_of(line)
                if graph == CONCEPTS_GRAPH_IRI:
                    dropped_concepts += 1
                    if in_lines % progress_every == 0:
                        _print_progress(progress_label, in_lines, t0)
                    continue
                # Defensive: concept graph IRI could appear as subject/object
                # in e.g. provenance. Drop those too for safety.
                dropped_concepts += 1
                if in_lines % progress_every == 0:
                    _print_progress(progress_label, in_lines, t0)
                continue

            # Drop mentionsConcept predicate quads.
            if MENTIONS_CONCEPT_IRI in line:
                dropped_mentions += 1
                if in_lines % progress_every == 0:
                    _print_progress(progress_label, in_lines, t0)
                continue

            # Rewrite SFI IRIs inline.
            if SFI_PREFIX in line:
                new_line = _rewrite_line(line, sfi_to_new)
                if new_line != line:
                    rewritten += 1
                line = new_line

            fout.write(line)
            out_lines += 1

            if in_lines % progress_every == 0:
                _print_progress(progress_label, in_lines, t0)

    elapsed = time.time() - t0
    print(
        f"[{progress_label}] done: in={in_lines:,} out={out_lines:,} "
        f"dropped_concepts={dropped_concepts:,} dropped_mentions={dropped_mentions:,} "
        f"rewritten={rewritten:,} elapsed={elapsed:.1f}s",
        flush=True,
    )
    return {
        "input_lines": in_lines,
        "output_lines": out_lines,
        "dropped_concepts_graph": dropped_concepts,
        "dropped_mentions_concept": dropped_mentions,
        "sfi_terms_rewritten": rewritten,
    }


def _print_progress(label: str, lines: int, t0: float) -> None:
    elapsed = max(time.time() - t0, 1e-6)
    rate = lines / elapsed
    print(
        f"[{label}] {lines:,} lines  ({rate/1e6:.2f} M/s)  "
        f"elapsed={elapsed:.1f}s",
        flush=True,
    )


def verify_output(path: Path) -> None:
    """Fail loud if the output still contains SFI artefacts."""
    if not path.exists():
        return
    bad_sfi = 0
    bad_concepts = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if "vocab/term/" in line:
                bad_sfi += 1
            if "urn:voices:graph:concepts" in line:
                bad_concepts += 1
            if bad_sfi or bad_concepts:
                # No need to scan further once we already know it's dirty.
                break
    if bad_sfi or bad_concepts:
        raise AssertionError(
            f"Verification failed for {path}: "
            f"vocab/term leftovers={bad_sfi}, concepts leftovers={bad_concepts}"
        )


def _default_v1_dir() -> Path:
    return Path(os.environ.get("V1_OUTPUT_DIR", "/mnt/d/Projets/voices/workspace/KG2026.paper/output"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strip SFI thesaurus IRIs from v1 N-Quads.")
    v1 = _default_v1_dir()
    parser.add_argument("--input", type=Path, default=v1 / "kg2026_paper.nq")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--embeddings", type=Path, default=None,
                        help="Optional utterance_embeddings.nq to rewrite in parallel.")
    parser.add_argument("--embeddings-out", type=Path, default=None)
    parser.add_argument("--nqs-in", type=Path, default=None)
    parser.add_argument("--nqs-out", type=Path, default=None)
    parser.add_argument("--stats", type=Path, default=None,
                        help="Path to write stats JSON. Defaults to <output dir>/stats.json")
    parser.add_argument("--progress-every", type=int, default=1_000_000)
    parser.add_argument("--no-verify", action="store_true",
                        help="Skip the post-run correctness scan.")
    args = parser.parse_args(argv)

    if args.embeddings is not None and args.embeddings_out is None:
        args.embeddings_out = args.output.parent / "utterance_embeddings_v2.nq"
    if args.nqs_in is not None and args.nqs_out is None:
        args.nqs_out = args.output.with_suffix(".nqs")
    if args.stats is None:
        args.stats = args.output.parent / "stats.json"

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 2

    t_start = time.time()

    # ----- Pass 1: build SFI → local-place map across all relevant inputs.
    scan_inputs = [args.input]
    if args.embeddings is not None:
        scan_inputs.append(args.embeddings)
    if args.nqs_in is not None:
        scan_inputs.append(args.nqs_in)

    print(f"[pass1] scanning: {[str(p) for p in scan_inputs]}", flush=True)
    t_p1 = time.time()
    sfi_to_new, collisions = build_sfi_map(scan_inputs)
    print(
        f"[pass1] done: {len(sfi_to_new):,} SFI IRIs mapped, "
        f"{collisions:,} collisions disambiguated, "
        f"elapsed={time.time() - t_p1:.1f}s",
        flush=True,
    )

    # ----- Pass 2: stream-rewrite each file.
    main_stats = process_file(
        args.input, args.output, sfi_to_new, "main", progress_every=args.progress_every
    )

    emb_stats = None
    if args.embeddings is not None and args.embeddings.exists():
        emb_stats = process_file(
            args.embeddings, args.embeddings_out, sfi_to_new, "embeddings",
            progress_every=args.progress_every,
        )

    nqs_stats = None
    if args.nqs_in is not None and args.nqs_in.exists():
        nqs_stats = process_file(
            args.nqs_in, args.nqs_out, sfi_to_new, "nqs",
            progress_every=args.progress_every,
        )

    # ----- Verify correctness.
    if not args.no_verify:
        verify_output(args.output)
        if args.embeddings_out is not None:
            verify_output(args.embeddings_out)
        if args.nqs_out is not None:
            verify_output(args.nqs_out)

        # Line-count invariant on the main file.
        expected = (
            main_stats["input_lines"]
            - main_stats["dropped_concepts_graph"]
            - main_stats["dropped_mentions_concept"]
        )
        if expected != main_stats["output_lines"]:
            raise AssertionError(
                f"Main output line count mismatch: expected {expected}, "
                f"got {main_stats['output_lines']}"
            )

    elapsed = time.time() - t_start
    stats = {
        "input_lines": main_stats["input_lines"],
        "output_lines": main_stats["output_lines"],
        "dropped_concepts_graph": main_stats["dropped_concepts_graph"],
        "dropped_mentions_concept": main_stats["dropped_mentions_concept"],
        "sfi_terms_rewritten": main_stats["sfi_terms_rewritten"],
        "unique_places_minted": len(sfi_to_new),
        "slug_collisions_disambiguated": collisions,
        "elapsed_seconds": round(elapsed, 2),
    }
    if emb_stats is not None:
        stats["embeddings"] = emb_stats
    if nqs_stats is not None:
        stats["nqs"] = nqs_stats

    args.stats.parent.mkdir(parents=True, exist_ok=True)
    with args.stats.open("w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2)
        fh.write("\n")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
