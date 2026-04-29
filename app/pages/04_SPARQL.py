"""SPARQL Playground — run queries directly against Fuseki (incl. RDF-star)."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.auth_gate import render_user_badge  # noqa: E402
from components.credits import render_credits_footer  # noqa: E402
from components.sparql_client import (  # noqa: E402
    VOICES_PREFIXES,
    cached_badge,
    fuseki_available,
    fuseki_status_badge,
    run_sparql,
    show_sparql_error,
)

st.set_page_config(page_title="SPARQL Playground", layout="wide")
render_user_badge()
fuseki_status_badge()

st.title("SPARQL Playground")
st.caption("VOICES KG v2 — direct querying of the triplestore")

if not fuseki_available():
    st.warning("The triplestore is not reachable.")
    st.stop()

PREBUILT: dict[str, str] = {
    "Count entities by type": """\
SELECT ?type (COUNT(?s) AS ?count)
WHERE { GRAPH ?g { ?s a ?type } }
GROUP BY ?type
ORDER BY DESC(?count)""",
    "Top 20 emotions with frequency": """\
SELECT ?label (COUNT(?emo) AS ?count)
WHERE {
  GRAPH ?g {
    ?emo a voices:EmotionAnnotation ;
         rdfs:label ?label .
  }
}
GROUP BY ?label
ORDER BY DESC(?count)
LIMIT 20""",
    "Events by historical period": """\
SELECT ?bucket (COUNT(?event) AS ?count)
WHERE {
  GRAPH ?g {
    ?event a voices:NarratedEvent ;
           voices:temporalBucket ?bucket .
  }
}
GROUP BY ?bucket
ORDER BY ?bucket""",
    "Activity-emotion co-occurrence": """\
SELECT ?activity_label ?emotion_label (COUNT(*) AS ?count)
WHERE {
  GRAPH ?g {
    ?event voices:hasActivity ?act ;
           voices:hasEmotion ?emo .
    ?act rdfs:label ?activity_label .
    ?emo rdfs:label ?emotion_label .
  }
}
GROUP BY ?activity_label ?emotion_label
ORDER BY DESC(?count)
LIMIT 50""",
    "Similarity pairs (top 20)": """\
SELECT ?emb1 ?emb2 ?score
WHERE {
  GRAPH ?g {
    ?emb1 voices:similarTo ?emb2 ;
          voices:similarityScore ?score .
  }
}
ORDER BY DESC(?score)
LIMIT 20""",
}

STAR_EXAMPLES: dict[str, str] = {
    "Star: annotation confidence distribution": """\
# Read the confidence attached to each hasActivity triple via RDF-star.
SELECT ?confidence (COUNT(*) AS ?count)
WHERE {
  GRAPH <urn:voices:graph:annotations> {
    << ?event voices:hasActivity ?act >> voices:confidence ?confidence .
  }
}
GROUP BY ?confidence
ORDER BY DESC(?count)""",
    "Star: extraction method per activity": """\
# Compare pattern vs LLM extraction methods for activities.
SELECT ?method (COUNT(*) AS ?count)
WHERE {
  GRAPH <urn:voices:graph:annotations> {
    << ?event voices:hasActivity ?act >> voices:method ?method .
  }
}
GROUP BY ?method
ORDER BY DESC(?count)""",
    "Star: low-confidence annotations sample": """\
# Inspect low-confidence annotation statements.
SELECT ?event ?activity ?confidence ?method
WHERE {
  GRAPH <urn:voices:graph:annotations> {
    << ?event voices:hasActivity ?act >> voices:confidence ?confidence ;
                                          voices:method ?method .
    FILTER (xsd:decimal(?confidence) < 0.6)
    OPTIONAL { ?act rdfs:label ?activity . }
  }
}
LIMIT 25""",
}

st.sidebar.markdown("### Pre-built queries")
standard_choice = st.sidebar.selectbox(
    "Standard queries", ["(write your own)"] + list(PREBUILT.keys())
)

st.sidebar.markdown("### SPARQL-star examples")
star_choice = st.sidebar.selectbox(
    "RDF-star queries", ["(none)"] + list(STAR_EXAMPLES.keys())
)

if star_choice != "(none)":
    default_query = VOICES_PREFIXES + "\n" + STAR_EXAMPLES[star_choice]
elif standard_choice != "(write your own)":
    default_query = VOICES_PREFIXES + "\n" + PREBUILT[standard_choice]
else:
    default_query = VOICES_PREFIXES + "\nSELECT * WHERE { GRAPH ?g { ?s ?p ?o } } LIMIT 10"

query = st.text_area("SPARQL Query", value=default_query, height=320)

if st.button("Run query", type="primary"):
    with st.spinner("Querying..."):
        result = run_sparql(query)
    show_sparql_error()
    cached_badge()
    if not result.empty:
        st.success(f"{len(result)} results")
        st.dataframe(result, use_container_width=True, height=500)
    elif not st.session_state.get("sparql_error"):
        st.info("Query returned no results.")

with st.expander("About SPARQL-star", expanded=False):
    st.markdown(
        "RDF-star lets you attach metadata to statements themselves. "
        "Example: `<< ?event voices:hasActivity ?a >> voices:confidence 0.87 .` "
        "In VOICES v2 these meta-triples live in the **annotations** graph and "
        "record the extraction method, confidence, and pattern used for each "
        "automatically-generated assertion."
    )

render_credits_footer()
