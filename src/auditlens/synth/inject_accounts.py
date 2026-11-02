"""Anomaly injectors about account usage (type 10: unusual pairings, rare user-account use)."""

from __future__ import annotations

from itertools import product

from auditlens.synth.baseline import JOURNAL_DECADES
from auditlens.synth.context import GenContext

# (debit, credit) pairs that never occur in normal activity
RARE_PAIRS = [
    (8100, 1000),  # Suspense paid from bank
    (3100, 1000),  # Retained earnings paid out in cash
    (1000, 6600),  # cash received against travel expense
    (6600, 4000),  # travel expense credited to product revenue
    (1500, 4100),  # fixed asset against service revenue
    (4000, 1000),  # revenue reversed straight to cash
    (6000, 2000),  # salaries booked through accounts payable
    (5000, 1100),  # COGS booked against receivables
]
MAX_PER_USER_ACCOUNT = 2


def inject_unusual_pairings(ctx: GenContext, n: int) -> None:
    """Manual journals using a debit/credit account pair that is otherwise never seen."""
    creators = ctx.users_with_role("accountant", "senior_accountant")
    dates = ctx.sample_dates(n, [1] * 12)
    ctx.rng.shuffle(dates)
    for i, d in enumerate(dates):
        debit, credit = RARE_PAIRS[i % len(RARE_PAIRS)]
        e = ctx.make_journal(
            debit,
            credit,
            ctx.benford_amount(JOURNAL_DECADES),
            d,
            creator=str(ctx.rng.choice(creators)),
            kind="journal",
            description=f"Manual journal {d:%b %Y}",
        )
        ctx.label(e, "unusual_account_use", note=f"rare pair Dr {debit} / Cr {credit}")


def inject_rare_user_accounts(ctx: GenContext, n: int) -> None:
    """An AP clerk books an invoice to an account outside their normal portfolio."""
    clerks = ctx.users_with_role("ap_clerk")
    by_clerk = {
        c: {m.account for m in ctx.md.vendor_meta.values() if m.clerk == c and m.decade_weights}
        for c in clerks
    }
    combos = []  # (clerk, vendor) where the vendor's account is new for the clerk
    for clerk, (vid, meta) in product(clerks, ctx.md.vendor_meta.items()):
        if meta.decade_weights and meta.account not in by_clerk[clerk]:
            combos.append((clerk, vid, meta.account))
    by_pair: dict[tuple[str, int], list[str]] = {}
    for clerk, vid, acct in combos:
        by_pair.setdefault((clerk, acct), []).append(vid)
    keys = sorted(by_pair)
    ctx.rng.shuffle(keys)
    plan = [k for _ in range(MAX_PER_USER_ACCOUNT) for k in keys][:n]
    dates = ctx.sample_dates(len(plan), [1] * 12)
    ctx.rng.shuffle(dates)
    for (clerk, acct), d in zip(plan, dates, strict=True):
        vid = str(ctx.rng.choice(by_pair[(clerk, acct)]))
        meta = ctx.md.vendor_meta[vid]
        inv = ctx.make_invoice(vid, d, ctx.benford_amount(meta.decade_weights), creator=clerk)
        ctx.label(inv, "unusual_account_use", note=f"{clerk} never normally posts to {acct}")
