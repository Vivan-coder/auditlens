"""Feature engineering for the Isolation Forest (one row per journal entry).

No labels and no generator internals are used: every feature is computed from the journal and,
where available, the user table. The audit-rule signals themselves (self-approval, near-limit
amounts, missing approver) are deliberately NOT features, so the model contributes an independent
view instead of repeating the rules.
"""

from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from auditlens import bh_calendar as cal
from auditlens.dataset import Dataset

FEATURE_LABELS = {
    "log_amount": "entry amount (log)",
    "n_lines": "number of lines",
    "is_round": "round amount",
    "account_amount_z": "amount vs. typical for the account",
    "has_vendor": "vendor-related entry",
    "vendor_count_log": "number of entries for the vendor (log)",
    "vendor_amount_z": "amount vs. typical for the vendor",
    "amount_to_vendor_median": "amount relative to the vendor's median",
    "twin_reldiff": "closeness of amount to a neighbouring vendor entry",
    "twin_gap_days": "days to that neighbouring vendor entry",
    "day_of_week": "day of week",
    "is_weekend": "posted on a weekend",
    "is_holiday": "posted on a public holiday",
    "day_of_month": "day of month",
    "days_to_month_end": "days before month end",
    "lag_days": "days between document and posting",
    "is_manual": "manually keyed",
    "user_account_rarity": "rarity of this user/account combination",
    "account_pair_rarity": "rarity of this debit/credit account pair",
    "approver_limit_ratio": "amount as a multiple of the approver's limit",
}
FEATURES = list(FEATURE_LABELS)


def _account_z(ds: Dataset) -> pd.Series:
    """Largest |z-score| of any line's log-amount versus the other lines on the same account."""
    j = ds.journal
    la = np.log(j[["debit", "credit"]].max(axis=1).clip(lower=0.01))
    g = la.groupby(j["account"])
    z = ((la - g.transform("mean")) / g.transform("std").replace(0, np.nan)).fillna(0).abs()
    return z.groupby(j["entry_id"]).max()


def _vendor_features(ds: Dataset) -> pd.DataFrame:
    """Vendor frequency and amount statistics, plus closeness to neighbouring vendor entries."""
    e = ds.entries
    v = e[e["vendor_id"].notna()].copy()
    v["la"] = np.log(v["amount"].clip(lower=0.01))
    g = v.groupby("vendor_id")["la"]
    count, std = g.transform("size"), g.transform("std")
    v["vendor_count_log"] = np.log1p(count)
    v["vendor_amount_z"] = ((v["la"] - g.transform("mean")) / std).where(
        (count >= 5) & (std > 0), 0.0
    )
    v["amount_to_vendor_median"] = v["la"] - np.log(
        v.groupby("vendor_id")["amount"].transform("median").clip(lower=0.01)
    )
    v = v.sort_values(["vendor_id", "is_payment", "posting_date", "entry_id"])
    grp = v.groupby(["vendor_id", "is_payment"])
    best_rel = pd.Series(1.0, index=v.index)
    best_gap = pd.Series(365.0, index=v.index)
    for shift in (1, -1):
        other_amt = grp["amount"].shift(shift)
        other_day = grp["posting_date"].shift(shift)
        rel = ((v["amount"] - other_amt).abs() / v["amount"].clip(lower=0.01)).fillna(1.0)
        gap = (v["posting_date"] - other_day).abs().dt.days.fillna(365).clip(upper=365)
        better = rel < best_rel
        best_rel, best_gap = rel.where(better, best_rel), gap.where(better, best_gap)
    v["twin_reldiff"], v["twin_gap_days"] = best_rel.clip(upper=1.0), best_gap
    v["has_vendor"] = 1.0
    cols = [
        "has_vendor",
        "vendor_count_log",
        "vendor_amount_z",
        "amount_to_vendor_median",
        "twin_reldiff",
        "twin_gap_days",
    ]
    out = v.set_index("entry_id")[cols].reindex(e["entry_id"])
    out["twin_reldiff"] = out["twin_reldiff"].fillna(1.0)
    out["twin_gap_days"] = out["twin_gap_days"].fillna(365.0)
    return out.fillna(0.0)


def _rarity(ds: Dataset) -> pd.DataFrame:
    """-log10 of how common this user/account and debit/credit pair are in the ledger."""
    e = ds.entries
    n = len(e)
    ua_rows = [
        (eid, u, a)
        for eid, u, dr, cr in zip(
            e["entry_id"], e["created_by"], e["debit_accounts"], e["credit_accounts"], strict=True
        )
        for a in set(dr) | set(cr)
    ]
    ua = pd.DataFrame(ua_rows, columns=["entry_id", "user", "account"])
    user_total = e.groupby("created_by")["entry_id"].nunique()
    ua["p"] = ua.groupby(["user", "account"])["entry_id"].transform("nunique") / ua["user"].map(
        user_total
    )
    pair_rows = [
        (eid, d, c)
        for eid, dr, cr in zip(
            e["entry_id"], e["debit_accounts"], e["credit_accounts"], strict=True
        )
        for d, c in product(dr, cr)
    ]
    pr = pd.DataFrame(pair_rows, columns=["entry_id", "debit", "credit"])
    pr["p"] = pr.groupby(["debit", "credit"])["entry_id"].transform("nunique") / n
    out = pd.DataFrame(index=e["entry_id"])
    out["user_account_rarity"] = (-np.log10(ua["p"])).groupby(ua["entry_id"]).max()
    out["account_pair_rarity"] = (-np.log10(pr["p"])).groupby(pr["entry_id"]).max()
    return out.fillna(0.0)


def build_features(ds: Dataset) -> pd.DataFrame:
    """Feature matrix indexed by entry_id (columns: FEATURES). Pure function of the journal."""
    e = ds.entries.set_index("entry_id")
    post = e["posting_date"]
    holidays = {d for y in post.dt.year.unique() for d in cal.bahrain_holidays(int(y))}
    f = pd.DataFrame(index=e.index)
    f["log_amount"] = np.log10(e["amount"].clip(lower=0.01))
    f["n_lines"] = e["n_lines"]
    f["is_round"] = ((e["amount"] >= 1000) & (e["amount"] % 1000 == 0)).astype(float)
    f["account_amount_z"] = _account_z(ds).reindex(e.index)
    f["day_of_week"] = post.dt.day_of_week
    f["is_weekend"] = post.dt.day_of_week.isin(cal.WEEKEND_WEEKDAYS).astype(float)
    f["is_holiday"] = post.dt.date.isin(holidays).astype(float)
    f["day_of_month"] = post.dt.day
    f["days_to_month_end"] = ((post + pd.offsets.MonthEnd(0)) - post).dt.days
    f["lag_days"] = (post - e["document_date"]).dt.days
    f["is_manual"] = (e["source"] == "manual").astype(float)
    f = f.join(_vendor_features(ds)).join(_rarity(ds))
    if not ds.users.empty:
        limit = e["approved_by"].map(ds.users.set_index("user_id")["approval_limit"])
        f["approver_limit_ratio"] = (e["amount"] / limit.where(limit > 0)).clip(upper=10).fillna(0)
    else:
        f["approver_limit_ratio"] = 0.0
    return f[FEATURES].astype(float).fillna(0.0)
