#!/usr/bin/env python3
"""precompute_surprise.py — surface terms over-represented in each life period.

Why
---
Keyword-search alone confirms hypotheses ("does *boots* spike during the war?")
but doesn't *generate* them. This script surfaces unexpectedly-frequent words
per period so historians can browse rather than guess.

Method
------
For each life period p, score every word w by Bayesian log-odds-ratio with a
uniform Dirichlet prior (Monroe, Colaresi, Quinn 2008). Compared to plain TF-IDF,
this is much more robust for differently-sized buckets and for very common /
very rare words. The score is unitless; positive = over-represented in p.

Input
-----
For each period in voices:temporalBucket, query Fuseki for all segment texts
referenced by events tagged with that period. Tokenise with a simple ASCII-letter
regex, drop a basic English stop-list, drop tokens shorter than 3 chars.

Output
------
output/caches/surprise_terms.json:

    {
      "during_war": [
        {"term": "boots", "score": 4.12, "count": 312, "period_count": 312, "rest_count": 21},
        ...
      ],
      ...
    }

Top 50 terms per period, sorted by score descending. Filtered to terms with
period_count >= MIN_COUNT_IN_PERIOD so we don't surface noise.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
FUSEKI_URL = os.environ.get("FUSEKI_URL", "http://localhost:3032/voices").rstrip("/")
DEFAULT_CACHE_DIR = Path(os.environ.get("CACHE_DIR", str(PROJECT_DIR / "output" / "caches")))

MIN_COUNT_IN_PERIOD = 25       # ignore words mentioned <25 times in the period
TOP_PER_PERIOD = 50            # how many to keep per period
PRIOR_ALPHA = 0.5              # Dirichlet smoothing constant
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")  # >=3 chars, allow internal '-

# Compact English stop-list — these dominate any corpus and are never insightful.
STOPWORDS = set("""
a about above after again against all am an and any are arent as at be because been
before being below between both but by cant cannot could couldnt did didnt do does doesnt doing dont
down during each few for from further had hadnt has hasnt have havent having he hed hell hes her here
heres hers herself him himself his how hows i id ill im ive if in into is isnt it its itself lets me
more most mustnt my myself no nor not of off on once only or other ought our ours ourselves out over
own same shant she shed shell shes should shouldnt so some such than that thats the their theirs them
themselves then there theres these they theyd theyll theyre theyve this those through to too under
until up very was wasnt we wed well were werent weve what whats when whens where wheres which while who
whos whom why whys with wont would wouldnt you youd youll youre youve your yours yourself yourselves
just like get got going know think really say said came went come oh um uh well one two three many
people thing things something nothing anything everything someone anyone everyone yes also yeah back
right way day days year years time times little big much never always see saw look looked tell told asked
even still want wanted thought knew tried take took give gave find found put let used use made make
seemed seem feel felt around toward away here there
""".split())


def log(msg: str) -> None:
    print(f"[surprise] {msg}", file=sys.stderr, flush=True)


def sparql_select(query: str, *, timeout: float = 600.0) -> list[dict]:
    data = urllib.parse.urlencode({"query": query}).encode("utf-8")
    req = urllib.request.Request(
        f"{FUSEKI_URL}/sparql",
        data=data,
        headers={
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    return payload.get("results", {}).get("bindings", [])


def list_periods() -> list[str]:
    rows = sparql_select(
        "PREFIX voices: <https://w3id.org/voices/ontology#>\n"
        "SELECT DISTINCT ?p WHERE {\n"
        "  GRAPH <urn:voices:graph:events> { ?ev voices:temporalBucket ?p }\n"
        "} ORDER BY ?p"
    )
    return [r["p"]["value"] for r in rows if "p" in r]


def stream_segments_for_period(period: str, *, page_size: int = 50000) -> "Iterable[str]":
    """Yield transcript text for every segment whose event has this period."""
    offset = 0
    safe = period.replace('"', '\\"')
    while True:
        q = (
            "PREFIX voices: <https://w3id.org/voices/ontology#>\n"
            "SELECT ?text WHERE {\n"
            "  GRAPH <urn:voices:graph:events> {\n"
            f'    ?ev voices:temporalBucket "{safe}" .\n'
            "    ?seg voices:segmentRefersToEvent ?ev .\n"
            "  }\n"
            "  GRAPH <urn:voices:graph:transcripts> {\n"
            "    ?seg voices:transcriptText ?text .\n"
            "  }\n"
            f"}} LIMIT {page_size} OFFSET {offset}"
        )
        rows = sparql_select(q)
        if not rows:
            return
        for r in rows:
            t = r.get("text", {}).get("value")
            if t:
                yield t
        if len(rows) < page_size:
            return
        offset += page_size


def tokenise(text: str) -> "Iterable[str]":
    for m in TOKEN_RE.finditer(text.lower()):
        # Drop apostrophes so contractions ("don't", "didn't") collapse onto
        # the stop-list entries ("dont", "didnt"). Keep hyphenated words intact.
        tok = m.group(0).replace("'", "").strip("-")
        if len(tok) < 3:
            continue
        if tok in STOPWORDS:
            continue
        yield tok


def stream_segments_with_emotions(period: str, *, page_size: int = 25000):
    """Yield (text, emotion_categories) per segment in this period.

    `emotion_categories` is a possibly-empty list of strings — segments without
    an emotion annotation still count toward the global per-period bucket.
    """
    offset = 0
    safe = period.replace('"', '\\"')
    while True:
        q = (
            "PREFIX voices: <https://w3id.org/voices/ontology#>\n"
            "SELECT ?seg ?text (GROUP_CONCAT(DISTINCT ?cat;separator='|') AS ?cats) WHERE {\n"
            "  GRAPH <urn:voices:graph:events> {\n"
            f'    ?ev voices:temporalBucket "{safe}" .\n'
            "    ?seg voices:segmentRefersToEvent ?ev .\n"
            "  }\n"
            "  GRAPH <urn:voices:graph:transcripts> {\n"
            "    ?seg voices:transcriptText ?text .\n"
            "  }\n"
            "  OPTIONAL {\n"
            "    GRAPH <urn:voices:graph:annotations> {\n"
            "      ?ev voices:hasEmotion ?ann .\n"
            "      ?ann voices:emotionCategory ?cat .\n"
            "    }\n"
            "  }\n"
            f"}} GROUP BY ?seg ?text ORDER BY ?seg LIMIT {page_size} OFFSET {offset}"
        )
        rows = sparql_select(q)
        if not rows:
            return
        for r in rows:
            t = r.get("text", {}).get("value")
            cats_str = r.get("cats", {}).get("value", "")
            emotions = [c for c in cats_str.split("|") if c]
            if t:
                yield t, emotions
        if len(rows) < page_size:
            return
        offset += page_size


def filter_to_nouns(vocab: set[str]) -> set[str]:
    """POS-tag each unique vocabulary word with spaCy; keep NOUN/PROPN only.

    Tagging in isolation (no sentence context) is imperfect but very fast for
    a vocabulary of ~50K. For ambiguous tokens (e.g. "run"), spaCy defaults to
    the most-common POS — which usually disqualifies common verbs and is the
    correct call here. Specific historical nouns ("ghetto", "boots") tag
    unambiguously as NOUN.
    """
    try:
        import spacy
    except ImportError as e:
        raise SystemExit(
            "spaCy is required for POS filtering. Install via:\n"
            "  python -m venv .venv-precompute && "
            ".venv-precompute/bin/pip install spacy && "
            ".venv-precompute/bin/python -m spacy download en_core_web_sm"
        ) from e
    try:
        nlp = spacy.load("en_core_web_sm", disable=["parser", "ner", "lemmatizer"])
    except OSError as e:
        raise SystemExit(
            "spaCy model en_core_web_sm not found. Install via:\n"
            "  .venv-precompute/bin/python -m spacy download en_core_web_sm"
        ) from e
    nouns: set[str] = set()
    vocab_list = list(vocab)
    for tok, doc in zip(vocab_list, nlp.pipe(vocab_list, batch_size=256)):
        if doc and len(doc) > 0 and doc[0].pos_ in ("NOUN", "PROPN"):
            nouns.add(tok)
    return nouns


def log_odds_z(c1: int, n1: int, c2: int, n2: int, alpha: float = PRIOR_ALPHA) -> float:
    """Bayesian log-odds-ratio (informative Dirichlet prior), Monroe et al. 2008.

    Higher = more over-represented in group 1 vs group 2. Variance-adjusted
    so common and rare words are comparable.
    """
    a1 = c1 + alpha
    a2 = c2 + alpha
    b1 = n1 - c1 + alpha
    b2 = n2 - c2 + alpha
    # log-odds in each group
    lo1 = math.log(a1 / b1)
    lo2 = math.log(a2 / b2)
    delta = lo1 - lo2
    var = 1.0 / a1 + 1.0 / a2  # variance of log-odds difference
    if var <= 0:
        return 0.0
    return delta / math.sqrt(var)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--top", type=int, default=TOP_PER_PERIOD,
                        help=f"top N terms per period (default: {TOP_PER_PERIOD})")
    parser.add_argument("--min-count", type=int, default=MIN_COUNT_IN_PERIOD,
                        help=f"drop terms with <N occurrences in period (default: {MIN_COUNT_IN_PERIOD})")
    args = parser.parse_args(argv)

    args.cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.cache_dir / "surprise_terms.json"
    out_path_emo = args.cache_dir / "surprise_terms_by_emotion.json"

    log(f"Fuseki: {FUSEKI_URL}")
    periods = list_periods()
    log(f"Periods found: {len(periods)} — {periods}")
    if not periods:
        log("No periods in data — abort.")
        return 1

    # Single pass over each period: count globally + per emotion category.
    # A segment with multiple emotion tags contributes to each tag's bucket
    # (consistent with computing within-period contrasts).
    counts_g: dict[str, Counter[str]] = {}      # period -> term -> count
    totals_g: dict[str, int] = {}               # period -> total tokens
    counts_e: dict[str, dict[str, Counter[str]]] = {}  # period -> emo -> term -> count
    totals_e: dict[str, dict[str, int]] = {}    # period -> emo -> total tokens

    for p in periods:
        log(f"Tokenising period={p} ...")
        cg: Counter[str] = Counter()
        ce: dict[str, Counter[str]] = defaultdict(Counter)
        te: dict[str, int] = defaultdict(int)
        seg_count = 0
        token_count = 0
        t0 = time.time()
        for text, emotions in stream_segments_with_emotions(p):
            seg_count += 1
            toks = list(tokenise(text))
            for tok in toks:
                cg[tok] += 1
            token_count += len(toks)
            for emo in emotions:
                ce_emo = ce[emo]
                for tok in toks:
                    ce_emo[tok] += 1
                te[emo] += len(toks)
            if seg_count % 25000 == 0:
                log(f"  ...{seg_count:,} segs, {token_count:,} tokens "
                    f"({time.time() - t0:.1f}s)")
        counts_g[p] = cg
        totals_g[p] = token_count
        counts_e[p] = dict(ce)
        totals_e[p] = dict(te)
        log(f"  done: {seg_count:,} segs, {token_count:,} tokens, "
            f"vocab={len(cg):,}, emotions={dict(te)}, {time.time() - t0:.1f}s")

    # Build full vocabulary across all buckets, POS-tag once, drop non-nouns.
    log("Building vocabulary ...")
    vocab: set[str] = set()
    for cg in counts_g.values():
        vocab.update(cg.keys())
    log(f"Vocabulary size: {len(vocab):,}")
    log("POS-tagging vocabulary with spaCy (NOUN/PROPN filter) ...")
    t0 = time.time()
    nouns = filter_to_nouns(vocab)
    log(f"  kept {len(nouns):,} / {len(vocab):,} as NOUN/PROPN ({time.time()-t0:.1f}s)")

    # Filter all counters down to nouns. Recompute totals to reflect noun-only
    # corpus sizes (denominator in log-odds).
    for p in periods:
        counts_g[p] = Counter({t: c for t, c in counts_g[p].items() if t in nouns})
        totals_g[p] = sum(counts_g[p].values())
        for emo in list(counts_e[p].keys()):
            counts_e[p][emo] = Counter({t: c for t, c in counts_e[p][emo].items() if t in nouns})
            totals_e[p][emo] = sum(counts_e[p][emo].values())

    grand_total = sum(totals_g.values())
    log(f"Total noun tokens across periods: {grand_total:,}")

    # ── 1. Global per-period log-odds (period vs rest of corpus) ──────────
    log("Scoring log-odds per (term, period) — global ...")
    out: dict[str, list[dict]] = {}
    for p in periods:
        c_p = counts_g[p]
        n_p = totals_g[p]
        scored: list[tuple[float, str, int, int]] = []
        for term, c1 in c_p.items():
            if c1 < args.min_count:
                continue
            c2 = sum(counts_g[q].get(term, 0) for q in periods if q != p)
            n2 = grand_total - n_p
            z = log_odds_z(c1, n_p, c2, n2)
            scored.append((z, term, c1, c2))
        scored.sort(reverse=True)
        out[p] = [
            {"term": t, "score": round(z, 4),
             "period_count": c1, "rest_count": c2}
            for z, t, c1, c2 in scored[: args.top]
        ]

    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    log(f"Wrote {out_path}")
    for p, rows in out.items():
        sample = ", ".join(r["term"] for r in rows[:8])
        log(f"  {p:<22} -> {sample}")

    # ── 2. Per (period, emotion) log-odds (this emotion vs others IN period) ──
    # Within-period contrast isolates "what makes a moment in this period feel
    # this way" — independent of which periods are over-represented overall.
    log("Scoring log-odds per (term, period, emotion) ...")
    out_emo: dict[str, dict[str, list[dict]]] = {}
    for p in periods:
        out_emo[p] = {}
        emos_in_p = list(counts_e[p].keys())
        for emo in emos_in_p:
            c_pe = counts_e[p][emo]
            n_pe = totals_e[p][emo]
            if n_pe == 0:
                continue
            n_rest = sum(totals_e[p][e] for e in emos_in_p if e != emo)
            scored: list[tuple[float, str, int, int]] = []
            for term, c1 in c_pe.items():
                if c1 < args.min_count:
                    continue
                c2 = sum(counts_e[p][e].get(term, 0) for e in emos_in_p if e != emo)
                z = log_odds_z(c1, n_pe, c2, n_rest)
                scored.append((z, term, c1, c2))
            scored.sort(reverse=True)
            out_emo[p][emo] = [
                {"term": t, "score": round(z, 4),
                 "period_count": c1, "rest_count": c2}
                for z, t, c1, c2 in scored[: args.top]
            ]

    out_path_emo.write_text(json.dumps(out_emo, ensure_ascii=False, indent=2))
    log(f"Wrote {out_path_emo}")
    for p, by_emo in out_emo.items():
        for emo, rows in by_emo.items():
            sample = ", ".join(r["term"] for r in rows[:6])
            log(f"  {p:<22} {emo:<22} -> {sample}")

    print(json.dumps({"periods": list(out.keys()),
                      "out": str(out_path),
                      "out_by_emotion": str(out_path_emo),
                      "top_per_period": args.top}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
