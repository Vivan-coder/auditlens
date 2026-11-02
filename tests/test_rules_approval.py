"""Approval and segregation-of-duties rules."""

from __future__ import annotations

import pandas as pd

from auditlens.rules import approval
from helpers import codes, entry, invoice, make_ds

USERS = pd.DataFrame({"user_id": ["clerk1", "acct1"], "approval_limit": [0.0, 25000.0]})


def test_split_purchase_three_invoices_just_under_limit_flagged():
    ds = make_ds(
        [
            invoice("I1", "2025-04-06", "V1", 100, 24000),
            invoice("I2", "2025-04-07", "V1", 105, 23500),
            invoice("I3", "2025-04-08", "V1", 110, 24900),
        ]
    )
    flags = approval.split_below_limit(ds)
    assert set(flags["entry_id"]) == {"I1", "I2", "I3"}
    assert "just under the 25,000 approval limit" in flags.iloc[0]["reason"]


def test_split_not_flagged_for_two_invoices_other_creators_low_amounts_or_wide_spread():
    ds = make_ds(
        [
            invoice("A1", "2025-04-06", "V1", 100, 24000),
            invoice("A2", "2025-04-07", "V1", 105, 24100),  # only two
            invoice("B1", "2025-04-06", "V2", 100, 24000),
            invoice("B2", "2025-04-07", "V2", 105, 24100, created="clerk2"),  # different creator
            invoice("B3", "2025-04-08", "V2", 110, 24200, created="clerk3"),
            invoice("C1", "2025-04-06", "V3", 100, 20000),  # 80% of limit: not "just under"
            invoice("C2", "2025-04-07", "V3", 105, 20100),
            invoice("C3", "2025-04-08", "V3", 110, 20200),
            invoice("D1", "2025-01-06", "V4", 100, 24000),  # same vendor but months apart
            invoice("D2", "2025-03-06", "V4", 105, 24100),
            invoice("D3", "2025-05-08", "V4", 110, 24200),
        ]
    )
    assert approval.split_below_limit(ds).empty


def test_self_approved_only_flags_manual_entries_with_same_user():
    ds = make_ds(
        [
            entry("S1", "2025-04-06", created="acct1", approved="acct1"),
            entry("S2", "2025-04-06", created="clerk1", approved="acct1"),
            entry("S3", "2025-04-06", created="SYSTEM", approved=None, source="automated"),
        ]
    )
    assert set(approval.self_approved(ds)["entry_id"]) == {"S1"}


def test_no_approver_flags_manual_entries_without_one():
    ds = make_ds(
        [
            entry("N1", "2025-04-06", approved=None),
            entry("N2", "2025-04-06", approved="acct1"),
            entry("N3", "2025-04-06", approved=None, source="automated", created="SYSTEM"),
        ]
    )
    assert set(approval.no_approver(ds)["entry_id"]) == {"N1"}


def test_approver_over_limit():
    ds = make_ds(
        [
            entry("O1", "2025-04-06", amount=30000, approved="acct1"),
            entry("O2", "2025-04-06", amount=20000, approved="acct1"),
        ],
        users=USERS,
    )
    flags = approval.approver_over_limit(ds)
    assert set(flags["entry_id"]) == {"O1"}
    assert "exceeds the approval limit" in flags.iloc[0]["reason"]


def test_run_combines_codes():
    ds = make_ds([entry("S1", "2025-04-06", created="acct1", approved="acct1")], users=USERS)
    assert "SELF_APPROVED" in codes(approval.run(ds))
