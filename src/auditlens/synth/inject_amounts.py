"""Anomaly injectors about amounts and approvals (types 1, 2, 4, 5)."""

from __future__ import annotations

import copy
from datetime import timedelta

from auditlens import bh_calendar as cal
from auditlens.synth.baseline import ACCRUAL_ACCOUNTS, JOURNAL_DECADES
from auditlens.synth.context import GenContext
from auditlens.synth.master_data import ACCRUED

ROUND_AMOUNTS = [10000, 15000, 20000, 30000, 40000, 50000, 60000, 70000, 80000, 90000]


def inject_duplicate_payments(ctx: GenContext, n: int) -> None:
    """Pay the same invoice twice: same vendor, same/near-same amount, a few days apart."""
    pool = [
        e
        for e in ctx.entries
        if e.kind == "payment"
        and e.amount >= 500
        and e.posting_date <= cal.previous_business_day(ctx.last_posting_day - timedelta(days=10))
    ]
    picks = ctx.rng.choice(len(pool), size=min(n, len(pool)), replace=False)
    for i in picks:
        orig = pool[int(i)]
        new_date = orig.document_date
        for _ in range(int(ctx.rng.integers(1, 4))):  # 1-3 business days later
            new_date = cal.next_business_day(new_date + timedelta(days=1))
        factor = 1.0 if ctx.rng.random() < 0.6 else float(ctx.rng.uniform(0.995, 1.005))
        amount = round(orig.amount * factor, 3)
        dup = copy.deepcopy(orig)
        dup.uid = ctx.next_uid
        ctx.next_uid += 1
        dup.document_date = new_date
        dup.posting_date, dup.period = ctx.resolve_dates(new_date, "manual", 0)
        dup.lines[0].debit = amount
        dup.lines[1].credit = amount
        variant = ctx.rng.random()
        if variant < 1 / 3:  # same invoice paid twice: number repeated
            pass
        elif variant < 2 / 3:  # re-keyed with a suffix
            dup.invoice_number = f"{orig.invoice_number}-R"
        else:  # vendor re-billed under a brand-new invoice number
            dup.invoice_number = ctx.invoice_number_for(orig.vendor_id or "", new_date)
        dup.description = dup.description.replace(
            orig.invoice_number or "", dup.invoice_number or ""
        )
        dup.approved_by = ctx.approver_for(dup.created_by, amount)
        ctx.entries.append(dup)
        ctx.label(
            dup,
            "duplicate_payment",
            "injected",
            related=orig,
            note=f"duplicate of payment {orig.uid} (amount {orig.amount} vs {amount})",
        )
        ctx.label(orig, "duplicate_payment", "counterpart", related=dup)


def inject_split_purchases(ctx: GenContext, groups: int) -> None:
    """Split one large purchase into invoices just under an approval limit (same vendor/clerk)."""
    limits = sorted(
        r.approval_limit for r in ctx.cfg.roles.values() if 0 < r.approval_limit <= 100000
    )
    vendors = ctx.regular_vendors()
    chosen = ctx.rng.choice(vendors, size=min(groups, len(vendors)), replace=False)
    for vid in map(str, chosen):
        limit = float(ctx.rng.choice(limits))
        start = ctx.sample_dates(1, [1] * 11 + [0.001])[0]
        for k in range(int(ctx.rng.integers(3, 6))):
            d = cal.next_business_day(start + timedelta(days=int(ctx.rng.integers(0, 2)) + k))
            amount = round(limit * float(ctx.rng.uniform(0.90, 0.995)), 3)
            inv = ctx.make_invoice(vid, d, amount, lag=0)
            ctx.label(inv, "split_purchase", note=f"just under limit {limit:,.0f}")


def inject_round_amounts(ctx: GenContext, n: int) -> None:
    """Manual invoices for suspiciously round amounts."""
    vendors = ctx.regular_vendors()
    dates = ctx.sample_dates(n, [1] * 12)
    for d in dates:
        vid = str(ctx.rng.choice(vendors))
        amount = float(ctx.rng.choice(ROUND_AMOUNTS))
        inv = ctx.make_invoice(vid, d, amount)
        ctx.label(inv, "round_amount", note=f"amount {amount:,.0f}")


def inject_same_creator_approver(ctx: GenContext, n: int) -> None:
    """Journals where the person who created the entry also approved it."""
    creators = ctx.users_with_role("accountant", "senior_accountant")
    for d in ctx.sample_dates(n, [1] * 12):
        creator = str(ctx.rng.choice(creators))
        acct = int(ctx.rng.choice(ACCRUAL_ACCOUNTS))
        amount = ctx.benford_amount(JOURNAL_DECADES)
        e = ctx.make_journal(
            acct,
            ACCRUED,
            amount,
            d,
            creator=creator,
            approver=creator,
            description=f"Accrual {d:%b %Y} - {acct}",
            kind="accrual",
        )
        ctx.label(e, "same_creator_approver", note=f"self-approved by {creator}")
