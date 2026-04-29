#!/usr/bin/env bash
# smoke.sh — end-to-end readiness check for the VOICES KG v2 stack.
#
# Runs a sequence of HTTP probes against Caddy, Fuseki, the admin API and
# (optionally) Meilisearch. Prints a checklist; exits non-zero if any step
# fails. Call after `make up && make load && make index && make precompute`.
#
# Environment
# -----------
#   CADDY_HTTPS_PORT    default 8443
#   FUSEKI_HOST_PORT    default 3032
#   ADMIN_EMAIL         default admin@voices.local
#   ADMIN_PASSWORD      (no default — must be set in environment)
#   MEILI_MASTER_KEY    (no default — must be set in environment)
#   COMPOSE_PROJECT     default voices-kg-v2 (for docker compose exec fallback)
#
# Exit codes: 0 all good, 1 one or more checks failed.

set -uo pipefail

CADDY_HTTPS_PORT="${CADDY_HTTPS_PORT:-8443}"
FUSEKI_HOST_PORT="${FUSEKI_HOST_PORT:-3032}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@voices.local}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:?ADMIN_PASSWORD must be set in environment}"
MEILI_MASTER_KEY="${MEILI_MASTER_KEY:?MEILI_MASTER_KEY must be set in environment}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-voices-kg-v2}"

CADDY_BASE="https://localhost:${CADDY_HTTPS_PORT}"
FUSEKI_BASE="http://localhost:${FUSEKI_HOST_PORT}"
COOKIE_JAR="$(mktemp -t voices-smoke.XXXXXX)"
trap 'rm -f "$COOKIE_JAR"' EXIT

PASS=0
FAIL=0

check() {
    local label="$1"; shift
    local detail="$1"; shift
    if "$@" >/dev/null 2>&1; then
        printf "  [\033[32mOK\033[0m]   %-45s %s\n" "$label" "$detail"
        PASS=$((PASS + 1))
    else
        printf "  [\033[31mFAIL\033[0m] %-45s %s\n" "$label" "$detail"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== VOICES KG v2 smoke test ==="
echo "Caddy   : $CADDY_BASE"
echo "Fuseki  : $FUSEKI_BASE"
echo "Admin   : $ADMIN_EMAIL"
echo

# 1 — Caddy healthz
check "Caddy /healthz" "$CADDY_BASE/healthz" \
    bash -c "test \"\$(curl -kfs '$CADDY_BASE/healthz')\" = \"ok\""

# 2 — Fuseki ping
check "Fuseki /\$/ping" "$FUSEKI_BASE/\$/ping" \
    curl -fsS "$FUSEKI_BASE/\$/ping" -o /dev/null

# 3 — Fuseki has data
COUNT=$(curl -fsS -X POST "$FUSEKI_BASE/voices/sparql" \
    --data-urlencode "query=SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } }" \
    -H "Accept: application/sparql-results+json" \
    2>/dev/null \
    | python3 -c "import sys,json
try: print(int(json.load(sys.stdin)['results']['bindings'][0]['n']['value']))
except Exception: print(0)" 2>/dev/null || echo "0")
check "Fuseki quads > 1,000,000" "got=$COUNT" \
    bash -c "test \"$COUNT\" -gt 1000000"

# 4 — Admin /api/healthz via Caddy
check "Admin /api/healthz" "$CADDY_BASE/api/healthz" \
    curl -kfsS "$CADDY_BASE/api/healthz" -o /dev/null

# 5 — Login flow
LOGIN_CODE=$(curl -kfsS -o /dev/null -w "%{http_code}" \
    -c "$COOKIE_JAR" \
    -X POST "$CADDY_BASE/auth/login" \
    -d "email=${ADMIN_EMAIL}&password=${ADMIN_PASSWORD}" \
    --max-redirs 0 \
    2>/dev/null || echo "000")
check "Login flow (POST /auth/login)" "status=$LOGIN_CODE" \
    bash -c "[[ \"$LOGIN_CODE\" =~ ^(200|302|303)$ ]] && [ -s \"$COOKIE_JAR\" ]"

# 6 — Admin dashboard with cookie
DASH_CODE=$(curl -kfsS -o /dev/null -w "%{http_code}" \
    -b "$COOKIE_JAR" "$CADDY_BASE/admin/" 2>/dev/null || echo "000")
check "Admin dashboard (GET /admin/)" "status=$DASH_CODE" \
    bash -c "test \"$DASH_CODE\" = \"200\""

# 7 — SPARQL through the app stack (/sparql is proxied by Caddy)
SPARQL_CODE=$(curl -kfsS -o /dev/null -w "%{http_code}" \
    -X POST "$CADDY_BASE/sparql" \
    -b "$COOKIE_JAR" \
    --data-urlencode "query=SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o } LIMIT 1" \
    -H "Accept: application/sparql-results+json" \
    2>/dev/null || echo "000")
check "SPARQL through Caddy" "status=$SPARQL_CODE" \
    bash -c "test \"$SPARQL_CODE\" = \"200\""

# 8 — Meilisearch reachable (prefer docker exec because port isn't published)
meili_probe() {
    if command -v docker >/dev/null 2>&1; then
        if docker compose -p "$COMPOSE_PROJECT" exec -T meilisearch \
            wget -q -O - "http://127.0.0.1:7700/health" 2>/dev/null | grep -q "available"; then
            return 0
        fi
    fi
    # Fallback if someone exposed 7700 on host
    if curl -fsS "http://127.0.0.1:7700/health" -H "Authorization: Bearer $MEILI_MASTER_KEY" \
        2>/dev/null | grep -q "available"; then
        return 0
    fi
    return 1
}
check "Meilisearch /health" "docker exec or localhost:7700" meili_probe

echo
echo "=== ${PASS} pass / ${FAIL} fail ==="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
