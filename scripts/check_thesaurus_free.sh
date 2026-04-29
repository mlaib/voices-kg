#!/usr/bin/env bash
# check_thesaurus_free.sh — fail-loud verification that the published KG
# carries no SFI Shoah Foundation thesaurus content.
#
# Why
# ---
# The SFI thesaurus is proprietary and may not be republished. The build
# pipeline (a) re-mints every SFI vocab IRI as a local urn:voices:place:<slug>,
# and (b) drops the concepts named graph and mentionsConcept predicates.
# This script is the gate that catches regressions on the next build.
#
# We do NOT block SKOS itself — SKOS is a W3C vocabulary used by GeoNames,
# Wikidata, and authority files everywhere. Our outward `skos:exactMatch`
# alignments to those authorities follow that convention.
#
# Exit codes:
#   0 — clean (no thesaurus content found)
#   1 — taint detected (script prints which file + which pattern)
#   2 — required input file missing
#
# Usage:
#   bash scripts/check_thesaurus_free.sh                # default paths
#   bash scripts/check_thesaurus_free.sh path/to/my.nq  # check a specific file

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

DEFAULTS=(
    "$PROJECT_DIR/output/kg2026_v2.nq"
    "$PROJECT_DIR/output/kg2026_v2.nqs"
    "$PROJECT_DIR/output/utterance_embeddings_v2.nq"
    "$PROJECT_DIR/schema/voices_ontology_v2.ttl"
    "$PROJECT_DIR/schema/voices-alignment-v2.ttl"
)

if [ "$#" -gt 0 ]; then
    FILES=("$@")
else
    FILES=("${DEFAULTS[@]}")
fi

# Patterns to scan for. Each one represents SFI Shoah Foundation thesaurus
# *content* that may not be redistributed under our licensing agreement.
# We deliberately do NOT block the SKOS namespace itself: SKOS is a W3C
# vocabulary used by GeoNames, Wikidata, and most authority files for
# cross-vocabulary alignment, and our outward `skos:exactMatch` links to
# those authorities are exactly the convention.
PATTERNS=(
    # SFI thesaurus IRIs
    "http://voices\.uni\.lu/vocab/term/"
    # The dropped concepts named graph (carried SFI thesaurus content)
    "urn:voices:graph:concepts"
    # mentionsConcept predicate (carried SFI thesaurus references)
    "voices\.uni\.lu/ontology#mentionsConcept"
)

LABELS=(
    "SFI thesaurus IRI"
    "concepts named graph"
    "mentionsConcept predicate"
)

failed=0
for f in "${FILES[@]}"; do
    if [ ! -f "$f" ]; then
        echo "[skip] $f (not present)"
        continue
    fi
    for i in "${!PATTERNS[@]}"; do
        pattern="${PATTERNS[$i]}"
        label="${LABELS[$i]}"
        # Use grep -m 1 -E so we exit fast on first hit per file/pattern.
        if grep -m 1 -E -q "$pattern" "$f"; then
            echo "[FAIL] $f contains $label (/$pattern/)"
            failed=1
        fi
    done
done

if [ "$failed" -eq 0 ]; then
    echo "[OK] No SFI Shoah Foundation thesaurus content found in any scanned artefact."
    exit 0
else
    echo ""
    echo "Thesaurus content detected — fix before publishing."
    exit 1
fi
