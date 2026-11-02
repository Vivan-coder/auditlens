"""Amount rules: round numbers and large manual period-end entries."""

from __future__ import annotations

from auditlens.rules import amounts
from helpers import codes, entry, invoice, make_ds


def test_round_manual_amount_flagged_and_messy_amount_not():
    ds = make_ds(
        [
            entry("R1", "2025-04-06", amount=20000),
            entry("R2", "2025-04-06", amount=20000.5),
            entry("R3", "2025-04-06", amount=4000),  # below the minimum size
            entry(
                "R4",
                "2025-04-06",
                amount=20000,
                source="automated",
                created="SYSTEM",
                approved=None,
            ),
        ]
    )
    flags = amounts.round_amounts(ds)
    assert set(flags["entry_id"]) == {"R1"}
    assert "exact multiple of 1,000" in flags.iloc[0]["reason"]


def test_recurring_contract_amount_is_exempt():
    rent = [invoice(f"RENT{m}", f"2025-{m:02d}-02", "V9", 100 + m, 10000) for m in range(1, 8)]
    ds = make_ds([*rent, entry("ONEOFF", "2025-04-06", amount=10000, vendor="V8")])
    assert set(amounts.round_amounts(ds)["entry_id"]) == {"ONEOFF"}


def test_large_manual_entry_at_period_end_is_flagged_with_specific_code():
    ds = make_ds(
        [
            entry("END", "2025-03-27", amount=300123.456),  # last business days of March
            entry("MID", "2025-03-12", amount=300123.456),
            entry("SMALL", "2025-03-27", amount=100123.456),
            entry(
                "AUTO",
                "2025-03-27",
                amount=900123.456,
                source="automated",
                created="SYSTEM",
                approved=None,
            ),
        ]
    )
    c = codes(amounts.large_manual(ds))
    assert c["LARGE_MANUAL_PERIOD_END"] == {"END"}
    assert c["LARGE_MANUAL"] == {"MID"}
    assert "SMALL" not in c.get("LARGE_MANUAL", set()) | c["LARGE_MANUAL_PERIOD_END"]
