#!/usr/bin/env python3
"""Generate a tiny SYNTHETIC input set so the construction pipeline (Stages 3–4)
runs end-to-end with **zero gated inputs** — no VHA transcripts, no SFI thesaurus,
no OpenAI calls.

The text below is entirely invented for testing; it is NOT from any testimony.
Running this then `src/build.py --config config/config.sample.yaml` produces a toy
`sample/output/kg2026_paper.nq` that exercises every transform (activities, causes,
modes, historical events, temporal, emotions, places, people, physiology).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
PROC = BASE / "data" / "processed"
RAW = BASE / "data" / "raw"
PROC.mkdir(parents=True, exist_ok=True)
RAW.mkdir(parents=True, exist_ok=True)

# (interview_id, speaker, text) — invented sample utterances.
UTTERANCES = [
    (1, "INT", "INT: Where were you born?"),
    (1, "INTERVIEWEE", "We lived in Lviv before the war."),
    (1, "INTERVIEWEE", "In 1942 we were deported to the camp by train. [CRYING]"),
    (1, "INTERVIEWEE", "We were liberated in 1945."),
    (2, "INTERVIEWEE", "My father worked in forced labour in the factory."),
    (2, "INTERVIEWEE", "We were hiding in the forest before the war."),
    (2, "INTERVIEWEE", "I felt such fear during the war. [SILENCE]"),
    (3, "INTERVIEWEE", "After the war we moved to Berlin."),
    (3, "INTERVIEWEE", "I testified about these events many years later. [LAUGHTER]"),
]

# Build utterances frame in order; the loader assigns utterance_id = "<iid>_<global_row_index>".
urows = []
for pos, (iid, spk, text) in enumerate(UTTERANCES):
    urows.append({
        "interview_id": iid,
        "part_number": 1,
        "filename": f"{iid}.1.xml",
        "text": text,
        "start_timestamp": pos * 1000,
        "end_timestamp": pos * 1000 + 900,
        "speakers": spk,
        "word_count": len(text.split()),
        "char_count": len(text),
        "duration_ms": 900,
        "duration_minutes": 0.015,
    })
utt = pd.DataFrame(urows)
utt.to_parquet(PROC / "utterances.parquet", index=False)

# utterance_id as the loader computes it (global index over the loaded frame).
uid = [f'{r["interview_id"]}_{i}' for i, r in utt.reset_index(drop=True).iterrows()]

# events_v7: one narrated event per non-INT utterance, fields chosen to exercise transforms.
# index → (who, what, where, when, emotion)
EVENTS = {
    1: ("I; my family", "lived", "Lviv", "before the war", "nostalgia"),
    2: ("I; my family", "deported to the camp by train", "Auschwitz", "1942", "fear"),
    3: ("I", "liberated", "not stated", "1945", "relief"),
    4: ("my father", "forced labour in the factory", "Berlin", "during the war", "sadness"),
    5: ("we", "hiding in the forest", "forest", "before the war", "fear"),
    6: ("I", "not stated", "not stated", "during the war", "fear"),
    7: ("we", "moved to Berlin", "Berlin", "after the war", "hope"),
    8: ("I", "testified about these events", "not stated", "later", "determination"),
}
erows = []
for idx, (who, what, where, when, emo) in EVENTS.items():
    iid = utt.iloc[idx]["interview_id"]
    u = uid[idx]
    uhash = hashlib.md5(f"{u}|{what}".encode()).hexdigest()[:12]
    erows.append({
        "utterance_id": u,
        "interview_id": int(iid),
        "utterance_hash": uhash,
        "who": who, "what": what, "where": where, "when": when, "emotion": emo,
    })
pd.DataFrame(erows).to_parquet(PROC / "events_v7.parquet", index=False)

# metadata (invented)
meta = pd.DataFrame([
    {"IntCode": 1, "IntervieweeName": "Sample Survivor One", "Gender": "F",
     "recording_year": "1996", "testimony_title": "Sample Testimony 1"},
    {"IntCode": 2, "IntervieweeName": "Sample Survivor Two", "Gender": "M",
     "recording_year": "1997", "testimony_title": "Sample Testimony 2"},
    {"IntCode": 3, "IntervieweeName": "Sample Survivor Three", "Gender": "F",
     "recording_year": "1998", "testimony_title": "Sample Testimony 3"},
])
meta.to_csv(RAW / "transcript_testimonies_info.csv", index=False)

print(f"Wrote {len(utt)} utterances, {len(erows)} events, {len(meta)} interviews under {BASE}")
