"""Review queue: ranked entries, filters, bulk reviewer actions and Excel workpaper export."""

from __future__ import annotations

import re
from functools import partial

import pandas as pd
import streamlit as st

from auditlens.export import build_workpaper
from dashboard import state, style
from dashboard.state import STATUSES, Bundle

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TIER_CELL = {
    "High": "background-color:#fde3e2;color:#a02827;font-weight:600",
    "Medium": "background-color:#fdf0d0;color:#8a5a00;font-weight:600",
    "Low": "background-color:#eceae4;color:#52514e",
}


def _date_bounds(q: pd.DataFrame) -> tuple:
    return q["posting_date"].min().date(), q["posting_date"].max().date()


def filtered_queue(b: Bundle, q: pd.DataFrame, f: dict) -> pd.DataFrame:
    """Apply the filter dictionary to the queue (pure function, easy to test)."""
    m = (q["risk_score"] >= f["min_risk"]) & q["amount"].between(f["amt_min"], f["amt_max"])
    if f.get("tiers"):
        m &= q["risk_tier"].isin(f["tiers"])
    if f["codes"]:
        pat = "|".join(re.escape(c) for c in f["codes"])
        m &= q["rule_codes"].str.contains(pat)
    if f["users"]:
        m &= q["created_by"].isin(f["users"])
    if f["vendors"]:
        m &= q["vendor_id"].isin(f["vendors"])
    if f["accounts"]:
        wanted = set(f["accounts"])
        ea = b.entry_accounts()
        m &= q["entry_id"].map(lambda e: bool(ea.get(e, set()) & wanted))
    if f["dates"]:
        lo, hi = f["dates"]
        m &= q["posting_date"].between(pd.Timestamp(lo), pd.Timestamp(hi))
    if f["status"]:
        m &= q["entry_id"].map(lambda e: state.status_of(b, e) in f["status"])
    return q[m]


def _filters(b: Bundle, q: pd.DataFrame) -> dict:
    """Filter form: values apply together when the user presses Apply (no per-click reruns)."""
    names = b.account_names
    with st.form("queue_filters", border=True):
        c1, c2, c3 = st.columns(3)
        tiers = c1.multiselect("Risk tier", ["High", "Medium", "Low"])
        codes = c2.multiselect(
            "Test / reason code", sorted({c for s in q["rule_codes"] for c in s.split(";") if c})
        )
        status = c3.multiselect("Review status", STATUSES)
        c4, c5, c6 = st.columns(3)
        users = c4.multiselect("Created by", sorted(q["created_by"].dropna().unique()))
        vendors = c5.multiselect("Vendor", sorted(q["vendor_id"].dropna().unique()))
        acct_opts = sorted({a for s in b.entry_accounts().values() for a in s})
        accounts = c6.multiselect(
            "Account", acct_opts, format_func=lambda a: f"{a} {names.get(a, '')}".strip()
        )
        c7, c8, c9 = st.columns([3, 2, 2])
        lo, hi = _date_bounds(q)
        dr = c7.date_input("Posting date", (lo, hi), min_value=lo, max_value=hi)
        top = float(q["amount"].max())
        amt = c8.slider("Entry amount", 0.0, top, (0.0, top))
        min_risk = c9.slider("Minimum risk score", 0, 100, 0)
        st.form_submit_button("Apply filters", type="primary")
    return {
        "min_risk": min_risk,
        "tiers": tiers,
        "codes": codes,
        "status": status,
        "users": users,
        "vendors": vendors,
        "accounts": accounts,
        "dates": tuple(dr) if len(dr) == 2 else None,
        "amt_min": amt[0],
        "amt_max": amt[1],
    }


def _view(b: Bundle, q: pd.DataFrame) -> pd.DataFrame:
    v = q[
        [
            "rank",
            "entry_id",
            "risk_score",
            "risk_tier",
            "posting_date",
            "amount",
            "vendor_id",
            "created_by",
            "rule_codes",
            "reasons",
        ]
    ].copy()
    v.insert(4, "status", [state.status_of(b, e) for e in v["entry_id"]])
    v["posting_date"] = v["posting_date"].dt.date
    v["reasons"] = v["reasons"].str.slice(0, 220)
    for col in ("vendor_id", "created_by"):
        v[col] = v[col].fillna("")
    return v


