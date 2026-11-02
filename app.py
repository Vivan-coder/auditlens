"""AuditLens dashboard. Run with: streamlit run app.py"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for p in (ROOT, ROOT / "src"):  # works without `pip install -e .` (e.g. Streamlit Community Cloud)
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import streamlit as st  # noqa: E402
from dashboard import benford_page, detail, evaluation_page, overview, queue, state, style, upload  # noqa: E402
from dashboard.state import DEMO, UPLOADED  # noqa: E402

PAGES = {
    "Overview": overview.render,
    "Review queue": queue.render,
    "Entry detail": detail.render,
    "Benford analysis": benford_page.render,
    "Evaluation": evaluation_page.render,
    "Data upload": upload.render,
}


def _sidebar() -> None:
    st.sidebar.markdown('<div class="al-brand">AuditLens</div>', unsafe_allow_html=True)
    st.sidebar.caption("Audit analytics for journal entries: audit tests + unsupervised ML.")
    st.sidebar.radio("Navigate", list(PAGES), key="nav", label_visibility="collapsed")
    if "upload_bundle" in st.session_state:
        choice = st.session_state.get("active_dataset", DEMO)
        picked = st.sidebar.radio("Dataset", [DEMO, UPLOADED], index=[DEMO, UPLOADED].index(choice))
        st.session_state["active_dataset"] = picked
    st.sidebar.divider()
    st.sidebar.caption(
        "Portfolio project. All demo data is synthetic. Risk scores are screening "
        "indicators, not audit conclusions."
    )


def main() -> None:
    """Page shell: apply pending navigation, draw the sidebar, render the chosen page."""
    st.set_page_config(page_title="AuditLens", page_icon=None, layout="wide")
    style.inject_css()
    if "_goto" in st.session_state:  # navigation requested by a button callback or a rerun
        st.session_state["nav"] = st.session_state.pop("_goto")
    if "nav" not in st.session_state:  # deep link: ?page=Review%20queue
        wanted = st.query_params.get("page", "Overview")
        st.session_state["nav"] = wanted if wanted in PAGES else "Overview"
    _sidebar()
    bundle = state.active_bundle()
    PAGES[st.session_state["nav"]](bundle)


main()
