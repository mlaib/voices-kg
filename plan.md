# Implementation Plan — KG2026.paper_v2

Goal: running, publishable, thesaurus-free stack deployed via `docker compose up`
with admin auth, user management, SPARQL+search+API endpoints, and reviewer-grade
polish. Delivered incrementally across eight phases.

---

## ⏸ RESUME HERE (paused 2026-04-22)

### State at pause

**Built & tested:**
- ✅ Folder skeleton, `idea.md`, `plan.md`, `README.md` (with demo credentials).
- ✅ Infra config: `docker-compose.yml`, `Caddyfile`, `Dockerfile`s, `Makefile`, `.env`.
- ✅ `src/rebuild/filter.py` + `relabel.py` — tested on fixture, ran full-size.
- ✅ `admin/` FastAPI package — auth, users, REST API, all endpoints compile and serve.
- ✅ `app/` Streamlit — 5 pages, components, compiled OK.
- ✅ `scripts/` — indexers (Meilisearch, FAISS), precompute, fuseki_load, smoke.
- ✅ Docker images built (`voices-kg-v2-admin`, `voices-kg-v2-app`).
- ✅ Stack running healthy (all 6 services), HTTPS on `https://localhost:8443` via Caddy internal CA.
- ✅ Auth flow verified end-to-end: `admin@voices.local` / <REDACTED> → login → JWT cookie → `/admin/` returns 200, `/` returns 200.
- ✅ SPARQL routing via Caddy verified (`/sparql` → Fuseki `/voices/sparql`).

**Data generated (build_v2.sh finished cleanly):**
- ✅ `output/kg2026_v2.nq` — 2.9 GB, 17,186,500 quads + 127,440 relabel quads appended.
- ✅ `output/utterance_embeddings_v2.nq` — 412 MB, 2,589,820 quads.
- ✅ `output/stats.json` — 6,680 places minted, 260,050 SFI IRIs rewritten, 3.1M concepts-graph quads dropped, 0 slug collisions, 63,720 place labels + types emitted.
- ✅ Relabel step ran: every `urn:voices:place:X` has `rdf:type voices:Place` and `rdfs:label` in the metadata graph.

**NOT yet done:**
- ⏳ Fuseki load (upload 3.3 GB of quads — ~20–30 min).
- ⏳ Meilisearch segment indexing (`scripts/index_meilisearch.py`).
- ⏳ FAISS embedding index (`scripts/index_faiss.py`) — note the indexer expects actual vectors in the sidecar parquet dir under v1 `data/processed/utterance_embeddings/openai/`, not in the .nq.
- ⏳ Precompute dropdown JSON caches (`scripts/precompute_caches.py`).
- ⏳ Final smoke tests via `scripts/smoke.sh`.
- ⏳ Ontology HTML docs (WIDOCO) — optional, out-of-scope for MVP.

### How to resume

From `/mnt/d/Projets/voices/workspace/KG2026.paper_v2/`:

```bash
# 1. Confirm state — stats.json, relabel, and stack.
ls -la output/              # expect kg2026_v2.nq, utterance_embeddings_v2.nq, stats.json
cat output/stats.json | python3 -m json.tool

# 2. Make sure stack is up (it was up when paused; `make up` is idempotent).
make up
docker compose ps           # all 6 services should be healthy

# 3. Load the KG into Fuseki (~20–30 min for 3.3 GB upload).
bash scripts/fuseki_load.sh
# or: make load

# 4. Build Meilisearch segment index (requires Fuseki loaded).
# Meilisearch isn't host-exposed; run inside the network via admin container:
docker compose exec admin python /scripts/index_meilisearch.py
# (or temporarily expose Meilisearch port and run from host)

# 6. Build FAISS index — needs the sidecar parquet embeddings.
#    If they're not already at data/processed/utterance_embeddings/openai/,
#    set EMBEDDINGS_DIR to point at the v1 location.
EMBEDDINGS_DIR=/mnt/d/Projets/voices/workspace/KG2026.paper/data/processed/utterance_embeddings/openai \
  python3 scripts/index_faiss.py

# 7. Precompute dropdown JSON caches.
python3 scripts/precompute_caches.py

# 8. End-to-end smoke test.
bash scripts/smoke.sh

# 9. Open the app.
# https://localhost:8443   (accept self-signed cert)
# Login: admin@voices.local / <password from .env>
```

### Known issues / quirks to be aware of

