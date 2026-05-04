# Alignment-quality evaluation

A reproducible evaluation of the 2,530 `skos:exactMatch` triples
published in `schema/voices-alignment-v2.ttl`.

## What ships in this folder

| File | Purpose |
|---|---|
| `extract_sample.py`   | Deterministic stratified sampler. Pulls every alignment from the local Fuseki, stratifies by target authority (GeoNames vs Wikidata), draws a fixed-size sample with a seeded RNG, and writes `sample.csv` plus an empty `judgments.csv` template. |
| `sample.csv`          | The 200 sampled rows used in the published evaluation (134 GeoNames + 66 Wikidata; seed `20260504`). Read-only. |
| `auto_judge.py`       | Automated baseline check. For each sampled row, retrieves the target's Wikidata entity (direct lookup for Wikidata targets, via `wdt:P1566` for GeoNames targets), compares the target's canonical country to the country derived from the place slug (accounting for historical successor states), and writes `auto_judgments.csv`. Country-of-location only — does not evaluate place-name match within a country. |
| `auto_judgments.csv`  | Output of the automated baseline. Each row labelled `correct`, `incorrect`, or `unsure` with the reason in the `notes` column. This is the file the paper's §5.3 precision figure (98.6 %) is computed from. |
| `judgments.csv`       | Same rows as `sample.csv` plus empty `judgment` and `notes` columns, ready for any user to drive a deeper manual evaluation. Tracked in git so a future contribution can replay it. |
| `RUBRIC.md`           | Decision rules a human reviewer can use when populating `judgments.csv`: when to mark a row `correct`, `incorrect`, or `unsure`. |
| `sampling_method.md`  | Population, strata, sample size, seed, and reproduction instructions. |
| `compute_precision.py`| Reads any filled-in judgments file (auto or manual) and prints the overall and per-authority precision summary. |

## The published precision figure

The paper's §5.3 cites **98.6 %** automated-baseline precision
(141 of 143 auto-decidable alignments). Reproduce it with:

    python compute_precision.py auto_judgments.csv

## Driving a deeper evaluation yourself

The automated baseline only checks country-of-location. To estimate
precision at the level of the actual place-within-country, populate
the `judgments.csv` template by hand:

1. Open `judgments.csv` in your spreadsheet editor of choice.
2. For each row, click the `target_browse_url` to inspect the candidate
   match in GeoNames or Wikidata; decide using `RUBRIC.md`.
3. Set the `judgment` column to `correct`, `incorrect`, or `unsure`.
   Optionally write a short reason in `notes`.
4. Save the file and run:

       python compute_precision.py judgments.csv

   This prints the precision summary computed from your judgments,
   in the same format as the automated baseline.

## Reproducing the sample

Requires the local Fuseki to be loaded with the v2 KG.

    python extract_sample.py \
        --fuseki http://localhost:3032/voices \
        --out-sample sample.csv \
        --out-template judgments.csv \
        --total 200 \
        --seed 20260504

Same seed → same 200 rows.

## Reproducing the automated baseline

Requires internet access to the public Wikidata SPARQL endpoint.

    python auto_judge.py \
        --sample sample.csv \
        --out auto_judgments.csv

Output is fully deterministic for a given Wikidata snapshot.
