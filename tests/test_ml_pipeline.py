"""Features, Isolation Forest and the full pipeline on the generated dataset."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from auditlens.dataset import Dataset
from auditlens.ml.features import FEATURES, build_features
from auditlens.ml.model import ML_CODE, explain, score_entries
from auditlens.pipeline import analyse

SRC = Path(__file__).resolve().parents[1] / "src" / "auditlens"


@pytest.fixture(scope="module")
def ds(tables, cfg):
    return Dataset(
        journal=tables["journal_entries"],
        cfg=cfg,
        vendors=tables["vendors"],
        employees=tables["employees"],
        users=tables["users"],
        bank_changes=tables["vendor_bank_changes"].assign(
            change_date=lambda d: d["change_date"].astype("datetime64[ns]")
        ),
    )


@pytest.fixture(scope="module")
def result(ds, cfg):
    return analyse(ds, cfg)


def test_no_label_access_in_rules_or_ml_code():
    for folder in ("rules", "ml"):
        for path in (SRC / folder).glob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "load_labels" not in text and "labels.csv" not in text, path
            assert not re.search(r"\banomaly_type\b", text), path


def test_features_are_complete_numeric_and_one_row_per_entry(ds):
    f = build_features(ds)
    assert list(f.columns) == FEATURES
    assert f.index.is_unique and len(f) == ds.entries["entry_id"].nunique()
    assert np.isfinite(f.to_numpy()).all()
    assert f["lag_days"].min() >= 0 and f["is_weekend"].isin([0, 1]).all()


def test_features_work_on_a_journal_only_dataset(ds, cfg):
    bare = Dataset(journal=ds.journal, cfg=cfg)  # as for an uploaded CSV
    f = build_features(bare)
    assert len(f) == len(ds.entries) and (f["approver_limit_ratio"] == 0).all()


def test_scores_are_deterministic_and_in_unit_interval(result, cfg):
    again = score_entries(result.features, cfg)
    assert np.allclose(again["ml_raw"], result.ml_scores["ml_raw"])
    assert result.ml_scores["ml_score"].between(0, 1).all()
    assert result.ml_scores["ml_score"].max() == 1.0


def test_ml_flags_share_matches_config_and_have_reasons(result, cfg):
    expected = (1 - cfg.ml.flag_percentile) * len(result.ml_scores)
    assert abs(len(result.ml_flags) - expected) <= 0.01 * len(result.ml_scores)
    assert (result.ml_flags["rule_code"] == ML_CODE).all()
    assert result.ml_flags["reason"].str.contains("typical for similar entries").all()


def test_explain_names_requested_number_of_features(result):
    ids = list(result.ml_flags["entry_id"][:3])
    text = explain(result.features, ids, 2)
    assert all(t.count("typical for similar entries") == 2 for t in text.values())


def test_isolation_forest_finds_extreme_amounts(result, labels):
    big = set(labels.loc[labels["anomaly_type"] == "large_manual_period_end", "entry_id"])
    top = set(result.ml_scores.loc[result.ml_scores["ml_score"] >= 0.95, "entry_id"])
    assert len(big & top) / len(big) >= 0.8


def test_review_queue_puts_real_anomalies_first(result, labels):
    planted = set(labels["entry_id"])
    q = result.queue
    assert q["risk_score"].is_monotonic_decreasing
    assert q.head(50)["entry_id"].isin(planted).mean() >= 0.9
    assert q.head(100)["entry_id"].isin(planted).mean() >= 0.9
    assert (q["reasons"].str.len() > 0).all()


def test_combined_ranking_beats_ml_alone(result, labels):
    planted = set(labels["entry_id"])
    ml_top = result.ml_scores.sort_values("ml_score", ascending=False).head(100)["entry_id"]
    combined_top = result.queue.head(100)["entry_id"]
    assert combined_top.isin(planted).mean() > ml_top.isin(planted).mean()