- **Caddy self-signed cert**: browsers show a warning on first visit; click through. On a real domain, switch `Caddyfile` site address from `localhost, :80, :443` to the domain; Let's Encrypt is automatic.
- **Meilisearch indexer**: run inside the Docker network (`docker compose exec admin …`) because port 7700 is not bound on the host. Alternative: publish 7700 temporarily in `docker-compose.yml` under the `meilisearch` service.
- **FAISS indexer**: depends on parquet embeddings at a path outside the repo. If they're missing, `scripts/index_faiss.py` exits 0 with a warning and the similarity page gracefully degrades.
- **`make build` vs. `bash scripts/build_v2.sh`**: build_v2.sh patched to call `python3` explicitly (pyenv shims require it on this box). The Makefile uses `$(PY)` which resolves to `python3`.
- **Streamlit pages expect caches**: if `output/caches/*.json` are missing, pages fall back to live SPARQL — slower first paint but still works.

### Minimum viable "resume & go"

If the user just wants the app reachable with data:
```bash
cd /mnt/d/Projets/voices/workspace/KG2026.paper_v2
python3 -m src.rebuild.relabel --input output/kg2026_v2.nq
make up
bash scripts/fuseki_load.sh
# open https://localhost:8443
```

Meilisearch + FAISS are nice-to-have; the Explore + SPARQL pages work without them.

---


## Repository layout

```
KG2026.paper_v2/
├── README.md
├── idea.md
├── plan.md
├── docker-compose.yml
├── .env.example
├── Makefile
├── config/
│   └── config.yaml
├── docker/
│   ├── caddy/Caddyfile
│   ├── fuseki/config.ttl
│   └── streamlit.Dockerfile, admin.Dockerfile
├── src/
│   ├── common/ (shared utilities)
│   └── rebuild/
│       ├── filter.py          # SFI strip + place re-mint (pass 1+2)
│       ├── relabel.py         # emit labels graph (pass 3)
│       ├── realign.py         # fresh Wikidata/GeoNames alignments
│       └── topics.py          # optional additive Wikidata topic linker
├── schema/
│   ├── voices_ontology_v2.ttl  # copy, SFI refs stripped
│   └── voices-alignment-v2.ttl # new, no SFI
├── queries/
│   └── (updated queries, no SFI assumptions)
├── scripts/
│   ├── build_v2.sh             # end-to-end rebuild
│   ├── fuseki_load.sh
│   ├── index_meilisearch.py
│   ├── index_faiss.py
│   ├── precompute_caches.py
│   └── seed_admin.py
├── app/                        # Streamlit (copy + modify from v1)
│   ├── app.py
│   ├── components/
│   │   ├── data_loader.py
│   │   ├── sparql_client.py
│   │   ├── search_client.py    # Meilisearch
│   │   ├── similarity.py       # FAISS
│   │   ├── redis_cache.py
│   │   └── auth_gate.py
│   └── pages/
│       ├── 01_Interview_Explorer.py
│       ├── 02_Explore.py
│       ├── 03_Search.py        # new
│       ├── 04_SPARQL.py
│       └── 05_Downloads.py     # new
├── admin/                      # FastAPI
│   ├── main.py
│   ├── deps.py                 # DB + auth dependencies
│   ├── models.py               # SQLModel User/Role
│   ├── routes/
│   │   ├── admin.py            # /admin/* (gated)
│   │   ├── api.py              # /api/* (public, rate-limited)
│   │   └── auth.py             # /login, /logout, /me
│   └── templates/
│       ├── base.html
│       ├── login.html
│       └── admin.html
├── output/                     # generated artefacts (gitignored)
└── data/                       # symlinks to v1 input (gitignored)
```

## Phase 1 — Scaffolding & config (no heavy work)

- [x] Create folder skeleton.
- [x] Write `idea.md`, `plan.md`.
- [ ] Write `.env.example` with all required variables, ports, passwords.
- [ ] Write top-level `docker-compose.yml` — 6 services: fuseki, redis, meilisearch,
      admin (FastAPI), app (Streamlit), caddy.
- [ ] Write `docker/caddy/Caddyfile` with path routing + HTTPS (local self-signed).
- [ ] Write `docker/fuseki/config.ttl` with TDB2 + Jena Text index assembler.
- [ ] Write `config/config.yaml` capturing service URLs, paths, graph names.
- [ ] Write Dockerfiles: `docker/streamlit.Dockerfile`, `docker/admin.Dockerfile`.
- [ ] Write `Makefile` with one-shot targets: `build`, `load`, `index`, `up`, `seed`.

**Ports (no conflict with v1 3031/8502):**
- Fuseki: 3032 (internal 3030)
- Redis: 6380
- Meilisearch: 7700
- Admin (FastAPI): 8010
- App (Streamlit): 8503
- Caddy: 443/80

