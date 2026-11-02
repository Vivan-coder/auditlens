"""Helpers for building tiny hand-made ledgers to unit-test individual rules."""

from __future__ import annotations

import pandas as pd

from auditlens.config import load_config
from auditlens.dataset import Dataset

PAY, CASH, EXP = 2000, 1000, 6300


def entry(
    eid: str,
    doc: str,
    post: str | None = None,
    *,
    debit: int = EXP,
    credit: int = PAY,
    amount: float = 1234.567,
    vendor: str | None = None,
    inv: str | None = None,
    created: str = "clerk1",
    approved: str | None = "acct1",
    source: str = "manual",
    period: str | None = None,
) -> list[dict]:
    """Two journal lines forming one balanced entry."""
    post = post or doc
    base = {
        "entry_id": eid,
        "document_date": doc,
        "posting_date": post,
        "description": f"test {eid}",
        "vendor_id": vendor,
        "created_by": created,
        "approved_by": approved,
        "source": source,
        "invoice_number": inv,
        "period": period or doc[:7],
    }
    return [
        {**base, "line_id": f"{eid}-01", "account": debit, "debit": amount, "credit": 0.0},
        {**base, "line_id": f"{eid}-02", "account": credit, "debit": 0.0, "credit": amount},
    ]


def invoice(eid: str, doc: str, vendor: str, num: int | str, amount: float = 1234.567, **kw):
    """A vendor invoice entry (Dr expense / Cr payables)."""
    inv = num if isinstance(num, str) else f"INV-{num:06d}"
    return entry(eid, doc, vendor=vendor, inv=inv, amount=amount, **kw)


def payment(eid: str, doc: str, vendor: str, inv: str, amount: float = 1234.567, **kw):
    """A vendor payment entry (Dr payables / Cr cash)."""
    return entry(eid, doc, debit=PAY, credit=CASH, vendor=vendor, inv=inv, amount=amount, **kw)


def make_ds(entries: list[list[dict]], **master: pd.DataFrame) -> Dataset:
    """Dataset from a list of entries (each a list of lines) plus optional master tables."""
    rows = [line for e in entries for line in e]
    journal = pd.DataFrame(rows)
    for col in ("document_date", "posting_date"):
        journal[col] = pd.to_datetime(journal[col])
    return Dataset(journal=journal, cfg=load_config(), **master)


def codes(flags: pd.DataFrame) -> dict[str, set[str]]:
    """{rule_code: set of entry ids} for easy assertions."""
    return {c: set(g["entry_id"]) for c, g in flags.groupby("rule_code")}
