"""Shared credits / contact footer for every Streamlit page.

Single source of truth for institutional attribution (LIST), the maintainer
email, and the "continuously updated" note — bumping any of these here
propagates to all pages without per-page edits.
"""
from __future__ import annotations

import streamlit as st

MAINTAINER_NAME = "Mohamed Laib"
MAINTAINER_EMAIL = "mohamed.laib@list.lu"
INSTITUTION = "Luxembourg Institute of Science and Technology (LIST)"
PAPER_TITLE = (
    "VOICES: An Ontology and Knowledge Graph for Modelling "
    "Multimodal Holocaust Survivor Testimonies"
)


def render_credits_footer() -> None:
    """Render an institutional / contact / updates footer.

    Call once at the bottom of every Streamlit page.
    """
    st.divider()
    st.markdown(
        f"""
<div style="font-size:0.82em;color:#475569;line-height:1.6;
            margin-top:0.5rem;padding-top:0.4rem;">
  <p style="margin:0 0 0.4em 0;">
    <strong>VOICES Knowledge Graph</strong> &mdash; developed at the
    <span style="color:#0f172a;">{INSTITUTION}</span>.
    Companion resource to the ISWC&nbsp;2026 Resources Track paper
    <em>{PAPER_TITLE}</em>.
  </p>
  <p style="margin:0 0 0.4em 0;">
    <span style="color:#0f172a;">Living resource:</span>
    this knowledge graph is continuously updated and populated as new
    processing pipelines, alignments, and analytical applications are
    integrated.
  </p>
  <p style="margin:0;">
    Maintainer: {MAINTAINER_NAME} &mdash;
    <a href="mailto:{MAINTAINER_EMAIL}"
       style="color:#1d4ed8;text-decoration:none;">{MAINTAINER_EMAIL}</a>
  </p>
</div>
        """,
        unsafe_allow_html=True,
    )
