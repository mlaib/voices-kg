# VOICES Knowledge Graph — v2 (Thesaurus-free, Production-ready)

Companion release to the ISWC 2026 Resources Track paper

> **VOICES: An Ontology and Knowledge Graph for Modelling Multimodal
> Holocaust Survivor Testimonies**

This repository contains a clean, publishable rebuild of the VOICES knowledge graph.
Every dependency on the proprietary USC Shoah Foundation (SFI) thesaurus has been
removed; places and alignments are re-minted under this project's own namespace, and
the whole stack ships in a single `docker compose` for reviewer and public use.

See [`idea.md`](./idea.md) for the design rationale and [`plan.md`](./plan.md) for
the full implementation plan.

---

## Quick start

Prerequisites: Docker + Docker Compose, Python 3.11 (for the one-off re-materialization).

```bash
cd KG2026.paper_v2

# 1. Set local env (copy + edit if needed)
cp .env.example .env

# 2. Build the thesaurus-free knowledge graph
#    (reads from ../KG2026.paper/output/ by default; streams 3.4 GB once)
make build

# 3. Start the whole stack (Fuseki, Redis, Meilisearch, Admin API, Streamlit, Caddy)
make up

# 4. Load the KG + embeddings into Fuseki (first time only)
make load

# 5. Build search indexes and dropdown caches
make index
make precompute

# 6. Create the first admin user (idempotent)
make seed

# 7. Run smoke tests
make smoke
```

Then open **<https://localhost:8443>** in your browser and accept Caddy's self-signed
certificate.

### Demo credentials

The first admin user is created from `.env` on startup:

| Role  | Email                  | Password              |
|-------|------------------------|-----------------------|
| admin | `admin@voices.local`   | *(set via `ADMIN_PASSWORD` in `.env`)*   |

**Set `ADMIN_PASSWORD` in `.env` before starting the stack.** Run `make seed` after any change.

The admin console is reachable at **<https://localhost:8443/admin/>** — create
reviewer-role users there; they can log in at the same URL and browse the exploration
UI at `/`.

---

## Architecture

```
             ┌──────────────────────────────── Caddy (HTTPS, :8443) ──────────────────────────────┐
             │                                                                                     │
Browser ───► │  /auth/*, /admin/*, /api/*          →  FastAPI  (auth, admin, REST)                  │
             │  /sparql, /$/*                      →  Fuseki   (TDB2 + Jena Text Lucene)           │
             │  /downloads/*, /ontology/*          →  static (Caddy file_server)                    │
             │  /                                  →  Streamlit (gated by forward_auth)             │
             │                                                                                     │
             └────────────────────┬────────────────────┬──────────────────────┬────────────────────┘
                                  │                    │                      │
                              ┌───┴───┐          ┌─────┴─────┐          ┌─────┴──────┐
                              │ Redis │  ◄──────│  FastAPI   │───►     │ Meilisearch │
                              │(cache)│          │  + SQLite │          │ (full-text)│
                              └───────┘          └───────────┘          └────────────┘
                                                        │
                                                        └─► SPARQL — Fuseki
```

- **Fuseki** — TDB2 triplestore with Lucene text index for label lookups.
- **Redis** — shared query cache + session store (separate DBs per tenant).
- **Meilisearch** — fuzzy full-text search over ~640 K transcript segments.
- **FastAPI** (`admin/`) — auth (JWT in secure cookie), user management, REST API,
  rate-limited public endpoints, `/auth/verify` for Caddy's `forward_auth`.
- **Streamlit** (`app/`) — five-page exploration UI (home, interview browser,
  question templates, full-text search, SPARQL console, downloads). Caches hot
  data in Redis and reads dropdown options from pre-computed JSON snapshots.
- **Caddy** — HTTPS termination (internal CA locally, Let's Encrypt on a real
  domain), path routing, forward auth, gzip, HSTS.

### Service URLs

| Path                          | Service      | Auth                    |
|-------------------------------|--------------|-------------------------|
| `/`                           | Streamlit    | `REQUIRE_AUTH` toggle   |
| `/admin/`                     | FastAPI      | admin role only         |
| `/auth/login`                 | FastAPI      | public                  |
| `/api/interviews`, `/api/events`, `/api/search`, `/api/places`, `/api/similar/{id}` | FastAPI | public, 60 req/min/IP |
| `/sparql`                     | Fuseki       | public                  |
| `/downloads/kg2026_v2.nq`     | static       | public                  |
| `/ontology/voices_ontology_v2.ttl` | static  | public                  |
| `/healthz`                    | Caddy        | public                  |

---

## Adding users

Two ways:

**From the admin UI** — log in at `https://localhost:8443/admin/`, go to
*Users*, fill the form. New reviewers can log in immediately.

**From the CLI** — run inside the admin container:

```bash
docker compose exec admin python -c "
from admin.database import get_session, init_db
from admin.models import User, Role
from admin.security import hash_password
init_db()
with next(get_session()) as s:
    s.add(User(email='alice@example.org',
               password_hash=hash_password('choose-a-password'),
               role=Role.reviewer))
    s.commit()
"
```

---

## Rebuilding the KG from v1 source

`make build` runs two streaming passes over the v1 N-Quads:

1. **`src/rebuild/filter.py`** — line-based rewrite that drops the `concepts`
   named graph, strips `voices:mentionsConcept` triples, and re-mints every
   `http://voices.uni.lu/vocab/term/<id>` IRI as `urn:voices:place:<slug>`
   using the English label carried in the events graph. Deterministic slug
   collisions disambiguate by appending the numeric id. The published
   dataset carries no SFI Shoah Foundation thesaurus content. External
   alignments to GeoNames and Wikidata use `skos:exactMatch`, the W3C
   convention used by both target authorities for cross-vocabulary
   references.
2. **`src/rebuild/relabel.py`** — appends any missing
   `rdf:type voices:Place` / `rdfs:label` triples into the `metadata` graph
   so every place has a declaration. Idempotent.

Output: `output/kg2026_v2.nq` + optional `.nqs` + `utterance_embeddings_v2.nq`
+ `output/stats.json` (machine-readable build summary).

Post-build correctness checks (`make check`) fail loud if any
SFI-thesaurus content reappears in the output: namely, any
`vocab/term/`, the `graph:concepts` named graph, or the
`mentionsConcept` predicate. SKOS itself is not blocked — it's a W3C
vocabulary used by GeoNames and Wikidata, and we use it for outward
alignment.

---

## Deploying to a VM

The local stack is the same stack. For a real deployment:

1. DNS: point `voices.your-domain.org` at the VM's public IP.
2. Caddyfile: replace `tls internal` with the domain (`voices.your-domain.org`)
   and Caddy will fetch Let's Encrypt certs automatically.
3. `.env`: set `PUBLIC_BASE_URL=https://voices.your-domain.org`, rotate
   `JWT_SECRET`, `FUSEKI_ADMIN_PASSWORD`, `MEILI_MASTER_KEY`, `ADMIN_PASSWORD`.
4. Open ports 80 and 443 in the VM firewall.
5. `make all` on the VM after rsyncing the `output/` directory (or re-running
   `make build` with the v1 source mounted).
6. For public release (after acceptance), set `REQUIRE_AUTH=false` to drop
   the login wall on `/`; `/admin/*` stays gated.

---

## Licence

- **Code**: TBD.
- **Knowledge graph, ontology, alignments**: TBD.
- **Transcripts**: belong to their original rights-holders; not redistributed here.

The SFI thesaurus is deliberately absent; refer to the SFI VHA for that vocabulary.
