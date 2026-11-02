"""Amount tests: suspiciously round figures and large manual entries near period end.

Why auditors care: real transactions produce messy amounts; round figures suggest estimates or
fabrication. Large manual journals at period end are a recognised fraud and earnings-management
risk (management override of controls), so they are always examined.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from auditlens import bh_calendar as cal
from auditlens.dataset import Dataset
from auditlens.rules.base import combine, make_flags, money

FAMILY = "amounts"


def round_amounts(ds: Dataset) -> pd.DataFrame:
    """ROUND_AMOUNT: a manual entry for an exact multiple (e.g. 1,000) above a minimum size."""
    cfg = ds.cfg.rules.round_amount
    e = ds.entries[ds.entries["source"].isin(cfg.sources)]
    half = cfg.multiple / 2
    is_round = (e["amount"] >= cfg.min_amount) & np.isclose(
        (e["amount"] + half) % cfg.multiple - half, 0, atol=1e-6
    )
    repeats = e.groupby(["vendor_id", "amount"])["entry_id"].transform("size")
    contract = e["vendor_id"].notna() & (repeats >= cfg.recurring_repeat_exempt)
    hit = e[is_round & ~contract]
    reasons = [f"Amount {money(a)} is an exact multiple of {cfg.multiple:,}" for a in hit["amount"]]
    return make_flags(hit["entry_id"], FAMILY, "ROUND_AMOUNT", reasons)


def _period_end_days(ds: Dataset, years: list[int]) -> set:
    """The last N business days of every month (N from config)."""
    n = ds.cfg.rules.materiality.period_end_business_days
    return {d for y in years for m in range(1, 13) for d in cal.business_days_in_month(y, m)[-n:]}


def large_manual(ds: Dataset) -> pd.DataFrame:
    """LARGE_MANUAL_PERIOD_END / LARGE_MANUAL: manual entries at or above materiality."""
    cfg = ds.cfg.rules.materiality
    e = ds.entries
    e = e[e["source"].isin(cfg.sources) & (e["amount"] >= cfg.amount)]
    years = sorted(int(y) for y in ds.entries["posting_date"].dt.year.unique())
    near_end = e["posting_date"].dt.date.isin(_period_end_days(ds, years))
    a, b = e[near_end], e[~near_end]
    return combine(
        [
            make_flags(
                a["entry_id"],
                FAMILY,
                "LARGE_MANUAL_PERIOD_END",
                [
                    f"Manual entry of {money(x)} (materiality {cfg.amount:,.0f}) posted "
                    f"{d:%Y-%m-%d}, in the last {cfg.period_end_business_days} business days "
                    f"of the month"
                    for x, d in zip(a["amount"], a["posting_date"], strict=True)
                ],
            ),
            make_flags(
                b["entry_id"],
                FAMILY,
                "LARGE_MANUAL",
                [
                    f"Manual entry of {money(x)} is above materiality ({cfg.amount:,.0f})"
                    for x in b["amount"]
                ],
            ),
        ]
    )


def run(ds: Dataset) -> pd.DataFrame:
    """All amount tests."""
    return combine([round_amounts(ds), large_manual(ds)])
