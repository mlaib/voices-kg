"""Concept linking: match topic/hierarchy labels to SKOS thesaurus concepts."""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

TERM_BASE = "http://voices.uni.lu/vocab/term/"


def _canon_key(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text)).strip()
    t = t.casefold()
    t = re.sub(r"\s*\([^)]*\)", "", t)
    return t.strip(" ;,.")


class ConceptLinker:
    """Link topic/hierarchy concept labels to SKOS thesaurus entries."""

    def __init__(self, skos_data: dict, alignment_data: dict):
        self._label_map = skos_data.get("label_map", {})
        self._concepts = skos_data.get("concepts", {})
        self._alignment = alignment_data
        self._local_cache: dict[str, str] = {}
        self._stats = {"exact": 0, "local": 0}

    def link(self, concept_label: str) -> dict:
        key = _canon_key(concept_label)
        if not key:
            return {}

        # Exact SKOS match
        if key in self._label_map:
            term_id = self._label_map[key]
            concept = self._concepts[term_id]
            self._stats["exact"] += 1
            info = {
                "iri": f"<{concept['iri']}>",
                "label": concept["label"],
                "type": "skos",
                "term_id": term_id,
            }
            if term_id in self._alignment:
                align = self._alignment[term_id]
                info["external_links"] = align["exact_matches"] + align["close_matches"]
            return info

        # Local concept node
        slug = re.sub(r"[^a-z0-9]+", "-", key).strip("-")[:80]
        if not slug:
            slug = "concept"
        iri = f"<urn:voices:concept:{slug}>"
        self._local_cache[iri] = concept_label
        self._stats["local"] += 1
        return {"iri": iri, "label": concept_label.strip(), "type": "local"}

    @property
    def stats(self) -> dict:
        return dict(self._stats)
