"""Evaluation against the planted ground truth: `python -m auditlens.evaluate`.

Everything is at ENTRY level (one journal entry = one review item). A "positive" is any entry that
appears in labels.csv, including the genuine counterpart of a planted duplicate payment.

Conventions (also stated in the generated report):
* Recall (per type) = share of that type's positive entries that the system flagged at all.
* Precision (per type) for Rules and Combined = of the flagged entries carrying a rule designed for
  that type, the share that really are that type. ML has no designed type, so its per-type
  precision is its "yield": the share of ALL ML flags that are that type.
* Overall precision/recall/F1 treat any label as correct.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from auditlens.config import DATA_DIR, OUTPUT_DIR, ROOT, Config, load_config
from auditlens.dataset import Dataset, dataset_from_tables, load_labels
from auditlens.generate import generate
from auditlens.pipeline import AnalysisResult, analyse

SYSTEMS = ("rules", "ml", "combined")
SYSTEM_LABEL = {"rules": "Rules alone", "ml": "ML alone", "combined": "Combined"}

# Which rule codes are designed to detect which planted anomaly type.
TYPE_CODES: dict[str, list[str]] = {
    "duplicate_payment": ["DUP_SAME_INVOICE", "DUP_EXACT_AMOUNT", "DUP_NEAR_AMOUNT"],
    "split_purchase": ["SPLIT_BELOW_LIMIT"],
    "weekend_holiday_posting": ["WEEKEND_POSTING", "HOLIDAY_POSTING"],
    "round_amount": ["ROUND_AMOUNT"],
    "same_creator_approver": ["SELF_APPROVED"],
    "late_or_backdated_posting": ["POST_CLOSE_POSTING", "BACKDATED_POSTING"],
    "ghost_vendor": ["GHOST_VENDOR_BANK", "GHOST_VENDOR_ADDRESS"],
    "bank_change_large_payment": ["BANK_CHANGE_LARGE_PAYMENT"],
    "invoice_sequence_break": ["INVOICE_GAP", "INVOICE_OUT_OF_ORDER"],
    "unusual_account_use": ["RARE_ACCOUNT_PAIR", "RARE_USER_ACCOUNT"],
    "benford_violation": ["BENFORD_VENDOR"],
    "large_manual_period_end": ["LARGE_MANUAL_PERIOD_END"],
}


@dataclass
class Evaluation:
    """All evaluation tables for one dataset."""

    n_entries: int
    n_positives: int
    overall: pd.DataFrame  # index: system
    per_type: pd.DataFrame  # index: anomaly_type
    ranking: pd.DataFrame  # columns: system, k, precision_at_k, recall_at_k
    curves: pd.DataFrame  # index k, columns systems: precision@k
    cross_type: pd.DataFrame  # clean-entry flag counts per rule code (false-positive sources)
    queue_scores: pd.DataFrame  # entry_id, risk_score, is_positive (for the distribution chart)
    sensitivity: pd.DataFrame  # combined system at several risk thresholds


def prf(tp: int, flagged: int, positives: int) -> tuple[float, float, float]:
    """Precision, recall, F1 (0 when undefined)."""
    p = tp / flagged if flagged else 0.0
    r = tp / positives if positives else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion k/n."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def flagged_sets(result: AnalysisResult, cfg: Config) -> dict[str, set[str]]:
    """Entries each system flags."""
    thr = cfg.evaluation.combined_threshold
    return {
        "rules": set(result.rule_flags["entry_id"]),
        "ml": set(result.ml_flags["entry_id"]),
        "combined": set(result.scores.index[result.scores["risk_score"] >= thr]),
    }


def rankings(result: AnalysisResult) -> dict[str, pd.Index]:
    """Entry order each system would hand to an auditor (best first; ties broken by amount)."""
    sc, e = result.scores, result.dataset.entries.set_index("entry_id")
    df = pd.DataFrame(
        {
            "rule_score": sc["rule_score"],
            "ml_raw": result.ml_scores.set_index("entry_id")["ml_raw"],
            "risk": sc["risk_score"],
            "ml_score": sc["ml_score"],
            "amount": e["amount"],
        }
    )

    def order(cols: list[str]) -> pd.Index:
        return df.sort_values(cols, ascending=False, kind="stable").index

    return {
        "rules": order(["rule_score", "amount"]),
        "ml": order(["ml_raw"]),
        "combined": order(["risk", "ml_score", "amount"]),
    }


def overall_table(
    flagged: dict[str, set[str]], positives: set[str], n_entries: int
) -> pd.DataFrame:
    """Overall precision/recall/F1 (with 95% Wilson intervals) and flag rate per system."""
    rows = {}
    for s in SYSTEMS:
        tp = len(flagged[s] & positives)
        p, r, f = prf(tp, len(flagged[s]), len(positives))
        plo, phi = wilson(tp, len(flagged[s]))
        rlo, rhi = wilson(tp, len(positives))
        rows[s] = {
            "flagged": len(flagged[s]),
            "true_positives": tp,
            "precision": p,
            "recall": r,
            "f1": f,
            "precision_ci": (plo, phi),
            "recall_ci": (rlo, rhi),
            "flag_rate": len(flagged[s]) / n_entries,
        }
    return pd.DataFrame(rows).T


def per_type_table(
    result: AnalysisResult, flagged: dict[str, set[str]], labels: pd.DataFrame
) -> pd.DataFrame:
    """Precision / recall / F1 per anomaly type for each system (see module docstring)."""
    rule_hits = result.rule_flags
    rows = []
    for t, codes in TYPE_CODES.items():
        pos = set(labels.loc[labels["anomaly_type"] == t, "entry_id"])
        designed = set(rule_hits.loc[rule_hits["rule_code"].isin(codes), "entry_id"])
        row: dict = {"anomaly_type": t, "n_positives": len(pos)}
        for s in SYSTEMS:
            attributed = flagged[s] if s == "ml" else flagged[s] & designed
            p = len(attributed & pos) / len(attributed) if attributed else 0.0
            r = len(flagged[s] & pos) / len(pos) if pos else 0.0
            row.update(
                {
                    f"{s}_precision": p,
                    f"{s}_recall": r,
                    f"{s}_f1": 2 * p * r / (p + r) if p + r else 0.0,
                }
            )
        rows.append(row)
    return pd.DataFrame(rows).set_index("anomaly_type")


def ranking_tables(
    orders: dict[str, pd.Index], positives: set[str], cfg: Config
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Precision/recall at the configured K values, and the precision@K curve."""
    rows = []
    for s in SYSTEMS:
        hit = orders[s].isin(positives)
        for k in cfg.evaluation.top_k:
            tp = int(hit[:k].sum())
            rows.append(
                {"system": s, "k": k, "precision_at_k": tp / k, "recall_at_k": tp / len(positives)}
            )
    ks = list(range(10, cfg.evaluation.curve_max_k + 1, 10))
    curves = pd.DataFrame(
        {s: [orders[s].isin(positives)[:k].mean() for k in ks] for s in SYSTEMS}, index=ks
    )
    return pd.DataFrame(rows), curves


