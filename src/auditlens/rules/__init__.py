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


def run_all_rules(ds: Dataset) -> pd.DataFrame:
    """Run every test family; one flags table (entry_id, family, rule_code, reason, ...)."""
    return combine([mod.run(ds) for mod in FAMILIES.values()])


__all__ = ["FAMILIES", "FLAG_COLUMNS", "run_all_rules"]
