"""Entity resolution for people and places across interviews."""
from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict

log = logging.getLogger(__name__)

TERM_BASE = "http://voices.uni.lu/vocab/term/"


def _normalize(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text


def _canon_key(text: str) -> str:
    t = _normalize(text).casefold()
    t = re.sub(r"\s*\([^)]*\)", "", t)
    return t.strip(" ;,.")


def _stable_id(text: str, length: int = 12) -> str:
    return hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:length]


def _slugify(text: str, length: int = 80) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (base or _stable_id(text))[:length]


# ---- People ----

NOT_A_PERSON = {
    "not stated", "none", "nan", "n/a", "unknown", "narrator",
    "interviewer", "the interviewer", "the narrator",
}


def split_people(value: str) -> list[str]:
    if not value:
        return []
    v = _normalize(value)
    if v.casefold() in NOT_A_PERSON:
        return []
    chunks = re.split(r"[;|]", v)
    out: list[str] = []
    for c in chunks:
        c = _normalize(c)
        if not c or c.casefold() in NOT_A_PERSON:
            continue
        if "," in c and not re.search(r"\b[A-Z][a-z]+,\s*[A-Z][a-z]+\b", c):
            out.extend([_normalize(p) for p in c.split(",") if _normalize(p)])
        else:
            out.append(c)
    return [p for p in out if p.casefold() not in NOT_A_PERSON and len(p) > 1]


class PersonResolver:
    """Cross-interview person entity resolution via canonical key."""

    def __init__(self):
        self._key_to_iri: dict[str, str] = {}
        self._iri_to_label: dict[str, str] = {}

    def resolve(self, name: str) -> tuple[str, str]:
        key = _canon_key(name)
        if key in self._key_to_iri:
            return self._key_to_iri[key], self._iri_to_label[self._key_to_iri[key]]
        iri = f"urn:voices:person:{_slugify(name)}"
        self._key_to_iri[key] = iri
        self._iri_to_label[iri] = _normalize(name)
        return iri, _normalize(name)

    @property
    def count(self) -> int:
        return len(self._iri_to_label)


# ---- Places ----

def split_locations(value: str) -> list[str]:
    if not value or value.strip().casefold() in ("not stated", "nan", "none", ""):
        return []
    parts = re.split(r"[;|]", _normalize(value))
    return [_normalize(p) for p in parts if _normalize(p) and
            _normalize(p).casefold() not in ("not stated", "nan", "none")]


class PlaceResolver:
    """Resolve place mentions to SKOS concepts or local nodes, with Wikidata/GeoNames chaining."""

    def __init__(self, skos_data: dict, alignment_data: dict):
        self._label_map = skos_data.get("label_map", {})
        self._concepts = skos_data.get("concepts", {})
        self._alignment = alignment_data
        self._local_cache: dict[str, str] = {}
        self._iri_to_info: dict[str, dict] = {}
        self._stats = {"skos_exact": 0, "local": 0}

    def resolve(self, place_text: str) -> dict:
        key = _canon_key(place_text)
        if not key:
            return {}

        # Try exact SKOS match
        if key in self._label_map:
            term_id = self._label_map[key]
            concept = self._concepts[term_id]
            iri = f"<{concept['iri']}>"
            self._stats["skos_exact"] += 1
            info = {
                "iri": iri,
                "label": concept["label"] or place_text,
                "type": "skos",
                "term_id": term_id,
                "match_method": "skos_exact",
            }
            # Chain to Wikidata/GeoNames
            if term_id in self._alignment:
                align = self._alignment[term_id]
                info["wikidata"] = [u for u in align["exact_matches"] + align["close_matches"]
                                    if "wikidata.org" in u]
                info["geonames"] = [u for u in align["exact_matches"] + align["close_matches"]
                                    if "geonames.org" in u]
                info["link_confidence"] = align["confidence"]
            self._iri_to_info[iri] = info
            return info

        # Mint local place node
        slug = _slugify(place_text)
        iri = f"<urn:voices:place:{slug}>"
        if iri not in self._local_cache:
            self._local_cache[iri] = place_text
            self._stats["local"] += 1
        info = {"iri": iri, "label": _normalize(place_text), "type": "local", "match_method": "local_mint"}
        self._iri_to_info[iri] = info
        return info

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    @property
    def all_places(self) -> dict[str, dict]:
        return dict(self._iri_to_info)
