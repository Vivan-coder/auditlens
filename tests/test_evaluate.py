"""Evaluation metrics: arithmetic on tiny examples, then sanity checks on the full run."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from auditlens.dataset import dataset_from_tables
from auditlens.eval_charts import save_charts
from auditlens.eval_report import render_report
from auditlens.evaluate import (
    SYSTEMS,
    TYPE_CODES,
    evaluate_result,
    overall_table,
    per_type_table,
    prf,
    to_metrics_json,
    wilson,
)
from auditlens.pipeline import analyse
from auditlens.rules import RULE_CODES
from auditlens.rules.base import make_flags


def test_prf_arithmetic_and_zero_division():
    assert prf(8, 10, 16) == (0.8, 0.5, pytest.approx(2 * 0.8 * 0.5 / 1.3))
    assert prf(0, 0, 5) == (0.0, 0.0, 0.0)
    assert prf(0, 4, 0) == (0.0, 0.0, 0.0)


def test_wilson_interval_matches_known_values():
    lo, hi = wilson(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3) and hi == pytest.approx(0.5962, abs=1e-3)
    assert wilson(0, 0) == (0.0, 0.0)
    lo, hi = wilson(100, 100)
    assert hi == pytest.approx(1.0) and lo > 0.95


def test_overall_table_counts():
    flagged = {"rules": {"a", "b", "x"}, "ml": {"a"}, "combined": {"a", "b"}}
    out = overall_table(flagged, positives={"a", "b", "c", "d"}, n_entries=100)
    assert out.loc["rules", "true_positives"] == 2 and out.loc[
        "rules", "precision"
    ] == pytest.approx(2 / 3)
    assert out.loc["rules", "recall"] == 0.5
    assert out.loc["ml", "precision"] == 1.0 and out.loc["ml", "recall"] == 0.25
    assert out.loc["combined", "flag_rate"] == 0.02


def test_per_type_precision_uses_designed_rules_and_recall_uses_any_flag():
    # Entry e1 and e2 are 'round_amount' positives; e3 is a 'same_creator_approver' positive.
    labels = pd.DataFrame(
        {
            "entry_id": ["e1", "e2", "e3"],
            "anomaly_type": ["round_amount", "round_amount", "same_creator_approver"],
        }
    )
    rule_flags = pd.concat(
        [
            make_flags(["e1", "e9"], "amounts", "ROUND_AMOUNT", ["r", "r"]),  # e9 is a false alarm
            make_flags(["e3"], "approval", "SELF_APPROVED", ["s"]),
            make_flags(["e2"], "x", "WEEKEND_POSTING", ["w"]),  # e2 caught by an unrelated rule
        ]
    )
    result = SimpleNamespace(rule_flags=rule_flags)
    flagged = {"rules": set(rule_flags["entry_id"]), "ml": {"e1", "z"}, "combined": {"e1", "e3"}}
    t = per_type_table(result, flagged, labels)
    assert t.loc["round_amount", "rules_precision"] == 0.5  # 1 of {e1, e9}
    assert t.loc["round_amount", "rules_recall"] == 1.0  # e2 counts as surfaced
    assert t.loc["round_amount", "ml_precision"] == 0.5  # yield: e1 of {e1, z}
    assert t.loc["same_creator_approver", "combined_recall"] == 1.0
    assert t.loc["weekend_holiday_posting", "n_positives"] == 0
    assert set(t.index) == set(TYPE_CODES)


def test_every_rule_code_is_mapped_to_an_anomaly_type_or_documented_as_unplanted():
    mapped = {c for codes in TYPE_CODES.values() for c in codes}
    unplanted = {"NO_APPROVER", "APPROVER_OVER_LIMIT", "LARGE_MANUAL", "DUPLICATE_INVOICE_NUMBER"}
    assert mapped | unplanted == set(RULE_CODES)


# ---- full run ---------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def ev_and_result(tables, cfg, labels):
    result = analyse(dataset_from_tables(tables, cfg), cfg)
    return evaluate_result(result, labels, cfg), result


def test_overall_results_are_sane(ev_and_result):
    ev, _ = ev_and_result
    o = ev.overall
    assert o.loc["rules", "recall"] >= 0.95
    assert o.loc["rules", "precision"] > o.loc["ml", "precision"] * 3
    assert o.loc["ml", "flag_rate"] == pytest.approx(0.02, abs=0.002)
    assert (o["f1"] <= 1).all() and (o["precision"] <= 1).all()


def test_precision_at_top_of_queue_and_curves(ev_and_result):
    ev, _ = ev_and_result
    r = ev.ranking.set_index(["system", "k"])
    assert r.loc[("combined", 50), "precision_at_k"] >= 0.9
    assert r.loc[("combined", 100), "precision_at_k"] >= 0.9
    assert r.loc[("combined", 100), "precision_at_k"] > r.loc[("ml", 100), "precision_at_k"]
    assert list(ev.curves.columns) == list(SYSTEMS)
    assert ev.curves.index.max() == 500


def test_threshold_sensitivity_trades_precision_for_recall(ev_and_result):
    s = ev_and_result[0].sensitivity
    assert s["recall"].is_monotonic_decreasing
    assert s["flagged"].is_monotonic_decreasing
    assert s["precision"].iloc[-1] >= s["precision"].iloc[0]


def test_report_charts_and_json(ev_and_result, cfg, tmp_path):
    ev, _ = ev_and_result
    charts = save_charts(ev, tmp_path)
    assert len(charts) == 3 and all(p.exists() and p.stat().st_size > 5000 for p in charts)
    text = render_report(ev, cfg, None, charts_dir="charts")
    for heading in (
        "Overall results",
        "Per anomaly type",
        "Weaknesses and caveats",
        "Auditor capacity",
    ):
        assert heading in text
    assert "synthetic" in text and "circular" in text
    blob = json.loads(json.dumps(to_metrics_json(ev)))
    assert set(blob["overall"]) == set(SYSTEMS)
    assert len(blob["per_type"]) == 12
