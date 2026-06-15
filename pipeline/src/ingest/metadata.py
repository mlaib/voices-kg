"""Load interview metadata CSV."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)


def load_metadata(path: Path, interview_ids: list[int] | None = None) -> pd.DataFrame:
    log.info("Loading metadata from %s", path)
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(path, encoding=enc)
            break
        except (UnicodeDecodeError, Exception):
            continue
    else:
        df = pd.read_csv(path, encoding="latin-1", errors="replace")

    if interview_ids:
        df = df[df["IntCode"].isin(interview_ids)].copy()

    log.info("Loaded metadata for %d interviews", len(df))
    return df


def metadata_by_id(df: pd.DataFrame) -> dict[int, dict]:
    return {int(row["IntCode"]): row.to_dict() for _, row in df.iterrows()}
