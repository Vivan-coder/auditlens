"""Data upload: CSV -> column mapping -> pydantic validation -> analysis."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
import streamlit as st

from auditlens.schema import (
    ALL_FIELDS,
    REQUIRED_FIELDS,
    apply_mapping,
    suggest_mapping,
    template_csv,
    validate_journal,
)
from dashboard import state
from dashboard.state import UPLOADED, Bundle

NONE = "(not in my file)"
HELP = {
    "entry_id": "Groups lines into one journal entry",
    "posting_date": "Date the entry hit the ledger",
    "account": "GL account code (a whole number)",
    "debit": "Debit amount (blank = 0)",
    "credit": "Credit amount (blank = 0)",
    "line_id": "Unique id per line (generated if missing)",
    "document_date": "Invoice / source document date",
    "description": "Free text",
    "vendor_id": "Needed by the duplicate, Benford, vendor tests",
    "created_by": "User who keyed the entry",
    "approved_by": "User who approved it",
    "source": "manual or automated",
    "invoice_number": "Vendor invoice number",
    "period": "Accounting period YYYY-MM (derived if missing)",
}


@st.cache_data(show_spinner=False, max_entries=3)
def read_csv_bytes(data: bytes) -> pd.DataFrame:
    """Parse the uploaded CSV with every column as text so nothing is silently coerced."""
    return pd.read_csv(BytesIO(data), dtype=str, keep_default_na=False, na_values=[""])


def _mapping_form(cols: list[str]) -> dict[str, str | None]:
    guess = suggest_mapping(cols)
    options = [NONE, *cols]
    mapping: dict[str, str | None] = {}
    c1, c2 = st.columns(2)
    for i, f in enumerate(ALL_FIELDS):
        req = f in REQUIRED_FIELDS
        default = options.index(guess[f]) if guess[f] in options else 0
        box = (c1 if i % 2 == 0 else c2).selectbox(
            f"{f}{' *' if req else ''}", options, index=default, help=HELP[f], key=f"map_{f}"
        )
        mapping[f] = None if box == NONE else box
    return mapping


def _show_result(res) -> None:
    st.divider()
    if res.ok:
        st.success(f"Valid: {res.n_rows:,} lines in {res.n_entries:,} balanced entries.")
    else:
        st.error(
            f"{len(res.errors)} problem(s) found. Fix the file or the mapping and validate again."
        )
        errs = pd.DataFrame(res.errors)
        errs["row"] = errs["row"].apply(lambda r: "" if pd.isna(r) else int(r))
        st.dataframe(
            errs.rename(
                columns={
                    "row": "CSV row",
                    "column": "Column",
                    "problem": "Problem",
                    "value": "Value",
                }
            ),
            hide_index=True,
            width="stretch",
        )
        st.download_button(
            "Download error list (CSV)", errs.to_csv(index=False), "validation_errors.csv"
        )
    for w in res.warnings:
        st.warning(w)


def _run_analysis(name: str, journal: pd.DataFrame) -> None:
    with st.spinner("Running audit tests and the anomaly model..."):
        bundle = state.make_uploaded_bundle(name, journal)
    st.session_state["upload_bundle"] = bundle
    st.session_state["active_dataset"] = UPLOADED
    state.goto("Overview")
    st.rerun()


def render(b: Bundle) -> None:
    """Render the upload page."""
    st.title("Data upload")
    st.markdown(
        "Upload a journal-entry CSV (one row per journal line). Map your columns to the AuditLens "
        "schema, validate, then run the same audit tests and anomaly model on your data. "
        "Required fields are marked *. Don't upload confidential data to a public deployment: "
        "this app is a portfolio demo."
    )
    st.download_button(
        "Download a CSV template", template_csv(), "auditlens_template.csv", mime="text/csv"
    )
    file = st.file_uploader("Journal entries CSV", type=["csv"])
    if file is None:
        st.info("No file yet. Use the template above to see the expected layout.")
        return
    try:
        raw = read_csv_bytes(file.getvalue())
    except Exception as exc:  # unreadable file: report plainly
        st.error(f"Could not read this file as CSV: {exc}")
        return
    st.caption(f"{len(raw):,} rows, {len(raw.columns)} columns. Preview:")
    st.dataframe(raw.head(8), hide_index=True, width="stretch")
    st.subheader("1. Map columns")
    mapping = _mapping_form(list(raw.columns))
    dayfirst = (
        st.radio(
            "Date format", ["Year first (2025-03-31)", "Day first (31/03/2025)"], horizontal=True
        )
        == "Day first (31/03/2025)"
    )
    st.subheader("2. Validate")
    if st.button("Validate file", type="primary"):
        res = validate_journal(apply_mapping(raw, mapping), dayfirst=dayfirst)
        st.session_state["upload_result"] = (file.name, res)
    name_res = st.session_state.get("upload_result")
    if not name_res or name_res[0] != file.name:
        return
    _show_result(name_res[1])
    if name_res[1].ok:
        st.subheader("3. Analyse")
        if st.button("Run analysis on this file", type="primary"):
            _run_analysis(file.name, name_res[1].journal)
