"""Static evaluation charts (matplotlib), styled with the validated reference palette."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from auditlens.evaluate import SYSTEM_LABEL, SYSTEMS, Evaluation  # noqa: E402

SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
SERIES = {"rules": "#2a78d6", "ml": "#eb6834", "combined": "#1baf7a"}  # categorical slots 1-3
PLANTED, CLEAN = "#6250d6", "#b9b8b2"  # violet (slot 7) for planted anomalies, neutral for clean


def _style(ax, title: str) -> None:
    """Recessive grid and axes, short statement title in primary ink."""
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=12, color=INK, fontweight="bold", pad=14)
    ax.grid(axis="x" if ax.get_ylim()[1] > 0 else "y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=9, length=0)


def _fig(width: float = 9, height: float = 5):
    fig, ax = plt.subplots(figsize=(width, height), facecolor=SURFACE)
    return fig, ax


def recall_by_type(ev: Evaluation, path: Path) -> None:
    """Grouped horizontal bars: share of each planted type that each system surfaced."""
    df = ev.per_type.sort_values("rules_recall")
    fig, ax = _fig(9, 6.2)
    h, y = 0.2, np.arange(len(df))
    for i, s in enumerate(SYSTEMS):
        ax.barh(
            y + (i - 1) * (h + 0.03),
            df[f"{s}_recall"] * 100,
            height=h,
            color=SERIES[s],
            label=SYSTEM_LABEL[s],
        )
    ax.set_yticks(
        y,
        [
            f"{t.replace('_', ' ')} (n={n})"
            for t, n in zip(df.index, df["n_positives"], strict=True)
        ],
    )
    ax.set_xlim(0, 100)
    ax.set_xlabel("% of planted entries flagged", color=INK_2, fontsize=9)
    _style(ax, "Rules catch what they target; ML only the statistically odd")
    ax.legend(loc="lower right", frameon=False, labelcolor=INK_2, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def precision_at_k(ev: Evaluation, path: Path) -> None:
    """Line chart: share of the top K reviewed entries that are real anomalies."""
    fig, ax = _fig(9, 4.8)
    for s in SYSTEMS:
        ax.plot(
            ev.curves.index, ev.curves[s] * 100, color=SERIES[s], linewidth=2, label=SYSTEM_LABEL[s]
        )
        ax.annotate(
            SYSTEM_LABEL[s],
            (ev.curves.index[-1], ev.curves[s].iloc[-1] * 100),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            color=INK,
            fontsize=9,
        )
    for k in (50, 100):
        ax.axvline(k, color=GRID, linewidth=1, zorder=0)
    ax.set_ylim(0, 105)
    ax.set_xlim(0, ev.curves.index[-1] * 1.18)
    ax.set_xlabel("Entries reviewed (K, highest risk first)", color=INK_2, fontsize=9)
    ax.set_ylabel("Precision@K (%)", color=INK_2, fontsize=9)
    _style(ax, "Rules and combined ranking are near-perfect in the top 100; ML alone is not")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.legend(loc="lower left", frameon=False, labelcolor=INK_2, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def risk_distribution(ev: Evaluation, path: Path) -> None:
    """Histogram of combined risk scores, planted anomalies versus all other entries."""
    q = ev.queue_scores
    bins = np.arange(0, 105, 5)
    fig, ax = _fig(9, 4.6)
    ax.hist(
        q.loc[~q["is_positive"], "risk_score"].clip(upper=99.9),
        bins=bins,
        color=CLEAN,
        label="Clean entries",
    )
    ax.hist(
        q.loc[q["is_positive"], "risk_score"].clip(upper=99.9),
        bins=bins,
        color=PLANTED,
        alpha=0.9,
        label="Planted anomalies",
    )
    ax.set_yscale("log")
    ax.set_xlabel("Combined risk score", color=INK_2, fontsize=9)
    ax.set_ylabel("Entries (log scale)", color=INK_2, fontsize=9)
    _style(ax, "Planted anomalies sit at the high end; most clean entries score zero")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.legend(loc="upper right", frameon=False, labelcolor=INK_2, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def save_charts(ev: Evaluation, out_dir: Path) -> list[Path]:
    """Render all evaluation charts to PNG files; returns their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        out_dir / "recall_by_type.png",
        out_dir / "precision_at_k.png",
        out_dir / "risk_distribution.png",
    ]
    recall_by_type(ev, paths[0])
    precision_at_k(ev, paths[1])
    risk_distribution(ev, paths[2])
    return paths