def _bulk_buttons(b: Bundle, selected: list[str]) -> None:
    c = st.columns(4)
    n = len(selected)
    c[0].button(
        f"Mark reviewed ({n})",
        disabled=n == 0,
        width="stretch",
        on_click=state.set_status,
        args=(b, selected, "Reviewed"),
    )
    c[1].button(
        f"Mark false positive ({n})",
        disabled=n == 0,
        width="stretch",
        on_click=state.set_status,
        args=(b, selected, "False positive"),
    )
    c[2].button(
        "Reset to pending",
        disabled=n == 0,
        width="stretch",
        on_click=state.set_status,
        args=(b, selected, "Pending"),
    )
    c[3].button(
        "Open in detail view",
        disabled=n != 1,
        width="stretch",
        type="primary",
        on_click=state.open_entry,
        args=(selected[0] if n else "",),
    )


def _workpaper_inputs(b: Bundle) -> dict:
    cfg = b.dataset.cfg
    with st.expander("Workpaper details (printed on the Excel cover sheet)"):
        c1, c2 = st.columns(2)
        entity = c1.text_input("Entity", value=cfg.company.name, key="wp_entity")
        period = c2.text_input("Period", value=f"FY{cfg.company.fiscal_year}", key="wp_period")
        preparer = c1.text_input("Prepared by", key="wp_preparer")
        reviewer = c2.text_input("Reviewed by", key="wp_reviewer")
    return {"entity": entity, "period": period, "preparer": preparer, "reviewer": reviewer}


def render(b: Bundle) -> None:
    """Render the review queue page."""
    style.page_header("Review queue", "Ranked exceptions for follow-up, with reviewer sign-off")
    if b.synthetic:
        style.synthetic_banner()
    q = b.queue
    if q.empty:
        st.info("Nothing was flagged in this dataset.")
        return
    f = _filters(b, q)
    fq = filtered_queue(b, q, f)
    st.markdown(
        f"**{len(fq):,}** entries match, total value **{fq['amount'].sum():,.0f}** "
        f"{b.dataset.cfg.company.currency}. Select rows to review them."
    )
    view = _view(b, fq)
    shown = view.style.map(lambda t: TIER_CELL.get(t, ""), subset=["risk_tier"])
    event = st.dataframe(
        shown,
        key="queue_table",
        on_select="rerun",
        selection_mode="multi-row",
        hide_index=True,
        width="stretch",
        height=430,
        column_config={
            "rank": st.column_config.NumberColumn("Rank", width="small"),
            "entry_id": st.column_config.TextColumn("Entry"),
            "risk_score": st.column_config.ProgressColumn(
                "Risk", min_value=0, max_value=100, format="%.0f"
            ),
            "risk_tier": st.column_config.TextColumn("Tier", width="small"),
            "posting_date": st.column_config.DateColumn("Posted"),
            "amount": st.column_config.NumberColumn("Amount", format="%.2f"),
            "vendor_id": "Vendor",
            "created_by": "Created by",
            "status": "Status",
            "rule_codes": st.column_config.TextColumn("Reason codes", width="medium"),
            "reasons": st.column_config.TextColumn("Why flagged", width="large"),
        },
    )
    selected = [view.iloc[i]["entry_id"] for i in event.selection.rows if i < len(view)]
    _bulk_buttons(b, selected)
    meta = _workpaper_inputs(b)
    # Built only when the user clicks download, from plain snapshots (runs on another thread).
    build = partial(
        build_workpaper,
        fq,
        dict(state.statuses(b)),
        dict(state.notes(b)),
        b.name,
        n_scanned=len(b.dataset.entries),
        **meta,
    )
    st.download_button(
        "Export filtered entries to Excel workpaper",
        data=build,
        file_name="auditlens_workpaper.xlsx",
        mime=XLSX_MIME,
        disabled=fq.empty,
        type="primary",
    )