## Phase 2 — Re-materialize the KG (SFI-free)

- [ ] `src/rebuild/filter.py`: streaming pass over `v1/output/kg2026_paper.nq`
      that produces `output/kg2026_v2.nq`:
  - skip `<…:graph:concepts>` quads
  - rewrite SFI place IRIs → `urn:voices:place:<slug>`, using a scan-first label map
  - drop `voices:mentionsConcept` quads
  - skip alignment triples whose subject is an SFI IRI (we rebuild them)
  - preserve events, annotations, embeddings, metadata, transcripts, provenance
- [ ] `src/rebuild/relabel.py`: emit `<urn:voices:place:slug> a voices:Place ; rdfs:label "…"@en .`
      triples into `metadata` graph.
- [ ] `src/rebuild/realign.py`: for each surviving place, Wikidata+GeoNames lookup
      (cached, resumable, rate-limited), emit `skos:exactMatch` into `alignment`
      graph. Coverage reported as a build stat.
- [ ] RDF-star .nqs file: regenerate from v1 `.nqs` with same rewrites.
- [ ] `scripts/build_v2.sh`: orchestrate the above, produce
      `output/{kg2026_v2.nq, kg2026_v2.nqs, stats.json}`.
- [ ] Clean ontology: `schema/voices_ontology_v2.ttl` with SFI references removed;
      `schema/voices-alignment-v2.ttl` replaces the data/thesaurus ttl.

Acceptance: `output/kg2026_v2.nq` contains zero `sfi` substrings; places all have
labels; Wikidata coverage printed.

## Phase 3 — Infrastructure (triplestore + indexes + cache)

- [ ] `scripts/fuseki_load.sh`: uploads both .nq and .nqs files to Fuseki, verifies
      count.
- [ ] `scripts/index_meilisearch.py`: extracts segment text with interview+timestamp
      and ships to Meilisearch for fuzzy full-text. One JSON doc per segment.
- [ ] `scripts/index_faiss.py`: reads embeddings from `.nq`, builds FAISS IVFFlat
      index, dumps to `output/similarity.faiss` + `output/similarity.ids.json`.
- [ ] `scripts/precompute_caches.py`: computes static JSON files consumed by the app:
      activity list, emotion list, places list (top-N), interviews list, corpus
      summary stats — one SPARQL query each, dumps to `output/caches/`.

Acceptance: three non-Fuseki indexes are built; reindex repeatable via Makefile target.

## Phase 4 — Streamlit exploration app

- [ ] Copy `KG2026.paper/app/*` to `app/`, remove concept-graph dependencies.
- [ ] `components/sparql_client.py`: unchanged shape, but queries run against 3032
      and tolerate absence of `concepts` graph.
- [ ] `components/redis_cache.py`: wrapper around Redis for query-result cache keyed
      on SPARQL hash + graph version. Falls back to in-memory if Redis down.
- [ ] `components/search_client.py`: thin wrapper over Meilisearch SDK.
- [ ] `components/similarity.py`: thin wrapper over FAISS index (memory-mapped).
- [ ] `components/auth_gate.py`: reads session cookie set by FastAPI; redirects to
      `/login` if absent; exposes current-user helper.
- [ ] Pages:
  - `01_Interview_Explorer.py` — unchanged semantics, reads pre-computed JSON for
    its dropdowns.
  - `02_Explore.py` — question templates; drop any concept-graph template; add a
    "search transcript" template powered by Meilisearch.
  - `03_Search.py` — dedicated Meilisearch UI with filters.
  - `04_SPARQL.py` — unchanged; add sample queries that use SPARQL-star for
    confidence/provenance.
  - `05_Downloads.py` — download links for `.nq`, `.nqs`, ontology, queries,
    with DCAT metadata.
- [ ] `app.py` home page: corpus stats from pre-computed JSON, one SPARQL-free chart.

Acceptance: app launches without Fuseki running and shows pre-computed data; with
Fuseki up, all pages fully functional.

## Phase 5 — FastAPI admin + REST API

- [ ] `admin/main.py`: FastAPI app; mounts `/auth`, `/admin`, `/api`.
- [ ] `admin/models.py`: SQLModel `User(id, email, password_hash, role, created_at,
      last_login)`, `Role in {admin, reviewer}`.
- [ ] `admin/deps.py`: DB session, `current_user`, `require_admin` dependencies;
      bcrypt + JWT (signed secure cookie, not header).
- [ ] `routes/auth.py`:
  - `POST /auth/login` → set httponly cookie, redirect.
  - `POST /auth/logout` → clear cookie.
  - `GET /auth/me` → JSON current user.
