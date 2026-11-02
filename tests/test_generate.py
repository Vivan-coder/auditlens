"""Tests for the synthetic data generator."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from auditlens import bh_calendar as cal
from auditlens.config import load_config
from auditlens.generate import JOURNAL_COLUMNS, generate
from conftest import small_cfg

ALL_TYPES = {
    "duplicate_payment",
    "split_purchase",
    "weekend_holiday_posting",
    "round_amount",
    "same_creator_approver",
    "late_or_backdated_posting",
    "ghost_vendor",
    "bank_change_large_payment",
    "invoice_sequence_break",
    "unusual_account_use",
    "benford_violation",
    "large_manual_period_end",
}


def first_digit_pvalue(amounts: pd.Series) -> float:
    """Chi-square p-value of first digits against Benford's Law."""
    digits = amounts.astype(str).str.lstrip("0.").str[0].astype(int)
    obs = np.bincount(digits, minlength=10)[1:]
    exp = np.log10(1 + 1 / np.arange(1, 10)) * obs.sum()
    return float(stats.chisquare(obs, exp).pvalue)


def entry_level(journal: pd.DataFrame) -> pd.DataFrame:
    """One row per entry."""
    return journal.drop_duplicates("entry_id").set_index("entry_id")


# ---- structure ------------------------------------------------------------------------------
def test_every_entry_balances(journal):
    sums = journal.groupby("entry_id")[["debit", "credit"]].sum()
    assert ((sums["debit"] - sums["credit"]).abs() < 1e-6).all()


def test_lines_have_one_side_and_positive_amounts(journal):
    assert ((journal["debit"] > 0) ^ (journal["credit"] > 0)).all()
    assert (journal[["debit", "credit"]] >= 0).all().all()


def test_line_count_close_to_target(journal, cfg):
    assert abs(len(journal) - cfg.generation.target_lines) / cfg.generation.target_lines < 0.05


def test_journal_has_expected_columns_and_no_labels(journal):
    assert list(journal.columns) == JOURNAL_COLUMNS
    assert not any("label" in c or "anomaly" in c for c in journal.columns)


def test_ids_unique_and_dates_consistent(journal):
    assert journal["line_id"].is_unique
    assert (journal["document_date"] <= journal["posting_date"]).all()
    assert journal["document_date"].dt.year.eq(2025).all()


def test_all_accounts_in_chart(journal, tables):
    assert set(journal["account"]) <= set(tables["chart_of_accounts"]["account"])


# ---- reproducibility ----------------------------------------------------------------------------
def test_same_seed_is_reproducible():
    a, b = generate(small_cfg(7)), generate(small_cfg(7))
    for name in a:
        pd.testing.assert_frame_equal(a[name], b[name])


def test_different_seed_changes_data():
    a, b = generate(small_cfg(7)), generate(small_cfg(8))
    assert not a["journal_entries"]["debit"].equals(b["journal_entries"]["debit"])


# ---- labels -------------------------------------------------------------------------------------
def test_labels_reference_real_entries_and_cover_all_types(journal, labels):
    assert set(labels["entry_id"]) <= set(journal["entry_id"])
    assert set(labels["related_entry_id"].dropna()) <= set(journal["entry_id"])
    assert set(labels["anomaly_type"]) == ALL_TYPES


def test_planted_counts_match_config(labels, cfg):
    inj = labels[labels["role"] == "injected"]
    n = lambda t: inj.loc[inj["anomaly_type"] == t, "entry_id"].nunique()  # noqa: E731
    assert n("duplicate_payment") == cfg.anomalies.duplicate_payment
    assert n("weekend_holiday_posting") == cfg.anomalies.weekend_holiday_posting
    assert n("round_amount") == cfg.anomalies.round_amount
    assert n("same_creator_approver") == cfg.anomalies.same_creator_approver
    assert n("benford_violation") == cfg.anomalies.benford_vendor_invoices
    assert n("late_or_backdated_posting") == (
        cfg.anomalies.post_close_posting + cfg.anomalies.backdated_posting
    )


