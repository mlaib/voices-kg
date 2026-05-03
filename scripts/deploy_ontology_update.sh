#!/usr/bin/env bash
# deploy_ontology_update.sh
# ===========================================================================
# Pulls the latest commit on the VM and serves the new ontology .ttl through
# the existing Caddy container. Idempotent and zero-downtime.
#
# What this does NOT touch:
#   - the Fuseki dataset (no reload required: ontology .ttl is a static
#     asset, not loaded into the triplestore)
#   - the Streamlit app, Redis, Meilisearch, FastAPI containers
#   - any RDF-star embeddings or alignment graphs
#
# It is therefore safe to run mid-production.
#
# Usage on the VM (assumes the repo is at $REPO_DIR and the docker compose
# project name is "voices-kg-v2"):
#
#   sudo -u <deploy-user> bash scripts/deploy_ontology_update.sh
#
# or via SSH from your workstation:
#
#   ssh su_laib@192.168.108.32 \
#     'cd ~/voices-kg && bash scripts/deploy_ontology_update.sh'
#
# Exit codes:
#   0 - success
#   1 - git pull failed (commit not present or merge conflict)
#   2 - ontology .ttl missing after pull (bad branch state)
#   3 - Caddy container not responding to /ontology/voices_ontology_v2.ttl
# ===========================================================================

set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
ONTOLOGY_PATH="${REPO_DIR}/schema/voices_ontology_v2.ttl"
PUBLIC_URL="${PUBLIC_BASE_URL:-https://localhost:8443}/ontology/voices_ontology_v2.ttl"
EXPECTED_VERSION="${EXPECTED_VERSION:-2.1-unified}"

log() { echo "[deploy] $*" >&2; }

cd "$REPO_DIR"

log "Repo: $REPO_DIR"
log "Branch: $(git rev-parse --abbrev-ref HEAD)  Commit before pull: $(git rev-parse --short HEAD)"

# 1) Pull latest
log "Pulling latest commit ..."
if ! git pull --ff-only origin main; then
    log "ERROR: git pull failed (possible merge conflict or branch divergence)"
    exit 1
fi
log "Commit after pull:  $(git rev-parse --short HEAD)"

# 2) Sanity-check the new ontology exists and has the expected version
if [ ! -f "$ONTOLOGY_PATH" ]; then
    log "ERROR: ontology not found at $ONTOLOGY_PATH"
    exit 2
fi
if ! grep -q "owl:versionInfo \"${EXPECTED_VERSION}\"" "$ONTOLOGY_PATH"; then
    log "WARN: ontology version is not '${EXPECTED_VERSION}'."
    grep "owl:versionInfo" "$ONTOLOGY_PATH" | head -1
    log "      Continuing anyway."
fi

# 3) Run the SFI cleanliness gate (must still pass)
log "Running scripts/check_thesaurus_free.sh ..."
if ! bash scripts/check_thesaurus_free.sh; then
    log "ERROR: SFI cleanliness gate failed. Aborting deploy."
    exit 4
fi

# 4) Caddy serves /ontology from the bind-mounted ./schema directory.
#    No restart needed. Confirm the new file is reachable.
log "Verifying public ontology endpoint at $PUBLIC_URL ..."
HTTP_CODE=$(curl -sk -o /tmp/served_ontology.ttl -w "%{http_code}" "$PUBLIC_URL")
if [ "$HTTP_CODE" != "200" ]; then
    log "ERROR: Caddy returned HTTP $HTTP_CODE for the ontology URL."
    exit 3
fi
SERVED_VERSION=$(grep -oE 'owl:versionInfo "[^"]+"' /tmp/served_ontology.ttl | head -1)
log "Served ontology version: ${SERVED_VERSION:-(not found)}"

# 5) Done.
log "=== Deploy complete ==="
log "New ontology served at: $PUBLIC_URL"
log "No service restart required (ontology is a static asset)."
