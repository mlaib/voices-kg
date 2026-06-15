"""Load topic and hierarchy CSV tables."""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)


def _clean_col(col: str) -> str:
    c = re.sub(r"\s+", " ", str(col)).strip()
    c = re.sub(r"\(N\d+\)", "", c)
    return c.strip()


def load_topic_tables(
    topics_dir: Path,
    interview_ids: list[int] | None = None,
    source_label: str = "topics_flat",
) -> dict[int, pd.DataFrame]:
    """Load per-interview topic CSV files. Returns {interview_id -> melted DataFrame}."""
    log.info("Loading topic tables from %s", topics_dir)
    if not topics_dir.exists():
        return {}

    files = sorted(topics_dir.glob("interview_*.csv"))
    result: dict[int, pd.DataFrame] = {}

    for f in files:
        try:
            iid = int(f.stem.split("_")[1])
        except (IndexError, ValueError):
            continue
        if interview_ids and iid not in interview_ids:
            continue

        try:
            df = pd.read_csv(f)
        except Exception as e:
            log.warning("Failed to load %s: %s", f.name, e)
            continue

        if "segment_number" not in df.columns:
            continue

        value_cols = [c for c in df.columns
                      if c not in {"segment_number", "unmatched_keywords", "segment"}]
        if not value_cols:
            continue

        melted = df.melt(
            id_vars=["segment_number"],
            value_vars=value_cols,
            var_name="concept",
            value_name="weight",
        )
        melted["weight"] = pd.to_numeric(melted["weight"], errors="coerce")
        melted = melted.dropna(subset=["weight"])
        melted["concept"] = melted["concept"].map(_clean_col)
        melted["source"] = source_label
        result[iid] = melted

    log.info("Loaded topic tables for %d interviews", len(result))
    return result


def load_hierarchy_tables(
    hierarchy_dir: Path,
    interview_ids: list[int] | None = None,
) -> dict[int, pd.DataFrame]:
    return load_topic_tables(
        hierarchy_dir, interview_ids, source_label="topics_hierarchy"
    )
