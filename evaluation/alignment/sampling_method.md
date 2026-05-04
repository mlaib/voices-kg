# Alignment-quality evaluation — sampling method

## Population

The published VOICES alignment graph (`schema/voices-alignment-v2.ttl`,
also queryable in the `urn:voices:graph:alignment` named graph) contains
**2,530** `skos:exactMatch` triples linking minted
`urn:voices:place:<slug>` IRIs to GeoNames or Wikidata authority IRIs.

| Target authority | Count | Share |
|---|---:|---:|
| GeoNames        | 1,701 | 67.2% |
| Wikidata        | 829   | 32.8% |
| **Total**       | **2,530** | **100.0%** |

## Sample

We draw a **stratified random sample of size 200** from this population,
proportionally allocated across target authorities to preserve the
GeoNames / Wikidata mix:

| Target authority | Sample size |
|---|---:|
| GeoNames | 134 |
| Wikidata | 66  |
| **Total** | **200** |

## Reproducibility

The sample is fully deterministic for a given pair of (alignment graph,
random seed). The configuration used in the published evaluation:

- **Random seed**: `20260504`
- **Alignment graph**: as published in commit `8780695` of
  `voices-kg.git@main`
- **Stratification key**: target authority (`geonames` | `wikidata`),
  derived from the IRI prefix
- **Within-stratum order**: alphabetical by `place_iri`, then sampled
  with `random.Random(seed).sample(...)`

## Reproducing the sample

From the project root, with the local Fuseki running and loaded:

    cd evaluation/alignment
    python extract_sample.py \\
        --fuseki http://localhost:3032/voices \\
        --out-sample sample.csv \\
        --out-template judgments.csv \\
        --total 200 \\
        --seed 20260504

This regenerates `sample.csv` (the 200 rows) and an empty
`judgments.csv` template ready for the expert reviewer to fill in.

## Justification

A 200-pair sample over a 2,530-triple population gives a 95% confidence
interval of approximately ±3 percentage points around any precision
estimate near 95%. This is tight enough to substantiate the headline
number reported in the paper while keeping the manual-review effort
proportionate (~30–45 minutes for an expert reviewer).
