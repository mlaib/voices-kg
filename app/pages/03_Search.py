"""Search — Meilisearch-backed full-text over transcript segments."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.auth_gate import render_user_badge  # noqa: E402
from components.credits import render_credits_footer  # noqa: E402
from components.data_loader import (  # noqa: E402
    as_label_list,
    load_interviews,
)
from components.search_client import (  # noqa: E402
    meili_status_badge,
    meilisearch_available,
    search as meili_search,
)
from components.sparql_client import fuseki_status_badge  # noqa: E402

st.set_page_config(page_title="Search", layout="wide")
render_user_badge()
fuseki_status_badge()
meili_status_badge()

st.title("Full-text search")
st.caption("VOICES KG v2 — Meilisearch over transcript segments")

if not meilisearch_available():
    st.warning(
        "The search index is not reachable. Full-text search is unavailable until "
        "Meilisearch is back online."
    )
    st.stop()

# The Meilisearch index only carries text + speaker metadata per segment;
# emotion / activity tags live in the triplestore on the *event* layer, not
# the segment layer, so they aren't filterable here. Use the Overview's
# Discover panel for emotion-aware exploration.
survivors = as_label_list(load_interviews())

query = st.text_input("Search transcripts", placeholder="e.g. Auschwitz, father, train")
survivor_f = st.selectbox("Filter by survivor", ["(any)"] + survivors)

# Pagination
if "search_offset" not in st.session_state:
    st.session_state["search_offset"] = 0

col_run, col_prev, col_next = st.columns([2, 1, 1])
with col_run:
    run = st.button("Search", type="primary")
with col_prev:
    if st.button("Previous page"):
        st.session_state["search_offset"] = max(0, st.session_state["search_offset"] - 20)
with col_next:
    if st.button("Next page"):
        st.session_state["search_offset"] += 20

# Reset offset on new query
if run:
    st.session_state["search_offset"] = 0

filters: list[str] = []
if survivor_f != "(any)":
    esc = survivor_f.replace("'", "\\'")
    filters.append(f"survivor = '{esc}'")

if query:
    result = meili_search(
        query,
        filters=filters or None,
        limit=20,
        offset=st.session_state["search_offset"],
        attributes_to_highlight=["text", "content"],
    )
    if result.get("error"):
        st.error(f"Search error: {result['error']}")
    hits = result.get("hits", [])
    total = result.get("estimatedTotalHits", len(hits))
    if not hits:
        st.info("No data in this release." if total == 0 else "No more results on this page.")
    else:
        st.metric("Matches (estimated)", total)

        # Distribution of hits on the current page — quick visual context
        # for where the query is landing. Uses only the in-memory hits so it
        # adds zero extra queries.
        try:
            import pandas as pd
            import plotly.express as px

            survivors_hit = [h.get("survivor") for h in hits if h.get("survivor")]
            if survivors_hit:
                df_hits = (
                    pd.Series(survivors_hit, name="survivor")
                    .value_counts()
                    .head(10)
                    .rename("hits_on_page")
                    .reset_index()
                )
                with st.expander("Top survivors in current page of results", expanded=False):
                    fig_hits = px.bar(
                        df_hits,
                        x="survivor", y="hits_on_page",
                        labels={"survivor": "Survivor", "hits_on_page": "Matching segments"},
                        color_discrete_sequence=["#4C78A8"],
                    )
                    fig_hits.update_layout(height=260, xaxis_tickangle=-30, showlegend=False,
                                           margin=dict(l=10, r=10, t=10, b=10))
                    st.plotly_chart(fig_hits, use_container_width=True)
        except Exception:
            pass

        for hit in hits:
            fmt = hit.get("_formatted", {}) or {}
            text = (
                fmt.get("text")
                or fmt.get("content")
                or hit.get("text")
                or hit.get("content")
                or ""
            )
            survivor = hit.get("survivor") or "Unknown"
            interview_iri = hit.get("interview_id") or ""
            seg_iri = hit.get("iri") or ""
            start_ms = hit.get("start_ms")
            ts_label = ""
            try:
                if start_ms is not None:
                    mins = int(start_ms) // 60000
                    secs = (int(start_ms) // 1000) % 60
                    ts_label = f" · ⏱ {mins:02d}:{secs:02d}"
            except (TypeError, ValueError):
                pass
            st.markdown(f"**{survivor}**{ts_label}")
            st.markdown(text, unsafe_allow_html=True)
            if interview_iri:
                # Stash everything the Explorer needs to land on the right
                # testimony AND scroll to the segment that matched the query.
                if st.button(
                    "Open interview",
                    key=f"open_{hit.get('id', interview_iri)}",
                ):
                    st.session_state["interview_picker"] = survivor
                    st.session_state["_jump_search"] = {
                        "interview_iri": interview_iri,
                        "segment_iri": seg_iri,
                        "start_ms": start_ms,
                        "query": query,
                        "snippet": text,
                    }
                    st.switch_page("pages/01_Interview_Explorer.py")
            st.divider()
    st.caption(
        f"Showing results {st.session_state['search_offset'] + 1}–"
        f"{st.session_state['search_offset'] + len(hits)} of ~{total}"
    )
else:
    st.info("Enter a keyword or phrase above to search the transcript segments.")

render_credits_footer()
