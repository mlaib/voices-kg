"""Load OpenAI event embeddings from per-interview parquet files."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def load_embeddings(
    embeddings_dir: Path,
    interview_ids: list[int] | None = None,
) -> pd.DataFrame:
    log.info("Loading embeddings from %s", embeddings_dir)
    if not embeddings_dir.exists():
        log.warning("Embeddings directory not found: %s", embeddings_dir)
        return pd.DataFrame()

    files = sorted(embeddings_dir.glob("interview_*_embeddings_openai.parquet"))
    if interview_ids:
        id_set = set(interview_ids)
        files = [f for f in files if _extract_id(f) in id_set]

    frames = []
    for f in files:
        try:
            iid = _extract_id(f)
            df = pd.read_parquet(f)
            df["interview_id"] = iid
            frames.append(df)
        except Exception as e:
            log.warning("Failed to load %s: %s", f.name, e)

    if not frames:
        return pd.DataFrame()

    result = pd.concat(frames, ignore_index=True)
    log.info("Loaded %d embeddings from %d files", len(result), len(frames))
    return result


def _extract_id(path: Path) -> int:
    name = path.stem
    parts = name.split("_")
    return int(parts[1])


def embeddings_to_matrix(df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Convert embedding column to a numpy matrix + list of utterance_hashes."""
    vectors = np.stack(df["embedding"].to_numpy())
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    vectors = vectors / norms
    keys = df["utterance_hash"].tolist()
    return vectors, keys
