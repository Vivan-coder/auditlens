"""Vendor master-data rules: ghost vendors and bank changes."""

from __future__ import annotations

import pandas as pd

from auditlens.rules import vendors
from helpers import codes, invoice, make_ds, payment

EMPLOYEES = pd.DataFrame(
    {
        "employee_id": ["E1", "E2"],
        "address": ["Flat 1, Road 2, Manama", "Flat 9, Road 9, Riffa"],
        "bank_account": ["BH11AAAA00000000000001", "BH22BBBB00000000000002"],
    }
)
VENDORS = pd.DataFrame(
    {
        "vendor_id": ["V1", "V2", "V3"],
        "vendor_name": ["Ghost Bank Co", "Ghost Address Co", "Honest Co"],
        "address": ["Other St 1", "flat 1,  road 2, MANAMA", "Elsewhere 7"],
        "bank_account": [
            "bh11aaaa00000000000001",
            "BH99ZZZZ00000000000009",
            "BH33CCCC00000000000003",
        ],
    }
)


def test_ghost_vendor_sharing_bank_account_or_address_flags_all_its_entries():
    ds = make_ds(
        [
            invoice("G1", "2025-04-06", "V1", 100),
            payment("G2", "2025-05-06", "V1", "INV-000100"),
            invoice("A1", "2025-04-06", "V2", 100),
            invoice("H1", "2025-04-06", "V3", 100),
        ],
        vendors=VENDORS,
        employees=EMPLOYEES,
    )
    c = codes(vendors.ghost_vendors(ds))
    assert c["GHOST_VENDOR_BANK"] == {"G1", "G2"}  # case-insensitive match
    assert c["GHOST_VENDOR_ADDRESS"] == {"A1"}  # whitespace/case/punctuation-insensitive
    flags = vendors.ghost_vendors(ds)
    assert "shares its bank account with employee E1" in flags.iloc[0]["reason"]


def test_ghost_rule_skips_without_master_data():
    assert vendors.ghost_vendors(make_ds([invoice("I", "2025-04-06", "V1", 1)])).empty


def _bank_ds(pay_date: str, amount: float):
    changes = pd.DataFrame({"vendor_id": ["V1"], "change_date": pd.to_datetime(["2025-06-01"])})
    history = [
        payment(f"H{i}", f"2025-0{i}-10", "V1", f"INV-00000{i}", 2000.0) for i in range(1, 5)
    ]
    return make_ds(
        [*history, payment("TARGET", pay_date, "V1", "INV-000099", amount)], bank_changes=changes
    )


def test_large_payment_soon_after_bank_change_flagged():
    flags = vendors.bank_change_large_payment(_bank_ds("2025-06-05", 60000))
    assert set(flags["entry_id"]) == {"TARGET"}
    assert "4 days after its bank account changed" in flags.iloc[0]["reason"]


def test_small_or_late_payment_after_bank_change_not_flagged():
    assert vendors.bank_change_large_payment(_bank_ds("2025-06-05", 2500)).empty  # small
    assert vendors.bank_change_large_payment(_bank_ds("2025-07-20", 60000)).empty  # 49 days later
    assert vendors.bank_change_large_payment(_bank_ds("2025-05-30", 60000)).empty  # before change
