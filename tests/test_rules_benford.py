"""Benford first-digit rule."""

from __future__ import annotations

import numpy as np
import pandas as pd

from auditlens.rules import benford
from helpers import invoice, make_ds


def _vendor_invoices(vendor: str, amounts: np.ndarray) -> list:
    return [
        invoice(f"{vendor}-{i}", "2025-04-06", vendor, 100 + 8 * i, float(a))
        for i, a in enumerate(amounts)
    ]


def test_first_digit_extraction():
    s = pd.Series([0.0123, 987.0, 1000.0, 5.5, 19999.99, 0.0])
    assert list(benford.first_digits(s)) == [1, 9, 1, 5, 1]


def test_conforming_vendor_passes_and_fabricated_vendor_fails():
    rng = np.random.default_rng(1)
    natural = np.round(10 ** rng.uniform(2, 5, 300), 3)  # log-uniform = Benford
    invented = np.round(rng.uniform(7000, 9990, 80), 3)  # digits 7-9 only
    ds = make_ds([*_vendor_invoices("GOOD", natural), *_vendor_invoices("BAD", invented)])
    table = benford.benford_table(ds).set_index("vendor_id")
    assert table.loc["GOOD", "p_value"] > 0.01
    assert table.loc["BAD", "p_value"] < 1e-10
    flags = benford.run(ds)
    assert set(flags["entry_id"]) == {f"BAD-{i}" for i in range(80)}
    assert "deviate from Benford" in flags.iloc[0]["reason"]


def test_vendor_below_minimum_sample_is_skipped_not_flagged():
    ds = make_ds(_vendor_invoices("TINY", np.full(20, 9000.0)))  # blatantly non-Benford but n=20
    assert benford.benford_table(ds).empty
    assert benford.run(ds).empty


def test_table_reports_observed_digit_shares():
    rng = np.random.default_rng(2)
    ds = make_ds(_vendor_invoices("V", np.round(10 ** rng.uniform(2, 5, 200), 3)))
    row = benford.benford_table(ds).iloc[0]
    assert abs(sum(row[f"d{d}"] for d in range(1, 10)) - 1) < 1e-9
    assert row["n"] == 200
