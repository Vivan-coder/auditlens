"""Common result format for every audit test."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from auditlens.dataset import Dataset

FLAG_COLUMNS = ["entry_id", "family", "rule_code", "reason", "related_entry_id"]

Rule = Callable[[Dataset], pd.DataFrame]


def empty_flags() -> pd.DataFrame:
    """A flags table with no rows."""
    return pd.DataFrame(columns=FLAG_COLUMNS)


def make_flags(
    entry_ids: pd.Series | list,
    family: str,
    rule_code: str,
    reasons: pd.Series | list[str],
    related: pd.Series | list | None = None,
) -> pd.DataFrame:
    """Build flag rows. Every flag carries a machine code and a human-readable reason."""
    df = pd.DataFrame(
        {
            "entry_id": list(entry_ids),
            "family": family,
            "rule_code": rule_code,
            "reason": list(reasons),
            "related_entry_id": list(related) if related is not None else None,
        }
    )
    return df[FLAG_COLUMNS]


def combine(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate flag tables, dropping duplicates of (entry, rule code)."""
    frames = [f for f in frames if len(f)]
    if not frames:
        return empty_flags()
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates(["entry_id", "rule_code"]).reset_index(drop=True)


def money(x: float) -> str:
    """Format an amount for a reason string."""
    return f"{x:,.3f}"
