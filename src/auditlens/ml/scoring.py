"""Combined risk score and the ranked review queue.

risk = rule evidence (noisy-OR of weighted rule hits, 0-100) + ML points (0 to ml_max_points,
only for entries flagged by the Isolation Forest), capped at 100. Rules carry most of
the weight because they are specific and explainable; the ML score lifts unusual entries that no
rule describes and breaks ties among entries with similar rule evidence.
"""

from __future__ import annotations

import pandas as pd

from auditlens.config import Config
from auditlens.dataset import Dataset
from auditlens.ml.model import ML_CODE

QUEUE_DETAIL_COLS = [
    "posting_date",
    "document_date",
    "amount",
    "vendor_id",
    "created_by",
    "approved_by",
    "source",
    "invoice_number",
    "description",
    "period",
]


def rule_score(flags: pd.DataFrame, cfg: Config) -> pd.Series:
    """Noisy-OR of rule weights per entry: 100 * (1 - prod(1 - w/100)). ML flags are excluded."""
    f = flags[flags["rule_code"] != ML_CODE]
    w = f["rule_code"].map(cfg.scoring.rule_weights).fillna(cfg.scoring.default_rule_weight)
    survive = (1 - w / 100).groupby(f["entry_id"]).prod()
    return (100 * (1 - survive)).rename("rule_score")


def ml_points(scores: pd.DataFrame, cfg: Config) -> pd.Series:
    """0..ml_max_points, rising linearly across the ML-flagged slice of scores, 0 elsewhere.

    Starting at ml.flag_percentile means every entry that earns ML points also carries an
    ML_ANOMALY flag, and therefore a reason.
    """
    floor = cfg.ml.flag_percentile
    scaled = ((scores.set_index("entry_id")["ml_score"] - floor) / (1 - floor)).clip(lower=0)
    return (scaled * cfg.scoring.ml_max_points).rename("ml_points")


def combined_scores(entry_ids: pd.Index, flags: pd.DataFrame, scores: pd.DataFrame, cfg: Config):
    """DataFrame (index entry_id): rule_score, ml_score, ml_points, risk_score."""
    out = pd.DataFrame(index=entry_ids)
    out["rule_score"] = rule_score(flags, cfg).reindex(entry_ids).fillna(0.0)
    s = scores.set_index("entry_id")
    out["ml_score"] = s["ml_score"].reindex(entry_ids).fillna(0.0)
    out["ml_points"] = ml_points(scores, cfg).reindex(entry_ids).fillna(0.0)
    out["risk_score"] = (out["rule_score"] + out["ml_points"]).clip(upper=100.0)
    return out


def build_review_queue(
    ds: Dataset, flags: pd.DataFrame, scores: pd.DataFrame, cfg: Config
) -> pd.DataFrame:
    """Ranked review queue: one row per entry with risk_score >= queue_min_score.

    Columns: rank, entry_id, risk_score, rule_score, ml_score, n_flags, rule_codes, reasons,
    related_entry_ids, plus entry details (date, amount, vendor, users, ...).
    """
    entries = ds.entries.set_index("entry_id")
    sc = combined_scores(entries.index, flags, scores, cfg)
    ordered = flags.assign(_ml=flags["rule_code"] == ML_CODE).sort_values(["entry_id", "_ml"])
    grouped = ordered.groupby("entry_id")
    agg = pd.DataFrame(
        {
            "n_flags": grouped.size(),
            "rule_codes": grouped["rule_code"].agg(lambda s: ";".join(s)),
            "reasons": grouped["reason"].agg(lambda s: " | ".join(s)),
            "related_entry_ids": grouped["related_entry_id"].agg(
                lambda s: ";".join(sorted({x for x in s if isinstance(x, str)}))
            ),
        }
    )
    q = sc.join(agg, how="left").join(entries[QUEUE_DETAIL_COLS])
    q = q[q["risk_score"] >= cfg.scoring.queue_min_score]
    q = q.sort_values(["risk_score", "ml_score", "amount"], ascending=False)
    q.insert(0, "rank", range(1, len(q) + 1))
    q["n_flags"] = q["n_flags"].fillna(0).astype(int)
    for col in ("rule_codes", "reasons", "related_entry_ids"):
        q[col] = q[col].fillna("")
    return q.reset_index()
