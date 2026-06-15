#!/usr/bin/env python3
"""KG2026.paper — Knowledge graph builder (paper-aligned implementation).

Orchestrates: ingest → transform → serialize → validate.
Produces N-Quads with named graphs, stats JSON.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# ---- local imports (resolve paths) ----
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.ingest.events import load_events
from src.ingest.utterances import load_utterances
from src.ingest.metadata import load_metadata, metadata_by_id
from src.ingest.thesaurus import load_thesaurus, load_alignment
from src.ingest.embeddings import load_embeddings
from src.ingest.topics import load_topic_tables, load_hierarchy_tables
from src.transform.entities import (
    PersonResolver, PlaceResolver, split_people, split_locations,
)
from src.transform.temporal import parse_when, temporal_bucket
from src.transform.emotions import parse_emotions, extract_physio_markers
from src.transform.activities import (
    classify_activities, classify_modes, classify_causes, classify_historical_events,
)
from src.transform.concepts import ConceptLinker
from src.serialize.nquads import (
    NQuadWriter, literal, iri,
    RDF_TYPE, RDFS_LABEL, RDFS_COMMENT,
    XSD_INT, XSD_FLOAT, XSD_GYEAR, XSD_DATETIME,
)
from src.serialize.stats import StatsCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("kg2026_paper")

# ---- Namespace constants ----
VOICES = "http://voices.uni.lu/ontology#"
CRM = "http://www.cidoc-crm.org/cidoc-crm/"
SKOS = "http://www.w3.org/2004/02/skos/core#"
TIME = "http://www.w3.org/2006/time#"
OA = "http://www.w3.org/ns/oa#"
MA = "http://www.w3.org/ns/ma-ont#"
PROV = "http://www.w3.org/ns/prov#"

# Named graphs
G_META = "urn:voices:graph:metadata"
G_TRANS = "urn:voices:graph:transcripts"
G_EVENTS = "urn:voices:graph:events"
G_ANNOT = "urn:voices:graph:annotations"
G_CONCEPTS = "urn:voices:graph:concepts"
G_EMBED = "urn:voices:graph:embeddings"
G_PROV = "urn:voices:graph:provenance"
G_ALIGN = "urn:voices:graph:alignment"


def _stable_id(text: str, length: int = 12) -> str:
    return hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:length]


def _slugify(text: str, length: int = 80) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (base or _stable_id(text))[:length]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def _coerce(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = _normalize(str(value))
    return "" if text.casefold() == "nan" else text


def parse_interview_ids(arg: str, events_df: pd.DataFrame, meta_df: pd.DataFrame) -> list[int]:
    arg = arg.strip().lower()
    if arg == "all":
        e_ids = set(events_df["interview_id"].dropna().astype(int).unique())
        m_ids = set(meta_df["IntCode"].dropna().astype(int).unique())
        return sorted(e_ids.intersection(m_ids))
    return sorted(set(int(x.strip()) for x in arg.split(",") if x.strip()))


def build(config_path: Path, interview_ids_override: str | None = None) -> dict:
    """Main build entry point."""
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = Path(cfg["paths"]["workspace_root"])
    # A relative workspace_root is resolved against the pipeline/ directory
    # (config lives in pipeline/config/), so the pipeline is location-independent
    # and standalone. Absolute paths are used as-is.
    if not root.is_absolute():
        root = (config_path.resolve().parent.parent / root)

    run_id = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log.info("=== KG2026.paper build started — run %s ===", run_id)

    # ---- 1. INGEST ----
    log.info("--- Phase 1: Ingest ---")

    events_path = root / cfg["paths"]["events_parquet"]
    utt_path = root / cfg["paths"]["utterances_parquet"]
    meta_path = root / cfg["paths"]["metadata_csv"]
    thesaurus_path = root / cfg["paths"]["thesaurus_ttl"]
    alignment_path = root / cfg["paths"]["alignment_ttl"]
    topics_dir = root / cfg["paths"]["topics_dir"]
    hierarchy_dir = root / cfg["paths"]["hierarchy_dir"]
    embeddings_dir = root / cfg["paths"]["embeddings_dir"]
    out_dir = root / cfg["paths"]["output_dir"]

    # Determine interview IDs
    ids_arg = interview_ids_override or cfg["build"]["interview_ids"]
    events_all = pd.read_parquet(events_path, columns=["interview_id"])
    meta_all = load_metadata(meta_path)
    interview_ids = parse_interview_ids(ids_arg, events_all, meta_all)
    log.info("Building for %d interviews", len(interview_ids))

    # Load data
    events = load_events(events_path, interview_ids)
    utterances = load_utterances(utt_path, interview_ids)
    meta = load_metadata(meta_path, interview_ids)
    meta_map = metadata_by_id(meta)
    skos_data = load_thesaurus(thesaurus_path)
    alignment_data = load_alignment(alignment_path)

    # ---- 2. SETUP RESOLVERS ----
    person_resolver = PersonResolver()
    place_resolver = PlaceResolver(skos_data, alignment_data)
    concept_linker = ConceptLinker(skos_data, alignment_data)

    # ---- 3. SERIALIZE ----
    log.info("--- Phase 2: Transform + Serialize ---")
    out_dir.mkdir(parents=True, exist_ok=True)
    nq_path = out_dir / "kg2026_paper.nq"
    writer = NQuadWriter(nq_path)

    stats = StatsCollector(run_id, interview_ids, {
        "include_topics": cfg["build"]["include_topics"],
        "include_hierarchy": cfg["build"]["include_hierarchy"],
        "include_embeddings": cfg["build"]["include_embeddings"],
        "compute_similarity": cfg["build"]["compute_similarity"],
    })

    created_at = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
    run_iri = iri(f"urn:voices:run:{run_id}")

    # Provenance run
    writer.quad(run_iri, RDF_TYPE, iri(f"{PROV}Activity"), G_PROV)
    writer.quad(run_iri, RDFS_LABEL, literal("KG2026.paper build run"), G_PROV)
    writer.quad(run_iri, iri(f"{PROV}startedAtTime"), literal(created_at, datatype=XSD_DATETIME), G_PROV)

    # Source provenance
    for name, path in [("events", events_path), ("utterances", utt_path),
                       ("metadata", meta_path), ("thesaurus", thesaurus_path),
                       ("alignment", alignment_path)]:
        src = iri(f"urn:voices:source:{name}")
        writer.quad(src, RDF_TYPE, iri(f"{PROV}Entity"), G_PROV)
        writer.quad(src, RDFS_LABEL, literal(name), G_PROV)
        writer.quad(run_iri, iri(f"{PROV}used"), src, G_PROV)

    # Track entities for dedup
    emitted_people: set[str] = set()
    emitted_places: set[str] = set()
    emitted_activities: set[str] = set()
    emitted_modes: set[str] = set()
    emitted_causes: set[str] = set()
    emitted_hist: set[str] = set()
    emitted_emotions: set[str] = set()

    # -- Per-interview processing --
    for idx, iid in enumerate(interview_ids):
        if idx % 50 == 0:
            log.info("Processing interview %d/%d (id=%d)", idx + 1, len(interview_ids), iid)

        interview_iri = iri(f"urn:voices:interview:{iid}")
        writer.quad(interview_iri, RDF_TYPE, iri(f"{VOICES}Interview"), G_META)
        writer.quad(interview_iri, iri(f"{VOICES}interviewId"), literal(str(iid), datatype=XSD_INT), G_META)
        writer.quad(interview_iri, iri(f"{PROV}wasGeneratedBy"), run_iri, G_PROV)
        stats.add("interviews")

        # Metadata
        if iid in meta_map:
            row = meta_map[iid]
            name = _coerce(row.get("IntervieweeName"))
            if name:
                writer.quad(interview_iri, RDFS_LABEL, literal(name, lang="en"), G_META)
            for col, pred in [
                ("Gender", "gender"), ("CollectionOwner", "collectionOwner"),
                ("recording_year", "recordingYear"), ("testimony_title", "testimonyTitle"),
                ("provenance", "provenance"), ("interview_summary", "interviewSummary"),
            ]:
                val = _coerce(row.get(col))
                if val:
                    writer.quad(interview_iri, iri(f"{VOICES}{pred}"), literal(val), G_META)
            for col in ("media_url", "thumbnail_url"):
                val = _coerce(row.get(col))
                if val:
                    writer.quad(interview_iri, iri(f"{VOICES}{col}"), literal(val), G_META)

        # Utterances for this interview
        iid_utts = utterances[utterances["interview_id"] == iid].copy()
        utt_id_list = iid_utts["utterance_id"].tolist()

        for u_idx, (_, urow) in enumerate(iid_utts.iterrows()):
            uid = urow["utterance_id"]
            seg_iri = iri(f"urn:voices:segment:{uid}")
            writer.quad(seg_iri, RDF_TYPE, iri(f"{VOICES}InterviewSegment"), G_TRANS)
            writer.quad(interview_iri, iri(f"{VOICES}hasSegment"), seg_iri, G_TRANS)
            writer.quad(seg_iri, iri(f"{VOICES}utteranceId"), literal(uid), G_TRANS)
            writer.quad(seg_iri, iri(f"{VOICES}segmentOrdinal"), literal(str(u_idx), datatype=XSD_INT), G_TRANS)

            text = _coerce(urow.get("text"))
            if text:
                writer.quad(seg_iri, iri(f"{VOICES}transcriptText"), literal(text, lang="en"), G_TRANS)

            speaker = _coerce(urow.get("speakers"))
            if speaker:
                writer.quad(seg_iri, iri(f"{VOICES}speakerCode"), literal(speaker), G_TRANS)

            for ts_col, pred in [("start_timestamp", "startTimestampMs"), ("end_timestamp", "endTimestampMs")]:
                ts = urow.get(ts_col)
                if ts is not None and not (isinstance(ts, float) and math.isnan(ts)):
                    writer.quad(seg_iri, iri(f"{VOICES}{pred}"), literal(str(int(ts)), datatype=XSD_INT), G_TRANS)

            # Physiology from transcript markers
            markers = extract_physio_markers(text)
            for marker in markers:
                marker_iri = iri(f"urn:voices:physio:{_slugify(marker)}")
                writer.quad(seg_iri, iri(f"{VOICES}hasPhysiologicalProcess"), marker_iri, G_ANNOT)
                writer.quad(marker_iri, RDFS_LABEL, literal(marker), G_ANNOT)
                stats.add("physio_annotations")

            stats.add("segments")

        # Events for this interview
        iid_events = events[events["interview_id"] == iid].copy()

        for _, erow in iid_events.iterrows():
            uid = str(erow["utterance_id"])
            uhash = str(erow["utterance_hash"])
            event_iri = iri(f"urn:voices:event:{uhash}")
            seg_iri = iri(f"urn:voices:segment:{uid}")

            writer.quad(event_iri, RDF_TYPE, iri(f"{VOICES}NarratedEvent"), G_EVENTS)
            writer.quad(seg_iri, iri(f"{VOICES}segmentRefersToEvent"), event_iri, G_EVENTS)
            stats.add("events")

            # WHO — people
            who_text = _coerce(erow.get("who"))
            for person_name in split_people(who_text):
                p_iri, p_label = person_resolver.resolve(person_name)
                p_iri_str = iri(p_iri)
                writer.quad(event_iri, iri(f"{VOICES}hasParticipant"), p_iri_str, G_EVENTS)
                if p_iri not in emitted_people:
                    writer.quad(p_iri_str, RDF_TYPE, iri(f"{VOICES}Person"), G_EVENTS)
                    writer.quad(p_iri_str, RDFS_LABEL, literal(p_label, lang="en"), G_EVENTS)
                    emitted_people.add(p_iri)

            # WHAT
            what_text = _coerce(erow.get("what"))
            if what_text and what_text.casefold() != "not stated":
                writer.quad(event_iri, iri(f"{VOICES}whatText"), literal(what_text, lang="en"), G_EVENTS)

                # Activities
                has_activity = iri(f"{VOICES}hasActivity")
                for act in classify_activities(what_text):
                    act_iri = iri(f"urn:voices:activity:{act}")
                    writer.quad(event_iri, has_activity, act_iri, G_EVENTS)
                    if act not in emitted_activities:
                        writer.quad(act_iri, RDF_TYPE, iri(f"{VOICES}Activity"), G_EVENTS)
                        writer.quad(act_iri, RDFS_LABEL, literal(act.replace("_", " ")), G_EVENTS)
                        emitted_activities.add(act)
                        stats.add("activities")

                # Modes
                has_mode = iri(f"{VOICES}hasMode")
                for mode in classify_modes(what_text):
                    mode_iri = iri(f"urn:voices:mode:{mode}")
                    writer.quad(event_iri, has_mode, mode_iri, G_EVENTS)
                    if mode not in emitted_modes:
                        writer.quad(mode_iri, RDF_TYPE, iri(f"{VOICES}Mode"), G_EVENTS)
                        writer.quad(mode_iri, RDFS_LABEL, literal(mode.replace("_", " ")), G_EVENTS)
                        emitted_modes.add(mode)
                        stats.add("modes")

                # Causes
                has_cause = iri(f"{VOICES}hasCause")
                for cause in classify_causes(what_text):
                    cause_iri = iri(f"urn:voices:cause:{cause}")
                    writer.quad(event_iri, has_cause, cause_iri, G_EVENTS)
                    if cause not in emitted_causes:
                        writer.quad(cause_iri, RDF_TYPE, iri(f"{VOICES}Cause"), G_EVENTS)
                        writer.quad(cause_iri, RDFS_LABEL, literal(cause.replace("_", " ")), G_EVENTS)
                        emitted_causes.add(cause)
                        stats.add("causes")

                # Historical events
                has_hist = iri(f"{VOICES}alignsWithHistoricalEvent")
                for hist in classify_historical_events(what_text):
                    hist_iri = iri(f"urn:voices:historical:{_slugify(hist)}")
                    writer.quad(event_iri, has_hist, hist_iri, G_EVENTS)
                    if hist not in emitted_hist:
                        writer.quad(hist_iri, RDF_TYPE, iri(f"{VOICES}HistoricalEvent"), G_EVENTS)
                        writer.quad(hist_iri, RDFS_LABEL, literal(hist.replace("_", " ")), G_EVENTS)
                        emitted_hist.add(hist)
                        stats.add("historical_events")

            # WHERE — places
            where_text = _coerce(erow.get("where"))
            has_location = iri(f"{VOICES}hasLocation")
            skos_exact_match = iri(f"{SKOS}exactMatch")
            for place_name in split_locations(where_text):
                place_info = place_resolver.resolve(place_name)
                if place_info:
                    p_iri = place_info["iri"]
                    writer.quad(event_iri, has_location, p_iri, G_EVENTS)

                    if p_iri not in emitted_places:
                        if place_info["type"] == "skos":
                            writer.quad(p_iri, RDF_TYPE, iri(f"{SKOS}Concept"), G_EVENTS)
                        else:
                            writer.quad(p_iri, RDF_TYPE, iri(f"{CRM}E53_Place"), G_EVENTS)
                        writer.quad(p_iri, RDFS_LABEL, literal(place_info["label"], lang="en"), G_EVENTS)

                        # Wikidata/GeoNames alignment
                        for wk in place_info.get("wikidata", []):
                            writer.quad(p_iri, skos_exact_match, iri(wk), G_ALIGN)
                            stats.add("wikidata_links")
                        for gn in place_info.get("geonames", []):
                            writer.quad(p_iri, skos_exact_match, iri(gn), G_ALIGN)
                            stats.add("geonames_links")

                        emitted_places.add(p_iri)

            # WHEN — temporal
            when_text = _coerce(erow.get("when"))
            when_info = parse_when(when_text)
            if when_info:
                writer.quad(event_iri, iri(f"{VOICES}whenText"), literal(when_text), G_EVENTS)
                has_time_interval = iri(f"{VOICES}hasTimeInterval")
                if when_info.get("start_year"):
                    interval_iri = iri(f"urn:voices:time:{uhash}")
                    writer.quad(event_iri, has_time_interval, interval_iri, G_EVENTS)
                    writer.quad(interval_iri, RDF_TYPE, iri(f"{TIME}Interval"), G_EVENTS)
                    writer.quad(interval_iri, iri(f"{TIME}hasBeginning"),
                                literal(str(when_info["start_year"]), datatype=XSD_GYEAR), G_EVENTS)
                    if when_info.get("end_year"):
                        writer.quad(interval_iri, iri(f"{TIME}hasEnd"),
                                    literal(str(when_info["end_year"]), datatype=XSD_GYEAR), G_EVENTS)
                    stats.add("temporal_annotations")

                bucket = temporal_bucket(when_info)
                if bucket:
                    writer.quad(event_iri, iri(f"{VOICES}temporalBucket"), literal(bucket), G_EVENTS)

            # EMOTION
            emotion_text = _coerce(erow.get("emotion"))
            has_emotion = iri(f"{VOICES}hasEmotion")
            for emo in parse_emotions(emotion_text):
                emo_slug = _slugify(emo["label"])
                emo_iri = iri(f"urn:voices:emotion:{uhash}:{emo_slug}")
                writer.quad(event_iri, has_emotion, emo_iri, G_ANNOT)
                writer.quad(emo_iri, RDF_TYPE, iri(f"{VOICES}EmotionAnnotation"), G_ANNOT)
                writer.quad(emo_iri, RDFS_LABEL, literal(emo["label"]), G_ANNOT)
                writer.quad(emo_iri, iri(f"{VOICES}hasValence"), literal(str(emo["valence"]), datatype=XSD_FLOAT), G_ANNOT)
                writer.quad(emo_iri, iri(f"{VOICES}hasArousal"), literal(str(emo["arousal"]), datatype=XSD_FLOAT), G_ANNOT)
                writer.quad(emo_iri, iri(f"{VOICES}hasIntensity"), literal(str(emo["intensity"]), datatype=XSD_FLOAT), G_ANNOT)
                writer.quad(emo_iri, iri(f"{VOICES}emotionCategory"), literal(emo["category"]), G_ANNOT)

                if emo["label"] not in emitted_emotions:
                    emitted_emotions.add(emo["label"])
                stats.add("emotion_annotations")

    # ---- CONCEPT MENTIONS ----
    if cfg["build"]["include_topics"]:
        log.info("--- Phase 3: Concept mentions ---")
        topic_tables = load_topic_tables(topics_dir, interview_ids)
        hierarchy_tables = {}
        if cfg["build"]["include_hierarchy"]:
            hierarchy_tables = load_hierarchy_tables(hierarchy_dir, interview_ids)

        topic_thresh = cfg["thresholds"]["topic_weight_min"]
        hier_thresh = cfg["thresholds"]["hierarchy_weight_min"]
        hier_top_k = cfg["thresholds"]["hierarchy_top_k"]

        for iid in interview_ids:
            iid_utts = utterances[utterances["interview_id"] == iid]
            utt_ids = iid_utts["utterance_id"].tolist()
            if not utt_ids:
                continue

            for source_label, tables, thresh, top_k in [
                ("topics_flat", topic_tables, topic_thresh, None),
                ("topics_hierarchy", hierarchy_tables, hier_thresh, hier_top_k),
            ]:
                if iid not in tables:
                    continue
                df = tables[iid]
                df = df[df["weight"] >= thresh]
                if top_k is not None:
                    df = (df.sort_values(["segment_number", "weight"], ascending=[True, False])
                          .groupby("segment_number", as_index=False).head(top_k))

                if df.empty:
                    continue

                n_segments = int(df["segment_number"].max())
                seg_size = len(utt_ids) / max(n_segments, 1)

                for _, crow in df.iterrows():
                    seg_n = int(crow["segment_number"])
                    concept_label = str(crow["concept"]).strip()
                    weight = float(crow["weight"])
                    if not concept_label:
                        continue

                    # Map segment number to utterance IDs
                    start_idx = int((seg_n - 1) * seg_size)
                    end_idx = min(int(seg_n * seg_size), len(utt_ids))
                    target_uids = utt_ids[start_idx:end_idx] if start_idx < len(utt_ids) else []

                    info = concept_linker.link(concept_label)
                    if not info:
                        continue

                    for uid in target_uids[:1]:  # Link to first utterance in segment
                        seg_iri = iri(f"urn:voices:segment:{uid}")
                        cm_iri = iri(f"urn:voices:concept-mention:{_stable_id(f'{uid}:{concept_label}:{source_label}')}")
                        writer.quad(seg_iri, iri(f"{VOICES}hasConceptMention"), cm_iri, G_CONCEPTS)
                        writer.quad(cm_iri, RDF_TYPE, iri(f"{VOICES}ConceptMention"), G_CONCEPTS)
                        writer.quad(cm_iri, iri(f"{VOICES}usesConcept"), info["iri"], G_CONCEPTS)
                        writer.quad(cm_iri, iri(f"{VOICES}mentionWeight"), literal(f"{weight:.4f}", datatype=XSD_FLOAT), G_CONCEPTS)
                        writer.quad(cm_iri, iri(f"{VOICES}mentionSource"), literal(source_label), G_CONCEPTS)
                        stats.add("concept_mentions")

        # Free topic/hierarchy memory
        del topic_tables, hierarchy_tables
        import gc; gc.collect()

    # ---- EMBEDDINGS (streamed per-interview to avoid OOM) ----
    all_similarity_edges: list[tuple[str, str, float, int]] = []

    if cfg["build"]["include_embeddings"]:
        log.info("--- Phase 4: Embeddings (per-interview streaming) ---")
        model_name = cfg["embedding"]["model_name"]
        emb_dim = cfg["embedding"]["dimensions"]
        sim_top_k = cfg["thresholds"]["similarity_top_k"]
        sim_thresh = cfg["thresholds"]["similarity_min"]
        do_similarity = cfg["build"]["compute_similarity"]

        emb_files = sorted(embeddings_dir.glob("interview_*_embeddings_openai.parquet"))
        iid_set = set(interview_ids)

        for fi, emb_file in enumerate(emb_files):
            try:
                iid = int(emb_file.stem.split("_")[1])
            except (IndexError, ValueError):
                continue
            if iid not in iid_set:
                continue

            if fi % 100 == 0:
                log.info("Embeddings: processing file %d/%d (interview %d)",
                         fi + 1, len(emb_files), iid)

            try:
                edf = pd.read_parquet(emb_file)
            except Exception as e:
                log.warning("Failed to load %s: %s", emb_file.name, e)
                continue

            # Write embedding quads
            iris_for_sim = []
            vecs_for_sim = []
            for _, erow in edf.iterrows():
                uhash = str(erow["utterance_hash"])
                emb_iri_str = f"urn:voices:embedding:{uhash}"
                event_iri_str = f"urn:voices:event:{uhash}"

                writer.quad(iri(event_iri_str), iri(f"{VOICES}hasEmbedding"), iri(emb_iri_str), G_EMBED)
                writer.quad(iri(emb_iri_str), RDF_TYPE, iri(f"{VOICES}Embedding"), G_EMBED)
                writer.quad(iri(emb_iri_str), iri(f"{VOICES}embeddingModel"), literal(model_name), G_EMBED)
                writer.quad(iri(emb_iri_str), iri(f"{VOICES}embeddingDim"), literal(str(emb_dim), datatype=XSD_INT), G_EMBED)
                stats.add("embeddings")

                iris_for_sim.append(emb_iri_str)
                vecs_for_sim.append(erow["embedding"])

            # Per-interview similarity (memory-safe: one interview at a time)
            if do_similarity and len(vecs_for_sim) >= 2:
                vectors = np.array(vecs_for_sim, dtype=np.float32)
                norms = np.linalg.norm(vectors, axis=1, keepdims=True)
                norms[norms == 0.0] = 1.0
                vectors = vectors / norms
                sim = vectors @ vectors.T
                np.fill_diagonal(sim, -1.0)

                for i in range(sim.shape[0]):
                    row = sim[i]
                    if sim_top_k >= len(row):
                        idxs = np.argsort(row)[::-1]
                    else:
                        idxs = np.argpartition(row, -sim_top_k)[-sim_top_k:]
                        idxs = idxs[np.argsort(row[idxs])[::-1]]
                    for j in idxs:
                        score = float(row[j])
                        if score < sim_thresh:
                            break
                        if i < j:
                            all_similarity_edges.append(
                                (iris_for_sim[i], iris_for_sim[j], score, iid))

                del vectors, sim  # free memory immediately

            del edf, vecs_for_sim, iris_for_sim  # free per-interview memory

        log.info("Embeddings done: %d total, %d similarity edges",
                 stats._counts.get("embeddings", 0), len(all_similarity_edges))

        # Write similarity edges
        similar_to = iri(f"{VOICES}similarTo")
        for k1, k2, score, _iid in all_similarity_edges:
            writer.quad(iri(k1), similar_to, iri(k2), G_EMBED)
            writer.quad(iri(k2), similar_to, iri(k1), G_EMBED)
            writer.quad(iri(k1), iri(f"{VOICES}similarityScore"),
                        literal(f"{score:.4f}", datatype=XSD_FLOAT), G_EMBED)
            stats.add("similarity_edges")

    writer.close()

    # ---- STATS ----
    stats.set("people", person_resolver.count)
    stats.set("places_skos", place_resolver.stats.get("skos_exact", 0))
    stats.set("places_local", place_resolver.stats.get("local", 0))
    stats.set("concept_links_skos", concept_linker.stats.get("exact", 0))
    stats.set("concept_links_local", concept_linker.stats.get("local", 0))
    stats.set("total_quads", writer.count)

    stats_path = out_dir / "kg2026_paper.stats.json"
    stats.save(stats_path)

    log.info("=== Build complete: %d quads written to %s ===", writer.count, nq_path)
    log.info("Stats: %s", json.dumps(stats.to_dict()["stats"], indent=2))

    return stats.to_dict()


def main():
    parser = argparse.ArgumentParser(description="KG2026.paper Knowledge Graph Builder")
    parser.add_argument("--config", type=Path,
                        default=PROJECT_DIR / "config" / "config.yaml")
    parser.add_argument("--interview-ids", type=str, default=None,
                        help="Override interview IDs: 'all' or '8,9,10'")
    args = parser.parse_args()
    build(args.config, args.interview_ids)


if __name__ == "__main__":
    main()
