"""End-to-end analysis: rules + ML + risk score. The single entry point the app and CLI use."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from auditlens.config import OUTPUT_DIR, Config
from auditlens.dataset import Dataset
from auditlens.ml.features import build_features
from auditlens.ml.model import ml_flags, score_entries
from auditlens.ml.scoring import build_review_queue, combined_scores
from auditlens.rules import run_all_rules
from auditlens.rules.base import combine


@dataclass
class AnalysisResult:
    """Everything produced by one analysis run."""

    dataset: Dataset
    rule_flags: pd.DataFrame  # rule hits only
    ml_flags: pd.DataFrame  # ML_ANOMALY hits
    flags: pd.DataFrame  # both, one row per (entry, rule_code)
    features: pd.DataFrame
    ml_scores: pd.DataFrame  # entry_id, ml_raw, ml_score
    scores: pd.DataFrame  # indexed by entry_id: rule_score, ml_score, ml_points, risk_score
    queue: pd.DataFrame  # ranked review queue


def analyse(ds: Dataset, cfg: Config | None = None) -> AnalysisResult:
    """Run every rule, the Isolation Forest, and build the ranked review queue."""
    cfg = cfg or ds.cfg
    rule_flags = run_all_rules(ds)
    features = build_features(ds)
    ml_scores = score_entries(features, cfg)
    ml_hits = ml_flags(features, ml_scores, cfg)
    flags = combine([rule_flags, ml_hits])
    queue = build_review_queue(ds, flags, ml_scores, cfg)
    scores = combined_scores(ds.entries["entry_id"], flags, ml_scores, cfg)
    return AnalysisResult(ds, rule_flags, ml_hits, flags, features, ml_scores, scores, queue)


def save_outputs(result: AnalysisResult, out_dir: Path | str = OUTPUT_DIR) -> None:
    """Write the review queue, flags and scores to CSV for inspection and the dashboard."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result.queue.to_csv(out / "review_queue.csv", index=False)
    result.flags.to_csv(out / "flags.csv", index=False)
    result.scores.reset_index().to_csv(out / "scores.csv", index=False)


def main() -> None:
    """CLI: `python -m auditlens.pipeline` analyses data/ and writes outputs/review_queue.csv."""
    from auditlens.config import load_config

    cfg = load_config()
    result = analyse(Dataset.from_dir(cfg), cfg)
    save_outputs(result)
    q = result.queue
    print(f"{len(result.dataset.entries):,} entries scanned, {len(q):,} in the review queue")
    print(f"Top of queue: {q['entry_id'].iloc[0]} (risk {q['risk_score'].iloc[0]:.1f})")
    print(f"Wrote review_queue.csv, flags.csv, scores.csv to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