# ---- planted anomalies really have the property; clean data does not ------------------------
def test_weekend_holiday_labels_and_clean_manual_entries(journal, labels):
    e = entry_level(journal)
    off = e["posting_date"].map(lambda d: not cal.is_business_day(d.date()))
    planted = set(labels.loc[labels["anomaly_type"] == "weekend_holiday_posting", "entry_id"])
    assert off[list(planted)].all()
    clean_manual = (e["source"] == "manual") & ~e.index.isin(planted)
    assert not off[clean_manual].any()  # normal manual postings are on business days


def test_post_close_and_backdated(journal, labels):
    e = entry_level(journal)
    closes = e["period"].map(lambda p: pd.Timestamp(cal.period_close_date(p, 5)))
    late = labels[labels["note"].str.startswith("post-close")]["entry_id"]
    assert (e.loc[late, "posting_date"] > closes[late]).all()
    clean = e.index.difference(labels["entry_id"])
    assert (e.loc[clean, "posting_date"] <= closes[clean]).all()
    back = labels[labels["note"].str.startswith("backdated")]["entry_id"]
    lag = (e["posting_date"] - e["document_date"]).dt.days
    assert (lag[back] >= 45).all()
    assert (lag[clean] <= 10).all()


def test_same_creator_approver_only_when_planted(journal, labels):
    e = entry_level(journal)
    manual = e[e["source"] == "manual"]
    same = set(manual.index[manual["created_by"] == manual["approved_by"]])
    planted = set(labels.loc[labels["anomaly_type"] == "same_creator_approver", "entry_id"])
    assert same == planted


def test_manual_entries_have_approver_and_automated_do_not(journal):
    e = entry_level(journal)
    assert e.loc[e["source"] == "manual", "approved_by"].notna().all()
    assert e.loc[e["source"] == "automated", "approved_by"].isna().all()


def test_clean_entries_respect_approval_limits(journal, labels, tables):
    e = entry_level(journal)
    amount = journal.groupby("entry_id")["debit"].sum()
    limits = tables["users"].set_index("user_id")["approval_limit"]
    clean = e[(e["source"] == "manual") & ~e.index.isin(labels["entry_id"])]
    assert (amount[clean.index].values <= limits[clean["approved_by"]].values).all()


def test_duplicate_payments_match_original(journal, labels):
    dups = labels[(labels["anomaly_type"] == "duplicate_payment") & (labels["role"] == "injected")]
    e = entry_level(journal)
    amt = journal[journal["debit"] > 0].groupby("entry_id")["debit"].sum()
    for _, r in dups.iterrows():
        a, b = r["entry_id"], r["related_entry_id"]
        assert e.loc[a, "vendor_id"] == e.loc[b, "vendor_id"]
        assert abs(amt[a] - amt[b]) / amt[b] <= 0.0051
        assert 1 <= abs((e.loc[a, "document_date"] - e.loc[b, "document_date"]).days) <= 7


def test_split_purchases_sit_just_below_an_approval_limit(journal, labels, cfg):
    limits = [r.approval_limit for r in cfg.roles.values() if r.approval_limit > 0]
    ids = labels.loc[labels["anomaly_type"] == "split_purchase", "entry_id"]
    amt = journal[journal["entry_id"].isin(ids) & (journal["debit"] > 0)]["debit"]
    assert all(any(0.9 * lim <= a < lim for lim in limits) for a in amt)


def test_round_amounts_are_round(journal, labels):
    ids = labels.loc[labels["anomaly_type"] == "round_amount", "entry_id"]
    amt = journal[journal["entry_id"].isin(ids) & (journal["debit"] > 0)]["debit"]
    assert (amt % 1000 == 0).all()


def test_ghost_vendors_share_employee_details(tables, labels):
    vendors, emps = tables["vendors"], tables["employees"]
    ghost_ids = {n.split()[1] for n in labels.loc[labels["anomaly_type"] == "ghost_vendor", "note"]}
    assert len(ghost_ids) == 3
    shared = vendors[vendors["vendor_id"].isin(ghost_ids)]
    hit = shared["bank_account"].isin(emps["bank_account"]) | shared["address"].isin(
        emps["address"]
    )
    assert hit.all()
    clean = vendors[~vendors["vendor_id"].isin(ghost_ids)]
    assert not clean["bank_account"].isin(emps["bank_account"]).any()
    assert not clean["address"].isin(emps["address"]).any()


