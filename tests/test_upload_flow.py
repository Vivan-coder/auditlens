"""The upload path end to end without the UI: CSV text -> mapping -> validation -> analysis."""

from __future__ import annotations

import pandas as pd
import pytest
from dashboard.queue import filtered_queue
from dashboard.state import make_uploaded_bundle
from dashboard.upload import read_csv_bytes

from auditlens.config import get_config
from auditlens.schema import apply_mapping, suggest_mapping, validate_journal


@pytest.fixture(scope="module")
def foreign_csv(journal) -> bytes:
    """A slice of the journal exported with someone else's column names and formats."""
    keep = journal["entry_id"].drop_duplicates().iloc[:3000]
    j = journal[journal["entry_id"].isin(keep)].copy()
    out = pd.DataFrame(
        {
            "Journal ID": j["entry_id"],
            "GL Date": j["posting_date"].dt.strftime("%d/%m/%Y"),
            "Invoice Date": j["document_date"].dt.strftime("%d/%m/%Y"),
            "GL Account": j["account"],
            "Dr": j["debit"].map(lambda x: f"{x:,.3f}" if x else ""),
            "Cr": j["credit"].map(lambda x: f"{x:,.3f}" if x else ""),
            "Memo": j["description"],
            "Supplier": j["vendor_id"],
            "Prepared By": j["created_by"],
            "Approver": j["approved_by"],
            "Entry Type": j["source"].map({"manual": "Manual", "automated": "System"}),
            "Reference": j["invoice_number"],
        }
    )
    return out.to_csv(index=False).encode()


def test_foreign_file_maps_validates_and_analyses(foreign_csv):
    raw = read_csv_bytes(foreign_csv)
    mapping = suggest_mapping(list(raw.columns))
    assert all(mapping[f] for f in ("entry_id", "posting_date", "account", "debit", "credit"))
    assert mapping["vendor_id"] == "Supplier" and mapping["source"] == "Entry Type"
    res = validate_journal(apply_mapping(raw, mapping), dayfirst=True)
    assert res.ok, res.errors[:3]
    bundle = make_uploaded_bundle("test.csv", res.journal)
    assert bundle.labels is None and bundle.evaluation() is None
    assert len(bundle.queue) > 0 and (bundle.queue["reasons"].str.len() > 0).all()
    assert bundle.dataset.vendors.empty  # master-data rules skipped, the rest ran
    assert set(bundle.result.rule_flags["family"]) & {"timing", "approval", "pairings"}


def test_wrong_date_format_is_caught_with_row_numbers(foreign_csv):
    raw = read_csv_bytes(foreign_csv)
    res = validate_journal(apply_mapping(raw, suggest_mapping(list(raw.columns))), dayfirst=False)
    assert not res.ok  # 13/03/2025 is not a valid month-first date
    assert res.errors[0]["column"] in {"posting_date", "document_date"}
    assert isinstance(res.errors[0]["row"], int)


def test_queue_filter_function_combines_conditions(journal, cfg):
    from dashboard.state import Bundle

    from auditlens.dataset import Dataset
    from auditlens.pipeline import analyse

    ds = Dataset(journal=journal, cfg=get_config())
    b = Bundle("t", ds, analyse(ds, cfg))
    q = b.queue
    base = {
        "min_risk": 0,
        "codes": [],
        "status": [],
        "users": [],
        "vendors": [],
        "accounts": [],
        "dates": None,
        "amt_min": 0.0,
        "amt_max": float(q["amount"].max()),
    }
    assert len(filtered_queue(b, q, base)) == len(q)
    code = q["rule_codes"].iloc[0].split(";")[0]
    only = filtered_queue(b, q, {**base, "codes": [code]})
    assert 0 < len(only) <= len(q) and only["rule_codes"].str.contains(code).all()
    hi = filtered_queue(b, q, {**base, "min_risk": 50})
    assert (hi["risk_score"] >= 50).all() and len(hi) < len(q)
    user = q["created_by"].iloc[0]
    assert set(filtered_queue(b, q, {**base, "users": [user]})["created_by"]) == {user}
    acct = next(iter(b.entry_accounts()[q["entry_id"].iloc[0]]))
    sub = filtered_queue(b, q, {**base, "accounts": [acct]})
    assert q["entry_id"].iloc[0] in set(sub["entry_id"])
