"""Path helpers shared across rebuild and indexer scripts."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

V1_DEFAULT_OUTPUT = "/mnt/d/Projets/voices/workspace/KG2026.paper/output"


def v1_output_dir() -> Path:
    """Directory containing the v1 .nq/.nqs to transform. Overridable via env."""
    return Path(os.environ.get("V1_OUTPUT_DIR", V1_DEFAULT_OUTPUT))


def output_dir() -> Path:
    d = REPO_ROOT / "output"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    d = output_dir() / "caches"
    d.mkdir(parents=True, exist_ok=True)
    return d
