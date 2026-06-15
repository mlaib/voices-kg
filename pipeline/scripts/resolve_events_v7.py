"""Resolve pronouns and context-fill where/when in events_v6.parquet → events_v7.parquet.

Tier 1 — trivial rules:
  I/me/myself            → survivor name
  we/us/ourselves        → "<Survivor> and family"
  my <X> / our <X>       → "<Survivor>'s <X>"
  compound "I, my X"     → expanded component-wise

Tier 2 — local coreference (lookback window = 10 events, same interview):
  he/him/his             → nearest prior who with male marker
  she/her/hers           → nearest prior who with female marker
  they/them/their        → nearest prior plural/group who
  (fallback)             → most recent non-pronoun who

Tier 3 — sticky context fill for where/when:
  "not stated" or empty  → forward-fill from most recent non-empty value
                           within the same interview
"""
from __future__ import annotations
import os

import re
import sys
from collections import deque
from pathlib import Path

import pandas as pd

WS = Path(os.environ.get("VOICES_WS", "."))
EVENTS_IN = WS / "data/processed/events_v6.parquet"
EVENTS_OUT = WS / "data/processed/events_v7.parquet"
META_CSV = WS / "data/raw/transcript_testimonies_info.csv"

PRONOUN_FIRST = re.compile(r"^(i|we|he|she|they|me|us|him|her|them|my|our|his|their|hers|theirs|ourselves|myself|themselves|himself|herself|it)\b", re.I)
SELF_RE = re.compile(r"^(i|me|myself)$", re.I)
WE_RE = re.compile(r"^(we|us|ourselves)$", re.I)
MY_RE = re.compile(r"^(?:my)\s+(.+)$", re.I)
OUR_RE = re.compile(r"^(?:our)\s+(.+)$", re.I)
THIRD_RE = re.compile(r"^(he|she|they|him|her|them|his|hers|their|theirs)\b", re.I)

MALE_MARKERS = {"father", "brother", "uncle", "grandfather", "husband", "son",
                "dad", "papa", "grandpa", "boy", "man", "men", "boys", "sons",
                "brothers", "uncles", "grandfathers"}
FEMALE_MARKERS = {"mother", "sister", "aunt", "grandmother", "wife", "daughter",
                  "mom", "mama", "grandma", "girl", "woman", "women", "girls",
                  "daughters", "sisters", "aunts", "grandmothers"}

LOOKBACK = 10


def _has_any(text: str, markers: set[str]) -> bool:
    toks = re.findall(r"[a-zA-Z]+", text.lower())
    return any(t in markers for t in toks)


def _is_pronoun(text: str) -> bool:
    return bool(PRONOUN_FIRST.match(text.strip()))


