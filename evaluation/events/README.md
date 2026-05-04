# Event-extraction quality evaluation

A reproducible evaluation framework for the populated knowledge
graph: how accurate are the structured dimensions
(`participants`, `activity`, `location`, `temporal`, `emotion`)
that the extraction pipeline derives from each survivor utterance?

This folder ships **the framework only**, not a precision number.
The paper's §5.3.3 cites it as published material that any reviewer
or future contributor can drive themselves.

## Files

| File | Purpose |
|---|---|
| `extract_sample.py`   | Deterministic random sampler. Pulls every NarratedEvent + its source utterance + all extracted dimensions from the local Fuseki, then samples 100 with a seeded RNG. |
| `sample.csv`          | The 100 sampled events (read-only; the published baseline of what gets reviewed). |
| `judgments.csv`       | Same rows plus five empty per-dimension judgment columns ready for any reviewer to fill. |
| `RUBRIC.md`           | Decision rules for marking each per-dimension cell as `correct`, `incorrect`, or `unsure`. |
| `compute_precision.py`| Reads a filled judgments file and prints per-dimension precision plus a macro-averaged figure. |

## Why no precision number is published

Unlike alignment, where Wikidata gives an automated reference, event
extraction has no automated ground truth: the only way to evaluate
"is the extracted activity right?" is for a human to read the
utterance and judge. Rather than ship a number from a small or
unverified review, the framework is published so the figure can be
produced by:

- the authors when expert time is available;
- a reviewer who wants to verify a specific claim;
- a future contributor extending the resource;

…and the produced number is automatically reproducible against the
same `sample.csv` (deterministic from seed `20260504`).

## Driving the evaluation

1. Open `judgments.csv` in your spreadsheet editor of choice.
2. For each row, read the `segment_text` and inspect the extracted
   dimensions in the next eight columns.
3. For each of the five judgment columns
   (`judgment_participants`, `judgment_activity`,
   `judgment_location`, `judgment_temporal`, `judgment_emotion`),
   write `correct`, `incorrect`, or `unsure` per `RUBRIC.md`.
4. Save and run:

       python compute_precision.py judgments.csv

   Prints per-dimension precision and a macro-averaged figure.

## Reproducing the sample

Requires the local Fuseki to be loaded with the v2 KG.

    python extract_sample.py \\
        --fuseki http://localhost:3032/voices \\
        --out-sample sample.csv \\
        --out-template judgments.csv \\
        --total 100 \\
        --seed 20260504
