# VOICES KG v2 — Thesaurus-free, Publication-ready

## What this release is

A clean, publishable rebuild of the VOICES Holocaust-testimony knowledge graph that
**removes every dependency on the USC Shoah Foundation (SFI) thesaurus** and ships a
production-grade application for reviewers and public users.

The underlying ontology, event extractions, embeddings, and annotations are preserved.
Only the licensed vocabulary layer is gone, and the places/concepts/alignments that
referenced it have been re-minted under the project's own namespace with fresh
alignments to open standards.

## Why the thesaurus had to go

The SFI Subject Thesaurus is a proprietary SKOS vocabulary. Republishing it (or any
derivative that exposes its IRI structure) requires a paid license. The v1 KG used it
in three places:

1. **Topic tagging** — segments were linked to SFI concepts (`concepts` named graph).
2. **Place identifiers** — matched places took the SFI term IRI as their primary URI.
3. **Wikidata/GeoNames alignments** — the `alignment` graph was keyed on SFI term IDs,
   so external links chained through SFI.

A surface strip of the `concepts` graph would have left orphan SFI IRIs throughout the
events and alignment graphs — blank labels, broken queries, and a legally ambiguous
artefact. The v2 work re-mints everything instead.

## What changes in the graph

| Aspect | v1 (SFI-bound) | v2 (clean) |
|---|---|---|
| Place IRIs | `http://sfi…/term/<id>` | `urn:voices:place:<slug>` |
| Place labels | In `concepts` graph | In `metadata` graph, native |
| Topic layer | SFI concept IRIs | Wikidata topics (additive stage) |
| Alignments | SFI → Wikidata/GeoNames | Local-place → Wikidata/GeoNames |
| `concepts` graph | SFI SKOS hierarchy | Wikidata topics only |
| Ontology imports | SFI references | EHRI-friendly, no SFI |
| License | Mixed (SFI non-redistributable) | CC-BY 4.0 end-to-end |

**Event structure, emotions, embeddings, similarity, provenance, and RDF-star
annotations are unchanged.** The v1 .nq is the upstream source; v2 is a transformation
of it.

## Design principles

1. **Self-contained.** No runtime dependency on a licensed vocabulary. Every IRI that
   appears in the public `.nq` resolves against this project's namespace or a
   standard open vocabulary (Wikidata, GeoNames, SKOS core, FOAF, PROV-O).
2. **Extensible at the alignment layer.** The `alignment` named graph is a drop-in
   attachment point — any external SKOS vocabulary (EHRI, LoC, Yad Vashem) can be
   added later by publishing `skos:exactMatch` triples. The core KG is vocabulary-agnostic.
3. **Publishable as a resource.** Dereferenceable URIs, content negotiation (HTML/TTL),
   ontology documentation, VoID/DCAT metadata, example SPARQL queries, permanent
   download links.
4. **Built for interaction, not just storage.** A reviewer/user-facing app sits
   on top with full-text search, interview browsing, question-template exploration,
   and free SPARQL — with proper auth, admin tooling, and performance engineering.

## Rebuild approach — "partial re-materialization"

Rather than re-run LLM extraction (days of compute, non-deterministic), v2 transforms
the existing `output/kg2026_paper.nq` in a streaming pass:

1. **Scan** the `concepts` graph once, build `{ SFI-IRI → english label }` map for
   every place concept that was referenced.
2. **Stream-rewrite** the full `.nq`:
   - Skip all quads in the `concepts` named graph.
   - Skip `skos:exactMatch`/`skos:closeMatch` quads whose subject is an SFI IRI that
     is not chained through a place IRI that survives.
   - Rewrite every SFI-place IRI to `urn:voices:place:<slug>` throughout events and
     annotations graphs.
   - Drop topic-tagging predicates (`voices:mentionsConcept` → SFI).
   - Emit a fresh `metadata`-style graph declaring `<urn:voices:place:X> a voices:Place ; rdfs:label "…"@en`.
3. **Rebuild** the alignment graph: for every surviving place, look up Wikidata +
   GeoNames by label (cached, rate-limited, resumable) and emit `skos:exactMatch`
   triples keyed on the new local IRIs.
4. **(Optional additive stage)** Per-event Wikidata topic linker — extracts a short
   list of Wikidata QIDs from each event's `whatText` and emits them into a rebuilt
   `concepts` graph. Runs independently of the main filter pipeline and can be
   skipped or deferred without affecting correctness.

The result is `kg2026_v2.nq` + `kg2026_v2.nqs` (star), ready to load into Fuseki.

## App and deployment shape

A **two-service app** behind a **Caddy reverse proxy**:

- **Streamlit** (`/`) — exploration UI (testimony browser, question templates, free
  SPARQL, full-text search, similarity). Caches hot data in Redis and pre-computed
  JSON snapshots at build time.
- **FastAPI** (`/admin/*`, `/api/*`) — admin console (user management, cache flush,
  reindex trigger) + public REST API for programmatic access. Auth via secure
  cookies; users in SQLite.

Backed by:

- **Fuseki TDB2 + Jena Text (Lucene)** — SPARQL endpoint with label-index speedups.
- **Meilisearch** — fuzzy full-text over transcript segments (the capability Fuseki
  cannot provide well).
- **FAISS** — precomputed similarity index for the embeddings graph.
- **Redis** — shared cache and session store.

All orchestrated via a single `docker-compose.yml` that reproduces the whole stack
on any VM with Docker.

## Reviewer-visible "best-app" commitments

- First pageload under 1s after caches are warm.
- Every page works offline from the pre-computed JSON where possible.
- Ontology is auto-documented (WIDOCO) and browseable at `/ontology/`.
- `curl -H "Accept: text/turtle" http://host/resource/place/<slug>` returns TTL.
- SPARQL-star pages show confidence, extraction method, and provenance on edges
  directly — no reification ceremony.
- Download links for the `.nq`, `.nqs`, ontology, and example queries are one click.

## Scope boundaries (what v2 does not promise)

- **No SFI-level topic coverage.** The additive Wikidata-topic stage is lighter;
  it's per-event entity/topic linking, not the curated hierarchical tagging SFI
  provided. This is documented as extensible via EHRI/LoC in future work.
- **No LLM re-extraction.** Events are reused from v1 as-is.
- **No automated fact-checking.** Confidence is self-reported by the extractor, not
  validated against external ground truth.
