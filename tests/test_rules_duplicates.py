"""Duplicate payment rules: catch the planted case, leave the clean case alone."""

from __future__ import annotations

from auditlens.rules import duplicates
from helpers import codes, make_ds, payment


def test_same_invoice_paid_twice_flags_both_with_related_ids():
    ds = make_ds(
        [
            payment("P1", "2025-05-04", "V1", "INV-000100", 5000),
            payment("P2", "2025-05-06", "V1", "INV-000100-R", 5000),
        ]
    )
    flags = duplicates.run(ds)
    assert codes(flags)["DUP_SAME_INVOICE"] == {"P1", "P2"}
    rel = flags[flags.rule_code == "DUP_SAME_INVOICE"].set_index("entry_id")["related_entry_id"]
    assert rel["P1"] == "P2" and rel["P2"] == "P1"
    assert "paid more than once" in flags.iloc[0]["reason"]


def test_exact_amount_within_window_flagged_even_with_new_invoice_number():
    ds = make_ds(
        [
            payment("P1", "2025-05-04", "V1", "INV-000100", 8000.25),
            payment("P2", "2025-05-08", "V1", "INV-000555", 8000.25),
        ]
    )
    c = codes(duplicates.run(ds))
    assert c["DUP_EXACT_AMOUNT"] == {"P1", "P2"}
    assert "DUP_SAME_INVOICE" not in c


def test_near_amount_flagged_as_weak_signal_only_inside_tolerance():
    near = make_ds(
        [
            payment("P1", "2025-05-04", "V1", "INV-000100", 10000),
            payment("P2", "2025-05-06", "V1", "INV-000555", 10030),  # 0.3% apart
        ]
    )
    assert codes(duplicates.run(near))["DUP_NEAR_AMOUNT"] == {"P1", "P2"}
    far = make_ds(
        [
            payment("P1", "2025-05-04", "V1", "INV-000100", 10000),
            payment("P2", "2025-05-06", "V1", "INV-000555", 10200),  # 2% apart
        ]
    )
    assert duplicates.run(far).empty


def test_clean_payments_not_flagged():
    ds = make_ds(
        [
            payment("P1", "2025-05-04", "V1", "INV-000100", 5000),
            payment("P2", "2025-06-20", "V1", "INV-000101", 5000),  # same amount, 47 days apart
            payment("P3", "2025-05-05", "V2", "INV-000100", 5000),  # other vendor
            payment("P4", "2025-05-05", "V1", "INV-000300", 7777),  # different amount
        ]
    )
    assert duplicates.run(ds).empty
