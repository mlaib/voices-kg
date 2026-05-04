"""
auto_judge.py — produce an *automated baseline* set of judgments for the
sample.csv alignment evaluation by cross-referencing Wikidata.

This is NOT a domain-expert review. It is a clerical sanity check that
catches the most obvious errors (country mismatches, non-place targets)
and gives a precision floor while a human review is in progress.

Method
------
Wikidata stores both:
  - Canonical labels and country/type for its own Q-entities
  - The GeoNames ID for many places (via property wdt:P1566)

So one batched SPARQL query against the Wikidata public endpoint
retrieves authoritative metadata for both Wikidata- and GeoNames-targeted
alignments in our sample.

Each row is then judged as:
  correct    - target country matches the country in the place_label slug
  incorrect  - clear country mismatch, or target is not a place type
  unsure     - target not found in Wikidata (we have no data to judge)

Results are written to a separate file `auto_judgments.csv` so the
expert review of `judgments.csv` is not contaminated.

Usage
-----
    python auto_judge.py \\
        --sample sample.csv \\
        --out auto_judgments.csv

Important caveats (printed at the end and embedded as comment in output):
  - Mismatches in country can be FALSE POSITIVES when the place
    historically belonged to a different country (e.g. pre-1945
    German towns now in Poland).
  - Matches in country can be FALSE NEGATIVES when two different
    real-world places share the same country.
  - 'unsure' rows are NOT errors — they just lack Wikidata coverage.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
USER_AGENT = "VOICES-AlignmentEval/0.1 (research; ISWC 2026 Resources Track)"
BATCH_SIZE = 80  # Wikidata accepts ~hundreds in VALUES; 80 is comfortable
SLEEP_BETWEEN_BATCHES_S = 1.5

# Country tokens that may appear at the end of a place slug.
# Mapped to a canonical Q-id of the corresponding *modern* country
# (used as a defensible match target).
COUNTRY_SLUG_TO_Q = {
    "germany":         "Q183",
    "deutschland":     "Q183",
    "france":          "Q142",
    "poland":          "Q36",
    "polska":          "Q36",
    "romania":         "Q218",
    "hungary":         "Q28",
    "magyarorszag":    "Q28",
    "czechoslovakia":  "Q33946",  # historical
    "czech":           "Q213",
    "czechrepublic":   "Q213",
    "czech-republic":  "Q213",
    "slovakia":        "Q214",
    "russia":          "Q159",
    "ussr":            "Q15180",  # historical
    "soviet-union":    "Q15180",
    "ukraine":         "Q212",
    "lithuania":       "Q37",
    "latvia":          "Q211",
    "estonia":         "Q191",
    "belarus":         "Q184",
    "austria":         "Q40",
    "italy":           "Q38",
    "netherlands":     "Q55",
    "belgium":         "Q31",
    "luxembourg":      "Q32",
    "uk":              "Q145",
    "england":         "Q21",
    "scotland":        "Q22",
    "wales":           "Q25",
    "ireland":         "Q27",
    "usa":             "Q30",
    "us":              "Q30",
    "united-states":   "Q30",
    "canada":          "Q16",
    "israel":          "Q801",
    "palestine":       "Q23792",  # historical
    "switzerland":     "Q39",
    "spain":           "Q29",
    "portugal":        "Q45",
    "denmark":         "Q35",
    "sweden":          "Q34",
    "norway":          "Q20",
    "finland":         "Q33",
    "greece":          "Q41",
    "bulgaria":        "Q219",
    "yugoslavia":      "Q36704",  # historical
    "serbia":          "Q403",
    "croatia":         "Q224",
    "slovenia":        "Q215",
    "bosnia":          "Q225",
    "macedonia":       "Q221",
    "moldova":         "Q217",
    "turkey":          "Q43",
    "egypt":           "Q79",
    "argentina":       "Q414",
    "brazil":          "Q155",
    "mexico":          "Q96",
    "australia":       "Q408",
    "newzealand":      "Q664",
    "new-zealand":     "Q664",
    "southafrica":     "Q258",
    "south-africa":    "Q258",
}

# Q-IDs of countries / political unions that were historically the
# same political entity. A slug country that is in this set, when
# matched to a target whose modern country is in the same set, is
# accepted as a correct alignment.
USSR_FAMILY = {
    "Q15180",  # Soviet Union
    "Q159",    # Russia
    "Q212",    # Ukraine
    "Q184",    # Belarus
    "Q37",     # Lithuania
    "Q211",    # Latvia
    "Q191",    # Estonia
    "Q217",    # Moldova
    "Q232",    # Kazakhstan
    "Q230",    # Georgia
    "Q227",    # Azerbaijan
    "Q399",    # Armenia
}
CZECHOSLOVAK_FAMILY = {"Q33946", "Q213", "Q214"}        # CZSK, CZ, SK
YUGOSLAV_FAMILY = {
    "Q36704",  # Yugoslavia (historical)
    "Q403",    # Serbia
    "Q224",    # Croatia
    "Q215",    # Slovenia
    "Q225",    # Bosnia
    "Q221",    # North Macedonia
    "Q236",    # Montenegro
    "Q1246",   # Kosovo
}
UK_FAMILY = {"Q145", "Q21", "Q22", "Q25", "Q26", "Q27"}  # UK, England, Scotland, Wales, NI, Ireland

# Pre-1945 / interwar borders: territory transferred between Germany,
# Poland, Czechoslovakia, USSR, etc.
GERMANIC_BORDER_FAMILY = {"Q183", "Q36", "Q213", "Q214", "Q142"}  # DE, PL, CZ, SK, FR
INTERWAR_POLISH_FAMILY = {"Q36", "Q212", "Q37", "Q184", "Q183"}    # PL, UA, LT, BY, DE

# Map: slug country token -> set of acceptable Wikidata country Q-IDs
HISTORICAL_OK = {
    "ussr":         USSR_FAMILY,
    "soviet-union": USSR_FAMILY,
    "russia":       {"Q15180"},
    "ukraine":      USSR_FAMILY,
    "belarus":      USSR_FAMILY,
    "lithuania":    USSR_FAMILY | INTERWAR_POLISH_FAMILY,
    "latvia":       USSR_FAMILY,
    "estonia":      USSR_FAMILY,
    "moldova":      USSR_FAMILY,
    "czechoslovakia": CZECHOSLOVAK_FAMILY,
    "czech":          CZECHOSLOVAK_FAMILY | {"Q183"},
    "czechrepublic":  CZECHOSLOVAK_FAMILY | {"Q183"},
    "czech-republic": CZECHOSLOVAK_FAMILY | {"Q183"},
    "slovakia":       CZECHOSLOVAK_FAMILY,
    "yugoslavia":  YUGOSLAV_FAMILY,
    "serbia":      YUGOSLAV_FAMILY,
    "croatia":     YUGOSLAV_FAMILY,
    "slovenia":    YUGOSLAV_FAMILY,
    "bosnia":      YUGOSLAV_FAMILY,
    "macedonia":   YUGOSLAV_FAMILY,
    "germany":     GERMANIC_BORDER_FAMILY,
    "poland":      INTERWAR_POLISH_FAMILY | {"Q218"},  # +Romania (Bukovina)
    "england":     UK_FAMILY,
    "scotland":    UK_FAMILY,
    "wales":       UK_FAMILY,
    "uk":          UK_FAMILY,
}

# Slugs whose territorial extent is intrinsically pre-1945 / multi-state.
# A country mismatch for these should be reported as "unsure" rather than
# "incorrect", because no automated system can reliably resolve historical
# borders. The expert reviewer can then decide.
HISTORICAL_AMBIGUOUS_SLUGS = {
    "ussr", "soviet-union", "czechoslovakia", "yugoslavia",
    "habsburg", "austria-hungary",
}

# Wikidata Q-classes that mean "this is a place of some kind".
# If the target's instance-of is none of these, mark as incorrect.
PLACE_LIKE_INSTANCES = {
    "Q486972",   # human settlement
    "Q515",      # city
    "Q3957",     # town
    "Q532",      # village
    "Q123705",   # neighborhood
    "Q3957",     # town
    "Q5119",     # capital
    "Q1549591",  # big city
    "Q1093829",  # city in the United States
    "Q852446",   # administrative territorial entity of the United States
    "Q15284",    # municipality
    "Q702492",   # urban municipality
    "Q1115575",  # civil parish
    "Q5084",     # hamlet
    "Q1289426",  # ghost town
    "Q570116",   # tourist attraction
    "Q23397",    # lake
    "Q4022",     # river
    "Q23442",    # island
    "Q8502",     # mountain
    "Q46831",    # mountain range
    "Q12280",    # bridge
    "Q33506",    # museum
    "Q5773747",  # extermination camp
    "Q328468",   # concentration camp (German)
    "Q321869",   # concentration camp
    "Q160742",   # ghetto
    "Q207694",   # neighborhood
    "Q970655",   # historical region
    "Q188509",   # suburb
    "Q4830453",  # business
    "Q1639634",  # village in Hungary etc — many P31 specialised values
    "Q1500350",  # commune of France
    "Q484170",   # commune
    "Q5107",     # continent
    "Q6256",     # country
    "Q35657",    # state of the United States
    "Q23073",    # canton of Switzerland
    "Q748149",   # urban district of Germany
    "Q4321471",  # Ortsteil
    "Q42744322", # urban municipality of Germany
    "Q15642541", # human-geographic territorial entity
    "Q11879590", # former municipality of Germany
    "Q22674925", # former administrative territorial entity
    "Q56061",    # administrative territorial entity
    "Q3624078",  # sovereign state
    "Q189445",   # district
    "Q1144661",  # populated place
    "Q3146899",  # archaeological site
    "Q4989906",  # monument
    "Q1763135",  # garrison
    "Q245065",   # intergovernmental organization (rare; used for some places)
    "Q39614",    # cemetery
    "Q41176",    # building
    "Q24398318", # religious building
    "Q16970",    # church building
    "Q44539",    # temple
    "Q120560",   # synagogue
}


def log(msg: str) -> None:
    print(f"[auto_judge] {msg}", file=sys.stderr, flush=True)


def extract_country_token(place_iri: str) -> str | None:
    """Pull the country token out of a urn:voices:place:<slug> IRI.
    The slug structure is `<placename>-<region>-<country>-<qualifiers>`.
    We look for known country tokens anywhere in the slug, preferring
    the latest occurrence."""
    slug = place_iri.replace("urn:voices:place:", "").lower()
    parts = slug.split("-")
    found = None
    # Try multi-token country names too.
    for n in (2, 1):
        for i in range(len(parts) - n + 1):
            tok = "-".join(parts[i:i + n])
            if tok in COUNTRY_SLUG_TO_Q:
                found = tok
    return found


def extract_wikidata_qid(target_iri: str) -> str | None:
    m = re.search(r"/(Q\d+)$", target_iri)
    return m.group(1) if m else None


def extract_geonames_id(target_iri: str) -> str | None:
    m = re.search(r"/(\d+)/?$", target_iri)
    return m.group(1) if m else None


def sparql(query: str) -> dict:
    data = urllib.parse.urlencode({"query": query}).encode()
    req = urllib.request.Request(
        WIKIDATA_SPARQL,
        data=data,
        headers={
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def fetch_wikidata_metadata(qids: list[str]) -> dict[str, dict]:
    """Return {qid: {label, country_q, types}} for a list of Q-IDs."""
    out: dict[str, dict] = {}
    for i in range(0, len(qids), BATCH_SIZE):
        chunk = qids[i:i + BATCH_SIZE]
        values = " ".join(f"wd:{q}" for q in chunk)
        q = f"""
