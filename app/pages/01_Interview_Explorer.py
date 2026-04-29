"""Interview Explorer — read a single testimony with events, emotions, timeline."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.auth_gate import render_user_badge  # noqa: E402
from components.credits import render_credits_footer  # noqa: E402
from components.data_loader import (  # noqa: E402
    load_interview_detail,
    load_interviews_meta,
)
from components.sparql_client import (  # noqa: E402
    cached_badge,
    fuseki_available,
    fuseki_status_badge,
    show_sparql_error,
)

st.set_page_config(page_title="Interview Explorer", layout="wide")
render_user_badge()
fuseki_status_badge()

st.title("Interview Explorer")
st.caption("VOICES KG v2 — single-testimony view")
st.markdown(
    "Select a survivor to explore their testimony: what they experienced, "
    "where, when, and how they felt."
)

if not fuseki_available():
    st.warning("The triplestore is not reachable. Please try again shortly.")
    st.stop()

interviews = load_interviews_meta()
if not interviews:
    st.info("No interviews available in this release.")
    st.stop()

df_int = pd.DataFrame(interviews)
df_int = df_int[df_int["id"].astype(str) != ""].reset_index(drop=True)
if df_int.empty:
    st.info("No interviews with valid IRIs — cannot build selector.")
    st.stop()

# ── Jump-from-Search context ─────────────────────────────────────────────
# When the user clicks "Open interview" on the Search page, that page sets
# `interview_picker` to the survivor name and stashes the matched segment +
# query in `_jump_search`. We pop it here so it only fires once, reset the
# browse filters so the target survivor isn't filtered out, and remember
# the jump for the banner / scroll later.
_jump_ctx: dict | None = None
if "_jump_search" in st.session_state:
    _jump_ctx = st.session_state.pop("_jump_search")
    for k in ("filter_name_q", "filter_yr_range", "filter_gender_pick"):
        st.session_state.pop(k, None)

# ── Quick stats strip ────────────────────────────────────────────────────
years = pd.to_numeric(df_int.get("year", pd.Series(dtype=str)), errors="coerce")
year_min = int(years.dropna().min()) if years.notna().any() else None
year_max = int(years.dropna().max()) if years.notna().any() else None
g_norm = df_int.get("gender", pd.Series(dtype=str)).fillna("").astype(str).str.lower()
n_total = len(df_int)
n_men = (g_norm == "male").sum()
n_women = (g_norm == "female").sum()

s1, s2, s3 = st.columns(3)
s1.metric("Testimonies", f"{n_total:,}")
if year_min is not None and year_max is not None:
    s2.metric("Recorded", f"{year_min}–{year_max}")
else:
    s2.metric("Recorded", "—")
if n_men + n_women > 0:
    pct_w = round(100 * n_women / (n_men + n_women))
    s3.metric("Survivors", f"{pct_w}% women · {100 - pct_w}% men")
else:
    s3.metric("Survivors", "—")

# ── Browse & filter ──────────────────────────────────────────────────────
with st.expander("Browse & filter testimonies", expanded=_jump_ctx is None):
    fc1, fc2, fc3 = st.columns([3, 2, 2])
    with fc1:
        name_q = st.text_input("Search by survivor name",
                               placeholder="e.g. Aaron, Goldberg, Bomba…",
                               key="filter_name_q").strip()
    with fc2:
        if year_min is not None and year_max is not None and year_max > year_min:
            yr_range = st.slider("Recorded between",
                                 min_value=year_min, max_value=year_max,
                                 value=(year_min, year_max),
                                 key="filter_yr_range")
        else:
            yr_range = None
    with fc3:
        gender_options = ["Any"] + sorted(g for g in g_norm.unique() if g)
        gender_pick = st.selectbox("Gender", gender_options,
                                   format_func=lambda g: g.title() if g != "Any" else g,
                                   key="filter_gender_pick")

    filtered = df_int.copy()
    if name_q:
        filtered = filtered[
            filtered["label"].astype(str).str.contains(name_q, case=False, na=False)
        ]
    if yr_range:
        yrs = pd.to_numeric(filtered["year"], errors="coerce")
        filtered = filtered[(yrs >= yr_range[0]) & (yrs <= yr_range[1])]
    if gender_pick != "Any":
        filtered = filtered[
            filtered["gender"].astype(str).str.lower() == gender_pick.lower()
        ]
    filtered = filtered.sort_values("label").reset_index(drop=True)

    pickcol, randcol = st.columns([5, 1])
    with randcol:
        st.write("")  # vertical alignment
        if st.button("🎲 Random", use_container_width=True,
                     disabled=filtered.empty):
            import random
            st.session_state["interview_picker"] = random.choice(
                filtered["label"].tolist()
            )
            st.rerun()
    with pickcol:
        if filtered.empty:
            st.warning("No testimonies match these filters.")
            st.stop()
        st.caption(f"{len(filtered):,} of {n_total:,} testimonies match")
        labels_to_id = dict(zip(filtered["label"], filtered["id"]))
        # Keep a stable selection across reruns; default to first matching label.
        if (st.session_state.get("interview_picker") not in labels_to_id):
            st.session_state["interview_picker"] = filtered["label"].iloc[0]
        selected_label = st.selectbox(
            "Choose a testimony",
            list(labels_to_id.keys()),
            key="interview_picker",
        )
        interview_iri = labels_to_id[selected_label]

detail = load_interview_detail(interview_iri)
show_sparql_error()
cached_badge()

metadata = detail.get("metadata", {})
events_df: pd.DataFrame = detail.get("events", pd.DataFrame())
emotions_df: pd.DataFrame = detail.get("emotions", pd.DataFrame())
places_df: pd.DataFrame = detail.get("places", pd.DataFrame())

# Header
st.subheader(metadata.get("label", selected_label))
col1, col2, col3 = st.columns(3)
col1.write(f"**Recorded:** {metadata.get('year', 'unknown')}")
col2.write(f"**Gender:** {metadata.get('gender', '') or '—'}")
col3.write(f"**Events:** {len(events_df):,}")

# ── "Jumped from search" banner + segment context ─────────────────────────
if _jump_ctx:
    start_ms = _jump_ctx.get("start_ms")
    query    = _jump_ctx.get("query") or ""
    snippet  = _jump_ctx.get("snippet") or ""
    ts = ""
    try:
        if start_ms is not None:
            mins = int(start_ms) // 60000
            secs = (int(start_ms) // 1000) % 60
            ts = f" · ⏱ minute {mins:02d}:{secs:02d}"
    except (TypeError, ValueError):
        pass
    st.info(
        f"Jumped from search for **\"{query}\"**{ts}. "
        "Use the events table or the Read transcript expander below to find the matching passage."
    )
    if snippet:
        st.markdown(
            f"<blockquote style='border-left:4px solid #2563EB;background:#EFF6FF;"
            f"padding:8px 16px;border-radius:4px;font-size:0.95em;color:#1E3A8A;'>"
            f"<em>matched passage:</em> {snippet}</blockquote>",
            unsafe_allow_html=True,
        )

if events_df.empty:
    st.info("No events found for this interview.")
    st.stop()

# Hero quote — first non-empty narrated event, as a teaser for the testimony.
if "what" in events_df.columns:
    quotes = events_df["what"].dropna().astype(str).str.strip()
    quotes = quotes[quotes.str.len() > 0]
    if not quotes.empty:
        first_quote = quotes.iloc[0]
        if len(first_quote) > 320:
            first_quote = first_quote[:320].rstrip() + "…"
        st.markdown(
            f"<blockquote style='border-left:4px solid #6B7280;padding:8px 16px;"
            f"color:#374151;font-style:italic;background:#F9FAFB;border-radius:4px;'>"
            f"{first_quote}</blockquote>",
            unsafe_allow_html=True,
        )

# Filters
st.sidebar.markdown("### Filter events")

def _uniq(series: pd.Series) -> list[str]:
    if series is None or series.empty:
        return []
    return sorted({str(v) for v in series.dropna() if str(v).strip()})

activities = _uniq(events_df.get("activity", pd.Series(dtype=str)))
emotions = _uniq(events_df.get("emotion", pd.Series(dtype=str)))
places = _uniq(events_df.get("where", pd.Series(dtype=str)))

act_filter = st.sidebar.selectbox("What happened?", ["Everything"] + activities)
emo_filter = st.sidebar.selectbox("How did they feel?", ["Any emotion"] + emotions)
loc_filter = st.sidebar.selectbox("Where?", ["Anywhere"] + places)

focus = events_df.copy()
if act_filter != "Everything" and "activity" in focus.columns:
    focus = focus[focus["activity"].astype(str) == act_filter]
if emo_filter != "Any emotion" and "emotion" in focus.columns:
    focus = focus[focus["emotion"].astype(str) == emo_filter]
if loc_filter != "Anywhere" and "where" in focus.columns:
    focus = focus[focus["where"].astype(str) == loc_filter]

st.write(f"Showing **{len(focus):,}** of {len(events_df):,} events")

# Emotions chart
if not emotions_df.empty:
    try:
        import plotly.express as px

        st.subheader("Emotions in this testimony")
        top_emo = emotions_df.head(15)
        fig = px.bar(
            top_emo,
            x="emotion",
            y="count",
            labels={"emotion": "Emotion", "count": "Times expressed"},
            color="emotion",
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig.update_layout(height=320, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.info(f"Could not render emotions chart: {e}")

# Emotion arc — valence over time (Vonnegut-style story shape)
if (
    "start" in focus.columns
    and "valence" in focus.columns
    and focus["valence"].notna().any()
):
    try:
        import plotly.express as px

        arc = focus.copy()
        arc["valence_num"] = pd.to_numeric(arc["valence"], errors="coerce")
        arc["start_min"] = pd.to_numeric(arc["start"], errors="coerce") / 60000.0
        arc = arc[arc["valence_num"].notna() & arc["start_min"].notna()]
        if not arc.empty:
            # Smooth with rolling mean to highlight the narrative arc rather
            # than every individual annotation spike.
            arc = arc.sort_values("start_min").reset_index(drop=True)
            arc["valence_smooth"] = (
                arc["valence_num"].rolling(window=15, min_periods=1, center=True).mean()
            )
            st.subheader("Emotion arc")
            st.caption(
                "Valence (negative → positive) of each narrated event, in the order "
                "the survivor tells them. The line is a rolling average; dots are "
                "individual events."
            )
            fig_arc = px.scatter(
                arc,
                x="start_min",
                y="valence_num",
                color="emotion" if "emotion" in arc.columns else None,
                hover_data=[c for c in ["what", "where", "activity"] if c in arc.columns],
                labels={"start_min": "Minutes into interview", "valence_num": "Valence"},
                opacity=0.55,
            )
            fig_arc.add_scatter(
                x=arc["start_min"], y=arc["valence_smooth"],
                mode="lines", name="Rolling average",
                line=dict(color="#1F2937", width=2.5),
                hoverinfo="skip",
            )
            fig_arc.add_hline(y=0, line_dash="dot", line_color="#9CA3AF")
            fig_arc.update_layout(height=340, legend_title_text="")
            st.plotly_chart(fig_arc, use_container_width=True)
    except Exception as e:
        st.info(f"Could not render emotion arc: {e}")

# Timeline
if "start" in focus.columns and focus["start"].notna().any():
    try:
        import plotly.express as px

        timeline = focus.copy()
        timeline["start_min"] = pd.to_numeric(timeline["start"], errors="coerce") / 60000.0
        timeline = timeline[timeline["start_min"].notna()]
        if not timeline.empty:
            st.subheader("Narrative timeline")
            st.caption("Events as they appear in the recording (minutes into interview).")
            color_col = "activity" if "activity" in timeline.columns else None
            fig_t = px.strip(
                timeline,
                x="start_min",
                y=color_col,
                color=color_col,
                hover_data=[c for c in ["what", "where", "emotion"] if c in timeline.columns],
                labels={"start_min": "Minutes into interview"},
            )
            fig_t.update_layout(height=300)
            st.plotly_chart(fig_t, use_container_width=True)
    except Exception as e:
        st.info(f"Could not render timeline: {e}")

# Places
if not places_df.empty:
    st.subheader("Places mentioned")
    st.dataframe(places_df.head(30), use_container_width=True)

# Event table
st.subheader("Events")
display_cols = [c for c in ["what", "where", "when", "activity", "emotion"] if c in focus.columns]
if display_cols:
    rendered = focus[display_cols].rename(
        columns={
            "what": "What happened",
            "where": "Where",
            "when": "When",
            "activity": "Activity type",
            "emotion": "Emotion",
        }
    )
    # When the user came here from a Search hit, highlight the events that fall
    # within ~30 s of the matched segment so the row is easy to spot.
    jump_ms = (_jump_ctx or {}).get("start_ms")
    try:
        jump_ms = int(jump_ms) if jump_ms is not None else None
    except (TypeError, ValueError):
        jump_ms = None
    if jump_ms is not None and "start" in focus.columns:
        starts_ms = pd.to_numeric(focus["start"], errors="coerce")
        match_mask = ((starts_ms - jump_ms).abs() <= 30_000).fillna(False).reset_index(drop=True)
        if match_mask.any():
            def _hl(_, mask=match_mask):
                return [
                    "background-color: #FEF3C7; font-weight: 500;" if mask.iloc[i] else ""
                    for i in range(len(mask))
                ]
            try:
                styled = rendered.reset_index(drop=True).style.apply(_hl, axis=0)
                st.dataframe(styled, use_container_width=True, height=480)
            except Exception:
                st.dataframe(rendered, use_container_width=True, height=480)
        else:
            st.dataframe(rendered, use_container_width=True, height=480)
    else:
        st.dataframe(rendered, use_container_width=True, height=480)

# Transcript excerpts — auto-expanded if jumping from search
with st.expander("Read transcript excerpts",
                 expanded=_jump_ctx is not None):
    if "what" in focus.columns:
        for _, row in focus.head(50).iterrows():
            quote = str(row.get("what", "") or "").strip()
            if not quote:
                continue
            emo = str(row.get("emotion", "") or "").strip()
            prefix = f"**[{emo}]** " if emo else ""
            st.markdown(f"{prefix}{quote}")
            st.divider()

render_credits_footer()
