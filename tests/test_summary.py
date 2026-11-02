"""Risk tiers and the executive summary."""

from __future__ import annotations

import pandas as pd
import pytest

from auditlens.config import load_config
from auditlens.dataset import dataset_from_tables
from auditlens.ml.scoring import risk_tier
from auditlens.pipeline import analyse
from auditlens.summary import (
    THEMES,
    attention,
    headline,
    split_attention,
    themes,
    tier_counts,
)

CFG = load_config()


def test_risk_tier_boundaries_come_from_config():
    t = CFG.scoring.risk_tiers
    s = pd.Series([0.0, t.medium - 0.01, t.medium, t.high - 0.01, t.high, 100.0])
    assert list(risk_tier(s, CFG)) == ["Low", "Low", "Medium", "Medium", "High", "High"]


@pytest.fixture(scope="module")
def result(tables, cfg):
    return analyse(dataset_from_tables(tables, cfg), cfg)


def test_queue_has_tiers_consistent_with_scores(result):
    q = result.queue
    t = CFG.scoring.risk_tiers
    assert set(q["risk_tier"]) <= {"High", "Medium", "Low"}
    assert (q.loc[q["risk_tier"] == "High", "risk_score"] >= t.high).all()
    assert (q.loc[q["risk_tier"] == "Low", "risk_score"] < t.medium).all()
    assert sum(tier_counts(q).values()) == len(q)


def test_themes_put_rule_based_findings_first_and_ml_last(result, cfg):
    th = themes(result, cfg)
    assert th and all(t.procedure and t.title for t in th)
    assert {t.family for t in th} <= set(THEMES)
    assert all(t.entries > 0 and t.top_codes for t in th)
    rule_themes = [t for t in th if t.family != "ml"]
    assert [t.value for t in rule_themes] == sorted((t.value for t in rule_themes), reverse=True)
    if any(t.family == "ml" for t in th):
        assert th[-1].family == "ml"  # the lower-confidence lead is listed last


def test_split_attention_separates_rule_backed_from_ml_only(result):
    backed, ml_only = split_attention(result.queue)
    assert (backed["rule_score"] > 0).all() and (ml_only["rule_score"] <= 0).all()
    assert len(backed) + len(ml_only) == len(attention(result.queue))
    ml_theme = next((t for t in themes(result, CFG) if t.family == "ml"), None)
    if ml_theme:
        assert ml_theme.entries == len(ml_only)  # ML theme counts only unexplained entries


def test_headline_reports_counts_and_flags_ml_only_as_lower_confidence(result, cfg):
    text = headline(result, cfg)
    tc = tier_counts(result.queue)
    backed, ml_only = split_attention(result.queue)
    assert f"**{tc['High']:,}** high risk" in text and "journal entries" in text
    assert f"**{len(backed):,}** of these match at least one specific audit test" in text
    assert f"**{len(ml_only):,}**" in text and "lower-confidence" in text


def test_summary_never_reads_labels():
    import inspect

    import auditlens.summary as mod

    src = inspect.getsource(mod)
    assert "load_labels" not in src and "anomaly_type" not in src and "labels.csv" not in src