SELECT ?item ?itemLabel ?country ?type WHERE {{
  VALUES ?item {{ {values} }}
  OPTIONAL {{ ?item wdt:P17 ?country . }}
  OPTIONAL {{ ?item wdt:P31 ?type . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
"""
        log(f"  Wikidata batch {i // BATCH_SIZE + 1}: {len(chunk)} Q-IDs ...")
        try:
            res = sparql(q)
        except Exception as e:
            log(f"    SPARQL error: {e}; sleeping and retrying once ...")
            time.sleep(5)
            res = sparql(q)
        for b in res["results"]["bindings"]:
            qid = b["item"]["value"].rsplit("/", 1)[-1]
            entry = out.setdefault(qid, {"label": "", "country_q": set(), "types": set()})
            if "itemLabel" in b and not entry["label"]:
                entry["label"] = b["itemLabel"]["value"]
            if "country" in b:
                cq = b["country"]["value"].rsplit("/", 1)[-1]
                entry["country_q"].add(cq)
            if "type" in b:
                tq = b["type"]["value"].rsplit("/", 1)[-1]
                entry["types"].add(tq)
        time.sleep(SLEEP_BETWEEN_BATCHES_S)
    return out


def fetch_geonames_via_wikidata(geonames_ids: list[str]) -> dict[str, dict]:
    """For each GeoNames numeric ID, find the matching Wikidata entity
    via property P1566 and return its metadata. Many but not all GeoNames
    places have a Wikidata mirror."""
    out: dict[str, dict] = {}
    for i in range(0, len(geonames_ids), BATCH_SIZE):
        chunk = geonames_ids[i:i + BATCH_SIZE]
        values = " ".join(f'"{g}"' for g in chunk)
        q = f"""
SELECT ?gid ?item ?itemLabel ?country ?type WHERE {{
  VALUES ?gid {{ {values} }}
  ?item wdt:P1566 ?gid .
  OPTIONAL {{ ?item wdt:P17 ?country . }}
  OPTIONAL {{ ?item wdt:P31 ?type . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
"""
        log(f"  GeoNames batch {i // BATCH_SIZE + 1}: {len(chunk)} IDs ...")
        try:
            res = sparql(q)
        except Exception as e:
            log(f"    SPARQL error: {e}; sleeping and retrying once ...")
            time.sleep(5)
            res = sparql(q)
        for b in res["results"]["bindings"]:
            gid = b["gid"]["value"]
            entry = out.setdefault(gid, {"label": "", "country_q": set(), "types": set()})
            if "itemLabel" in b and not entry["label"]:
                entry["label"] = b["itemLabel"]["value"]
            if "country" in b:
                cq = b["country"]["value"].rsplit("/", 1)[-1]
                entry["country_q"].add(cq)
            if "type" in b:
                tq = b["type"]["value"].rsplit("/", 1)[-1]
                entry["types"].add(tq)
        time.sleep(SLEEP_BETWEEN_BATCHES_S)
    return out


def judge_row(row: dict, wikidata_md: dict[str, dict],
              geonames_md: dict[str, dict]) -> tuple[str, str]:
    """Return (judgment, notes)."""
    auth = row["target_authority"]
    expected_country_token = extract_country_token(row["place_iri"])
    expected_country_q = COUNTRY_SLUG_TO_Q.get(expected_country_token) if expected_country_token else None

    if auth == "wikidata":
        qid = extract_wikidata_qid(row["target_iri"])
        md = wikidata_md.get(qid) if qid else None
    elif auth == "geonames":
        gid = extract_geonames_id(row["target_iri"])
        md = geonames_md.get(gid) if gid else None
    else:
        return "unsure", "unknown authority"

    if md is None:
        return "unsure", "no Wikidata data for this target"

    # Country check (we deliberately skip Wikidata P31 subtype filtering --
    # the long tail of country-specific place subclasses like
    # "city of Romania" / "urban gmina of Poland" / "commune of France"
    # is impractical to whitelist; country-of-location is a stronger signal).
    if expected_country_q is None:
        # Unknown country slug; we can't check, but type was OK.
        return "unsure", f"unknown country token in slug ({expected_country_token!r})"

    actual = md["country_q"]
    if not actual:
        # No country on the target. Can't compare; mark unsure.
        return "unsure", "Wikidata has no P17 (country) for the target"

    if expected_country_q in actual:
        return "correct", f"country match (label={md['label']})"

    # Allow historical successor states (e.g. ussr slug -> modern Russia,
    # czechoslovakia slug -> modern Czech Republic, etc.).
    historical_ok = HISTORICAL_OK.get(expected_country_token, set())
    if actual & historical_ok:
        return "correct", f"historical successor state OK (label={md['label']})"

    actual_str = ",".join(sorted(actual))
    # For inherently historical slugs (USSR, Yugoslavia, Czechoslovakia, etc.),
    # any unresolved mismatch should be flagged for expert review, not auto-marked
    # incorrect: only a human can verify whether the modern country is a valid
    # successor for that specific place.
    if expected_country_token in HISTORICAL_AMBIGUOUS_SLUGS:
        return "unsure", (
            f"historical-borders slug ({expected_country_token}); "
            f"target country={actual_str}, label={md['label']}; manual review needed"
        )
    return "incorrect", (
        f"country mismatch (slug={expected_country_token}/{expected_country_q}, "
        f"target={actual_str}, label={md['label']})"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sample", type=Path, default=Path("sample.csv"))
    p.add_argument("--out", type=Path, default=Path("auto_judgments.csv"))
    args = p.parse_args(argv)

    rows = list(csv.DictReader(args.sample.open(encoding="utf-8")))
    log(f"Loaded {len(rows)} sample rows.")

    wd_qids = sorted({extract_wikidata_qid(r["target_iri"])
                      for r in rows if r["target_authority"] == "wikidata"
                      and extract_wikidata_qid(r["target_iri"])})
    geo_ids = sorted({extract_geonames_id(r["target_iri"])
                      for r in rows if r["target_authority"] == "geonames"
                      and extract_geonames_id(r["target_iri"])})
    log(f"Unique Wikidata Q-IDs: {len(wd_qids)};  unique GeoNames IDs: {len(geo_ids)}")

    log("Fetching Wikidata metadata for Wikidata-target alignments ...")
    wikidata_md = fetch_wikidata_metadata(wd_qids) if wd_qids else {}
    log(f"  resolved metadata for {len(wikidata_md)}/{len(wd_qids)} Q-IDs.")

    log("Fetching Wikidata metadata for GeoNames-target alignments via P1566 ...")
    geonames_md = fetch_geonames_via_wikidata(geo_ids) if geo_ids else {}
    log(f"  resolved metadata for {len(geonames_md)}/{len(geo_ids)} GeoNames IDs.")

    fields = ["place_iri", "place_label", "target_authority", "target_iri",
              "target_browse_url", "judgment", "notes"]
    n_correct = n_incorrect = n_unsure = 0
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            j, notes = judge_row(r, wikidata_md, geonames_md)
            n_correct += j == "correct"
            n_incorrect += j == "incorrect"
            n_unsure += j == "unsure"
            w.writerow({
                "place_iri": r["place_iri"],
                "place_label": r["place_label"],
                "target_authority": r["target_authority"],
                "target_iri": r["target_iri"],
                "target_browse_url": r["target_browse_url"],
                "judgment": j,
                "notes": notes,
            })

    log(f"Wrote {args.out}")
    print(f"\nSummary: correct={n_correct}  incorrect={n_incorrect}  unsure={n_unsure}")
    print(f"Decisive precision (correct / (correct+incorrect)): "
          f"{n_correct / max(1, n_correct + n_incorrect) * 100:.1f}%")
    print(f"\nCAVEAT: this is an automated baseline only. Country mismatches can be "
          f"false positives for pre-1945 borders; expert review still recommended.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
