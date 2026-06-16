# Rebuilding VOICES from v1 source (maintainers)

> Not needed to run the stack — the built artefacts already ship in `output/`.
> This is for maintainers re-materialising the dataset from the upstream v1
> N-Quads. It requires Python 3.11 and the v1 output directory mounted
> read-only (`V1_OUTPUT_DIR` in `.env`).

`make build` runs two streaming passes over the v1 N-Quads:

1. **`src/rebuild/filter.py`** — drops the `concepts` named graph, strips
   `voices:mentionsConcept` triples, and re-mints every
   `http://voices.uni.lu/vocab/term/<id>` IRI as `urn:voices:place:<slug>`
   using the English label carried in the events graph (slug collisions
   disambiguate by appending the numeric id). The published dataset
   carries no SFI thesaurus content; outward alignments to GeoNames and
   Wikidata use `skos:exactMatch`.
2. **`src/rebuild/relabel.py`** — appends any missing `rdf:type
   voices:Place` / `rdfs:label` triples into the `metadata` graph so every
   place has a declaration. Idempotent.

`make build` produces the **full** dump `output/kg2026_v2.nq` (plus
`output/stats.json`). The **public** dump `output/kg2026_v2_public.nq` is
then produced by `scripts/strip_transcript_text.py`, which removes the
`voices:transcriptText` literals.

The fail-loud post-build gate `make check` re-asserts SFI cleanliness: no
`vocab/term/`, no `graph:concepts`, no `mentionsConcept`. SKOS is unblocked
— it is a W3C vocabulary used by GeoNames and Wikidata for outward
alignment. `make all` chains the full maintainer pipeline:
`build → check → up → load → index → precompute → seed → smoke`.

---
