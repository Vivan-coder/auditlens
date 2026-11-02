"""Account-usage tests: unusual debit/credit pairings and rare user-account combinations.

Why auditors care: a journal that moves value between accounts that are never otherwise linked
(e.g. Suspense paid from Bank), or a user posting to an account outside their normal duties, are
typical signs of error or override. Rarity is judged against the ledger's own history.
"""

from __future__ import annotations

from itertools import product

import pandas as pd

from auditlens.dataset import Dataset
from auditlens.rules.base import combine, make_flags

FAMILY = "pairings"


def rare_pairs(ds: Dataset) -> pd.DataFrame:
    """RARE_ACCOUNT_PAIR: a debit/credit account pair seen only a handful of times all year."""
    e = ds.entries
    rows = [
        (eid, d, c)
        for eid, dr, cr in zip(
            e["entry_id"], e["debit_accounts"], e["credit_accounts"], strict=True
        )
        for d, c in product(dr, cr)
    ]
    pairs = pd.DataFrame(rows, columns=["entry_id", "debit", "credit"])
    pairs["n"] = pairs.groupby(["debit", "credit"])["entry_id"].transform("nunique")
    rare = pairs[pairs["n"] <= ds.cfg.rules.pairings.rare_pair_max_count]
    rare = rare.drop_duplicates("entry_id")
    reasons = [
        f"Debit {d} / credit {c} is an unusual account pairing: seen in only {n} entries all year"
        for d, c, n in zip(rare["debit"], rare["credit"], rare["n"], strict=True)
    ]
    return make_flags(rare["entry_id"], FAMILY, "RARE_ACCOUNT_PAIR", reasons)


def rare_user_accounts(ds: Dataset) -> pd.DataFrame:
    """RARE_USER_ACCOUNT: a user with a real history posts to an account they almost never use."""
    cfg = ds.cfg.rules.pairings
    e = ds.entries[ds.entries["source"] == "manual"]
    rows = [
        (eid, user, acct)
        for eid, user, dr, cr in zip(
            e["entry_id"], e["created_by"], e["debit_accounts"], e["credit_accounts"], strict=True
        )
        for acct in set(dr) | set(cr)
    ]
    ua = pd.DataFrame(rows, columns=["entry_id", "user", "account"])
    ua["count"] = ua.groupby(["user", "account"])["entry_id"].transform("nunique")
    ua["user_total"] = ua["user"].map(e.groupby("created_by")["entry_id"].nunique())
    rare = ua[
        (ua["count"] <= cfg.rare_user_account_max_count)
        & (ua["user_total"] >= cfg.user_min_entries)
    ].drop_duplicates("entry_id")
    reasons = [
        f"{u} posted to account {a} in only {n} of their {t} manual entries (unusual for this user)"
        for u, a, n, t in zip(
            rare["user"], rare["account"], rare["count"], rare["user_total"], strict=True
        )
    ]
    return make_flags(rare["entry_id"], FAMILY, "RARE_USER_ACCOUNT", reasons)


def run(ds: Dataset) -> pd.DataFrame:
    """All account-usage tests."""
    return combine([rare_pairs(ds), rare_user_accounts(ds)])
