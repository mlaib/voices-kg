# VOICES KG construction pipeline

This directory contains the **construction** pipeline that builds the VOICES
knowledge graph from raw testimony transcripts — i.e. the four stages described
in §4 of the paper. It is **separate from the repository's serving stack**
(`../app`, `../admin`, `../docker`, `../src`), which only *hosts* the already-built
KG. In short:

- `pipeline/`  →  **build** the KG (transcripts → N-Quads)
- repo root    →  **serve** the pre-built KG (Fuseki + API + Streamlit)

Code is released under **Apache-2.0** (same as the rest of the repo's code). The
**inputs** are gated (see *Inputs* below) and are **not** redistributed here.

---

## Stage map (→ paper §4)

| Stage | Dir / file | Paper | What it does |
|---|---|---|---|
| 1. Parse & segment | `stage1_parse/parse_transcripts.py`, `create_utterances_v2.py` | §4.1 | VHA XML (`<p>`/`<span>`, `m` timestamps) → `utterances.parquet`; forward-fill speakers, stable IDs |
| 2. LLM extraction | `stage2_extract/event_extractor_v6.py` (+ `prompts/event_extraction_prompt.md`) | §4.2 | `gpt-4o-mini` (temp 0.3, JSON mode) extracts **who/what/where/when/emotion** per utterance → `events_v6.parquet` |
| 2b. Resolve | `stage2_extract/export_v6_to_parquet.py`, `scripts/resolve_events_v7.py` | §4.2–4.3 | export to parquet; pronoun resolution (`I`→survivor) + context-fill of `where`/`when` → `events_v7.parquet` |
| 3. Enrich / transform | `src/transform/` | §4.3 | from `what`: regex classify **14 activities / 5 causes / 6 modes / 10 historical events**; `when`→OWL-Time interval + 10 period buckets; `emotion`→valence/arousal + 4 macro-categories + `[CRYING]`-style physiological markers; place/person resolution |
| 4. Materialise | `src/serialize/nquads.py`, `src/build.py` | §4.4 | emit N-Quads across the seven named graphs; embeddings (`text-embedding-3-small`, 1536-d) + cosine **similarity ≥ 0.82**, top-5 `similarTo`; PROV-O provenance; structural validation |

Orchestrator: `src/build.py` (`ingest → transform → serialize → validate`).
Key parameters live in `config/config.yaml`.

### How place alignment actually works (read this)

Place mentions are matched by **exact canonical label** to the archive's controlled
vocabulary (the SFI thesaurus); matched terms carry the thesaurus's **pre-computed**
GeoNames/Wikidata links, which VOICES re-publishes as `skos:exactMatch` (re-keyed to
local `urn:voices:place:` IRIs). Unmatched mentions are minted as local IRIs with no
outward link. There is **no live label-similarity query and no tunable place
threshold** — only an exact-match bridge. VOICES republishes **only the resulting
open links, never the proprietary thesaurus itself**, which is why the public release
is "thesaurus-free" even though the *build* uses the thesaurus internally. (The only
fuzzy threshold in the config, `concept_fuzzy_min: 0.85`, is for topic/concept linking,
which is stripped from the public KG.)

---

## Inputs (gated — not in this repo)

The pipeline consumes data that is **not ours to redistribute**:

- **VHA transcripts / derived parquet** (`data/**`): derived from the USC Shoah
  Foundation Visual History Archive — copyrighted. See the repo's *Data notice*.
- **SFI thesaurus + its alignment** (`config.paths.thesaurus_ttl`, `alignment_ttl`):
  proprietary controlled vocabulary used only as the internal place-alignment bridge.

The code **degrades gracefully when these are absent**: missing thesaurus → places
are minted locally (no outward links) and concept/topic linking is skipped; the build
still completes. Set the relevant `build:` flags in `config/config.yaml`
(`include_topics`, `include_embeddings`, `compute_similarity`, …) to match the inputs
you actually have.

> **Standalone status.** The code is self-contained and portable: no hardcoded
> machine paths, no secrets (the OpenAI key is read from `OPENAI_API_KEY`), and a
> relative `workspace_root` is resolved against this directory. A **synthetic
> sample generator** (`sample/make_sample.py`) is bundled so the construction stages
> run **end-to-end with zero gated inputs** (no transcripts, no thesaurus, no OpenAI).
> This reproduces the *method and structure*, not a bit-identical copy of the
> published KG (LLM extraction is non-deterministic; the published place alignments
> require the SFI thesaurus).

---

## Quick start — standalone smoke build (no gated inputs)

From the repo root:

```bash
make pipeline-deps        # pip install -r pipeline/requirements.txt
make pipeline-sample      # generate synthetic sample + build a toy KG
# → pipeline/sample/output/kg2026_paper.nq  (a few hundred quads, all transforms exercised)
```

This needs **nothing external** — it proves the pipeline runs by itself.

## Build from your own VHA XML transcripts

For a researcher who holds VHA access (transcripts obtained from the USC Shoah
Foundation) and an OpenAI key:

```bash
export OPENAI_API_KEY=sk-...
make build-from-transcripts XML=/path/to/your/xml/transcripts
# parse → utterances_v2 → gpt-4o-mini extract → resolve_v7 → build (Stages 1–4)
# then serve: make up load   (loads the built .nq into the Dockerised stack)
```

Or run the stages manually:

```bash
cd pipeline
python stage1_parse/parse_transcripts.py --transcripts-dir <DIR> --output-dir sample/data/processed
python stage1_parse/create_utterances_v2.py --source sample/data/processed/utterances.parquet --target sample/data/processed/utterances_v2.parquet
python stage2_extract/event_extractor_v6.py        # needs OPENAI_API_KEY
python scripts/resolve_events_v7.py
python src/build.py --config config/config.yaml     # workspace_root → sample/
```

Output N-Quads + stats are written under `<workspace_root>/output/`. Without the
(gated) SFI thesaurus, places are minted locally with no outward GeoNames/Wikidata
links — the rest of the graph builds normally.

---

## Notes

- Use **`event_extractor_v6.py`** (who/what/where/when/emotion). An older
  `cedric-code/Event_extractor.py` variant (who/what/where/why + snippets) exists in
  our archives but did **not** build the published KG — do not use it.
- The 0.82 similarity cut-off, the 30-entry valence/arousal table, and the
  14/5/6/10 controlled-vocabulary lexicons are in `config/config.yaml` and
  `src/transform/`.

## Planned improvements

- **Place span-grounding guard** (`src/transform/entities.py`): emit a place IRI
  for a mention only when its label actually occurs in the source utterance text.
  The event-extraction evaluation found location to be the weakest dimension
  (precision ≈ 48%), dominated by places that the utterance does not mention; this
  guard would remove most of those false positives. Historical/multilingual
  gazetteer linking (e.g. Lemberg/Lviv/Lwów) is a further, larger improvement.
