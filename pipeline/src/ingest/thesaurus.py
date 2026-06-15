"""Load SFI Thesaurus SKOS + Wikidata/GeoNames alignment using rdflib."""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

TERM_BASE = "http://voices.uni.lu/vocab/term/"


def _normalize_key(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    text = text.casefold()
    text = re.sub(r"\s*\([^)]*\)", "", text)
    return text.strip(" ;,")


def load_thesaurus(thesaurus_path: Path) -> dict:
    """Load SKOS thesaurus: returns {normalized_label -> {iri, label, broader, notation}}."""
    log.info("Loading SKOS thesaurus from %s", thesaurus_path)
    if not thesaurus_path.exists():
        log.warning("Thesaurus file not found: %s", thesaurus_path)
        return {}

    concepts: dict[str, dict] = {}   # term_id -> info
    label_map: dict[str, str] = {}   # normalized_label -> term_id

    current_id = None
    with thesaurus_path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("@"):
                continue

            # New subject
            m = re.match(r"^(term:\d+)\b", line)
            if m:
                current_id = m.group(1).split(":")[1]
                if current_id not in concepts:
                    concepts[current_id] = {
                        "iri": f"{TERM_BASE}{current_id}",
                        "label": "",
                        "broader": None,
                        "notation": current_id,
                    }

            if current_id:
                pm = re.search(r'skos:prefLabel\s+"(.*?)"@en', line)
                if pm:
                    label = pm.group(1)
                    concepts[current_id]["label"] = label
                    label_map[_normalize_key(label)] = current_id

                bm = re.search(r"skos:broader\s+term:(\d+)", line)
                if bm:
                    concepts[current_id]["broader"] = bm.group(1)

    log.info("Loaded %d SKOS concepts, %d label entries", len(concepts), len(label_map))
    return {"concepts": concepts, "label_map": label_map}


def load_alignment(alignment_path: Path) -> dict[str, dict]:
    """Load voices-alignment.ttl: returns {term_id -> {exact/close matches, confidence}}."""
    log.info("Loading alignment from %s", alignment_path)
    if not alignment_path.exists():
        log.warning("Alignment file not found: %s", alignment_path)
        return {}

    alignments: dict[str, dict] = {}
    current_id = None

    with alignment_path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("@"):
                continue

            m = re.match(r"^term:(\d+)\b", line)
            if m:
                current_id = m.group(1)
                if current_id not in alignments:
                    alignments[current_id] = {
                        "exact_matches": [],
                        "close_matches": [],
                        "confidence": 0.0,
                    }

            if current_id:
                em = re.search(r"skos:exactMatch\s+<([^>]+)>", line)
                if em:
                    alignments[current_id]["exact_matches"].append(em.group(1))

                cm = re.search(r"skos:closeMatch\s+<([^>]+)>", line)
                if cm:
                    alignments[current_id]["close_matches"].append(cm.group(1))

                cf = re.search(r'voices:linkConfidence\s+"([^"]+)"', line)
                if cf:
                    try:
                        alignments[current_id]["confidence"] = float(cf.group(1))
                    except ValueError:
                        pass

    log.info("Loaded alignment for %d terms", len(alignments))
    return alignments
