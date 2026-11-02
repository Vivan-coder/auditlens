"""Unsupervised anomaly scoring with an Isolation Forest, plus plain-language explanations."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from auditlens.config import Config
from auditlens.ml.features import FEATURE_LABELS
from auditlens.rules.base import make_flags

ML_CODE = "ML_ANOMALY"


def score_entries(features: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Isolation Forest anomaly scores.

    Returns entry_id, ml_raw (higher = more anomalous) and ml_score, the percentile rank of
    ml_raw in [0, 1] (1.0 = the most anomalous entry). Percentiles make the score easy to
    threshold and to combine with rule evidence.
    """
    model = IsolationForest(
        n_estimators=cfg.ml.n_estimators, random_state=cfg.ml.seed, contamination="auto", n_jobs=1
    )
    model.fit(features.to_numpy())
    raw = -model.score_samples(features.to_numpy())
    out = pd.DataFrame({"entry_id": features.index, "ml_raw": raw})
    out["ml_score"] = out["ml_raw"].rank(pct=True)
    return out


def peer_stats(features: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-entry peer median and robust scale, where peers = same source and vendor/non-vendor.

    Comparing a manual vendor invoice with automated payroll would make every manual entry look
    odd, so explanations are relative to similar entries only. Scale = 1.4826 * MAD, falling back
    to the standard deviation (and then 1) for features with no spread inside the group.
    """
    key = features["is_manual"].astype(int) * 2 + features["has_vendor"].astype(int)
    g = features.groupby(key)
    med = g.transform("median")
    mad = (features - med).abs().groupby(key).transform("median") * 1.4826
    scale = mad.where(mad > 0, g.transform("std")).fillna(1.0).replace(0, 1.0)
    return med, scale


def robust_z(features: pd.DataFrame) -> pd.DataFrame:
    """Robust z-score of each feature against the entry's peer group."""
    med, scale = peer_stats(features)
    return (features - med) / scale


def explain(features: pd.DataFrame, entry_ids: list[str], k: int) -> dict[str, str]:
    """For each entry, name the k features that deviate most from similar entries."""
    med, scale = peer_stats(features)
    z = ((features - med) / scale).loc[entry_ids]
    out: dict[str, str] = {}
    for eid in entry_ids:
        top = z.loc[eid].abs().sort_values(ascending=False).head(k).index
        parts = [
            f"{FEATURE_LABELS[f]}: {features.loc[eid, f]:.2f} "
            f"(typical for similar entries {med.loc[eid, f]:.2f})"
            for f in top
        ]
        out[eid] = "; ".join(parts)
    return out


def ml_flags(features: pd.DataFrame, scores: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """ML_ANOMALY flags for entries in the top (1 - flag_percentile) of scores, with reasons."""
    hit = scores[scores["ml_score"] >= cfg.ml.flag_percentile].sort_values(
        "ml_score", ascending=False
    )
    why = explain(features, hit["entry_id"].tolist(), cfg.ml.explain_top_features)
    top = f"top {100 * (1 - cfg.ml.flag_percentile):.0f}%"
    reasons = [
        f"Statistically unusual entry (anomaly score in the {top}): {why[e]}"
        for e in hit["entry_id"]
    ]
    return make_flags(hit["entry_id"], "ml", ML_CODE, reasons)


def top_percentile_threshold(scores: pd.Series, q: float) -> float:
    """Score value at percentile q (helper for charts and tests)."""
    return float(np.quantile(scores, q))
