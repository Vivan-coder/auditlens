"""Look and feel: CSS, KPI cards and Plotly layout shared by every page."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"  # validated categorical slots 1-3

CSS = """
<style>
.block-container {padding-top: 1.6rem; max-width: 1280px;}
h1 {font-weight: 700; letter-spacing: -0.01em;}
section[data-testid="stSidebar"] {border-right: 1px solid #e6e5e1;}
.al-kpi {background:#ffffff; border:1px solid #e6e5e1; border-radius:10px; padding:14px 16px;
         height:100%;}
.al-kpi .l {font-size:.74rem; text-transform:uppercase; letter-spacing:.05em; color:#52514e;}
.al-kpi .v {font-size:1.75rem; font-weight:700; color:#0b0b0b; line-height:1.25;}
.al-kpi .s {font-size:.8rem; color:#52514e;}
.al-banner {background:#eef4fc; border:1px solid #cfe0f6; color:#1b4f99; border-radius:8px;
            padding:8px 12px; font-size:.85rem; margin-bottom:.8rem;}
.al-reason {border-left:3px solid #2a78d6; background:#f6f8fc; border-radius:4px;
            padding:.45rem .8rem; margin:.4rem 0; font-size:.93rem;}
.al-reason.ml {border-left-color:#eb6834; background:#fdf4ef;}
.al-tag {display:inline-block; padding:1px 9px; border-radius:999px; font-size:.72rem;
         background:#e1ecfa; color:#1b4f99; margin-right:8px; font-weight:600;}
.al-reason.ml .al-tag {background:#fbe3d8; color:#9a3a14;}
.al-status {display:inline-block; padding:2px 10px; border-radius:999px; font-size:.8rem;
            font-weight:600;}
.al-status.Pending {background:#eceae4; color:#52514e;}
.al-status.Reviewed {background:#d9f2e6; color:#0b6b45;}
.al-status.False-positive {background:#fde3e2; color:#a02827;}
footer {visibility: hidden;}
</style>
"""


def inject_css() -> None:
    """Add the app stylesheet."""
    st.markdown(CSS, unsafe_allow_html=True)


def kpi(label: str, value: str, sub: str = "") -> str:
    """HTML for one KPI card."""
    return (
        f'<div class="al-kpi"><div class="l">{label}</div><div class="v">{value}</div>'
        f'<div class="s">{sub or "&nbsp;"}</div></div>'
    )


def kpi_row(items: list[tuple[str, str, str]]) -> None:
    """A row of KPI cards: (label, value, subtitle)."""
    cols = st.columns(len(items))
    for col, (label, value, sub) in zip(cols, items, strict=True):
        col.markdown(kpi(label, value, sub), unsafe_allow_html=True)


def status_badge(status: str) -> str:
    """Coloured status pill."""
    css = status.replace(" ", "-")
    return f'<span class="al-status {css}">{status}</span>'


def synthetic_banner() -> None:
    """Reminder shown on every page for the demo dataset."""
    st.markdown(
        '<div class="al-banner">All data in this demo is <b>synthetic</b>: a fictional company, '
        "fictional vendors and people. Anomalies were planted deliberately for evaluation.</div>",
        unsafe_allow_html=True,
    )


def style_figure(fig: go.Figure, height: int = 340) -> go.Figure:
    """Recessive grid, ink text, thin marks, compact margins."""
    fig.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 36, "b": 8},
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font={"family": "Inter, Segoe UI, sans-serif", "size": 12, "color": INK_2},
        title={"font": {"size": 14, "color": INK}, "x": 0.0},
        legend={"orientation": "h", "y": -0.2, "x": 0.0, "font": {"color": INK_2}},
        hoverlabel={"font_size": 12},
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, tickfont={"color": INK_2})
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, tickfont={"color": INK_2})
    return fig


def show(fig: go.Figure) -> None:
    """Render a figure full-width without the toolbar."""
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
