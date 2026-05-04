# VOICES Knowledge Graph — v2

[![Code: Apache-2.0](https://img.shields.io/badge/Code-Apache--2.0-blue.svg)](LICENSE)
[![Data: CC BY 4.0](https://img.shields.io/badge/Data-CC%20BY%204.0-lightgrey.svg)](LICENSE-DATA.md)
[![ISWC 2026](https://img.shields.io/badge/ISWC-2026%20Resources%20Track-orange.svg)](https://iswc2026.semanticweb.org/)

Companion release to the ISWC 2026 Resources Track paper:

> **VOICES: An Ontology and Knowledge Graph for Modelling Multimodal
> Holocaust Survivor Testimonies.**

VOICES models Holocaust survivor testimonies — interviews, segments,
narrated events, places, emotions, embeddings, and alignments to external
authorities — as a Linked Data resource. The repository ships an OWL 2
ontology, a populated knowledge graph (≈16.7 M quads across seven named
graphs), an alignment graph linking minted place IRIs to GeoNames and
Wikidata, a reproducible evaluation framework, and a Dockerised
exploration stack (Fuseki + FastAPI + Streamlit + Caddy).

---

## Conceptual model

The ontology centres a `NarratedEvent` hub linking the `Interview` /
`InterviewSegment` spine to typed dimensions (participants, places,
activity, cause, mode, time, emotion, embeddings) and to a `HistoricalEvent`
side reference for outward alignment.

![VOICES ontology — conceptual model](docs/figures/VOICES-Ontology.png)

## Construction pipeline

A four-stage pipeline parses 982 XML transcripts into 647,455 utterances,
extracts 334,434 narrated events via an LLM, enriches them with GeoNames
and Wikidata authorities, and materialises the result into seven named
graphs in N-Quads.

![VOICES KG construction pipeline](docs/figures/VOICES-Pipeline.png)

---

## Contents of this repository

| Path | What |
|---|---|
| [`schema/`](schema/) | Ontology (`voices_ontology_v2.ttl`) and alignment graph (`voices-alignment-v2.ttl`) |
| [`src/`](src/) | KG construction pipeline (parsing, extraction, enrichment, materialisation) |
| [`app/`](app/) | Streamlit exploration UI |
| [`admin/`](admin/) | FastAPI auth + admin + REST API |
| [`docker/`](docker/) | Caddy + Fuseki container configuration |
| [`scripts/`](scripts/) | Build, deploy, indexing, and CI gate scripts |
| [`queries/`](queries/) | 15 SPARQL competency-question queries (`cq01..cq15`) |
| [`evaluation/`](evaluation/) | Reproducible evaluation framework (alignment + events) |
| [`output/`](output/) | Build artefacts (KG dumps, embeddings, statistics) |
| [`docs/`](docs/) | Figures and supporting documentation |

---

## Quick start

**Prerequisites.** Docker + Docker Compose; Python 3.11 (only for the
one-off rebuild from v1 source).

```bash
cd KG2026.paper_v2

# 1. Set local environment (copy + edit if needed)
cp .env.example .env

# 2. Build the knowledge graph (~3 GB, ~10 min, streams once)
make build

# 3. Start the full stack (Fuseki, Redis, Meilisearch, Admin API, Streamlit, Caddy)
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

Open <https://localhost:8443> and accept Caddy's self-signed certificate.

### Demo credentials

The first admin user is created from `.env` on startup:

| Role  | Email                | Password                                |
|-------|----------------------|-----------------------------------------|
| admin | `admin@voices.local` | *(set via `ADMIN_PASSWORD` in `.env`)* |

> **Set a strong `ADMIN_PASSWORD` in `.env` before starting the stack.**
> Run `make seed` after any change.

The admin console is reachable at <https://localhost:8443/admin/> —
create reviewer-role users there; they can log in at the same URL and
browse the exploration UI at `/`.

---

## Architecture

```
             ┌──────────────────── Caddy (HTTPS, :8443) ────────────────────┐
             │                                                              │
Browser ───► │  /auth/*, /admin/*, /api/*  →  FastAPI  (auth, admin, REST)  │
             │  /sparql, /$/*              →  Fuseki   (TDB2 + Lucene)      │
             │  /downloads/*, /ontology/*  →  static (Caddy file_server)    │
             │  /                          →  Streamlit (forward_auth)      │
             │                                                              │
             └────────────────┬───────────────┬────────────────┬────────────┘
                              │               │                │
                          ┌───┴───┐     ┌─────┴─────┐    ┌─────┴──────┐
                          │ Redis │ ◄──│  FastAPI   │──► │ Meilisearch│
                          │(cache)│     │  + SQLite  │    │ (full-text)│
                          └───────┘     └────────────┘    └────────────┘
                                              │
                                              └─► SPARQL — Fuseki
```

| Component | Role |
|---|---|
| **Fuseki** | Apache Jena TDB2 triplestore with Lucene text index for label lookups |
| **Redis** | Shared query cache + session store (separate DBs per tenant) |
| **Meilisearch** | Fuzzy full-text search over ~647 K transcript segments |
| **FastAPI** (`admin/`) | Auth (JWT in secure cookie), user management, REST API, rate-limited public endpoints, `/auth/verify` for Caddy `forward_auth` |
| **Streamlit** (`app/`) | Multi-page exploration UI (interview browser, narrative sankey, emotion arcs, full-text search, SPARQL console, downloads) |
| **Caddy** | HTTPS termination, path routing, forward auth, gzip, HSTS |

### Service URLs

| Path | Service | Auth |
|---|---|---|
| `/` | Streamlit | `REQUIRE_AUTH` toggle |
| `/admin/` | FastAPI | admin role only |
| `/auth/login` | FastAPI | public |
| `/api/interviews`, `/api/events`, `/api/search`, `/api/places`, `/api/similar/{id}` | FastAPI | public, 60 req/min/IP |
| `/sparql` | Fuseki | public |
| `/downloads/kg2026_v2_public.nq` | static | public |
| `/ontology/voices_ontology_v2.ttl` | static | public |
| `/healthz` | Caddy | public |

---

## Data and downloads

The published artefacts are streamed by Caddy from `output/` and `schema/`.

| Artefact | Approx. size | Notes |
|---|---|---|
| `output/kg2026_v2_public.nq` | ~2.6 GB | Public KG dump (16.66 M quads) — see *Transcript text* below |
| `output/utterance_embeddings_v2.nq` | ~393 MB | OpenAI `text-embedding-3-small` over 647 K segments, as RDF literals |
| `output/stats.json` | ~1 KB | Machine-readable build summary |
| `schema/voices_ontology_v2.ttl` | ~30 KB | OWL 2 DL ontology (Turtle), version 2.1 |
| `schema/voices-alignment-v2.ttl` | ~250 KB | 2,530 outward `skos:exactMatch` triples |
| `queries/cq01..cq15.rq` | small | Competency-question SPARQL queries |

### Transcript text

The full dump (`output/kg2026_v2.nq`) embeds the literal transcript text of
the testimonies via the `voices:transcriptText` property. That text is
sourced from the **USC Shoah Foundation Visual History Archive (VHA)** and
remains copyrighted by its rights-holders.

- The publicly downloadable file (`kg2026_v2_public.nq`) **excludes the
  ~647 K `voices:transcriptText` literals**. All other named graphs are
  intact and queryable.
- For the original transcript text, please refer to the **USC Shoah
  Foundation VHA** at <https://sfi.usc.edu/vha>.
- Researchers with their own VHA access who need the full dump for
  replication can contact the maintainer.

See [`LICENSE-DATA.md`](LICENSE-DATA.md) for the full per-component
licensing matrix.

---

## Rebuilding the KG from v1 source

`make build` runs two streaming passes over the v1 N-Quads:

1. **`src/rebuild/filter.py`** — line-based rewrite that drops the
   `concepts` named graph, strips `voices:mentionsConcept` triples, and
   re-mints every `http://voices.uni.lu/vocab/term/<id>` IRI as
   `urn:voices:place:<slug>` using the English label carried in the
   events graph. Deterministic slug collisions disambiguate by appending
   the numeric id. The published dataset carries no SFI thesaurus
   content; outward alignments to GeoNames and Wikidata use
   `skos:exactMatch`, the W3C convention used by both target authorities
   for cross-vocabulary references.
2. **`src/rebuild/relabel.py`** — appends any missing
   `rdf:type voices:Place` / `rdfs:label` triples into the `metadata`
   graph so every place has a declaration. Idempotent.

Output: `output/kg2026_v2.nq` (full), `output/kg2026_v2_public.nq` (after
running `scripts/strip_transcript_text.py`), `output/utterance_embeddings_v2.nq`,
and `output/stats.json`.

The fail-loud post-build gate `make check` re-asserts SFI cleanliness:
no `vocab/term/`, no `graph:concepts`, no `mentionsConcept`. SKOS itself
is unblocked — it is a W3C vocabulary used by GeoNames and Wikidata, and
we use it for outward alignment.

---

## Evaluation

A reproducible evaluation framework lives in [`evaluation/`](evaluation/),
with two strands:

- **Alignment quality.** A 200-row stratified sample (134 GeoNames + 66
  Wikidata) is auto-judged via cross-reference to Wikidata's `wdt:P1566`
  (GeoNames id) property; the script reports precision over the sample
  alongside the rubric used for human re-verification.
- **Event extraction quality.** A 100-event deterministic sample is
  scored against a per-dimension rubric (subject, action, place, time,
  affect) covering both factual extraction and structural plausibility.

Each subdirectory contains its own `README.md`, `RUBRIC.md`, the sample
CSV, the judgment CSV, and the precision-computation script — re-running
`python compute_precision.py` produces the figures cited in the paper.

---

## Deploying to a VM

The local stack is the same stack. For a real deployment:

1. **DNS.** Point `voices.your-domain.org` at the VM's public IP.
2. **Caddyfile.** Replace `tls internal` with the domain
   (`voices.your-domain.org`) and Caddy will fetch Let's Encrypt certs
   automatically.
3. **`.env`.** Set `PUBLIC_BASE_URL=https://voices.your-domain.org` and
   rotate `JWT_SECRET`, `FUSEKI_ADMIN_PASSWORD`, `MEILI_MASTER_KEY`,
   `ADMIN_PASSWORD`.
4. **Firewall.** Open ports 80 and 443 in the VM firewall.
5. **`make all`** on the VM after rsyncing the `output/` directory (or
   re-running `make build` with the v1 source mounted).
6. **Public release.** Set `REQUIRE_AUTH=false` to drop the login wall on
   `/`; `/admin/*` stays gated.

---

## Citation

If you use VOICES in academic work, please cite:

```bibtex
@dataset{voices_kg_v2_2026,
  title       = {VOICES Knowledge Graph v2},
  subtitle    = {Holocaust survivor testimonies as RDF events,
                 emotions, places, and temporal alignments},
  author      = {Pruski, C{\'e}dric and Laib, Mohamed and
                 Da Silveira, Marcos and Toth, Gabor Mihaly},
  year        = {2026},
  version     = {2.0},
  institution = {Luxembourg Institute of Science and Technology (LIST)},
  note        = {Living resource — continuously updated}
}
```

---

## Licence

VOICES is released under a per-component licence:

| Component | Licence |
|---|---|
| Code (`src/`, `app/`, `admin/`, `scripts/`, `docker/`, evaluation `.py`) | **Apache License 2.0** ([`LICENSE`](LICENSE)) |
| Ontology, alignment graph, evaluation rubrics + samples, public KG dump | **CC BY 4.0** |
| Full KG dump (with transcript text) | **Not redistributed** — refer to USC Shoah Foundation VHA |

Full details in [`LICENSE-DATA.md`](LICENSE-DATA.md).

---

## Maintainer

**Mohamed Laib** — `mohamed.laib@list.lu`
Luxembourg Institute of Science and Technology (LIST)
