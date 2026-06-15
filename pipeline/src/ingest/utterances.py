"""Load utterances.parquet — transcript segments with timestamps."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

COLUMNS = [
    "interview_id", "part_number", "filename", "text",
    "start_timestamp", "end_timestamp", "speakers",
    "word_count", "duration_ms",
]


def load_utterances(path: Path, interview_ids: list[int] | None = None) -> pd.DataFrame:
    log.info("Loading utterances from %s", path)
    df = pd.read_parquet(path)
    # Keep only columns we need (that exist)
    cols = [c for c in COLUMNS if c in df.columns]
    df = df[cols].copy()
    if interview_ids:
        df = df[df["interview_id"].isin(interview_ids)].copy()

    df["text"] = df["text"].fillna("").astype(str)
    df["speakers"] = df["speakers"].fillna("").astype(str)

    # Build a stable utterance_id: interview_id + '_' + global row index
    df = df.reset_index(drop=True)
    df["utterance_id"] = df["interview_id"].astype(str) + "_" + df.index.astype(str)

    log.info("Loaded %d utterances across %d interviews",
             len(df), df["interview_id"].nunique())
    return df
