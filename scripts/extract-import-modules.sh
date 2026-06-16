#!/usr/bin/env bash
#
# Rebuild the minimal import modules for the VOICES ontology.
#
# Rationale (reviewer request): rather than importing each external ontology in
# full via owl:imports, VOICES imports small extracted MODULES that contain only
# the reused terms and the axioms relevant to them. This keeps the import closure
# small, makes reasoning/tooling (WIDOCO, OOPS!, Protégé) fast, and avoids pulling
# in large upper ontologies (e.g. BFO via MFOEM).
#
# Method:
#   * CIDOC-CRM, OWL-Time, Web Annotation (OA), Media Ontology (MA)
#       -> ROBOT `extract --method MIREOT` (term + ancestor hierarchy + labels)
#   * MFOEM (Emotion Ontology)
#       -> ROBOT `filter` keeping only MFOEM_000001 + its own annotations,
#          because its MIREOT ancestor chain is pure BFO/IAO upper-ontology
#          scaffolding that is not relevant to the VOICES domain.
#   * PROV-O is intentionally NOT imported: it was previously imported but no
#     prov: term is actually used in the ontology.
#
# Requirements: Java 11+, ROBOT (https://github.com/ontodev/robot), curl.
# Usage: scripts/extract-import-modules.sh
set -euo pipefail

ROBOT="${ROBOT:-robot}"                 # set ROBOT=/path/to/robot.jar wrapper or use 'java -jar robot.jar'
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$(mktemp -d)"
OUT="$ROOT/imports"
TERMS="$OUT/terms"
NS="https://w3id.org/voices/ontology/imports"

echo ">> downloading source ontologies into $SRC"
curl -sL -o "$SRC/crm.rdfs"   https://cidoc-crm.org/rdfs/7.1.3/CIDOC_CRM_v7.1.3.rdfs
curl -sL -o "$SRC/oa.ttl"     https://www.w3.org/ns/oa.ttl
curl -sL -o "$SRC/time.ttl"   https://www.w3.org/2006/time
curl -sL -o "$SRC/ma-ont.rdf" https://www.w3.org/ns/ma-ont.rdf
curl -sL -o "$SRC/MFOEM.owl"  https://raw.githubusercontent.com/jannahastings/emotion-ontology/master/ontology/MFOEM.owl

mireot () { # source termfile iri out
  $ROBOT extract --method MIREOT --input "$1" --lower-terms "$2" --annotate-with-source true \
    annotate --ontology-iri "$3" --output "$4"
}

echo ">> extracting MIREOT modules"
mireot "$SRC/crm.rdfs"   "$TERMS/cidoc-crm.txt" "$NS/cidoc-crm" "$OUT/cidoc-crm-module.ttl"
mireot "$SRC/oa.ttl"     "$TERMS/oa.txt"        "$NS/oa"        "$OUT/oa-module.ttl"
mireot "$SRC/time.ttl"   "$TERMS/time.txt"      "$NS/time"      "$OUT/time-module.ttl"
mireot "$SRC/ma-ont.rdf" "$TERMS/ma-ont.txt"    "$NS/ma-ont"    "$OUT/ma-ont-module.ttl"

echo ">> extracting MFOEM (term + own annotations only)"
$ROBOT filter --input "$SRC/MFOEM.owl" \
    --term http://purl.obolibrary.org/obo/MFOEM_000001 --select "self annotations" \
  annotate --ontology-iri "$NS/mfoem" \
    --annotation rdfs:isDefinedBy "http://purl.obolibrary.org/obo/MFOEM.owl" \
    --output "$OUT/mfoem-module.ttl"

echo ">> done. Modules written to $OUT/"
rm -rf "$SRC"
