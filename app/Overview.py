"""VOICES KG Explorer — Home."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.auth_gate import render_user_badge  # noqa: E402
from components.data_loader import (  # noqa: E402
    activity_counts_for_word,
    load_activities,
    load_sankey_flow,
    load_summary,
    load_surprise_terms,
    load_surprise_terms_by_emotion,
    period_counts_for_activity,
    period_counts_for_word,
    place_counts_for_word,
)
from components.credits import render_credits_footer  # noqa: E402
from components.sparql_client import fuseki_status_badge  # noqa: E402

DATASET_NAME = "VOICES Knowledge Graph"
DATASET_VERSION = "v2 (2026)"
CITATION = (
    "VOICES KG v2 — Holocaust survivor testimonies encoded as RDF events, "
    "emotions, places, and temporal alignments. "
    "Luxembourg Institute of Science and Technology (LIST), 2026. "
    "Living resource — continuously updated as new processing pipelines and "
    "analytical applications are integrated. "
    "Maintainer: Mohamed Laib <mohamed.laib@list.lu>."
)

st.set_page_config(
    page_title=f"{DATASET_NAME} Explorer",
    page_icon=":dove_of_peace:",
    layout="wide",
)

render_user_badge()
fuseki_status_badge()

st.title(f"{DATASET_NAME} Explorer")
st.caption(f"{DATASET_NAME} — {DATASET_VERSION}")
st.markdown(CITATION)

# --- High-level stat cards ---
summary = load_summary() or {}

c1, c2, c3 = st.columns(3)
c1.metric("Interviews", f"{int(summary.get('interviews', 0) or 0):,}")
c2.metric("Events", f"{int(summary.get('events', 0) or 0):,}")
c3.metric("Segments", f"{int(summary.get('segments', 0) or 0):,}")

st.divider()

# --- Top activities bar chart ---
st.subheader("Top activities")
activities = load_activities()
if activities:
    try:
        import pandas as pd
        import plotly.express as px

        df = pd.DataFrame(activities).head(15)
        if "count" in df.columns:
            df["count"] = pd.to_numeric(df["count"], errors="coerce").fillna(0)
        fig = px.bar(
            df,
            x="label",
            y="count",
            labels={"label": "Activity", "count": "Events"},
            color_discrete_sequence=["#4C78A8"],
        )
        fig.update_layout(height=380, xaxis_tickangle=-35, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.info(f"Could not render activities chart: {e}")
else:
    st.info("No data in this release.")

st.divider()

# --- Narrative flow Sankey: Period → Activity → Emotion category ---
st.subheader("Narrative flow across 982 testimonies")
st.caption(
    "Read left → right: each ribbon traces narrated events that took place in "
    "a **life period**, were classified as a particular **experience**, and "
    "carried an **emotional register**. Width = number of events. "
    "Hover a stream to read its exact path and count."
)
flow = load_sankey_flow()
if flow:
    try:
        import pandas as pd
        import plotly.graph_objects as go

        PERIOD_ORDER = [
            "pre_nazi", "nazi_rise", "pre_war", "childhood",
            "early_war", "during_war", "late_war_holocaust",
            "immediate_postwar", "post_war", "later_life",
        ]
        CATEGORY_ORDER = [
            "positive", "neutral",
            "negative_low_arousal", "negative_high_arousal",
        ]
        CATEGORY_COLOR = {
            "positive":              "#4CAF50",
            "neutral":               "#BDBDBD",
            "negative_low_arousal":  "#FF9800",
            "negative_high_arousal": "#C62828",
        }
        CATEGORY_LINK = {
            "positive":              "rgba(76,175,80,0.50)",
            "neutral":               "rgba(189,189,189,0.45)",
            "negative_low_arousal":  "rgba(255,152,0,0.50)",
            "negative_high_arousal": "rgba(198,40,40,0.55)",
        }

        df_flow = pd.DataFrame(flow)
        df_flow["count"] = pd.to_numeric(df_flow["count"], errors="coerce").fillna(0)
        # Drop rows whose period isn't in our canonical ordering — keeps the
        # visual chronologically sensible and guards against new period labels
        # appearing in the data without a code update.
        df_flow = df_flow[df_flow["period"].isin(PERIOD_ORDER)]
        periods_in = [p for p in PERIOD_ORDER if p in df_flow["period"].unique()]
        top_activities = (
            df_flow.groupby("activity")["count"].sum().nlargest(10).index.tolist()
        )
        df_flow = df_flow[df_flow["activity"].isin(top_activities)]
        categories_in = [c for c in CATEGORY_ORDER if c in df_flow["category"].unique()]

        nodes = periods_in + top_activities + categories_in
        idx = {n: i for i, n in enumerate(nodes)}

        src, tgt, val_, color = [], [], [], []
        # period -> activity
        pa = df_flow.groupby(["period", "activity"])["count"].sum().reset_index()
        for _, row in pa.iterrows():
            src.append(idx[row["period"]])
            tgt.append(idx[row["activity"]])
            val_.append(float(row["count"]))
            color.append("rgba(100,130,170,0.35)")
        # activity -> category
        ac = df_flow.groupby(["activity", "category"])["count"].sum().reset_index()
        for _, row in ac.iterrows():
            src.append(idx[row["activity"]])
            tgt.append(idx[row["category"]])
            val_.append(float(row["count"]))
            color.append(CATEGORY_LINK.get(row["category"], "rgba(120,120,120,0.35)"))

        node_color = (
            ["#6C8FBD"] * len(periods_in)
            + ["#3B5B86"] * len(top_activities)
            + [CATEGORY_COLOR.get(c, "#BDBDBD") for c in categories_in]
        )
        fig_flow = go.Figure(go.Sankey(
            arrangement="snap",
            textfont=dict(size=14, color="#111827",
                          family="Inter, system-ui, sans-serif"),
            node=dict(
                label=[n.replace("_", " ") for n in nodes],
                pad=22, thickness=18,
                color=node_color,
                line=dict(color="rgba(0,0,0,0)", width=0),
            ),
            link=dict(source=src, target=tgt, value=val_, color=color),
        ))
        fig_flow.update_layout(
            height=620, margin=dict(l=10, r=10, t=70, b=10),
            font=dict(size=14, color="#111827",
                      family="Inter, system-ui, sans-serif"),
            paper_bgcolor="white", plot_bgcolor="white",
        )
        # Column headers — Plotly's Sankey has no built-in support, so we draw
        # them as paper-coordinate annotations aligned with each column.
        header_style = dict(
            xref="paper", yref="paper", showarrow=False,
            font=dict(size=15, color="#111827",
                      family="Inter, system-ui, sans-serif"),
            yanchor="bottom",
        )
        fig_flow.add_annotation(x=0.0,  y=1.04, text="<b>Life period</b>",
                                xanchor="left",   **header_style)
        fig_flow.add_annotation(x=0.5,  y=1.04, text="<b>Experience</b>",
                                xanchor="center", **header_style)
        fig_flow.add_annotation(x=1.0,  y=1.04, text="<b>Emotional register</b>",
                                xanchor="right",  **header_style)
        # Subheader with the directional arrows so the relationship is obvious.
        fig_flow.add_annotation(
            x=0.5, y=1.10,
            text="<i>WHEN  →  WHAT  →  HOW IT FELT</i>",
            xref="paper", yref="paper", showarrow=False,
            font=dict(size=12, color="#6B7280",
                      family="Inter, system-ui, sans-serif"),
            xanchor="center", yanchor="bottom",
        )
        st.plotly_chart(fig_flow, use_container_width=True)

        # Inline legend for the four emotional registers — Plotly Sankey
        # links can't carry a legend natively, so we render swatches in HTML.
        legend_html = (
            '<div style="display:flex;gap:18px;flex-wrap:wrap;'
            'font-size:13px;color:#374151;margin-top:-6px;">'
            '<span style="display:inline-flex;align-items:center;gap:6px;">'
            '<span style="width:14px;height:14px;background:#4CAF50;border-radius:3px;"></span>'
            'positive</span>'
            '<span style="display:inline-flex;align-items:center;gap:6px;">'
            '<span style="width:14px;height:14px;background:#BDBDBD;border-radius:3px;"></span>'
            'neutral</span>'
            '<span style="display:inline-flex;align-items:center;gap:6px;">'
            '<span style="width:14px;height:14px;background:#FF9800;border-radius:3px;"></span>'
            'negative · low arousal (e.g. sadness)</span>'
            '<span style="display:inline-flex;align-items:center;gap:6px;">'
            '<span style="width:14px;height:14px;background:#C62828;border-radius:3px;"></span>'
            'negative · high arousal (e.g. fear, anger)</span>'
            '</div>'
        )
        st.markdown(legend_html, unsafe_allow_html=True)
    except Exception as e:
        st.info(f"Could not render narrative-flow Sankey: {e}")
else:
    st.info("Flow cache missing — run `make precompute`.")

st.divider()

# --- Topic-trajectory chart: activities over life periods --------------------
st.subheader("What was discussed when")
st.caption(
    "Each curve is one experience type. Click a name in the legend to hide or "
    "isolate it. Switch to **% of period** to see what dominated each life "
    "stage independently of how many events that period contains overall."
)
PERIOD_ORDER = [
    "pre_nazi", "nazi_rise", "pre_war", "childhood",
    "early_war", "during_war", "late_war_holocaust",
    "immediate_postwar", "post_war", "later_life",
]
flow_rows = load_sankey_flow()
if flow_rows:
    try:
        import pandas as pd
        import plotly.express as px

        df_pa = pd.DataFrame(flow_rows)
        df_pa["count"] = pd.to_numeric(df_pa["count"], errors="coerce").fillna(0)
        df_pa = df_pa[df_pa["period"].isin(PERIOD_ORDER)]
        df_pa = (
            df_pa.groupby(["period", "activity"])["count"]
            .sum()
            .reset_index()
        )

        # Order the x-axis chronologically.
        df_pa["period"] = pd.Categorical(df_pa["period"],
                                         categories=PERIOD_ORDER,
                                         ordered=True)

        # Limit to the 10 highest-volume activities so the legend stays usable;
        # the rest can still be discovered via the Explore page.
        top_acts = (
            df_pa.groupby("activity")["count"].sum()
            .nlargest(10).index.tolist()
        )
        df_pa = df_pa[df_pa["activity"].isin(top_acts)]

        mode = st.radio(
            "Y-axis",
            ["Counts", "% of period"],
            horizontal=True, label_visibility="collapsed",
        )

        if mode == "% of period":
            totals = df_pa.groupby("period", observed=True)["count"].sum()
            df_pa["value"] = df_pa.apply(
                lambda r: (r["count"] / totals[r["period"]] * 100.0)
                if totals.get(r["period"], 0) else 0.0,
                axis=1,
            )
            y_label = "Share of events in period (%)"
        else:
            df_pa["value"] = df_pa["count"]
            y_label = "Events"

        df_pa = df_pa.sort_values("period")
        fig_curves = px.line(
            df_pa,
            x="period", y="value", color="activity",
            labels={"period": "Life period", "value": y_label, "activity": "Experience"},
            markers=True,
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig_curves.update_layout(
            height=440, margin=dict(l=10, r=10, t=10, b=10),
            font=dict(size=13, color="#111827",
                      family="Inter, system-ui, sans-serif"),
            paper_bgcolor="white", plot_bgcolor="white",
            legend_title_text="Experience  (click to toggle)",
        )
        fig_curves.update_xaxes(categoryorder="array", categoryarray=PERIOD_ORDER,
                                tickangle=-25)
        st.plotly_chart(fig_curves, use_container_width=True)
    except Exception as e:
        st.info(f"Could not render trajectory chart: {e}")
else:
    st.info("Flow cache missing — run `make precompute`.")

st.divider()

# --- Discover topics: surprising-terms-per-period + cross-axis exploration --
st.subheader("Discover topics")
st.caption(
    "Pick a life period to surface the words that appear in those testimonies "
    "**far more often than elsewhere in the corpus** — micro-objects, place "
    "names, hidden vocabulary. Click any term to chart it; switch the x-axis "
    "to compare across **activities** or **places** instead of time."
)

surprise = load_surprise_terms()
surprise_emo = load_surprise_terms_by_emotion()
if not surprise:
    st.info(
        "Surprise-terms cache missing — run "
        "`python3 scripts/precompute_surprise.py` once to build it."
    )
else:
    if "discover_terms" not in st.session_state:
        st.session_state["discover_terms"] = []

    period_options = [p for p in PERIOD_ORDER if p in surprise] + [
        p for p in surprise if p not in PERIOD_ORDER
    ]
    default_idx = period_options.index("during_war") if "during_war" in period_options else 0

    EMOTION_LABELS = {
        "(all)": "(all emotions)",
        "positive": "Positive",
        "negative_high_arousal": "Negative · high arousal",
        "negative_low_arousal": "Negative · low arousal",
        "neutral": "Neutral",
    }
    pcol, ecol = st.columns([1, 1])
    with pcol:
        chosen_period = st.selectbox(
            "Life period",
            period_options,
            format_func=lambda p: p.replace("_", " "),
            index=default_idx,
        )
    with ecol:
        # Build emotion choices from whatever the cache has for this period,
        # falling back to "(all)" if the by-emotion cache is missing.
        emo_keys_for_period = sorted(surprise_emo.get(chosen_period, {}).keys())
        emo_options = ["(all)"] + emo_keys_for_period
        chosen_emotion = st.selectbox(
            "Emotion (default: all)",
            emo_options,
            format_func=lambda e: EMOTION_LABELS.get(e, e.replace("_", " ").title()),
            index=0,
            help="Filter the surprising terms to segments tagged with a specific "
                 "emotion register. Within-period contrast: 'what makes a moment "
                 "in this period feel this way'.",
        )

    if chosen_emotion == "(all)":
        rows = surprise.get(chosen_period, [])[:24]
        scope_label = chosen_period.replace("_", " ")
    else:
        rows = surprise_emo.get(chosen_period, {}).get(chosen_emotion, [])[:24]
        scope_label = (f"{chosen_period.replace('_', ' ')} · "
                       f"{EMOTION_LABELS.get(chosen_emotion, chosen_emotion).lower()}")
    st.markdown(
        f"**Top over-represented terms in _{scope_label}_** "
        f"_(click to chart)_"
    )
    if rows:
        cols = st.columns(6)
        for i, item in enumerate(rows):
            term = item["term"]
            count = item["period_count"]
            label = f"{term}  ·  {count}"
            if cols[i % 6].button(label, key=f"surprise_{chosen_period}_{term}",
                                  use_container_width=True):
                if term not in st.session_state["discover_terms"]:
                    st.session_state["discover_terms"].append(term)

    # Free-text fallback: search Meilisearch for any word, even if it's not
    # in the surprising-terms list (e.g. a hypothesis the historian wants to test).
    with st.form("discover_freeform", clear_on_submit=True):
        ftcol, btcol = st.columns([5, 1])
        with ftcol:
            free_term = st.text_input(
                "Or type any word to chart",
                placeholder="e.g. boots, toilet, soup, bicycle…",
                label_visibility="collapsed",
            )
        with btcol:
            submitted = st.form_submit_button("Add", use_container_width=True)
        if submitted and free_term and free_term.strip():
            t = free_term.strip().lower()
            if t and t not in st.session_state["discover_terms"]:
                st.session_state["discover_terms"].append(t)

    selected = st.session_state["discover_terms"]
    sel_col, clear_col = st.columns([5, 1])
    with sel_col:
        st.markdown(
            "**Charting:** "
            + (", ".join(f"`{t}`" for t in selected) if selected
               else "_(no terms selected yet)_")
        )
    with clear_col:
        if st.button("Clear", use_container_width=True, type="secondary",
                     disabled=not selected):
            st.session_state["discover_terms"] = []
            st.rerun()

    if selected:
        x_axis = st.radio(
            "Compare across",
            ["Life period", "Activity", "Place (top 15)"],
            horizontal=True,
        )
        try:
            import pandas as pd
            import plotly.express as px

            empty_terms: list[str] = []
            long_rows: list[dict] = []
            for term in selected:
                if x_axis == "Life period":
                    counts = period_counts_for_word(term)
                    cat_axis = PERIOD_ORDER
                elif x_axis == "Activity":
                    counts = activity_counts_for_word(term)
                    cat_axis = sorted(counts.keys(),
                                      key=lambda k: -counts.get(k, 0))[:15]
                else:  # Place
                    counts = place_counts_for_word(term)
                    cat_axis = sorted(counts.keys(),
                                      key=lambda k: -counts.get(k, 0))[:15]
                if not counts:
                    empty_terms.append(term)
                    continue
                for cat in cat_axis:
                    long_rows.append({
                        "term": term,
                        "axis": cat,
                        "count": int(counts.get(cat, 0)),
                    })

            if not long_rows:
                st.info("No matches for the selected terms on this axis.")
            else:
                df_disc = pd.DataFrame(long_rows)
                # Build the union of axis values across all selected terms,
                # ordered by the first term's ranking (so the curves align).
                if x_axis == "Life period":
                    axis_order = PERIOD_ORDER
                else:
                    axis_order = (
                        df_disc.groupby("axis")["count"].sum()
                        .sort_values(ascending=False)
                        .index.tolist()[:15]
                    )
                df_disc = df_disc[df_disc["axis"].isin(axis_order)]
                df_disc["axis"] = pd.Categorical(df_disc["axis"],
                                                 categories=axis_order,
                                                 ordered=True)
                df_disc = df_disc.sort_values("axis")

                axis_label = {"Life period": "Life period",
                              "Activity": "Activity",
                              "Place (top 15)": "Place"}[x_axis]
                fig_disc = px.line(
                    df_disc, x="axis", y="count", color="term",
                    labels={"axis": axis_label, "count": "Segment mentions",
                            "term": "Term"},
                    markers=True,
                    color_discrete_sequence=px.colors.qualitative.Bold,
                )
                fig_disc.update_layout(
                    height=440, margin=dict(l=10, r=10, t=10, b=10),
                    font=dict(size=13, color="#111827",
                              family="Inter, system-ui, sans-serif"),
                    paper_bgcolor="white", plot_bgcolor="white",
                    legend_title_text="Term  (click to toggle)",
                )
                fig_disc.update_xaxes(tickangle=-30)
                st.plotly_chart(fig_disc, use_container_width=True)
                if empty_terms:
                    st.caption(f"No matches: {', '.join(empty_terms)}")
        except Exception as e:
            st.info(f"Could not render discovery chart: {e}")

st.divider()

# --- Quick links ---
st.subheader("Explore")
colA, colB, colC = st.columns(3)
with colA:
    st.page_link("pages/01_Interview_Explorer.py", label="Interview Explorer", icon=":material/person:")
    st.page_link("pages/02_Explore.py", label="Explore by question", icon=":material/search:")
with colB:
    st.page_link("pages/03_Search.py", label="Full-text search", icon=":material/manage_search:")
    st.page_link("pages/04_SPARQL.py", label="SPARQL playground", icon=":material/code:")
with colC:
    st.page_link("pages/05_Downloads.py", label="Downloads", icon=":material/download:")

st.divider()
st.caption(
    "Navigate using the sidebar or the links above. All pages read from the same "
    "triplestore, search index, and precomputed caches."
)

render_credits_footer()
