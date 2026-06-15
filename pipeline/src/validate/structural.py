"""Structural integrity validation for the KG N-Quads output."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

VOICES = "https://w3id.org/voices/ontology#"
RDF_TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"

C_INTERVIEW = f"<{VOICES}Interview>"
C_SEGMENT = f"<{VOICES}InterviewSegment>"
C_EVENT = f"<{VOICES}NarratedEvent>"
P_SEGMENT = f"<{VOICES}hasSegment>"
P_SEG_EVENT = f"<{VOICES}segmentRefersToEvent>"

QUAD_RE = re.compile(r"^(<[^>]+>)\s+(<[^>]+>)\s+(.+?)\s+(<[^>]+>)\s+\.$")


def validate_nquads(nq_path: Path) -> dict:
    log.info("Validating %s", nq_path)

    interviews: set[str] = set()
    segments: set[str] = set()
    events: set[str] = set()
    seg_links: list[tuple[str, str]] = []
    evt_links: list[tuple[str, str]] = []
    total_lines = 0
    parse_errors = 0

    with nq_path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            total_lines += 1
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = QUAD_RE.match(line)
            if not m:
                parse_errors += 1
                continue
            s, p, o, _g = m.groups()

            if p == RDF_TYPE:
                if o == C_INTERVIEW:
                    interviews.add(s)
                elif o == C_SEGMENT:
                    segments.add(s)
                elif o == C_EVENT:
                    events.add(s)
            elif p == P_SEGMENT and o.startswith("<"):
                seg_links.append((s, o))
            elif p == P_SEG_EVENT and o.startswith("<"):
                evt_links.append((s, o))

    linked_segs = {seg for _, seg in seg_links}
    linked_evts = {ev for _, ev in evt_links}

    report = {
        "file": str(nq_path),
        "total_lines": total_lines,
        "parse_errors": parse_errors,
        "counts": {
            "interviews": len(interviews),
            "segments": len(segments),
            "events": len(events),
            "segment_links": len(seg_links),
            "event_links": len(evt_links),
        },
        "integrity": {
            "orphan_segments": len(segments - linked_segs),
            "orphan_events": len(events - linked_evts),
            "dangling_segment_refs": len([1 for _, s in seg_links if s not in segments]),
            "dangling_event_refs": len([1 for _, e in evt_links if e not in events]),
        },
        "ok": True,
    }

    for k, v in report["integrity"].items():
        if v > 0:
            report["ok"] = False
            log.warning("Integrity issue: %s = %d", k, v)

    if report["ok"]:
        log.info("Validation passed: all integrity checks OK")
    else:
        log.warning("Validation found issues")

    return report


def save_validation(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("Validation report saved to %s", path)
