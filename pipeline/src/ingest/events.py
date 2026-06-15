"""Load events_v7.parquet — LLM-extracted who/what/where/when/emotion per utterance.

Pronouns in `who` are resolved (Tier 1-3 rules in scripts/resolve_events_v7.py)
and `where`/`when` are forward-filled with sticky context within each interview.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

COLUMNS = [
    "utterance_id", "interview_id", "utterance_hash",
    "who", "what", "where", "when", "emotion",
]


def load_events(path: Path, interview_ids: list[int] | None = None) -> pd.DataFrame:
    log.info("Loading events from %s", path)
    try:
        if interview_ids:
            df = pd.read_parquet(path, columns=COLUMNS,
                                 filters=[("interview_id", "in", interview_ids)])
        else:
            df = pd.read_parquet(path, columns=COLUMNS)
    except Exception:
        df = pd.read_parquet(path, columns=COLUMNS)
        if interview_ids:
            df = df[df["interview_id"].isin(interview_ids)].copy()

    for col in ["who", "what", "where", "when", "emotion"]:
        df[col] = df[col].fillna("").astype(str)

    log.info("Loaded %d events across %d interviews", len(df), df["interview_id"].nunique())
    return df
