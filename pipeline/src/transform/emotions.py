"""Emotion processing: VAD scoring, physiological marker extraction."""
from __future__ import annotations

import re

# Valence-Arousal-Dominance lookup (expanded from v1)
EMOTION_VAD: dict[str, tuple[float, float, float]] = {
    "happiness": (0.90, 0.70, 0.80),
    "joy": (0.90, 0.75, 0.80),
    "relief": (0.60, 0.40, 0.50),
    "gratitude": (0.70, 0.50, 0.55),
    "hope": (0.60, 0.60, 0.60),
    "love": (0.85, 0.65, 0.65),
    "pride": (0.75, 0.65, 0.70),
    "sadness": (-0.80, 0.50, 0.70),
    "grief": (-0.90, 0.70, 0.85),
    "sorrow": (-0.85, 0.60, 0.75),
    "fear": (-0.90, 0.80, 0.85),
    "terror": (-0.95, 0.95, 0.90),
    "anxiety": (-0.70, 0.70, 0.65),
    "anger": (-0.80, 0.85, 0.80),
    "rage": (-0.90, 0.95, 0.90),
    "frustration": (-0.60, 0.65, 0.60),
    "disgust": (-0.75, 0.60, 0.65),
    "shame": (-0.70, 0.50, 0.65),
    "guilt": (-0.70, 0.55, 0.70),
    "confusion": (-0.30, 0.50, 0.45),
    "surprise": (0.20, 0.80, 0.60),
    "nostalgia": (0.10, 0.40, 0.50),
    "resignation": (-0.50, 0.30, 0.55),
    "determination": (0.40, 0.70, 0.75),
    "loneliness": (-0.75, 0.40, 0.65),
    "despair": (-0.95, 0.60, 0.85),
    "trauma": (-0.90, 0.75, 0.85),
    "bitterness": (-0.70, 0.55, 0.65),
    "helplessness": (-0.85, 0.50, 0.80),
    "disbelief": (-0.40, 0.65, 0.55),
}


def score_emotion(label: str) -> tuple[float, float, float]:
    """Return (valence, arousal, intensity) for an emotion label."""
    key = re.sub(r"\s+", " ", str(label)).strip().lower()
    if key in EMOTION_VAD:
        return EMOTION_VAD[key]
    # Fuzzy substring match
    for k, v in EMOTION_VAD.items():
        if k in key or key in k:
            return v
    return (0.0, 0.5, 0.5)


def classify_emotion_category(label: str) -> str:
    """Map an emotion label to a high-level category."""
    key = label.strip().lower()
    positive = {"happiness", "joy", "relief", "gratitude", "hope", "love", "pride",
                "determination", "surprise"}
    negative_high = {"fear", "terror", "anger", "rage", "despair", "trauma", "helplessness"}
    negative_low = {"sadness", "grief", "sorrow", "shame", "guilt", "loneliness",
                    "resignation", "nostalgia", "bitterness"}

    for p in positive:
        if p in key:
            return "positive"
    for n in negative_high:
        if n in key:
            return "negative_high_arousal"
    for n in negative_low:
        if n in key:
            return "negative_low_arousal"
    return "neutral"


def parse_emotions(emotion_text: str) -> list[dict]:
    """Parse emotion field (may contain multiple, semicolon-separated)."""
    if not emotion_text or emotion_text.strip().casefold() in ("not stated", "nan", "none", ""):
        return []

    labels = [e.strip() for e in re.split(r"[;,]", emotion_text) if e.strip()]
    results = []
    for label in labels:
        if label.casefold() in ("not stated", "nan"):
            continue
        v, a, i = score_emotion(label)
        results.append({
            "label": label,
            "valence": v,
            "arousal": a,
            "intensity": i,
            "category": classify_emotion_category(label),
        })
    return results


# ---- Physiological markers ----

PHYSIO_MARKERS = {
    "CRYING": "crying",
    "SOBBING": "sobbing",
    "SIGH": "sighing",
    "LAUGH": "laughing",
    "LAUGHING": "laughing",
    "PAUSE": "pause",
    "LONG PAUSE": "long_pause",
    "SILENCE": "silence",
    "WHISPER": "whispering",
    "WHISPERING": "whispering",
    "SHOUT": "shouting",
    "SHOUTING": "shouting",
    "BREATHING": "heavy_breathing",
    "HEAVY BREATHING": "heavy_breathing",
    "COUGH": "coughing",
    "COUGHING": "coughing",
    "CLEARS THROAT": "clearing_throat",
}


def extract_physio_markers(text: str) -> list[str]:
    if not text:
        return []
    found = re.findall(r"\[([A-Z][A-Z\s]{2,30})\]", text)
    out = []
    for f in found:
        label = re.sub(r"\s+", " ", f).strip().upper()
        if label in PHYSIO_MARKERS:
            out.append(PHYSIO_MARKERS[label])
    return list(set(out))
