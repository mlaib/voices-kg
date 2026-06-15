"""Embedding similarity computation."""
from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)


def compute_similarity_edges(
    vectors: np.ndarray,
    keys: list[str],
    interview_ids: list[int],
    top_k: int = 5,
    threshold: float = 0.82,
) -> list[tuple[str, str, float, int]]:
    """Compute top-k cosine similarity edges per interview.

    Returns list of (key_i, key_j, score, interview_id) where i < j.
    """
    edges = []
    unique_iids = sorted(set(interview_ids))

    for iid in unique_iids:
        mask = [i for i, x in enumerate(interview_ids) if x == iid]
        if len(mask) < 2:
            continue
        if len(mask) > 3000:
            log.warning("Skipping interview %d: %d vectors (too large)", iid, len(mask))
            continue

        sub_vectors = vectors[mask]
        sub_keys = [keys[i] for i in mask]

        sim = sub_vectors @ sub_vectors.T
        np.fill_diagonal(sim, -1.0)

        for i in range(sim.shape[0]):
            row = sim[i]
            if top_k >= len(row):
                idxs = np.argsort(row)[::-1]
            else:
                idxs = np.argpartition(row, -top_k)[-top_k:]
                idxs = idxs[np.argsort(row[idxs])[::-1]]

            for j in idxs:
                score = float(row[j])
                if score < threshold:
                    break
                if i < j:
                    edges.append((sub_keys[i], sub_keys[j], score, iid))

    log.info("Computed %d similarity edges", len(edges))
    return edges
