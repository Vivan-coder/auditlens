"""Rule-based audit tests. One module per test family; each exposes run(Dataset) -> flags."""

from __future__ import annotations

import pandas as pd

from auditlens.dataset import Dataset
from auditlens.rules import (
    amounts,
    approval,
    benford,
    duplicates,
    pairings,
    sequence,
    timing,
    vendors,
)
from auditlens.rules.base import FLAG_COLUMNS, combine

FAMILIES = {
    "duplicates": duplicates,
    "approval": approval,
    "timing": timing,
    "amounts": amounts,
    "vendors": vendors,
    "sequence": sequence,
    "benford": benford,
    "pairings": pairings,
}


RULE_CODES = [
    "DUP_SAME_INVOICE",
    "DUP_EXACT_AMOUNT",
    "DUP_NEAR_AMOUNT",
    "SPLIT_BELOW_LIMIT",
    "SELF_APPROVED",
    "NO_APPROVER",
    "APPROVER_OVER_LIMIT",
    "WEEKEND_POSTING",
    "HOLIDAY_POSTING",
    "POST_CLOSE_POSTING",
    "BACKDATED_POSTING",
    "ROUND_AMOUNT",
    "LARGE_MANUAL_PERIOD_END",
    "LARGE_MANUAL",
    "GHOST_VENDOR_BANK",
    "GHOST_VENDOR_ADDRESS",
    "BANK_CHANGE_LARGE_PAYMENT",
    "INVOICE_GAP",
    "INVOICE_OUT_OF_ORDER",
    "DUPLICATE_INVOICE_NUMBER",
    "BENFORD_VENDOR",
    "RARE_ACCOUNT_PAIR",
    "RARE_USER_ACCOUNT",
]


def run_all_rules(ds: Dataset) -> pd.DataFrame:
    """Run every test family; one flags table (entry_id, family, rule_code, reason, ...)."""
    return combine([mod.run(ds) for mod in FAMILIES.values()])


__all__ = ["FAMILIES", "FLAG_COLUMNS", "RULE_CODES", "run_all_rules"]
