"""Downloads — artefacts, query files, and dataset citation."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.auth_gate import render_user_badge  # noqa: E402
from components.credits import render_credits_footer  # noqa: E402
from components.sparql_client import fuseki_status_badge  # noqa: E402

st.set_page_config(page_title="Downloads", layout="wide")
render_user_badge()
fuseki_status_badge()

st.title("Downloads")
st.caption("VOICES KG v2 — artefacts and query files")

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/output"))
SCHEMA_DIR = Path(os.environ.get("SCHEMA_DIR", "/schema"))
QUERIES_DIR = Path(os.environ.get("QUERIES_DIR", "/queries"))
DOWNLOAD_BASE = "/downloads"  # served by Caddy

ARTEFACTS: list[dict] = [
    {
        "name": "kg2026_v2.nq",
        "path": OUTPUT_DIR / "kg2026_v2.nq",
        "url": f"{DOWNLOAD_BASE}/kg2026_v2.nq",
        "description": "Main knowledge graph as N-Quads (all named graphs).",
    },
    {
        "name": "kg2026_v2.nqs",
        "path": OUTPUT_DIR / "kg2026_v2.nqs",
        "url": f"{DOWNLOAD_BASE}/kg2026_v2.nqs",
        "description": "RDF-star annotation quads (confidence, method, pattern).",
    },
    {
        "name": "voices_ontology_v2.ttl",
        "path": SCHEMA_DIR / "voices_ontology_v2.ttl",
        "url": f"{DOWNLOAD_BASE}/voices_ontology_v2.ttl",
        "description": "VOICES v2 ontology (Turtle).",
    },
    {
        "name": "voices-alignment-v2.ttl",
        "path": SCHEMA_DIR / "voices-alignment-v2.ttl",
        "url": f"{DOWNLOAD_BASE}/voices-alignment-v2.ttl",
        "description": "Alignment stub linking VOICES classes to external vocabularies.",
    },
    {
        "name": "stats.json",
        "path": OUTPUT_DIR / "stats.json",
        "url": f"{DOWNLOAD_BASE}/stats.json",
        "description": "Build statistics (counts per graph, provenance, timings).",
    },
]


def _size_str(path: Path) -> str:
    try:
        if not path.exists():
            return "—"
        b = path.stat().st_size
    except Exception:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}" if unit != "B" else f"{b} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


# Core artefact table
st.subheader("Core artefacts")
rows = []
for a in ARTEFACTS:
    rows.append(
        {
            "File": a["name"],
            "Size": _size_str(a["path"]),
            "Description": a["description"],
            "Path": str(a["path"]),
            "Download": a["url"],
        }
    )
df = pd.DataFrame(rows)
st.dataframe(df, use_container_width=True, hide_index=True)

st.markdown("**Direct download links:**")
for a in ARTEFACTS:
    present = a["path"].exists()
    disabled_note = "" if present else "  _(not yet generated)_"
    st.markdown(f"- [`{a['name']}`]({a['url']}) — {_size_str(a['path'])}{disabled_note}")

st.divider()

# Query files
st.subheader("SPARQL query files")
query_rows: list[dict] = []
if QUERIES_DIR.exists():
    for qf in sorted(QUERIES_DIR.glob("*.rq")):
        query_rows.append(
            {
                "File": qf.name,
                "Size": _size_str(qf),
                "Path": str(qf),
                "Download": f"{DOWNLOAD_BASE}/queries/{qf.name}",
            }
        )
if query_rows:
    st.dataframe(pd.DataFrame(query_rows), use_container_width=True, hide_index=True)
    st.markdown("**Direct links:**")
    for row in query_rows:
        st.markdown(f"- [`{row['File']}`]({row['Download']}) — {row['Size']}")
else:
    st.info("No .rq files in this release.")

st.divider()

# Stats summary
st.subheader("Build statistics")
stats_path = OUTPUT_DIR / "stats.json"
if stats_path.exists():
    try:
        stats = json.loads(stats_path.read_text())
        st.json(stats)
    except Exception as e:
        st.warning(f"Could not parse stats.json: {e}")
else:
    st.info("stats.json not yet generated.")

st.divider()

# Cite this dataset
st.subheader("Cite this dataset")
citation_text = (
    "Pruski, C., Laib, M., Da Silveira, M., Toth, G. M. (2026). "
    "VOICES Knowledge Graph v2 — Holocaust survivor testimonies encoded as "
    "RDF events, emotions, places, and temporal alignments. "
    "Luxembourg Institute of Science and Technology (LIST). "
    "Available at: https://voices.list.lu"
)
bibtex = (
    "@dataset{voices_kg_v2_2026,\n"
    "  title       = {VOICES Knowledge Graph v2},\n"
    "  subtitle    = {Holocaust survivor testimonies as RDF events, "
    "emotions, places, and temporal alignments},\n"
    "  author      = {Pruski, C{\\'e}dric and Laib, Mohamed and "
    "Da Silveira, Marcos and Toth, Gabor Mihaly},\n"
    "  year        = {2026},\n"
    "  version     = {2.0},\n"
    "  institution = {Luxembourg Institute of Science and Technology (LIST)},\n"
    "  note        = {Living resource — continuously updated},\n"
    "  url         = {https://voices.list.lu}\n"
    "}"
)
st.markdown("**Plain text:**")
st.code(citation_text, language="text")
st.markdown("**BibTeX:**")
st.code(bibtex, language="bibtex")
st.markdown(
    "**Maintainer:** Mohamed Laib &mdash; "
    "[mohamed.laib@list.lu](mailto:mohamed.laib@list.lu)"
)

render_credits_footer()
