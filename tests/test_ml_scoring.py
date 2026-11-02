"""Risk score arithmetic and the review queue, on hand-made flags (no data generation)."""

from __future__ import annotations

import pandas as pd
import pytest

from auditlens.config import load_config
from auditlens.ml.model import ML_CODE
from auditlens.ml.scoring import build_review_queue, combined_scores, ml_points, rule_score
from auditlens.rules import RULE_CODES
from auditlens.rules.base import make_flags
from helpers import entry, make_ds

CFG = load_config()


def flags(*rows: tuple[str, str]) -> pd.DataFrame:
    """(entry_id, rule_code) pairs -> flags table."""
    parts = [make_flags([e], "x", c, [f"reason for {c}"]) for e, c in rows]
    return pd.concat(parts, ignore_index=True)


def test_every_rule_code_has_a_weight_and_no_unknown_weights():
    assert set(CFG.scoring.rule_weights) == set(RULE_CODES)


def test_rule_score_is_noisy_or_of_weights():
    w = CFG.scoring.rule_weights
    f = flags(("A", "SELF_APPROVED"), ("A", "ROUND_AMOUNT"), ("B", "SELF_APPROVED"))
    s = rule_score(f, CFG)
    expected_a = 100 * (1 - (1 - w["SELF_APPROVED"] / 100) * (1 - w["ROUND_AMOUNT"] / 100))
    assert s["A"] == pytest.approx(expected_a)
    assert s["B"] == pytest.approx(w["SELF_APPROVED"])
    assert s["B"] < s["A"] < 100  # evidence accumulates but saturates


def test_ml_flags_do_not_count_as_rule_evidence():
    s = rule_score(flags(("A", ML_CODE), ("B", "SELF_APPROVED")), CFG)
    assert "A" not in s.index


def test_ml_points_only_above_floor_and_capped():
    floor, cap = CFG.ml.flag_percentile, CFG.scoring.ml_max_points
    scores = pd.DataFrame({"entry_id": ["lo", "mid", "top"], "ml_score": [0.50, floor, 1.0]})
    p = ml_points(scores, CFG)
    assert p["lo"] == 0 and p["mid"] == 0
    assert p["top"] == pytest.approx(cap)


def test_risk_score_adds_ml_points_to_rules_and_caps_at_100():
    ids = pd.Index(["A", "B", "C"])
    f = flags(
        ("A", "SELF_APPROVED"),
        ("C", "GHOST_VENDOR_BANK"),
        ("C", "GHOST_VENDOR_ADDRESS"),
        ("C", "BANK_CHANGE_LARGE_PAYMENT"),
        ("C", "SPLIT_BELOW_LIMIT"),
        ("C", "DUP_SAME_INVOICE"),
    )
    sc = pd.DataFrame({"entry_id": ["A", "B", "C"], "ml_score": [1.0, 1.0, 1.0]})
    out = combined_scores(ids, f, sc, CFG)
    cap = CFG.scoring.ml_max_points
    assert out.loc["A", "risk_score"] == pytest.approx(out.loc["A", "rule_score"] + cap)
    assert out.loc["B", "risk_score"] == pytest.approx(cap)  # ML alone: bounded contribution
    assert out.loc["C", "risk_score"] == 100.0


def test_review_queue_is_ranked_explained_and_filtered():
    ds = make_ds(
        [
            entry("HI", "2025-04-06", amount=500),
            entry("LO", "2025-04-06", amount=600),
            entry("NONE", "2025-04-06", amount=700),
        ]
    )
    f = flags(("HI", "SELF_APPROVED"), ("HI", "ROUND_AMOUNT"), ("LO", "ROUND_AMOUNT"))
    sc = pd.DataFrame({"entry_id": ["HI", "LO", "NONE"], "ml_score": [0.2, 0.2, 0.2]})
    q = build_review_queue(ds, f, sc, CFG)
    assert list(q["entry_id"]) == ["HI", "LO"]  # NONE has no evidence: not queued
    assert list(q["rank"]) == [1, 2]
    assert q.loc[0, "rule_codes"] == "SELF_APPROVED;ROUND_AMOUNT"
    assert q.loc[0, "reasons"] == "reason for SELF_APPROVED | reason for ROUND_AMOUNT"
    assert q.loc[0, "n_flags"] == 2
    assert {"amount", "created_by", "posting_date"} <= set(q.columns)
