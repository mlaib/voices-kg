"""Explore — ask questions about the archive using fillable templates."""
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
    G_ANNOT,
    G_EVENTS,
    G_META,
    G_TRANS,
    as_label_list,
    load_activities,
    load_emotions,
    load_historical_events,
    load_interviews,
    load_places,
)
from components.search_client import meili_status_badge, search as meili_search  # noqa: E402
from components.sparql_client import (  # noqa: E402
    VOICES_PREFIXES,
    cached_badge,
    fuseki_available,
    fuseki_status_badge,
    run_sparql,
    run_sparql_dropdown,
    show_sparql_error,
)

st.set_page_config(page_title="Explore", layout="wide")
render_user_badge()
fuseki_status_badge()
meili_status_badge()

st.title("Explore the Testimonies")
st.caption("VOICES KG v2 — fillable-template question interface")
st.markdown(
    "Choose a question below, fill in the blanks, and press **Show results**. "
    "The system translates your question into a database query automatically."
)

if not fuseki_available():
    st.warning("The triplestore is not reachable — try again shortly.")
    st.stop()


def _show_query(sparql: str) -> None:
    with st.expander("View the SPARQL query behind this question", expanded=False):
        st.code(sparql, language="sparql")


def _render_empty() -> None:
    st.info("No data in this release.")


def _safe(value: str) -> str:
    """Minimal escape of user-picked labels for inline SPARQL literals."""
    return value.replace('"', '\\"').replace("\n", " ")


def _label_match(node_var: str, value: str, bind: str = "_lbl") -> str:
    """Build a tag-agnostic ``rdfs:label`` match.

    The KG mixes plain literals with ``@en``-tagged ones; SPARQL treats
    ``"x"`` and ``"x"@en`` as different terms when compared by ``=``. Using
    ``FILTER(STR(?lbl) = "x")`` matches both.
    """
    return (
        f'{node_var} rdfs:label ?{bind} . '
        f'FILTER(STR(?{bind}) = "{_safe(value)}")'
    )


# Dropdown options
activities = as_label_list(load_activities())
emotions = as_label_list(load_emotions())
places = as_label_list(load_places())
historical_events = as_label_list(load_historical_events())
interviews_records = load_interviews()
interviews = as_label_list(interviews_records)

# Periods come from temporalBucket (cheap dropdown query)
_periods_df = run_sparql_dropdown(
    VOICES_PREFIXES + f"""
SELECT ?bucket WHERE {{
  GRAPH <{G_EVENTS}> {{ ?e voices:temporalBucket ?bucket . }}
}} GROUP BY ?bucket ORDER BY ?bucket"""
)
periods = _periods_df["bucket"].tolist() if not _periods_df.empty else []


QUESTIONS = [
    "Which survivors described ___activity___ ?",
    "What emotions are expressed during ___activity___ ?",
    "Who talked about ___place___ and what happened there?",
    "Which testimonies mention ___emotion___ and in what context?",
    "What experiences are linked to ___historical_event___ ?",
    "What happened during the period ___period___ ?",
    "What is the emotional profile of ___interview___ ?",
    "Which places appear together with ___emotion___ ?",
    "Find testimonies mentioning ___keyword___",
    "Build your own question from filters",
]

selected_q = st.selectbox("Pick a question", QUESTIONS)
st.divider()


