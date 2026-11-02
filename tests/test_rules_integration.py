"""Rules run on the generated dataset: each planted type is caught, clean data stays quiet."""

from __future__ import annotations

import pytest

from auditlens.dataset import Dataset
from auditlens.rules import FAMILIES, run_all_rules
from auditlens.rules.base import FLAG_COLUMNS

TYPE_CODES = {
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


@pytest.fixture(scope="module")
def flags(tables, cfg):
    """Flags from running every rule on the generated dataset (no labels involved)."""
    ds = Dataset(
        journal=tables["journal_entries"],
        cfg=cfg,
        vendors=tables["vendors"],
        employees=tables["employees"],
        users=tables["users"],
        bank_changes=tables["vendor_bank_changes"].assign(
            change_date=lambda d: d["change_date"].astype("datetime64[ns]")
        ),
    )
    return run_all_rules(ds)


def test_flag_schema_and_reasons(flags):
    assert list(flags.columns) == FLAG_COLUMNS
    assert flags["reason"].str.len().gt(10).all()
    assert flags["rule_code"].notna().all()
    assert not flags.duplicated(["entry_id", "rule_code"]).any()
    assert set(flags["family"]) <= set(FAMILIES)


@pytest.mark.parametrize("anomaly_type", sorted(TYPE_CODES))
def test_each_planted_type_is_caught(flags, labels, anomaly_type):
    planted = set(labels.loc[labels["anomaly_type"] == anomaly_type, "entry_id"])
    caught = set(flags.loc[flags["rule_code"].isin(TYPE_CODES[anomaly_type]), "entry_id"])
    assert len(planted & caught) / len(planted) >= 0.95


def test_few_clean_entries_are_flagged(flags, journal, labels):
    clean = set(journal["entry_id"]) - set(labels["entry_id"])
    rate = len(set(flags["entry_id"]) & clean) / len(clean)
    assert rate < 0.01  # under 1% of clean entries reach an auditor
