"""Evaluation page: the Phase 4 metrics against the planted ground truth."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from auditlens.eval_report import pct, weaknesses_section
from auditlens.evaluate import SYSTEM_LABEL, SYSTEMS, Evaluation
from dashboard import style
from dashboard.state import Bundle

SERIES = {"rules": style.BLUE, "ml": style.ORANGE, "combined": style.AQUA}


def overall_frame(ev: Evaluation) -> pd.DataFrame:
    """Overall metrics formatted for display."""
    rows = []
    for s in SYSTEMS:
        r = ev.overall.loc[s]
        rows.append(
            {
                "System": SYSTEM_LABEL[s],
                "Flagged": int(r["flagged"]),
                "True positives": int(r["true_positives"]),
                "Precision": pct(r["precision"]),
                "Recall": pct(r["recall"]),
                "F1": round(float(r["f1"]), 3),
                "Share of ledger": pct(r["flag_rate"], 2),
            }
        )
    return pd.DataFrame(rows)


def per_type_frame(ev: Evaluation) -> pd.DataFrame:
    """Per anomaly type metrics formatted for display."""
    out = pd.DataFrame(
        {
            "Anomaly type": [t.replace("_", " ") for t in ev.per_type.index],
            "n": ev.per_type["n_positives"].to_numpy(),
        }
    )
    for s in SYSTEMS:
        label = SYSTEM_LABEL[s]
        out[f"{label} P"] = (ev.per_type[f"{s}_precision"] * 100).round(0).to_numpy()
        out[f"{label} R"] = (ev.per_type[f"{s}_recall"] * 100).round(0).to_numpy()
        out[f"{label} F1"] = ev.per_type[f"{s}_f1"].round(2).to_numpy()
    return out


def recall_chart(ev: Evaluation) -> go.Figure:
    """Grouped bars: recall by anomaly type and system."""
    df = ev.per_type.sort_values("rules_recall")
    labels = [t.replace("_", " ") for t in df.index]
    fig = go.Figure()
    for s in SYSTEMS:
        fig.add_bar(
            y=labels,
            x=df[f"{s}_recall"] * 100,
            name=SYSTEM_LABEL[s],
            orientation="h",
            marker_color=SERIES[s],
            hovertemplate="%{y}: %{x:.0f}%<extra>" + SYSTEM_LABEL[s] + "</extra>",
        )
    fig.update_layout(
        title="Recall by anomaly type (% of planted entries flagged)",
        barmode="group",
        xaxis={"range": [0, 100]},
        bargap=0.25,
    )
    return style.style_figure(fig, 560)


def curve_chart(ev: Evaluation) -> go.Figure:
    """Precision@K for the three systems."""
    fig = go.Figure()
    for s in SYSTEMS:
        fig.add_scatter(
            x=ev.curves.index,
            y=ev.curves[s] * 100,
            mode="lines",
            name=SYSTEM_LABEL[s],
            line={"color": SERIES[s], "width": 2},
            hovertemplate="Top %{x}: %{y:.0f}%<extra>" + SYSTEM_LABEL[s] + "</extra>",
        )
    fig.update_layout(
        title="Precision at K (share of the top K entries that are real anomalies)",
        xaxis_title="Entries reviewed (K)",
        yaxis={"title": "Precision (%)", "range": [0, 105]},
    )
    return style.style_figure(fig, 360)


def render(b: Bundle) -> None:
    """Render the evaluation page."""
    style.page_header("Evaluation", "How the tests performed against known, planted anomalies")
    ev = b.evaluation()
    if ev is None:
        st.info(
            "Evaluation needs ground-truth labels, which only the synthetic demo data has. "
            "Uploaded data has no known anomalies to score against."
        )
        return
    style.synthetic_banner()
    cfg = b.dataset.cfg
    st.markdown(
        f"Scored against **{ev.n_positives}** planted anomaly entries "
        f"({pct(ev.n_positives / ev.n_entries)} of {ev.n_entries:,} entries). The labels live in "
        "a separate "
        "file and were never used by any test or model. Evaluation is at entry level."
    )
    st.dataframe(overall_frame(ev), hide_index=True, width="stretch")
    st.caption(
        f"Rules alone = any audit test fired. ML alone = Isolation Forest top "
        f"{pct(1 - cfg.ml.flag_percentile, 0)}. "
        f"Combined = risk score of {cfg.evaluation.combined_threshold:g} or more."
    )
    st.subheader("Auditor capacity")
    k = ev.ranking.assign(System=lambda d: d["system"].map(SYSTEM_LABEL))
    pk = k.pivot(index="System", columns="k", values="precision_at_k").mul(100).round(0)
    pk.columns = [f"Precision@{c}" for c in pk.columns]
    st.dataframe(pk.loc[[SYSTEM_LABEL[s] for s in SYSTEMS]], width="stretch")
    style.show(curve_chart(ev))
    st.subheader("By anomaly type")
    style.show(recall_chart(ev))
    with st.expander("Precision, recall and F1 table"):
        st.dataframe(per_type_frame(ev), hide_index=True, width="stretch")
        st.caption(
            "P and R in %. P counts entries carrying a rule designed for that type; for ML it is "
            "the "
            "share of all ML flags that are that type."
        )
    with st.expander("Combined system: alert threshold sensitivity"):
        s = ev.sensitivity.assign(
            precision=lambda d: (d["precision"] * 100).round(1),
            recall=lambda d: (d["recall"] * 100).round(1),
            f1=lambda d: d["f1"].round(3),
        )
        st.dataframe(s, hide_index=True, width="stretch")
    st.subheader("Where the false positives come from")
    fp = ev.cross_type.head(8).reset_index()
    fp.columns = ["Flag source", "Entries flagged", "Of which clean", "Precision"]
    fp["Precision"] = (fp["Precision"] * 100).round(0)
    st.dataframe(fp, hide_index=True, width="stretch")
    st.subheader("Weaknesses and caveats")
    st.markdown(weaknesses_section(ev, cfg))
    st.caption(
        "The full report, including a multi-seed stability check, is in docs/evaluation_report.md."
    )
