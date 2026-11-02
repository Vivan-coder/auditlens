"""Vendor master-data tests: ghost vendors and bank-account changes.

Why auditors care: fictitious vendors (often set up with an employee's own bank account) and
hijacked bank details are the standard accounts-payable fraud schemes.
"""

from __future__ import annotations

import pandas as pd

from auditlens.dataset import Dataset
from auditlens.rules.base import combine, empty_flags, make_flags, money

FAMILY = "vendors"


def _norm(s: pd.Series) -> pd.Series:
    """Normalise text for matching (case, spacing, punctuation)."""
    return s.fillna("").str.lower().str.replace(r"[^a-z0-9]", "", regex=True)


def ghost_vendors(ds: Dataset) -> pd.DataFrame:
    """GHOST_VENDOR_BANK / GHOST_VENDOR_ADDRESS: a vendor shares details with an employee.

    Every entry posted to the vendor is flagged, because the risk attaches to the vendor.
    """
    if ds.vendors.empty or ds.employees.empty:
        return empty_flags()
    emp = ds.employees.assign(
        bank=_norm(ds.employees["bank_account"]), addr=_norm(ds.employees["address"])
    )
    ven = ds.vendors.assign(
        bank=_norm(ds.vendors["bank_account"]), addr=_norm(ds.vendors["address"])
    )
    rows = []
    for col, code, label in [
        ("bank", "GHOST_VENDOR_BANK", "bank account"),
        ("addr", "GHOST_VENDOR_ADDRESS", "address"),
    ]:
        m = ven[ven[col] != ""].merge(emp[emp[col] != ""], on=col, suffixes=("", "_emp"))
        for r in m.itertuples():
            hit = ds.entries[ds.entries["vendor_id"] == r.vendor_id]
            reason = (
                f"Vendor {r.vendor_id} ({r.vendor_name}) shares its {label} "
                f"with employee {r.employee_id}"
            )
            rows.append(make_flags(hit["entry_id"], FAMILY, code, [reason] * len(hit)))
    return combine(rows)


def bank_change_large_payment(ds: Dataset) -> pd.DataFrame:
    """BANK_CHANGE_LARGE_PAYMENT: a large payment soon after the vendor's bank details changed."""
    if ds.bank_changes.empty:
        return empty_flags()
    cfg = ds.cfg.rules.bank_change
    pay = ds.payments[["entry_id", "vendor_id", "posting_date", "amount"]]
    median = pay.groupby("vendor_id")["amount"].median().rename("median")
    m = pay.merge(ds.bank_changes[["vendor_id", "change_date"]], on="vendor_id")
    m = m.merge(median, on="vendor_id")
    days = (m["posting_date"] - m["change_date"]).dt.days
    big = (m["amount"] >= cfg.min_amount) & (m["amount"] >= cfg.median_multiple * m["median"])
    hit = m[days.between(0, cfg.window_days) & big]
    reasons = [
        f"Payment of {money(r.amount)} to vendor {r.vendor_id} "
        f"{(r.posting_date - r.change_date).days} days after its bank account changed on "
        f"{r.change_date:%Y-%m-%d} (vendor median payment {money(r.median)})"
        for r in hit.itertuples()
    ]
    return make_flags(hit["entry_id"], FAMILY, "BANK_CHANGE_LARGE_PAYMENT", reasons)


def run(ds: Dataset) -> pd.DataFrame:
    """All vendor tests."""
    return combine([ghost_vendors(ds), bank_change_large_payment(ds)])
