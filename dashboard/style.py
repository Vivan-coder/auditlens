"""Look and feel: a restrained, working-paper style. CSS, KPI cards, badges and Plotly layout."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
NAVY = "#1f3a5f"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"  # validated categorical slots 1-3

CSS = """
<style>
.block-container {padding-top: 3.4rem; max-width: 1280px;}
[data-testid="stToolbar"], [data-testid="stDeployButton"], footer {visibility: hidden; height: 0;}
section[data-testid="stSidebar"] {border-right: 1px solid #e6e5e1; background: #f4f5f7;}
section[data-testid="stSidebar"] .al-brand {font-size:1.25rem; font-weight:700; color:#1f3a5f;
    letter-spacing:-0.01em; margin-bottom:.1rem;}
.al-header {background: linear-gradient(100deg, #1f3a5f 0%, #2b5486 100%); color:#fff;
    border-radius:10px; padding:18px 24px; margin-bottom:1rem;}
.al-header h1 {color:#fff; font-size:1.55rem; font-weight:700; margin:0; padding:0;
    letter-spacing:-0.01em;}
.al-header p {color:#d6e2f2; margin:.25rem 0 0 0; font-size:.9rem;}
.al-kpi {background:#fff; border:1px solid #e6e5e1; border-top:3px solid #1f3a5f;
    border-radius:8px; padding:12px 16px; height:100%; transition: box-shadow .15s ease;}
.al-kpi:hover {box-shadow: 0 2px 10px rgba(31,58,95,.10);}
.al-kpi.High {border-top-color:#c0392b;} .al-kpi.Medium {border-top-color:#d98e04;}
.al-kpi .l {font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; color:#52514e;}
.al-kpi .v {font-size:1.7rem; font-weight:700; color:#0b0b0b; line-height:1.25;}
.al-kpi .s {font-size:.8rem; color:#52514e;}
.al-card {background:#fff; border:1px solid #e6e5e1; border-radius:8px; padding:14px 18px;
    margin-bottom:.8rem;}
.al-card h4 {margin:0 0 .35rem 0; font-size:1rem; color:#1f3a5f;}
.al-banner {background:#eef4fc; border:1px solid #cfe0f6; color:#1b4f99; border-radius:8px;
    padding:8px 12px; font-size:.85rem; margin-bottom:.9rem;}
.al-section {font-size:1.05rem; font-weight:700; color:#1f3a5f; margin:1.2rem 0 .4rem 0;
    padding-bottom:.25rem; border-bottom:2px solid #e6e5e1;}
.al-reason {border-left:3px solid #2a78d6; background:#f6f8fc; border-radius:4px;
    padding:.45rem .8rem; margin:.4rem 0; font-size:.93rem;}
.al-reason.ml {border-left-color:#eb6834; background:#fdf4ef;}
.al-tag {display:inline-block; padding:1px 9px; border-radius:999px; font-size:.72rem;
    background:#e1ecfa; color:#1b4f99; margin-right:8px; font-weight:600;}
.al-reason.ml .al-tag {background:#fbe3d8; color:#9a3a14;}
.al-pill {display:inline-block; padding:2px 10px; border-radius:999px; font-size:.78rem;
    font-weight:600; margin-right:6px;}
.al-pill.Pending {background:#eceae4; color:#52514e;}
.al-pill.Reviewed {background:#d9f2e6; color:#0b6b45;}
.al-pill.False-positive {background:#e9e7f7; color:#4a3fa3;}
.al-pill.High {background:#fde3e2; color:#a02827;}
.al-pill.Medium {background:#fdf0d0; color:#8a5a00;}
.al-pill.Low {background:#eceae4; color:#52514e;}
.stButton > button, .stDownloadButton > button {border-radius:6px; transition: all .12s ease;}
[data-testid="stDataFrame"] {border:1px solid #e6e5e1; border-radius:8px;}
</style>
"""


def inject_css() -> None:
    """Add the app stylesheet."""
    st.markdown(CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "") -> None:
    """Navy banner with the page title (replaces the default heading)."""
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(f'<div class="al-header"><h1>{title}</h1>{sub}</div>', unsafe_allow_html=True)


def section(title: str) -> None:
    """Small section heading with a rule."""
    st.markdown(f'<div class="al-section">{title}</div>', unsafe_allow_html=True)


def kpi(label: str, value: str, sub: str = "", tone: str = "") -> str:
    """HTML for one KPI card; `tone` ('High' or 'Medium') colours the top rule."""
    return (
        f'<div class="al-kpi {tone}"><div class="l">{label}</div><div class="v">{value}</div>'
        f'<div class="s">{sub or "&nbsp;"}</div></div>'
    )


def kpi_row(items: list[tuple]) -> None:
    """A row of KPI cards: (label, value, subtitle[, tone])."""
    cols = st.columns(len(items))
    for col, item in zip(cols, items, strict=True):
        col.markdown(kpi(*item), unsafe_allow_html=True)


def pill(text: str) -> str:
    """Coloured pill for a status or a risk tier."""
    css = text.replace(" ", "-")
    return f'<span class="al-pill {css}">{text}</span>'


status_badge = pill  # same look, kept for readability at call sites


def synthetic_banner() -> None:
    """Reminder shown on pages for the demo dataset."""
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
        title={"font": {"size": 14, "color": NAVY}, "x": 0.0},
        legend={"orientation": "h", "y": -0.2, "x": 0.0, "font": {"color": INK_2}},
        hoverlabel={"font_size": 12},
        transition={"duration": 250},
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, tickfont={"color": INK_2})
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, tickfont={"color": INK_2})
    return fig


def show(fig: go.Figure) -> None:
    """Render a figure full-width without the toolbar."""
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