# ---- Q1 -----------------------------------------------------------------
if selected_q == QUESTIONS[0]:
    if not activities:
        _render_empty()
    else:
        act = st.selectbox("Select an experience", activities)
        if act and st.button("Show results", type="primary"):
            sparql = VOICES_PREFIXES + f"""
SELECT ?survivor (COUNT(?event) AS ?mentions)
WHERE {{
  GRAPH <{G_META}> {{ ?interview a voices:Interview ; rdfs:label ?survivor . }}
  GRAPH <{G_TRANS}> {{ ?interview voices:hasSegment ?seg . }}
  GRAPH <{G_EVENTS}> {{
    ?seg voices:segmentRefersToEvent ?event .
    ?event voices:hasActivity ?act .
    {_label_match("?act", act)}
  }}
}}
GROUP BY ?survivor ORDER BY DESC(?mentions)"""
            df = run_sparql(sparql)
            show_sparql_error()
            cached_badge()
            if df.empty:
                _render_empty()
            else:
                st.metric("Survivors", len(df))
                import plotly.express as px

                fig = px.bar(
                    df.head(20),
                    x="survivor",
                    y="mentions",
                    labels={"survivor": "Survivor", "mentions": "Events"},
                )
                fig.update_layout(height=400, xaxis_tickangle=-45, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(df, use_container_width=True)

                # Emotional profile of this activity (Sankey to categories).
                flow_q = VOICES_PREFIXES + f"""
SELECT ?category (COUNT(?event) AS ?count)
WHERE {{
  GRAPH <{G_EVENTS}> {{
    ?event voices:hasActivity ?act .
    {_label_match("?act", act)}
  }}
  GRAPH <{G_ANNOT}> {{
    ?event voices:hasEmotion ?ann .
    ?ann voices:emotionCategory ?category .
  }}
}}
GROUP BY ?category"""
                flow_df = run_sparql_dropdown(flow_q)
                if not flow_df.empty:
                    import plotly.graph_objects as go

                    flow_df["count"] = pd.to_numeric(flow_df["count"], errors="coerce").fillna(0)
                    cat_order = ["positive", "neutral", "negative_low_arousal", "negative_high_arousal"]
                    cat_color = {
                        "positive":              "#4CAF50",
                        "neutral":               "#BDBDBD",
                        "negative_low_arousal":  "#FF9800",
                        "negative_high_arousal": "#C62828",
                    }
                    cat_link = {
                        "positive":              "rgba(76,175,80,0.50)",
                        "neutral":               "rgba(189,189,189,0.45)",
                        "negative_low_arousal":  "rgba(255,152,0,0.50)",
                        "negative_high_arousal": "rgba(198,40,40,0.55)",
                    }
                    categories = [c for c in cat_order if c in flow_df["category"].values]
                    src_idx = 0
                    nodes = [act] + categories
                    sankey = go.Figure(go.Sankey(
                        arrangement="snap",
                        node=dict(
                            label=[n.replace("_", " ") for n in nodes],
                            pad=22, thickness=18,
                            line=dict(color="white", width=0.5),
                            color=["#3B5B86"] + [cat_color.get(c, "#BDBDBD") for c in categories],
                        ),
                        link=dict(
                            source=[src_idx] * len(categories),
                            target=list(range(1, 1 + len(categories))),
                            value=[float(flow_df[flow_df["category"] == c]["count"].iloc[0]) for c in categories],
                            color=[cat_link.get(c, "rgba(120,120,120,0.35)") for c in categories],
                        ),
                    ))
                    sankey.update_layout(
                        height=420,
                        margin=dict(l=10, r=10, t=10, b=10),
                        font=dict(family="Inter, system-ui, sans-serif",
                                  size=14, color="#111827"),
                        paper_bgcolor="white", plot_bgcolor="white",
                    )
                    st.markdown(f"**Emotional register for _{act}_**")
                    st.plotly_chart(sankey, use_container_width=True)
            _show_query(sparql)


# ---- Q2 -----------------------------------------------------------------
elif selected_q == QUESTIONS[1]:
    if not activities:
        _render_empty()
    else:
        act = st.selectbox("Select an experience", activities)
        if act and st.button("Show results", type="primary"):
            sparql = VOICES_PREFIXES + f"""
SELECT ?emotion (COUNT(*) AS ?count)
WHERE {{
  GRAPH <{G_EVENTS}> {{
    ?event voices:hasActivity ?act .
    {_label_match("?act", act)}
  }}
  GRAPH <{G_ANNOT}> {{
    ?event voices:hasEmotion ?emo .
    ?emo rdfs:label ?emotion .
  }}
}}
GROUP BY ?emotion ORDER BY DESC(?count)"""
            df = run_sparql(sparql)
            show_sparql_error()
            cached_badge()
            if df.empty:
                _render_empty()
            else:
                import plotly.express as px

                fig = px.pie(df.head(15), names="emotion", values="count", title=f"Emotions during {act}")
                fig.update_layout(height=400)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(df, use_container_width=True)
            _show_query(sparql)


# ---- Q3 -----------------------------------------------------------------
elif selected_q == QUESTIONS[2]:
    if not places:
        _render_empty()
    else:
        place = st.selectbox("Select a place", places)
        if place and st.button("Show results", type="primary"):
            sparql = VOICES_PREFIXES + f"""
SELECT ?survivor ?what ?emotion
WHERE {{
  GRAPH <{G_META}> {{ ?interview a voices:Interview ; rdfs:label ?survivor . }}
  GRAPH <{G_TRANS}> {{ ?interview voices:hasSegment ?seg . }}
  GRAPH <{G_EVENTS}> {{
    ?seg voices:segmentRefersToEvent ?event .
    ?event voices:hasLocation ?place .
    {_label_match("?place", place)}
  }}
  OPTIONAL {{ GRAPH <{G_EVENTS}> {{ ?event voices:whatText ?what . }} }}
  OPTIONAL {{ GRAPH <{G_ANNOT}> {{ ?event voices:hasEmotion ?emo . ?emo rdfs:label ?emotion . }} }}
}}
LIMIT 100"""
            df = run_sparql(sparql)
            show_sparql_error()
            cached_badge()
            if df.empty:
                _render_empty()
            else:
                survivors = df["survivor"].nunique() if "survivor" in df.columns else 0
                c1, c2 = st.columns(2)
                c1.metric("Results", len(df))
                c2.metric("Distinct survivors", survivors)
                st.dataframe(
                    df.rename(
                        columns={"survivor": "Survivor", "what": "What happened", "emotion": "Emotion"}
                    ),
                    use_container_width=True,
                    height=500,
                )
            _show_query(sparql)


# ---- Q4 -----------------------------------------------------------------
elif selected_q == QUESTIONS[3]:
    if not emotions:
        _render_empty()
    else:
        emo = st.selectbox("Select an emotion", emotions)
        if emo and st.button("Show results", type="primary"):
            sparql = VOICES_PREFIXES + f"""
SELECT ?survivor ?what ?where
WHERE {{
  GRAPH <{G_META}> {{ ?interview a voices:Interview ; rdfs:label ?survivor . }}
  GRAPH <{G_TRANS}> {{ ?interview voices:hasSegment ?seg . }}
  GRAPH <{G_EVENTS}> {{ ?seg voices:segmentRefersToEvent ?event . }}
  GRAPH <{G_ANNOT}> {{
    ?event voices:hasEmotion ?emo .
    {_label_match("?emo", emo)}
  }}
  OPTIONAL {{ GRAPH <{G_EVENTS}> {{ ?event voices:whatText ?what . }} }}
  OPTIONAL {{ GRAPH <{G_EVENTS}> {{ ?event voices:hasLocation ?p . ?p rdfs:label ?where . }} }}
}}
LIMIT 100"""
            df = run_sparql(sparql)
            show_sparql_error()
            cached_badge()
            if df.empty:
                _render_empty()
            else:
                survivors = df["survivor"].nunique() if "survivor" in df.columns else 0
                st.metric(f"Survivors who expressed {emo}", survivors)
                st.dataframe(
                    df.rename(columns={"survivor": "Survivor", "what": "What happened", "where": "Where"}),
                    use_container_width=True,
                    height=500,
                )
            _show_query(sparql)


# ---- Q5 -----------------------------------------------------------------
elif selected_q == QUESTIONS[4]:
    if not historical_events:
        _render_empty()
    else:
        he = st.selectbox("Select a historical event", historical_events)
        if he and st.button("Show results", type="primary"):
            sparql = VOICES_PREFIXES + f"""
SELECT ?survivor ?what ?emotion ?when
WHERE {{
  GRAPH <{G_META}> {{ ?interview a voices:Interview ; rdfs:label ?survivor . }}
  GRAPH <{G_TRANS}> {{ ?interview voices:hasSegment ?seg . }}
  GRAPH <{G_EVENTS}> {{
    ?seg voices:segmentRefersToEvent ?event .
    ?event voices:alignsWithHistoricalEvent ?hist .
    {_label_match("?hist", he)}
  }}
  OPTIONAL {{ GRAPH <{G_EVENTS}> {{ ?event voices:whatText ?what . }} }}
  OPTIONAL {{ GRAPH <{G_ANNOT}> {{ ?event voices:hasEmotion ?emo . ?emo rdfs:label ?emotion . }} }}
  OPTIONAL {{ GRAPH <{G_EVENTS}> {{ ?event voices:whenText ?when . }} }}
}}
LIMIT 100"""
            df = run_sparql(sparql)
            show_sparql_error()
            cached_badge()
            if df.empty:
                _render_empty()
            else:
                st.metric("Accounts found", len(df))
                st.dataframe(
                    df.rename(
                        columns={
                            "survivor": "Survivor",
                            "what": "What happened",
                            "emotion": "Emotion",
                            "when": "When",
                        }
                    ),
                    use_container_width=True,
                    height=500,
                )
            _show_query(sparql)


# ---- Q6 -----------------------------------------------------------------
elif selected_q == QUESTIONS[5]:
    if not periods:
        _render_empty()
    else:
        period = st.selectbox("Select a historical period", periods)
        if period and st.button("Show results", type="primary"):
            sparql = VOICES_PREFIXES + f"""
SELECT ?activity (COUNT(?event) AS ?count)
WHERE {{
  GRAPH <{G_EVENTS}> {{
    ?event a voices:NarratedEvent ;
           voices:temporalBucket "{_safe(period)}" ;
           voices:hasActivity ?act .
    ?act rdfs:label ?activity .
  }}
}}
GROUP BY ?activity ORDER BY DESC(?count)"""
            df = run_sparql(sparql)
            show_sparql_error()
            cached_badge()
            if df.empty:
                _render_empty()
            else:
                import plotly.express as px

                fig = px.bar(df, x="activity", y="count", title=f"Activities during {period}")
                fig.update_layout(height=400, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(df, use_container_width=True)
            _show_query(sparql)


# ---- Q7 -----------------------------------------------------------------
elif selected_q == QUESTIONS[6]:
    if not interviews:
        _render_empty()
    else:
        interv = st.selectbox("Select a survivor", interviews)
        if interv and st.button("Show results", type="primary"):
            sparql = VOICES_PREFIXES + f"""
SELECT ?emotion (COUNT(?emo) AS ?count) ?valence ?arousal ?category
WHERE {{
  GRAPH <{G_META}> {{ ?interview a voices:Interview . {_label_match("?interview", interv)} }}
  GRAPH <{G_TRANS}> {{ ?interview voices:hasSegment ?seg . }}
  GRAPH <{G_EVENTS}> {{ ?seg voices:segmentRefersToEvent ?event . }}
  GRAPH <{G_ANNOT}> {{
    ?event voices:hasEmotion ?emo .
    ?emo rdfs:label ?emotion .
    OPTIONAL {{ ?emo voices:hasValence ?valence . }}
    OPTIONAL {{ ?emo voices:hasArousal ?arousal . }}
    OPTIONAL {{ ?emo voices:emotionCategory ?category . }}
  }}
}}
GROUP BY ?emotion ?valence ?arousal ?category
ORDER BY DESC(?count)"""
            df = run_sparql(sparql)
            show_sparql_error()
            cached_badge()
            if df.empty:
                _render_empty()
            else:
                import plotly.express as px

                fig = px.bar(
                    df,
                    x="emotion",
                    y="count",
                    color="category" if "category" in df.columns else None,
                    title=f"Emotional profile of {interv}",
                )
                fig.update_layout(height=400, xaxis_tickangle=-45)
                st.plotly_chart(fig, use_container_width=True)

                if "valence" in df.columns and "arousal" in df.columns:
                    df2 = df.copy()
                    df2["valence"] = pd.to_numeric(df2["valence"], errors="coerce")
                    df2["arousal"] = pd.to_numeric(df2["arousal"], errors="coerce")
                    df2["count"] = pd.to_numeric(df2["count"], errors="coerce")
                    df2 = df2.dropna(subset=["valence", "arousal"])
                    if not df2.empty:
                        fig2 = px.scatter(
                            df2,
                            x="valence",
                            y="arousal",
                            size="count",
                            color="emotion",
                            hover_name="emotion",
                            title="Valence-Arousal space",
                        )
                        fig2.update_layout(height=450)
                        fig2.add_vline(x=0, line_dash="dot", line_color="gray", opacity=0.3)
                        fig2.add_hline(y=0.5, line_dash="dot", line_color="gray", opacity=0.3)
                        st.plotly_chart(fig2, use_container_width=True)
                st.dataframe(df, use_container_width=True)
            _show_query(sparql)


# ---- Q8 -----------------------------------------------------------------
elif selected_q == QUESTIONS[7]:
    if not emotions:
        _render_empty()
    else:
        emo = st.selectbox("Select an emotion", emotions)
        if emo and st.button("Show results", type="primary"):
            sparql = VOICES_PREFIXES + f"""
SELECT ?place (COUNT(?event) AS ?count)
WHERE {{
  GRAPH <{G_EVENTS}> {{
    ?event voices:hasLocation ?loc .
    ?loc rdfs:label ?place .
  }}
  GRAPH <{G_ANNOT}> {{
    ?event voices:hasEmotion ?emo .
    {_label_match("?emo", emo)}
  }}
}}
GROUP BY ?place ORDER BY DESC(?count) LIMIT 30"""
            df = run_sparql(sparql)
            show_sparql_error()
            cached_badge()
            if df.empty:
                _render_empty()
            else:
                import plotly.express as px

                fig = px.bar(df, x="place", y="count", title=f"Places associated with {emo}")
                fig.update_layout(height=400, xaxis_tickangle=-45, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(df, use_container_width=True)
            _show_query(sparql)


# ---- Q9: keyword / Meilisearch -----------------------------------------
elif selected_q == QUESTIONS[8]:
    kw = st.text_input("Keyword or phrase", placeholder="e.g. Auschwitz, train, hunger")
    if kw and st.button("Search", type="primary"):
        res = meili_search(
            kw, limit=30, attributes_to_highlight=["text", "content"]
        )
        if res.get("error"):
            st.error(f"Search error: {res['error']}")
        hits = res.get("hits", [])
        if not hits:
            _render_empty()
        else:
            st.metric("Matches", res.get("estimatedTotalHits", len(hits)))
            for hit in hits:
                fmt = hit.get("_formatted", {}) or {}
                text = fmt.get("text") or fmt.get("content") or hit.get("text") or hit.get("content") or ""
                survivor = hit.get("survivor") or hit.get("interview_label") or ""
                activity = hit.get("activity") or ""
                st.markdown(f"**{survivor}** — _{activity}_", unsafe_allow_html=False)
                st.markdown(text, unsafe_allow_html=True)
                st.divider()


# ---- Free-form ----------------------------------------------------------
elif selected_q == QUESTIONS[9]:
    st.markdown("Combine any filters below. The system builds the query for you.")
    c1, c2, c3 = st.columns(3)
    with c1:
        act = st.selectbox("Activity", ["(any)"] + activities, key="ff_act")
    with c2:
        emo = st.selectbox("Emotion", ["(any)"] + emotions, key="ff_emo")
    with c3:
        place = st.selectbox("Place", ["(any)"] + places, key="ff_place")
    c4, c5 = st.columns(2)
    with c4:
        period = st.selectbox("Period", ["(any)"] + periods, key="ff_period")
    with c5:
        interv = st.selectbox("Survivor", ["(any)"] + interviews, key="ff_interv")

    if st.button("Build and run query", type="primary"):
        event_filters: list[str] = []
        annot_filters: list[str] = []
        meta_filters: list[str] = []
        if act != "(any)":
            event_filters.append(
                f'?event voices:hasActivity ?act . {_label_match("?act", act, "_act_lbl")}'
            )
        if place != "(any)":
            event_filters.append(
                f'?event voices:hasLocation ?loc . {_label_match("?loc", place, "_loc_lbl")}'
            )
        if period != "(any)":
            event_filters.append(f'?event voices:temporalBucket "{_safe(period)}" .')
        if emo != "(any)":
            annot_filters.append(
                f'?event voices:hasEmotion ?emo_node . {_label_match("?emo_node", emo, "_emo_lbl")}'
            )
        if interv != "(any)":
            meta_filters.append(_label_match("?interview", interv, "_int_lbl"))

        if not (event_filters or annot_filters or meta_filters):
            st.warning("Select at least one filter.")
        else:
            ef = "\n    ".join(event_filters)
            af = "\n    ".join(annot_filters)
            mf = "\n    ".join(meta_filters)
            annot_block = f"GRAPH <{G_ANNOT}> {{ {af} }}" if annot_filters else ""
            sparql = VOICES_PREFIXES + f"""
SELECT ?survivor ?what ?where ?when ?emotion_label
WHERE {{
  GRAPH <{G_META}> {{ ?interview a voices:Interview ; rdfs:label ?survivor . {mf} }}
  GRAPH <{G_TRANS}> {{ ?interview voices:hasSegment ?seg . }}
  GRAPH <{G_EVENTS}> {{
    ?seg voices:segmentRefersToEvent ?event .
    {ef}
  }}
  {annot_block}
  OPTIONAL {{ GRAPH <{G_EVENTS}> {{ ?event voices:whatText ?what . }} }}
  OPTIONAL {{ GRAPH <{G_EVENTS}> {{ ?event voices:hasLocation ?p . ?p rdfs:label ?where . }} }}
  OPTIONAL {{ GRAPH <{G_EVENTS}> {{ ?event voices:whenText ?when . }} }}
  OPTIONAL {{ GRAPH <{G_ANNOT}> {{ ?event voices:hasEmotion ?em . ?em rdfs:label ?emotion_label . }} }}
}}
LIMIT 200"""
            df = run_sparql(sparql)
            show_sparql_error()
            cached_badge()
            if df.empty:
                _render_empty()
            else:
                st.success(f"{len(df)} results found")
                st.dataframe(
                    df.rename(
                        columns={
                            "survivor": "Survivor",
                            "what": "What happened",
                            "where": "Where",
                            "when": "When",
                            "emotion_label": "Emotion",
                        }
                    ),
                    use_container_width=True,
                    height=500,
                )
            _show_query(sparql)

render_credits_footer()