def false_positive_sources(result: AnalysisResult, positives: set[str]) -> pd.DataFrame:
    """For every flag source, how many flagged entries are genuinely clean (not labelled)."""
    f = result.flags
    g = f.groupby("rule_code")["entry_id"].agg(
        flagged="nunique", clean=lambda s: len(set(s) - positives)
    )
    g["precision"] = 1 - g["clean"] / g["flagged"]
    return g.sort_values("clean", ascending=False)


def threshold_sensitivity(result: AnalysisResult, positives: set[str]) -> pd.DataFrame:
    """Combined system metrics if the alert threshold were different (shows the trade-off)."""
    risk = result.scores["risk_score"]
    rows = []
    for thr in (1, 10, 20, 30, 40, 50, 60):
        flagged = set(risk.index[risk >= thr])
        tp = len(flagged & positives)
        p, r, f = prf(tp, len(flagged), len(positives))
        rows.append(
            {"threshold": thr, "flagged": len(flagged), "precision": p, "recall": r, "f1": f}
        )
    return pd.DataFrame(rows)


def evaluate_result(result: AnalysisResult, labels: pd.DataFrame, cfg: Config) -> Evaluation:
    """Compute every table for one analysed dataset."""
    entries = result.dataset.entries["entry_id"]
    positives = set(labels["entry_id"])
    flagged = flagged_sets(result, cfg)
    ranking, curves = ranking_tables(rankings(result), positives, cfg)
    qs = result.scores[["risk_score"]].assign(is_positive=lambda d: d.index.isin(positives))
    return Evaluation(
        n_entries=len(entries),
        n_positives=len(positives),
        overall=overall_table(flagged, positives, len(entries)),
        per_type=per_type_table(result, flagged, labels),
        ranking=ranking,
        curves=curves,
        cross_type=false_positive_sources(result, positives),
        queue_scores=qs.reset_index(),
        sensitivity=threshold_sensitivity(result, positives),
    )


