"""Challenge ledger: controls caught, boundary cases missed as documented, decoys flagged."""

from __future__ import annotations

import pytest

from auditlens.challenge import VARIANTS, build_challenge
from auditlens.challenge_eval import render_report, summarise, variant_table
from auditlens.dataset import dataset_from_tables
from auditlens.pipeline import analyse


@pytest.fixture(scope="module")
def built(cfg):
    tables = build_challenge(cfg)
    result = analyse(dataset_from_tables(tables, cfg), cfg)
    return tables, result, variant_table(result, tables["labels"], cfg)


def test_every_variant_is_planted_and_labelled(built):
    tables, _, table = built
    assert set(table["variant"]) == set(VARIANTS)
    notes = tables["labels"]["note"]
    assert notes.str.startswith("variant:").all()
    assert set(tables["labels"]["role"]) <= {"injected", "counterpart", "decoy"}


def test_challenge_ledger_is_clean_apart_from_the_challenge_cases(built, labels):
    """No standard anomalies are planted here: every label comes from a challenge variant."""
    tables, _, _ = built
    j = tables["journal_entries"]
    sums = j.groupby("entry_id")[["debit", "credit"]].sum()
    assert ((sums["debit"] - sums["credit"]).abs() < 1e-6).all()
    assert tables["labels"]["entry_id"].nunique() < 400


def test_controls_are_caught_by_their_intended_rule(built):
    t = built[2].set_index("variant")
    controls = t[t["design"] == "detect"]
    assert len(controls) == 3
    assert (controls["intended_rule"] >= 0.9).all()


def test_boundary_variants_are_missed_by_intended_rules_as_documented(built):
    t = built[2].set_index("variant")
    boundary = t[t["design"] == "miss"]
    assert boundary["intended_rule"].mean() < 0.25
    for v in (
        "dup_late_repeat",
        "split_wide_band_80_88pct",
        "near_round_amounts",
        "manual_just_below_materiality",
        "reciprocal_approval_pair",
        "ghost_address_reformatted",
        "bank_change_payment_20_to_30_days",
        "benford_vendor_only_40_invoices",
        "backdated_20_to_26_days",
    ):
        assert t.loc[v, "intended_rule"] <= 0.2, v


def test_ml_catches_what_the_materiality_threshold_misses(built):
    t = built[2].set_index("variant")
    assert t.loc["manual_just_below_materiality", "intended_rule"] == 0
    assert t.loc["manual_just_below_materiality", "ml_any"] >= 0.8


def test_decoys_reach_the_queue(built):
    t = built[2]
    d = t[t["design"] == "decoy"]
    assert (d["combined"] >= 0.8).all()


def test_report_states_caveat_and_numbers(built, cfg):
    _, _, table = built
    text = render_report(table, cfg)
    s = summarise(table)
    assert "not independent validation" in text and "Results by variant" in text
    assert f"{s['detect_n']} entries" in text
    assert all(v in text for v in VARIANTS)


def test_challenge_build_is_deterministic(cfg):
    a, b = build_challenge(cfg), build_challenge(cfg)
    assert a["labels"].equals(b["labels"])
    assert a["journal_entries"]["debit"].equals(b["journal_entries"]["debit"])
