"""Approval and segregation-of-duties tests.

Why auditors care: the approval hierarchy is the main preventive control over spending. Splitting a
purchase to stay under a limit, or approving your own entry, defeats it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from auditlens.dataset import Dataset
from auditlens.rules.base import combine, empty_flags, make_flags, money

FAMILY = "approval"


def approval_tiers(ds: Dataset) -> list[float]:
    """Approval limits above zero, from config.yaml (the roles' limits)."""
    return sorted(r.approval_limit for r in ds.cfg.roles.values() if r.approval_limit > 0)


def _near_limit(amount: pd.Series, tiers: list[float], low_pct: float) -> pd.Series:
    """The limit an amount sits just under (low_pct% <= amount < limit), else NaN."""
    out = pd.Series(np.nan, index=amount.index)
    for t in tiers:
        out[(amount >= t * low_pct / 100) & (amount < t)] = t
    return out


def split_below_limit(ds: Dataset) -> pd.DataFrame:
    """SPLIT_BELOW_LIMIT: several near-limit invoices, same vendor and creator, close in time."""
    cfg = ds.cfg.rules.split_purchase
    inv = ds.invoices[["entry_id", "vendor_id", "created_by", "posting_date", "amount"]].copy()
    inv["limit"] = _near_limit(inv["amount"], approval_tiers(ds), cfg.band_low_pct)
    cand = inv.dropna(subset=["limit"]).sort_values("posting_date")
    rows: list[pd.DataFrame] = []
    for (vendor, creator), g in cand.groupby(["vendor_id", "created_by"]):
        days = g["posting_date"].to_numpy().astype("datetime64[D]")
        hit = np.zeros(len(g), dtype=bool)
        for i in range(len(g)):
            j = np.searchsorted(days, days[i] + np.timedelta64(cfg.window_days, "D"), side="right")
            if j - i >= cfg.min_count:
                hit[i:j] = True
        if hit.any():
            sel = g[hit]
            total = money(sel["amount"].sum())
            reasons = [
                f"{money(r.amount)} is just under the {r.limit:,.0f} approval limit; "
                f"{len(sel)} such invoices from {creator} to vendor {vendor} within "
                f"{cfg.window_days} days total {total}"
                for r in sel.itertuples()
            ]
            rows.append(make_flags(sel["entry_id"], FAMILY, "SPLIT_BELOW_LIMIT", reasons))
    return combine(rows)


def self_approved(ds: Dataset) -> pd.DataFrame:
    """SELF_APPROVED: the user who created a manual entry also approved it."""
    e = ds.entries
    hit = e[(e["source"] == "manual") & (e["created_by"] == e["approved_by"])]
    reasons = [f"Created and approved by the same user ({u})" for u in hit["created_by"]]
    return make_flags(hit["entry_id"], FAMILY, "SELF_APPROVED", reasons)


def no_approver(ds: Dataset) -> pd.DataFrame:
    """NO_APPROVER: a manual entry with no approver recorded."""
    e = ds.entries
    hit = e[(e["source"] == "manual") & e["approved_by"].isna()]
    reasons = ["Manual entry has no approver recorded"] * len(hit)
    return make_flags(hit["entry_id"], FAMILY, "NO_APPROVER", reasons)


def approver_over_limit(ds: Dataset) -> pd.DataFrame:
    """APPROVER_OVER_LIMIT: entry amount exceeds the approving user's authority."""
    if ds.users.empty:
        return empty_flags()
    limits = ds.users.set_index("user_id")["approval_limit"]
    e = ds.entries[ds.entries["approved_by"].notna()]
    lim = e["approved_by"].map(limits)
    hit = e[lim.notna() & (e["amount"] > lim)]
    reasons = [
        f"Amount {money(r.amount)} exceeds the approval limit of {r.approved_by} "
        f"({limits[r.approved_by]:,.0f})"
        for r in hit.itertuples()
    ]
    return make_flags(hit["entry_id"], FAMILY, "APPROVER_OVER_LIMIT", reasons)


def run(ds: Dataset) -> pd.DataFrame:
    """All approval tests."""
    return combine(
        [split_below_limit(ds), self_approved(ds), no_approver(ds), approver_over_limit(ds)]
    )