def run_once(cfg: Config) -> tuple[AnalysisResult, pd.DataFrame]:
    """Generate in memory for cfg's seed, analyse, and return (result, labels)."""
    tables = generate(cfg)
    return analyse(dataset_from_tables(tables, cfg), cfg), tables["labels"]


def seed_stability(cfg: Config) -> pd.DataFrame:
    """Overall metrics on freshly generated datasets (different seeds). One row per seed+system."""
    rows = []
    for seed in cfg.evaluation.stability_seeds:
        c = cfg.model_copy(deep=True)
        c.generation.seed = seed
        res, labels = run_once(c)
        ev = evaluate_result(res, labels, c)
        for s in SYSTEMS:
            r = ev.overall.loc[s]
            p100 = ev.ranking[(ev.ranking["system"] == s) & (ev.ranking["k"] == 100)]
            rows.append(
                {
                    "seed": seed,
                    "system": s,
                    "precision": r["precision"],
                    "recall": r["recall"],
                    "f1": r["f1"],
                    "p_at_100": float(p100["precision_at_k"].iloc[0]),
                }
            )
    return pd.DataFrame(rows)


def to_metrics_json(ev: Evaluation) -> dict:
    """A JSON-friendly summary (used by the dashboard and README)."""
    return {
        "n_entries": ev.n_entries,
        "n_positives": ev.n_positives,
        "overall": {
            s: {
                k: (list(v) if isinstance(v, tuple) else float(v))
                for k, v in ev.overall.loc[s].items()
            }
            for s in SYSTEMS
        },
        "per_type": json.loads(ev.per_type.to_json(orient="index")),
        "ranking": ev.ranking.to_dict(orient="records"),
    }


def main(argv: list[str] | None = None) -> None:
    """CLI: analyse data/, evaluate against labels.csv, write report + charts to outputs/."""
    from auditlens.eval_charts import save_charts
    from auditlens.eval_report import render_report

    p = argparse.ArgumentParser(description="Evaluate AuditLens against planted anomalies.")
    p.add_argument("--data", type=Path, default=DATA_DIR)
    p.add_argument("--out", type=Path, default=OUTPUT_DIR)
    p.add_argument("--no-stability", action="store_true", help="skip the multi-seed check")
    p.add_argument(
        "--publish-docs",
        action="store_true",
        help="also copy the report and charts into docs/ (committed)",
    )
    args = p.parse_args(argv)

    cfg = load_config()
    result = analyse(Dataset.from_dir(cfg, args.data), cfg)
    labels = load_labels(args.data)
    ev = evaluate_result(result, labels, cfg)
    stability = None if args.no_stability else seed_stability(cfg)

    args.out.mkdir(parents=True, exist_ok=True)
    charts = save_charts(ev, args.out / "charts")
    report = render_report(ev, cfg, stability, charts_dir="charts")
    (args.out / "evaluation_report.md").write_text(report, encoding="utf-8")
    (args.out / "metrics.json").write_text(
        json.dumps(to_metrics_json(ev), indent=2), encoding="utf-8"
    )
    print(report.split("## Per anomaly type")[0])
    print(f"Report: {args.out / 'evaluation_report.md'}")

    if args.publish_docs:
        docs_img = ROOT / "docs" / "images"
        docs_img.mkdir(parents=True, exist_ok=True)
        for c in charts:
            shutil.copy(c, docs_img / c.name)
        (ROOT / "docs" / "evaluation_report.md").write_text(
            render_report(ev, cfg, stability, charts_dir="images"), encoding="utf-8"
        )
        print("Published docs/evaluation_report.md and docs/images/")


if __name__ == "__main__":
    main()
