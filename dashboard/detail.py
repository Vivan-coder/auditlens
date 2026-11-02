"""Entry detail: the full entry, every reason it was flagged, related entries, review controls."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from auditlens.ml.model import ML_CODE
from dashboard import state, style
from dashboard.state import STATUSES, Bundle

RELATED_DAYS = 14
RELATED_AMOUNT_PCT = 0.02


def related_entries(b: Bundle, entry_id: str) -> pd.DataFrame:
    """Entries linked to this one: named by a rule, or the same vendor with a similar amount."""
    flags, entries = b.result.flags, b.dataset.entries.set_index("entry_id")
    why: dict[str, str] = {}
    for r in flags[flags["entry_id"] == entry_id].itertuples():
        if isinstance(r.related_entry_id, str):
            why.setdefault(r.related_entry_id, f"{r.rule_code}: counterpart named by the test")
    for r in flags[flags["related_entry_id"] == entry_id].itertuples():
        why.setdefault(r.entry_id, f"{r.rule_code}: this entry is its counterpart")
    me = entries.loc[entry_id]
    if isinstance(me["vendor_id"], str):
        v = entries[(entries["vendor_id"] == me["vendor_id"]) & (entries.index != entry_id)]
        close = (v["posting_date"] - me["posting_date"]).abs().dt.days <= RELATED_DAYS
        similar = (v["amount"] - me["amount"]).abs() <= RELATED_AMOUNT_PCT * me["amount"]
        for eid in v.index[close & similar]:
            why.setdefault(eid, "same vendor, similar amount, close in time")
        same_inv = v["invoice_number"].notna() & (v["invoice_number"] == me["invoice_number"])
        for eid in v.index[same_inv]:
            why.setdefault(eid, "same vendor and invoice number")
    ids = [e for e in why if e in entries.index]
    if not ids:
        return pd.DataFrame()
    out = entries.loc[
        ids, ["posting_date", "amount", "invoice_number", "created_by", "source"]
    ].copy()
    out.insert(0, "relationship", [why[e] for e in ids])
    out["risk_score"] = b.result.scores["risk_score"].reindex(ids).round(1)
    out["status"] = [state.status_of(b, e) for e in ids]
    return out.reset_index()


def _lines(b: Bundle, entry_id: str) -> pd.DataFrame:
    j = b.dataset.journal
    lines = j[j["entry_id"] == entry_id][["line_id", "account", "debit", "credit"]].copy()
    names = b.account_names
    lines.insert(2, "account_name", lines["account"].map(names).fillna(""))
    return lines


def _reasons(b: Bundle, entry_id: str) -> None:
    f = b.result.flags
    f = f[f["entry_id"] == entry_id]
    weights = b.dataset.cfg.scoring.rule_weights
    f = f.assign(_w=f["rule_code"].map(weights).fillna(0)).sort_values("_w", ascending=False)
    if f.empty:
        st.info("This entry has no flags.")
    for r in f.itertuples():
        ml = " ml" if r.rule_code == ML_CODE else ""
        st.markdown(
            f'<div class="al-reason{ml}"><span class="al-tag">{r.rule_code}</span>{r.reason}</div>',
            unsafe_allow_html=True,
        )


def _review_controls(b: Bundle, entry_id: str) -> None:
    key = f"status_{entry_id}"
    st.session_state[key] = state.status_of(b, entry_id)  # keep widget in sync with bulk actions

    def save_status() -> None:
        state.set_status(b, [entry_id], st.session_state[key])

    def save_note() -> None:
        state.notes(b)[entry_id] = st.session_state[f"note_{entry_id}"]

    st.radio("Review status", STATUSES, key=key, horizontal=True, on_change=save_status)
    st.session_state.setdefault(f"note_{entry_id}", state.notes(b).get(entry_id, ""))
    st.text_area(
        "Reviewer notes (included in the Excel workpaper)",
        key=f"note_{entry_id}",
        on_change=save_note,
        height=90,
    )


@st.fragment
def _review_panel(b: Bundle, entry_id: str) -> None:
    """Status pill and controls; a fragment, so changing status does not redraw the whole page."""
    st.markdown(style.pill(state.status_of(b, entry_id)), unsafe_allow_html=True)
    _review_controls(b, entry_id)


def _vendor_panel(b: Bundle, vendor_id: str) -> None:
    v = b.dataset.vendors
    if v.empty or vendor_id not in set(v["vendor_id"]):
        return
    row = v[v["vendor_id"] == vendor_id].iloc[0]
    with st.expander(f"Vendor {vendor_id}: {row['vendor_name']}"):
        st.write(f"**Address:** {row['address']}")
        st.write(
            f"**Bank account:** `{row['bank_account']}`  |  **Created:** {row['created_date']}"
        )
        bc = b.dataset.bank_changes
        if len(bc):
            mine = bc[bc["vendor_id"] == vendor_id]
            if len(mine):
                st.write("**Bank account changes**")
                st.dataframe(
                    mine[["change_date", "old_bank_account", "new_bank_account"]],
                    hide_index=True,
                    width="stretch",
                )


def _neighbours(q: pd.DataFrame, entry_id: str) -> tuple[str | None, str | None]:
    ids = list(q["entry_id"])
    if entry_id not in ids:
        return None, None
    i = ids.index(entry_id)
    return (ids[i - 1] if i > 0 else None), (ids[i + 1] if i + 1 < len(ids) else None)


def render(b: Bundle) -> None:
    """Render the entry detail page."""
    style.page_header(
        "Entry detail", "Why an entry was flagged, and what the auditor should look at"
    )
    q = b.queue
    options = list(q["entry_id"])
    current = st.session_state.get("detail_entry")
    if current and current not in options and current in set(b.dataset.entries["entry_id"]):
        options = [current, *options]
    if not options:
        st.info("No entries to show.")
        return
    if current not in options:
        st.session_state["detail_entry"] = options[0]
    entry_id = st.selectbox("Entry (queue order, highest risk first)", options, key="detail_entry")

    e = b.dataset.entries.set_index("entry_id").loc[entry_id]
    sc = b.result.scores.loc[entry_id]
    rank = q.index[q["entry_id"] == entry_id]
    tier = str(q.loc[rank[0], "risk_tier"]) if len(rank) else ""
    style.kpi_row(
        [
            (
                "Risk score",
                f"{sc['risk_score']:.0f}",
                f"{tier} risk, queue rank {int(q.loc[rank[0], 'rank'])}"
                if len(rank)
                else "not in queue",
                tier if tier in ("High", "Medium") else "",
            ),
            ("Rule evidence", f"{sc['rule_score']:.0f}", "weighted audit tests"),
            (
                "ML points",
                f"{sc['ml_points']:.0f}",
                f"anomaly percentile {100 * sc['ml_score']:.1f}",
            ),
            ("Amount", f"{e['amount']:,.2f}", b.dataset.cfg.company.currency),
        ]
    )
    prev_id, next_id = _neighbours(q, entry_id)
    c1, c2, _ = st.columns([1, 1, 4])
    c1.button(
        "Previous",
        disabled=prev_id is None,
        on_click=state.open_entry,
        args=(prev_id or "",),
        width="stretch",
    )
    c2.button(
        "Next",
        disabled=next_id is None,
        on_click=state.open_entry,
        args=(next_id or "",),
        width="stretch",
    )

    left, right = st.columns([3, 2])
    with left:
        style.section("Why it was flagged")
        _reasons(b, entry_id)
        style.section("Journal lines")
        st.dataframe(
            _lines(b, entry_id),
            hide_index=True,
            width="stretch",
            column_config={
                "debit": st.column_config.NumberColumn(format="%.3f"),
                "credit": st.column_config.NumberColumn(format="%.3f"),
            },
        )
        rel = related_entries(b, entry_id)
        style.section("Related entries")
        if rel.empty:
            st.caption("No related entries found.")
        else:
            st.dataframe(rel, hide_index=True, width="stretch")
            for rid in rel["entry_id"].head(3):
                with st.expander(f"Lines of {rid}"):
                    st.dataframe(_lines(b, rid), hide_index=True, width="stretch")
    with right:
        style.section("Entry")
        fields = {
            "Entry ID": entry_id,
            "Description": e["description"],
            "Posting date": f"{e['posting_date']:%Y-%m-%d}",
            "Document date": f"{e['document_date']:%Y-%m-%d}",
            "Period": e["period"],
            "Source": e["source"],
            "Created by": e["created_by"],
            "Approved by": e["approved_by"] if isinstance(e["approved_by"], str) else "none",
            "Vendor": e["vendor_id"] if isinstance(e["vendor_id"], str) else "none",
            "Invoice number": e["invoice_number"]
            if isinstance(e["invoice_number"], str)
            else "none",
        }
        st.table(pd.Series(fields, name="Value").astype(str))
        style.section("Review")
        _review_panel(b, entry_id)
        if isinstance(e["vendor_id"], str):
            _vendor_panel(b, e["vendor_id"])
