"""Overview page: what was scanned, what was flagged, and how much value is exposed."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard import state, style
from dashboard.state import Bundle


def _flag_counts(b: Bundle) -> pd.DataFrame:
    f = b.result.flags
    c = f.groupby("rule_code")["entry_id"].nunique().sort_values().reset_index()
    c.columns = ["Test", "Entries"]
    c["Type"] = c["Test"].map(lambda t: "Machine learning" if t == "ML_ANOMALY" else "Audit rule")
    return c


def render(b: Bundle) -> None:
    """Render the overview."""
    st.title("Overview")
    if b.synthetic:
        style.synthetic_banner()
    cfg = b.dataset.cfg
    q = b.queue
    thr = cfg.evaluation.combined_threshold
    high = q[q["risk_score"] >= thr]
    reviewed = sum(1 for e in q["entry_id"] if state.status_of(b, e) != "Pending")
    style.kpi_row(
        [
            (
                "Entries scanned",
                f"{len(b.dataset.entries):,}",
                f"{len(b.dataset.journal):,} journal lines",
            ),
            (
                "In review queue",
                f"{len(q):,}",
                f"{100 * len(q) / max(len(b.dataset.entries), 1):.1f}% of entries",
            ),
            ("High risk", f"{len(high):,}", f"risk score {thr:g} or more"),
            (
                "Value at risk",
                f"{high['amount'].sum():,.0f}",
                f"{cfg.company.currency}, high-risk entries",
            ),
            ("Review progress", f"{reviewed:,} / {len(q):,}", "reviewed or cleared"),
        ]
    )
    st.write("")
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
            title=f"High-risk value by month ({cfg.company.currency})",
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
    st.caption(
        "Risk score = weighted audit-rule evidence (up to 100) plus up to "
        f"{cfg.scoring.ml_max_points:g} points from the Isolation Forest for statistically "
        "unusual entries. "
        "It is a screening indicator, not a finding."
    )
