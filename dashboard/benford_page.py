"""Benford analysis page: observed first-digit shares against the expectation, per vendor."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from scipy import stats

from auditlens.rules.benford import DIGITS, EXPECTED_SHARE, benford_table, digit_counts
from dashboard import style
from dashboard.state import Bundle

MIN_INDICATIVE = 10


def _vendor_stats(amounts: pd.Series) -> dict:
    obs = digit_counts(amounts)
    chi2, p = stats.chisquare(obs, EXPECTED_SHARE * obs.sum())
    return {
        "obs": obs,
        "n": int(obs.sum()),
        "chi2": float(chi2),
        "p": float(p),
        "mad": float(np.abs(obs / obs.sum() - EXPECTED_SHARE).mean()),
    }


def digit_chart(s: dict, title: str) -> go.Figure:
    """Observed leading-digit shares (bars) versus the Benford expectation (line)."""
    fig = go.Figure()
    fig.add_bar(
        x=DIGITS,
        y=s["obs"] / s["n"] * 100,
        name="Observed",
        marker_color=style.BLUE,
        hovertemplate="Digit %{x}: %{y:.1f}%<extra>observed</extra>",
    )
    fig.add_scatter(
        x=DIGITS,
        y=EXPECTED_SHARE * 100,
        name="Benford expected",
        mode="lines+markers",
        line={"color": style.INK, "width": 2, "dash": "dot"},
        marker={"size": 8},
        hovertemplate="Digit %{x}: %{y:.1f}%<extra>expected</extra>",
    )
    fig.update_layout(
        title=title,
        xaxis={"title": "Leading digit", "dtick": 1},
        yaxis={"title": "% of invoices"},
        bargap=0.3,
    )
    return style.style_figure(fig, 380)


def render(b: Bundle) -> None:
    """Render the Benford page."""
    st.title("Benford analysis")
    if b.synthetic:
        style.synthetic_banner()
    cfg = b.dataset.cfg.rules.benford
    inv = b.dataset.invoices
    if inv.empty:
        st.info(
            "This dataset has no vendor invoices (credits to payables carrying a vendor and "
            "an invoice number)."
        )
        return
    st.markdown(
        "In naturally occurring amounts about **30%** start with 1 and about **5%** with 9. "
        "Fabricated amounts often break that pattern. The chi-square test needs enough invoices, "
        f"so vendors with fewer than **{cfg.min_invoices}** are only indicative."
    )
    table = benford_table(b.dataset)
    counts = inv.groupby("vendor_id").size()
    eligible = counts[counts >= MIN_INDICATIVE].index
    order = list(table["vendor_id"]) + [
        v for v in sorted(eligible) if v not in set(table["vendor_id"])
    ]
    if not order:
        st.info("No vendor has enough invoices to analyse.")
        return
    names = (
        dict(zip(b.dataset.vendors["vendor_id"], b.dataset.vendors["vendor_name"], strict=True))
        if len(b.dataset.vendors)
        else {}
    )
    vendor = st.selectbox(
        "Vendor (most unusual first)",
        order,
        format_func=lambda v: f"{v}  {names.get(v, '')}".strip(),
    )
    s = _vendor_stats(inv.loc[inv["vendor_id"] == vendor, "amount"])
    fails = s["p"] < cfg.p_threshold and s["n"] >= cfg.min_invoices
    if fails:
        verdict, note = "Deviates", "from Benford's Law"
    elif s["n"] >= cfg.min_invoices:
        verdict, note = "Conforms", "to Benford's Law"
    else:
        verdict, note = "Indicative", f"fewer than {cfg.min_invoices} invoices"
    style.kpi_row(
        [
            ("Invoices", f"{s['n']:,}", "amounts analysed"),
            ("Chi-square", f"{s['chi2']:.1f}", "8 degrees of freedom"),
            ("p-value", f"{s['p']:.2g}", f"flag below {cfg.p_threshold:g}"),
            ("Mean abs. deviation", f"{s['mad']:.3f}", "of digit shares"),
            ("Result", verdict, note),
        ]
    )
    style.show(digit_chart(s, f"Leading digits of invoice amounts: {vendor}"))
    st.subheader("All vendors")
    t = table.assign(
        result=lambda d: np.where(d["p_value"] < cfg.p_threshold, "Deviates", "Conforms")
    )
    st.dataframe(
        t[["vendor_id", "n", "chi2", "p_value", "mad", "result"]],
        hide_index=True,
        width="stretch",
        column_config={
            "n": "Invoices",
            "chi2": st.column_config.NumberColumn("Chi-square", format="%.1f"),
            "p_value": st.column_config.NumberColumn("p-value", format="%.2e"),
            "mad": st.column_config.NumberColumn("MAD", format="%.3f"),
        },
    )
    st.caption(
        "A low p-value is a lead, not proof: legitimate vendors with capped or contract "
        "prices also deviate. Multiple tests across many vendors will produce occasional "
        "false alarms by chance, which is why the threshold is strict."
    )
