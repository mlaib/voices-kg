"""
extract_sample.py — produce a stratified random sample of place alignments
for manual evaluation.

Pulls every (place_iri, place_label, target_iri) alignment triple from the
local Fuseki, stratifies by target authority (GeoNames vs Wikidata), then
samples a fixed number from each stratum with a deterministic seed.

The result is `sample.csv` and a paired `judgments.csv` template (same rows,
empty `judgment` column) ready for an expert to fill in.

Usage
-----
    python extract_sample.py \\
        --fuseki http://localhost:3032/voices \\
        --out-sample sample.csv \\
        --out-template judgments.csv \\
        --total 200 \\
        --seed 20260504

Output rows
-----------
    place_iri          urn:voices:place:<slug>
    place_label        rdfs:label of the place from the metadata graph
    target_authority   "geonames" | "wikidata"
    target_iri         the GeoNames or Wikidata URI
    target_browse_url  best-effort browser URL for the reviewer to inspect

Reproducibility
---------------
The sample is fully deterministic for a given seed and a given alignment
graph. Re-running on the same KG with the same seed produces the same
200 rows.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path


SPARQL_ALL_ALIGNMENTS = """
PREFIX skos:  <http://www.w3.org/2004/02/skos/core#>
PREFIX rdfs:  <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?place ?label ?target WHERE {
  GRAPH <urn:voices:graph:alignment> { ?place skos:exactMatch ?target }
  OPTIONAL {
    GRAPH <urn:voices:graph:metadata> { ?place rdfs:label ?label . FILTER (lang(?label) = "en" || lang(?label) = "") }
  }
}
"""


def fetch_alignments(fuseki_url: str) -> list[dict]:
    sparql = f"{fuseki_url.rstrip('/')}/sparql"
    data = urllib.parse.urlencode({"query": SPARQL_ALL_ALIGNMENTS}).encode()
    req = urllib.request.Request(
        sparql, data=data,
        headers={"Accept": "application/sparql-results+json",
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        results = json.load(resp)["results"]["bindings"]
    rows = []
    for r in results:
        place = r["place"]["value"]
        target = r["target"]["value"]
        label = r.get("label", {}).get("value", "")
        rows.append({"place_iri": place, "place_label": label, "target_iri": target})
    return rows


def classify_authority(iri: str) -> str:
    if iri.startswith("https://sws.geonames.org/"):
        return "geonames"
    if iri.startswith("https://www.wikidata.org/"):
        return "wikidata"
    return "other"


def browse_url_for(target_iri: str, authority: str) -> str:
    """Convert a machine IRI into a human-friendly browser URL."""
    if authority == "geonames":
        # https://sws.geonames.org/2077456/  ->  https://www.geonames.org/2077456
        gid = target_iri.rstrip("/").rsplit("/", 1)[-1]
        return f"https://www.geonames.org/{gid}"
    if authority == "wikidata":
        # https://www.wikidata.org/entity/Q5027553  ->  same; also accept /wiki/
        return target_iri.replace("/entity/", "/wiki/")
    return target_iri


def stratify_and_sample(rows: list[dict], total: int, seed: int) -> list[dict]:
    by_auth: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        a = classify_authority(r["target_iri"])
        r["target_authority"] = a
        by_auth[a].append(r)

    n_total = sum(len(v) for v in by_auth.values())
    rng = random.Random(seed)

    # Proportional allocation across strata, with rounding that always sums
    # to `total`. For two strata (geonames, wikidata) the rounding is trivial.
    quotas = {a: round(total * len(v) / n_total) for a, v in by_auth.items()}
    drift = total - sum(quotas.values())
    if drift != 0:
        # fix-up: nudge the largest stratum by `drift`
        biggest = max(by_auth, key=lambda a: len(by_auth[a]))
        quotas[biggest] += drift

    sample: list[dict] = []
    for a, q in quotas.items():
        pool = sorted(by_auth[a], key=lambda r: r["place_iri"])  # deterministic order
        sample.extend(rng.sample(pool, k=min(q, len(pool))))
    # Sort the final sample for stable output
    sample.sort(key=lambda r: (r["target_authority"], r["place_iri"]))
    return sample


def write_sample(rows: list[dict], path: Path) -> None:
    fields = ["place_iri", "place_label", "target_authority", "target_iri", "target_browse_url"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            r = dict(r)
            r["target_browse_url"] = browse_url_for(r["target_iri"], r["target_authority"])
            w.writerow({k: r.get(k, "") for k in fields})


def write_judgments_template(rows: list[dict], path: Path) -> None:
    fields = ["place_iri", "place_label", "target_authority", "target_iri",
              "target_browse_url", "judgment", "notes"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            r = dict(r)
            r["target_browse_url"] = browse_url_for(r["target_iri"], r["target_authority"])
            r["judgment"] = ""  # to be filled: correct | incorrect | unsure
            r["notes"] = ""
            w.writerow({k: r.get(k, "") for k in fields})


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fuseki", default="http://localhost:3032/voices",
                   help="SPARQL endpoint root (default: %(default)s)")
    p.add_argument("--out-sample", type=Path, default=Path("sample.csv"))
    p.add_argument("--out-template", type=Path, default=Path("judgments.csv"))
    p.add_argument("--total", type=int, default=200,
                   help="Total sample size (default: %(default)s)")
    p.add_argument("--seed", type=int, default=20260504,
                   help="Random seed for reproducibility (default: %(default)s)")
    args = p.parse_args(argv)

    print(f"[extract_sample] Fetching alignments from {args.fuseki} ...", file=sys.stderr)
    all_rows = fetch_alignments(args.fuseki)
    print(f"[extract_sample]   got {len(all_rows):,} alignment triples.", file=sys.stderr)

    sample = stratify_and_sample(all_rows, total=args.total, seed=args.seed)
    n_geo = sum(1 for r in sample if r["target_authority"] == "geonames")
    n_wik = sum(1 for r in sample if r["target_authority"] == "wikidata")
    print(f"[extract_sample] Sampled {len(sample)} rows: {n_geo} geonames + {n_wik} wikidata "
          f"(seed={args.seed}).", file=sys.stderr)

    write_sample(sample, args.out_sample)
    write_judgments_template(sample, args.out_template)
    print(f"[extract_sample] Wrote {args.out_sample} and {args.out_template}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
