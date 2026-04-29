#!/usr/bin/env bash
# fuseki_load.sh — upload N-Quads (+ optional RDF-star & embedding quads) to Fuseki.
#
# Usage (from host):
#   FUSEKI_URL=http://localhost:3032/voices \
#   FUSEKI_ADMIN_PASSWORD=<your-password> \
#   ./scripts/fuseki_load.sh
#
# Behaviour:
#   1. Waits up to 60s for Fuseki to respond on /$/ping.
#   2. Reads current quad count. If >1_000_000 aborts unless FORCE=1 is set.
#   3. Streams output/kg2026_v2.nq   (required) via POST /data.
#   4. Streams output/kg2026_v2.nqs  (optional, RDF-star).
#   5. Streams output/utterance_embeddings_v2.nq (optional).
#   6. Prints final quad count.
#
# Environment:
#   FUSEKI_URL              default http://localhost:3032/voices
#   FUSEKI_ADMIN_PASSWORD   required — set via environment or .env (admin user is "admin")
#   FORCE                   set to 1 to load even if dataset is populated
#
# Exit codes: 0 success, 1 upload failure, 2 missing input file, 3 Fuseki unreachable.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

NQ_FILE="$PROJECT_DIR/output/kg2026_v2.nq"
NQS_FILE="$PROJECT_DIR/output/kg2026_v2.nqs"
EMB_FILE="$PROJECT_DIR/output/utterance_embeddings_v2.nq"

FUSEKI_URL="${FUSEKI_URL:-http://localhost:3032/voices}"
ADMIN_USER="admin"
ADMIN_PASS="${FUSEKI_ADMIN_PASSWORD:?FUSEKI_ADMIN_PASSWORD must be set in environment}"
FORCE="${FORCE:-0}"

# Derive dataset root + base from $FUSEKI_URL.
#   Input:  http://host:3032/voices       -> BASE=http://host:3032  DS=voices
BASE="${FUSEKI_URL%/*}"
DATASET_NAME="${FUSEKI_URL##*/}"
DATA_URL="$FUSEKI_URL/data"
SPARQL_URL="$FUSEKI_URL/sparql"
PING_URL="$BASE/\$/ping"

log() { echo "[fuseki_load] $*" >&2; }

if [ ! -f "$NQ_FILE" ]; then
    log "ERROR: required file not found: $NQ_FILE"
    log "       run src/rebuild/filter.py first"
    exit 2
fi

log "=== Fuseki Data Loader ==="
log "URL      : $FUSEKI_URL"
log "Dataset  : $DATASET_NAME"
log "Main .nq : $NQ_FILE ($(du -h "$NQ_FILE" | cut -f1))"
[ -f "$NQS_FILE" ] && log ".nqs     : $NQS_FILE ($(du -h "$NQS_FILE" | cut -f1))" || log ".nqs     : (not present)"
[ -f "$EMB_FILE" ] && log "emb .nq  : $EMB_FILE ($(du -h "$EMB_FILE" | cut -f1))" || log "emb .nq  : (not present)"

log "Waiting for Fuseki ping at $PING_URL ..."
READY=0
for i in $(seq 1 60); do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "$PING_URL" 2>/dev/null || echo "000")
    if [ "$CODE" = "200" ]; then
        READY=1
        log "Fuseki is ready after ${i}s."
        break
    fi
    sleep 1
done
if [ "$READY" -ne 1 ]; then
    log "ERROR: Fuseki not reachable after 60s."
    exit 3
fi

count_quads() {
    curl -sf -X POST "$SPARQL_URL" \
        --data-urlencode "query=SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } }" \
        -H "Accept: application/sparql-results+json" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['results']['bindings'][0]['n']['value'])" \
        2>/dev/null || echo "0"
}

CURRENT=$(count_quads)
log "Current quad count: $CURRENT"

if [ "$CURRENT" -gt 1000000 ] && [ "$FORCE" != "1" ]; then
    log "Dataset already populated ($CURRENT quads > 1,000,000)."
    log "Refusing to reload. Set FORCE=1 to override."
    exit 0
fi

upload() {
    local path="$1"
    local label="$2"
    log "Uploading $label ($path) ..."
    local code
    code=$(curl -X POST "$DATA_URL" \
        -u "$ADMIN_USER:$ADMIN_PASS" \
        -H "Content-Type: application/n-quads" \
        -H "Transfer-Encoding: chunked" \
        -T "$path" \
        --progress-bar \
        -o /dev/null \
        -w "%{http_code}")
    if [ "$code" -ge 200 ] && [ "$code" -lt 300 ]; then
        log "  $label: HTTP $code OK"
    else
        log "ERROR: $label returned HTTP $code"
        exit 1
    fi
}

upload "$NQ_FILE" "kg2026_v2.nq"
[ -f "$NQS_FILE" ] && upload "$NQS_FILE" "kg2026_v2.nqs (RDF-star)"
[ -f "$EMB_FILE" ] && upload "$EMB_FILE" "utterance_embeddings_v2.nq"

FINAL=$(count_quads)
log "=== Load complete: $FINAL quads in Fuseki ==="
echo "$FINAL"