- [ ] `routes/admin.py`:
  - `GET /admin/` → dashboard (user count, cache stats, build info).
  - `GET /admin/users` → list; `POST /admin/users` → create; `DELETE /admin/users/{id}`;
    `POST /admin/users/{id}/reset`.
  - `POST /admin/cache/flush` → flushes Redis.
  - `POST /admin/reindex/meilisearch` → background task running `index_meilisearch.py`.
  - `GET /admin/logs` → tail of recent application log.
- [ ] `routes/api.py` (public, rate-limited):
  - `GET /api/interviews` paginated; `GET /api/interviews/{id}`.
  - `GET /api/events` with filters; `GET /api/events/{id}`.
  - `GET /api/search?q=…` → Meilisearch-backed.
  - `GET /api/places`, `GET /api/activities`, `GET /api/emotions`.
  - `GET /api/similar/{event_id}` → FAISS.
- [ ] Templates: minimal Jinja — base layout, login, admin dashboard; Tailwind
      via CDN for a clean look with no build step.
- [ ] `scripts/seed_admin.py`: creates first admin user interactively or from env
      (`ADMIN_EMAIL`, `ADMIN_PASSWORD`).

Acceptance: `curl -X POST /auth/login` returns cookie; `/admin/` blocks without
cookie; admin can add a reviewer and the reviewer can log into Streamlit.

## Phase 6 — Caddy routing and auth gate

- [ ] `Caddyfile`:
  - `/auth/*` and `/admin/*` and `/api/*` → `admin:8010`.
  - `/sparql`, `/dataset` → `fuseki:3030` (public, rate-limited).
  - `/ontology/*` → static files in Fuseki volume (content negotiation).
  - `/` (all else) → `forward_auth admin:8010/auth/verify` then `app:8501`.
  - `/healthz` simple.
  - Compress responses.
- [ ] FastAPI `/auth/verify`: checks cookie, returns 200 with `X-User` header or
      302 to `/auth/login`.
- [ ] `REQUIRE_AUTH` env var: when `false`, `forward_auth` is disabled in Caddy
      (dev mode or post-acceptance public release).
- [ ] Local HTTPS via Caddy's internal CA (`tls internal`).

Acceptance: `curl https://localhost/` redirects to login; after login, reaches
Streamlit; `/admin` requires role=admin.

## Phase 7 — Launch & smoke tests

- [ ] `make build` → re-materialize KG (phases 2–3).
- [ ] `make up` → `docker compose up -d`.
- [ ] `make seed` → create initial admin user from env.
- [ ] `make smoke`: runs curl-based checks:
  - Fuseki responds to `SELECT (COUNT(*))`.
  - Meilisearch health.
  - FastAPI `/auth/verify` returns 401.
  - Login → 200 + cookie.
  - `/admin/` with cookie → 200.
  - Streamlit app root → 200.
  - One SPARQL query end-to-end via the app's HTTP path.
- [ ] Fix any issues until smoke passes.

## Phase 8 — README + hand-off polish

- [ ] README with:
  - Quick start: `make up && make seed && open https://localhost`.
  - **Demo credentials:** `admin@voices.local` / *(set via `ADMIN_PASSWORD` in `.env`)*.
  - Architecture diagram.
  - Service URLs table.
  - Download links.
  - How to add users (both CLI and UI).
  - How to rebuild the KG from v1 source.
  - How to redeploy on a VM with a real domain.
- [ ] Ontology docs stub (WIDOCO job gated behind a Make target; doesn't block MVP).
- [ ] `.env.example` with every required var documented.

## Parallelism plan (for this session)

Phases 1 and 2 are pre-requisites for everything else (ports, paths, data).
Once scaffolding exists, the rest fan out:

- **Agent A** — re-materialize script + ontology cleaning (Phase 2).
- **Agent B** — Docker/Caddy/Fuseki config + dockerfiles (Phase 1 tail + 6).
- **Agent C** — FastAPI admin + REST + auth (Phase 5).
- **Agent D** — Streamlit app copy/modify + new pages (Phase 4).
- **Agent E** — Indexers + precompute + seed scripts (Phase 3).

Main agent integrates, runs `docker compose up`, iterates to green smoke.

## Out-of-scope (tracked, not done in this pass)

- WIDOCO ontology HTML generation (needs Java in container).
- GPT-powered Wikidata topic linker (additive stage, requires API key and compute).
- Uptime Kuma and other optional polish.
- Real-domain HTTPS (stays self-signed until VM hand-off).
- Kubernetes / scaling (Docker Compose is the deployment target for now).