def resolve_who(events: pd.DataFrame, meta_map: dict) -> tuple[list[str], list[str]]:
    resolved_all: list[str] = []
    method_all: list[str] = []

    prev_iv: int | None = None
    recent: deque[str] = deque(maxlen=LOOKBACK)

    for who_raw, iv in zip(events["who"].fillna("").tolist(),
                            events["interview_id"].tolist()):
        if iv != prev_iv:
            recent = deque(maxlen=LOOKBACK)
            prev_iv = iv

        meta = meta_map.get(iv, {})
        survivor = meta.get("name", "")
        gender = meta.get("gender", "")

        who = who_raw.strip()
        resolved = who
        method = "original"

        if not who:
            method = "empty"
        elif SELF_RE.match(who):
            resolved = survivor or who
            method = "rule_self"
        elif WE_RE.match(who):
            resolved = f"{survivor} and family" if survivor else who
            method = "rule_we"
        else:
            m_my = MY_RE.match(who)
            m_our = OUR_RE.match(who)
            if m_my or m_our:
                rel = (m_my or m_our).group(1).strip().rstrip(",.;:")
                resolved = f"{survivor}'s {rel}" if survivor else who
                method = "rule_relational"
            elif re.match(r"^i[,\s]", who, re.I):
                # Compound like "I, my mother" or "I and my brother"
                parts = re.split(r",|\sand\s", who, flags=re.I)
                new_parts = []
                for part in parts:
                    p = part.strip()
                    if not p:
                        continue
                    if SELF_RE.match(p):
                        new_parts.append(survivor or p)
                    elif MY_RE.match(p):
                        rel = MY_RE.match(p).group(1).strip()
                        new_parts.append(f"{survivor}'s {rel}" if survivor else p)
                    elif OUR_RE.match(p):
                        rel = OUR_RE.match(p).group(1).strip()
                        new_parts.append(f"{survivor}'s {rel}" if survivor else p)
                    else:
                        new_parts.append(p)
                resolved = ", ".join(new_parts)
                method = "rule_self_compound"
            elif THIRD_RE.match(who):
                first = who.lower().split()[0]
                candidates = list(recent)
                best = None
                if first in ("he", "him", "his"):
                    best = next((c for c in reversed(candidates) if _has_any(c, MALE_MARKERS)), None)
                    if not best:
                        # prefer survivor if male
                        if gender == "M" and survivor:
                            best = next((c for c in reversed(candidates) if c == survivor), None)
                elif first in ("she", "her", "hers"):
                    best = next((c for c in reversed(candidates) if _has_any(c, FEMALE_MARKERS)), None)
                    if not best and gender == "F" and survivor:
                        best = next((c for c in reversed(candidates) if c == survivor), None)
                elif first in ("they", "them", "their", "theirs"):
                    best = next((c for c in reversed(candidates)
                                 if (" and " in c.lower() or c.lower().endswith("s")
                                     or "family" in c.lower() or "parents" in c.lower())), None)
                if not best and candidates:
                    best = candidates[-1]
                if best:
                    if first in ("his", "her", "hers", "their", "theirs"):
                        resolved = f"{best}'s"
                    else:
                        resolved = best
                    method = "coref_local"
                else:
                    method = "unresolved_pronoun"

        # Feed buffer with non-pronoun resolved whos
        if resolved and not _is_pronoun(resolved) and method != "empty":
            if not recent or recent[-1] != resolved:
                recent.append(resolved)

        resolved_all.append(resolved)
        method_all.append(method)

    return resolved_all, method_all


def sticky_fill(events: pd.DataFrame, col: str) -> tuple[list[str], list[str]]:
    new_vals: list[str] = []
    methods: list[str] = []
    last_by_iv: dict[int, str] = {}
    for val, iv in zip(events[col].fillna("").tolist(),
                        events["interview_id"].tolist()):
        v = val.strip()
        if v and v.lower() != "not stated":
            last_by_iv[iv] = v
            new_vals.append(v)
            methods.append("original")
        elif iv in last_by_iv:
            new_vals.append(last_by_iv[iv])
            methods.append("context_sticky")
        else:
            new_vals.append("not stated")
            methods.append("unresolved")
    return new_vals, methods


def main() -> int:
    print(f"Loading {EVENTS_IN}")
    events = pd.read_parquet(EVENTS_IN)
    print(f"  {len(events):,} events")

    print(f"Loading {META_CSV}")
    meta_df = pd.read_csv(META_CSV, encoding="latin-1")
    meta_map = {
        int(row.IntCode): {"name": str(row.IntervieweeName), "gender": str(row.Gender)}
        for row in meta_df.itertuples(index=False)
        if pd.notna(row.IntCode) and pd.notna(row.IntervieweeName)
    }
    print(f"  {len(meta_map):,} interviews")

    # Sort by interview then by parsed suffix of utterance_id
    events["_uid_int"] = events["utterance_id"].str.split("_").str[1].astype(int)
    events = events.sort_values(["interview_id", "_uid_int"]).reset_index(drop=True)

    print("Resolving who...")
    who_resolved, who_method = resolve_who(events, meta_map)
    events["who_original"] = events["who"]
    events["who"] = who_resolved
    events["who_method"] = who_method

    print("Context-filling where...")
    where_new, where_method = sticky_fill(events, "where")
    events["where_original"] = events["where"]
    events["where"] = where_new
    events["where_method"] = where_method

    print("Context-filling when...")
    when_new, when_method = sticky_fill(events, "when")
    events["when_original"] = events["when"]
    events["when"] = when_new
    events["when_method"] = when_method

    events = events.drop(columns=["_uid_int"])

    # --- Summary ---
    print("\n=== Resolution summary ===")
    print("who_method:")
    print(events["who_method"].value_counts().to_string())
    print("\nwhere_method:")
    print(events["where_method"].value_counts().to_string())
    print("\nwhen_method:")
    print(events["when_method"].value_counts().to_string())

    print(f"\nWriting {EVENTS_OUT}")
    events.to_parquet(EVENTS_OUT, index=False)
    print(f"  {len(events):,} rows, {len(events.columns)} columns")
    print(f"  columns: {list(events.columns)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
