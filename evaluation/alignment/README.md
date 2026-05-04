# Alignment-quality evaluation

A reproducible manual-review pilot for the 2,530 `skos:exactMatch`
triples published in `schema/voices-alignment-v2.ttl`.

## Files

| File | Purpose |
|---|---|
| `extract_sample.py`   | Pulls a stratified random sample of alignments from the local Fuseki and writes `sample.csv` and an empty `judgments.csv` template. |
| `sample.csv`          | The 200 sampled rows (stratified 134 GeoNames + 66 Wikidata; seed `20260504`). Read-only — do not edit. |
| `judgments.csv`       | Same rows plus a `judgment` column for the expert reviewer to fill. Tracked in git so it can be replayed. |
| `RUBRIC.md`           | Decision rules: when to mark a row `correct`, `incorrect`, or `unsure`. |
| `sampling_method.md`  | Population, strata, sample size, seed, justification. |
| `compute_precision.py`| Reads a filled-in `judgments.csv` and prints the overall and per-authority precision summary that appears in §5.3 of the paper. |

## Workflow

1. **(Reviewer)** Open `judgments.csv` in your spreadsheet editor of choice.
2. For each row, click the `target_browse_url` to inspect the candidate
   match in GeoNames or Wikidata; decide using `RUBRIC.md`.
3. Set the `judgment` column to `correct`, `incorrect`, or `unsure`.
   Optionally write a short reason in `notes`.
4. Save the file and run:

       python compute_precision.py judgments.csv

   This prints the precision summary. Quote the reported overall and
   per-authority precision in the paper's §5.3.

## Reproducing the sample

Requires the local Fuseki to be loaded with the v2 KG.

    python extract_sample.py \
        --fuseki http://localhost:3032/voices \
        --out-sample sample.csv \
        --out-template judgments.csv \
        --total 200 \
        --seed 20260504

Same seed → same 200 rows.
