"""Invoice-number sequence tests: gaps, out-of-order and repeated numbers.

Why auditors care: vendor invoices normally arrive in numerical order. A jump can mean documents
were removed or the numbering was invented; a lower number arriving later suggests a backdated or
fabricated invoice; a repeated number suggests a duplicate.
"""

from __future__ import annotations

import pandas as pd

from auditlens.dataset import Dataset
from auditlens.rules.base import combine, make_flags

FAMILY = "sequence"


def _numbered_invoices(ds: Dataset) -> pd.DataFrame:
    """Invoices with a numeric invoice number, sorted by vendor, document date, number."""
    inv = ds.invoices[["entry_id", "vendor_id", "document_date", "invoice_number"]].copy()
    inv["num"] = pd.to_numeric(inv["invoice_number"].str.extract(r"(\d+)\D*$")[0], errors="coerce")
    inv = inv.dropna(subset=["num"])
    return inv.sort_values(["vendor_id", "document_date", "num"]).reset_index(drop=True)


def gaps_and_order(ds: Dataset) -> pd.DataFrame:
    """INVOICE_GAP / INVOICE_OUT_OF_ORDER, per vendor in document-date order."""
    inv = _numbered_invoices(ds)
    inv["prev_max"] = inv.groupby("vendor_id")["num"].transform(lambda s: s.cummax().shift())
    inv["step"] = inv["num"] - inv["prev_max"]
    gap = inv[inv["step"] > ds.cfg.rules.invoice_sequence.max_gap]
    ooo = inv[inv["step"] < 0]
    return combine(
        [
            make_flags(
                gap["entry_id"],
                FAMILY,
                "INVOICE_GAP",
                [
                    f"Invoice number jumps by {int(s)} from the previous invoice of vendor {v} "
                    f"(possible missing invoices)"
                    for s, v in zip(gap["step"], gap["vendor_id"], strict=True)
                ],
            ),
            make_flags(
                ooo["entry_id"],
                FAMILY,
                "INVOICE_OUT_OF_ORDER",
                [
                    f"Invoice {n} is lower than invoice {int(p)} already received from vendor {v}"
                    for n, p, v in zip(
                        ooo["invoice_number"], ooo["prev_max"], ooo["vendor_id"], strict=True
                    )
                ],
            ),
        ]
    )


def repeated_numbers(ds: Dataset) -> pd.DataFrame:
    """DUPLICATE_INVOICE_NUMBER: the same vendor invoice number booked twice."""
    inv = _numbered_invoices(ds)
    dup = inv[inv.duplicated(["vendor_id", "num"], keep=False)]
    reasons = [
        f"Invoice number {n} was booked more than once for vendor {v}"
        for n, v in zip(dup["invoice_number"], dup["vendor_id"], strict=True)
    ]
    return make_flags(dup["entry_id"], FAMILY, "DUPLICATE_INVOICE_NUMBER", reasons)


def run(ds: Dataset) -> pd.DataFrame:
    """All sequence tests."""
    return combine([gaps_and_order(ds), repeated_numbers(ds)])
