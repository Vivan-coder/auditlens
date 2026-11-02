"""Overview page: executive summary, risk tiers, key themes with follow-up, supporting charts."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from auditlens.summary import headline, split_attention, themes, tier_counts
from dashboard import state, style
from dashboard.state import Bundle


def _flag_counts(b: Bundle) -> pd.DataFrame:
    f = b.result.flags
    c = f.groupby("rule_code")["entry_id"].nunique().sort_values().reset_index()
    c.columns = ["Test", "Entries"]
    c["Type"] = c["Test"].map(lambda t: "Machine learning" if t == "ML_ANOMALY" else "Audit rule")
    return c


def _executive_summary(b: Bundle) -> None:
    cfg = b.dataset.cfg
    body = _md_to_html(headline(b.result, cfg))
    st.markdown(
        f'<div class="al-card"><h4>Executive summary</h4>{body}</div>', unsafe_allow_html=True
    )


def _md_to_html(text: str) -> str:
    """Bold markers to <b> for the HTML card (headline() uses **bold** only)."""
    parts = text.split("**")
    return "".join(f"<b>{p}</b>" if i % 2 else p for i, p in enumerate(parts))


def _kpis(b: Bundle) -> None:
    q, cfg = b.queue, b.dataset.cfg
    tc = tier_counts(q)
    backed, ml_only = split_attention(q)
    reviewed = sum(1 for e in q["entry_id"] if state.status_of(b, e) != "Pending")
    n = len(b.dataset.entries)
    style.kpi_row(
        [
            ("Entries scanned", f"{n:,}", f"{len(b.dataset.journal):,} journal lines"),
            (
                "High risk",
                f"{tc['High']:,}",
                f"risk score {cfg.scoring.risk_tiers.high:g}+",
                "High",
            ),
            (
                "Medium risk",
                f"{tc['Medium']:,}",
                f"risk score {cfg.scoring.risk_tiers.medium:g} to {cfg.scoring.risk_tiers.high:g}",
                "Medium",
            ),
            (
                "Value to follow up",
                f"{backed['amount'].sum():,.0f}",
                f"{cfg.company.currency}, rule-backed entries",
            ),
            ("Review progress", f"{reviewed:,} / {len(q):,}", "reviewed or cleared"),
        ]
    )


def _themes(b: Bundle) -> None:
    style.section("Key findings and suggested follow-up")
    found = themes(b.result, b.dataset.cfg)
    if not found:
        st.info("No high or medium risk themes were found.")
        return
    cur = b.dataset.cfg.company.currency
    for t in found:
        codes = ", ".join(f"`{c}`" for c in t.top_codes)
        with st.expander(f"{t.title}: {t.entries:,} entries, {cur} {t.value:,.0f}"):
            st.markdown(f"**Triggered by:** {codes}")
            st.markdown(f"**Suggested procedure:** {t.procedure}")
            st.caption("Open the Review queue and filter by the codes above to see each entry.")


def _charts(b: Bundle) -> None:
    style.section("Supporting analysis")
    q, cfg = b.queue, b.dataset.cfg
    left, right = st.columns(2)
    with left:
        counts = _flag_counts(b)
        fig = px.bar(
            counts,
            x="Entries",
            y="Test",
            orientation="h",
            color="Type",
            color_discrete_map={"Audit rule": style.BLUE, "Machine learning": style.ORANGE},
            title="Flags by test (entries)",
        )
        fig.update_layout(
            yaxis_title=None, xaxis_title=None, yaxis={"categoryorder": "total ascending"}
        )
        style.show(style.style_figure(fig, 520))
    with right:
        fig = px.histogram(
            q,
            x="risk_score",
            nbins=20,
            title="Risk score of queued entries",
            color_discrete_sequence=[style.BLUE],
        )
        fig.update_layout(xaxis_title="Risk score", yaxis_title="Entries", bargap=0.08)
        style.show(style.style_figure(fig, 250))
        high, _ = split_attention(q)
        by_month = (
            high.assign(Month=high["posting_date"].dt.strftime("%Y-%m"))
            .groupby("Month")["amount"]
            .sum()
            .reset_index()
        )
        fig = px.bar(
            by_month,
            x="Month",
            y="amount",
            title=f"Rule-backed high and medium risk value by month ({cfg.company.currency})",
            color_discrete_sequence=[style.BLUE],
        )
        fig.update_layout(xaxis_title=None, yaxis_title=None, bargap=0.25)
        style.show(style.style_figure(fig, 250))
    users = q["created_by"].value_counts().head(10).sort_values().reset_index()
    users.columns = ["User", "Queued entries"]
    fig = px.bar(
        users,
        x="Queued entries",
        y="User",
        orientation="h",
        title="Users with the most queued entries",
        color_discrete_sequence=[style.BLUE],
    )
    fig.update_layout(xaxis_title=None, yaxis_title=None)
    style.show(style.style_figure(fig, 320))


def render(b: Bundle) -> None:
    """Render the overview."""
    style.page_header("Overview", f"{b.name}: executive summary of the journal-entry analysis")
    if b.synthetic:
        style.synthetic_banner()
    if b.queue.empty:
        st.info("Nothing was flagged in this dataset.")
        return
    _executive_summary(b)
    _kpis(b)
    _themes(b)
    _charts(b)
    st.caption(
        "Risk score = weighted audit-rule evidence (up to 100) plus up to "
        f"{b.dataset.cfg.scoring.ml_max_points:g} points from the Isolation Forest for "
        "statistically unusual entries. It is a screening indicator, not a finding."
    )
