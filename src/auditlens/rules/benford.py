"""Benford's Law first-digit analysis per vendor.

Why auditors care: in naturally occurring financial data, about 30% of amounts start with 1 and
only about 5% with 9. Invented numbers rarely follow that pattern, so a vendor whose invoice
amounts deviate strongly deserves a closer look. The test needs enough invoices per vendor to be
meaningful, so small vendors are skipped (config: rules.benford.min_invoices).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from auditlens.dataset import Dataset
from auditlens.rules.base import combine, make_flags

FAMILY = "benford"
DIGITS = np.arange(1, 10)
EXPECTED_SHARE = np.log10(1 + 1 / DIGITS)


def first_digits(amounts: pd.Series) -> np.ndarray:
    """Leading non-zero digit of each positive amount."""
    a = amounts[amounts > 0].to_numpy(dtype=float)
    exponent = np.floor(np.log10(a))
    return np.minimum((a // 10**exponent).astype(int), 9)


def digit_counts(amounts: pd.Series) -> np.ndarray:
    """Counts of first digits 1..9."""
    return np.bincount(first_digits(amounts), minlength=10)[1:10]


def benford_table(ds: Dataset) -> pd.DataFrame:
    """Per-vendor Benford statistics for vendors with enough invoices.

    Columns: vendor_id, n, chi2, p_value, mad (mean absolute deviation of digit shares),
    and the observed share of each leading digit (d1..d9).
    """
    cfg = ds.cfg.rules.benford
    rows = []
    for vendor, g in ds.invoices.groupby("vendor_id"):
        if len(g) < cfg.min_invoices:
            continue
        obs = digit_counts(g["amount"])
        chi2, p = stats.chisquare(obs, EXPECTED_SHARE * obs.sum())
        row = {
            "vendor_id": vendor,
            "n": int(obs.sum()),
            "chi2": float(chi2),
            "p_value": float(p),
            "mad": float(np.abs(obs / obs.sum() - EXPECTED_SHARE).mean()),
        }
        row.update({f"d{d}": obs[d - 1] / obs.sum() for d in DIGITS})
        rows.append(row)
    cols = ["vendor_id", "n", "chi2", "p_value", "mad"] + [f"d{d}" for d in DIGITS]
    return pd.DataFrame(rows, columns=cols).sort_values("p_value").reset_index(drop=True)


def run(ds: Dataset) -> pd.DataFrame:
    """BENFORD_VENDOR: every invoice of a vendor whose first digits fail the chi-square test."""
    table = benford_table(ds)
    bad = table[table["p_value"] < ds.cfg.rules.benford.p_threshold]
    rows = []
    for r in bad.itertuples():
        inv = ds.invoices[ds.invoices["vendor_id"] == r.vendor_id]
        reason = (
            f"Vendor {r.vendor_id}: first digits of {r.n} invoices deviate from Benford's Law "
            f"(chi-square p = {r.p_value:.2e}, MAD = {r.mad:.3f})"
        )
        rows.append(make_flags(inv["entry_id"], FAMILY, "BENFORD_VENDOR", [reason] * len(inv)))
    return combine(rows)