def test_bank_change_precedes_large_payment(journal, labels, tables):
    ids = labels.loc[labels["anomaly_type"] == "bank_change_large_payment", "entry_id"]
    e = entry_level(journal)
    changes = tables["vendor_bank_changes"].assign(
        change_date=lambda d: pd.to_datetime(d["change_date"])
    )
    for eid in ids:
        v, when = e.loc[eid, "vendor_id"], e.loc[eid, "posting_date"]
        c = changes[changes["vendor_id"] == v]["change_date"]
        assert ((when - c).dt.days.between(1, 7)).any()


def test_invoice_sequence_breaks_exist(journal, labels):
    ids = set(labels.loc[labels["anomaly_type"] == "invoice_sequence_break", "entry_id"])
    inv = journal[
        (journal["account"] == 2000) & (journal["credit"] > 0) & journal["invoice_number"].notna()
    ].copy()
    inv["n"] = inv["invoice_number"].str.extract(r"INV-(\d+)")[0].astype(int)
    inv = inv.sort_values(["vendor_id", "document_date", "n"])
    inv["step"] = inv.groupby("vendor_id")["n"].diff()
    flagged = inv[(inv["step"] > 50) | (inv["step"] < 0)]
    assert ids <= set(flagged["entry_id"])
    # in clean data, consecutive invoice numbers never jump by more than 15
    clean_steps = inv[~inv["entry_id"].isin(ids) & inv["step"].notna()]["step"]
    assert (clean_steps <= 15).mean() > 0.99


def test_clean_amounts_follow_benford_and_planted_vendor_does_not(journal, labels):
    inv = journal[(journal["account"] == 2000) & (journal["credit"] > 0)]
    clean = inv[~inv["entry_id"].isin(labels["entry_id"])]
    assert first_digit_pvalue(clean["credit"]) > 0.01
    planted = labels.loc[labels["anomaly_type"] == "benford_violation", "entry_id"]
    assert first_digit_pvalue(inv[inv["entry_id"].isin(planted)]["credit"]) < 1e-10


def test_large_manual_entries_above_materiality_only_when_planted(journal, labels):
    e = entry_level(journal)
    amt = journal.groupby("entry_id")["debit"].sum()
    manual_big = set(e.index[(e["source"] == "manual") & (amt[e.index] >= 250000)])
    planted = set(labels.loc[labels["anomaly_type"] == "large_manual_period_end", "entry_id"])
    assert manual_big == planted


def test_volume_patterns(journal):
    e = entry_level(journal)
    by_month = e.groupby(e["posting_date"].dt.month).size()
    assert by_month.max() > 1.5 * by_month.min()  # seasonality
    sales = e[e["invoice_number"].fillna("").str.startswith("SI-") & (e["source"] == "automated")]
    last3 = [d for m in range(1, 13) for d in cal.business_days_in_month(2025, m)[-3:]]
    share = sales["document_date"].isin(pd.to_datetime(last3)).mean()
    assert share > 0.2  # month-end spike: ~14% of business days carry >20% of sales


def test_recurring_vendors_billed_monthly(journal, tables):
    rent = (
        tables["vendors"]
        .loc[tables["vendors"]["vendor_name"].str.contains("Real Estate"), "vendor_id"]
        .iloc[0]
    )
    inv = journal[
        (journal["vendor_id"] == rent) & (journal["credit"] > 0) & (journal["account"] == 2000)
    ]
    assert len(inv) == 12
    assert inv["credit"].nunique() == 1


def test_config_rejects_unknown_keys(tmp_path):
    import pytest
    from pydantic import ValidationError

    bad = tmp_path / "bad.yaml"
    bad.write_text(open(load_config.__globals__["DEFAULT_CONFIG_PATH"]).read() + "\nbogus: 1\n")
    with pytest.raises(ValidationError):
        load_config(bad)
