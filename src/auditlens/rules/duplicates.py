"""Duplicate payment tests.

Why auditors care: paying the same invoice twice is one of the most common and most expensive
control failures in accounts payable, and it is usually an honest mistake that nobody notices.
"""

from __future__ import annotations

import pandas as pd

from auditlens.dataset import Dataset
from auditlens.rules.base import combine, empty_flags, make_flags, money

FAMILY = "duplicates"


def base_invoice_number(numbers: pd.Series) -> pd.Series:
    """Invoice number without trailing re-key suffixes ('INV-001234-R' -> 'INV-001234')."""
    return numbers.fillna("").str.replace(r"\D+$", "", regex=True)


def _both_sides(pairs: pd.DataFrame, keys: list[str], code: str, text) -> pd.DataFrame:
    """Flag both entries of every pair, each pointing at the other."""
    if pairs.empty:
        return empty_flags()
    a = make_flags(pairs["entry_id"], FAMILY, code, text(pairs), pairs["entry_id_o"])

    def swap(c: str) -> str:
        if c in keys:
            return c
        return c[:-2] if c.endswith("_o") else c + "_o"

    swapped = pairs.rename(columns=swap)
    b = make_flags(swapped["entry_id"], FAMILY, code, text(swapped), swapped["entry_id_o"])
    return combine([a, b])


def _self_merge(p: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """All pairs of distinct payments sharing the keys (earlier id first)."""
    m = p.merge(p, on=keys, suffixes=("", "_o"))
    return m[m["entry_id"] < m["entry_id_o"]]


def same_invoice_paid_twice(ds: Dataset) -> pd.DataFrame:
    """DUP_SAME_INVOICE: two payments to one vendor referencing the same invoice number."""
    p = ds.payments[["entry_id", "vendor_id", "posting_date", "amount", "invoice_number"]].copy()
    p["base"] = base_invoice_number(p["invoice_number"])
    pairs = _self_merge(p[p["base"] != ""], ["vendor_id", "base"])

    def text(d: pd.DataFrame) -> list[str]:
        return [
            f"Invoice {r.base} of vendor {r.vendor_id} was paid more than once: "
            f"{money(r.amount)} on {r.posting_date:%Y-%m-%d} and {money(r.amount_o)} "
            f"on {r.posting_date_o:%Y-%m-%d} ({r.entry_id_o})"
            for r in d.itertuples()
        ]

    return _both_sides(pairs, ["vendor_id", "base"], "DUP_SAME_INVOICE", text)


def near_duplicate_amount(ds: Dataset) -> pd.DataFrame:
    """DUP_EXACT_AMOUNT / DUP_NEAR_AMOUNT: same vendor, same or near amount, a few days apart.

    An identical amount to the fils is strong evidence; "near" (within the tolerance) is weak
    because genuinely different invoices occasionally land close together by chance.
    """
    cfg = ds.cfg.rules.duplicates
    p = ds.payments[["entry_id", "vendor_id", "posting_date", "amount"]]
    p = p[p["amount"] >= cfg.min_amount]
    pairs = _self_merge(p, ["vendor_id"])
    days = (pairs["posting_date"] - pairs["posting_date_o"]).abs().dt.days
    diff = (pairs["amount"] - pairs["amount_o"]).abs()
    rel = diff / pairs[["amount", "amount_o"]].max(axis=1)
    pairs = pairs[(days <= cfg.window_days) & (rel <= cfg.amount_tolerance_pct / 100)]
    exact = pairs[(pairs["amount"] - pairs["amount_o"]).abs() < 0.0005]
    near = pairs.drop(exact.index)

    def text_for(kind: str):
        def text(d: pd.DataFrame) -> list[str]:
            return [
                f"Payment of {money(r.amount)} to vendor {r.vendor_id} on "
                f"{r.posting_date:%Y-%m-%d} {kind} {money(r.amount_o)} paid to the same vendor "
                f"on {r.posting_date_o:%Y-%m-%d} ({r.entry_id_o})"
                for r in d.itertuples()
            ]

        return text

    return combine(
        [
            _both_sides(exact, ["vendor_id"], "DUP_EXACT_AMOUNT", text_for("is identical to")),
            _both_sides(
                near,
                ["vendor_id"],
                "DUP_NEAR_AMOUNT",
                text_for(f"is within {cfg.amount_tolerance_pct}% of"),
            ),
        ]
    )


def run(ds: Dataset) -> pd.DataFrame:
    """All duplicate-payment tests."""
    return combine([same_invoice_paid_twice(ds), near_duplicate_amount(ds)])
