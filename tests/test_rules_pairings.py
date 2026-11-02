"""Unusual account pairing and rare user-account rules."""

from __future__ import annotations

from auditlens.rules import pairings
from helpers import entry, make_ds


def _normal(n: int, user: str = "acct1") -> list:
    return [entry(f"N{i}", "2025-04-06", debit=6100, credit=2000, created=user) for i in range(n)]


def test_rare_account_pair_flagged_common_pair_not():
    ds = make_ds([*_normal(60), entry("ODD", "2025-04-06", debit=8100, credit=1000)])
    flags = pairings.rare_pairs(ds)
    assert set(flags["entry_id"]) == {"ODD"}
    assert "Debit 8100 / credit 1000" in flags.iloc[0]["reason"]


def test_pair_seen_more_often_than_threshold_is_not_rare():
    odd = [entry(f"O{i}", "2025-04-06", debit=8100, credit=1000) for i in range(4)]
    ds = make_ds([*_normal(60), *odd])  # 4 > rare_pair_max_count (3)
    assert pairings.rare_pairs(ds).empty


def test_rare_user_account_flagged_for_user_with_history():
    ds = make_ds([*_normal(80), entry("X", "2025-04-06", debit=3100, credit=1000, created="acct1")])
    flags = pairings.rare_user_accounts(ds)
    assert set(flags["entry_id"]) == {"X"}
    assert "unusual for this user" in flags.iloc[0]["reason"]


def test_user_without_history_or_automated_entries_not_judged():
    newbie = make_ds(
        [
            *_normal(10, "newbie"),
            entry("X", "2025-04-06", debit=3100, credit=1000, created="newbie"),
        ]
    )
    assert pairings.rare_user_accounts(newbie).empty
    auto = [
        entry(
            f"A{i}",
            "2025-04-06",
            debit=6100,
            credit=2000,
            created="SYSTEM",
            approved=None,
            source="automated",
        )
        for i in range(80)
    ]
    odd = entry(
        "Y",
        "2025-04-06",
        debit=3100,
        credit=1000,
        created="SYSTEM",
        approved=None,
        source="automated",
    )
    assert pairings.rare_user_accounts(make_ds([*auto, odd])).empty
