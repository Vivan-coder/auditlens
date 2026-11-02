"""Challenge set: anomalies written to stress the rules, not to match their definitions.

The main synthetic dataset plants each anomaly exactly as its rule defines it, so rule recall there
is flattering. This module builds a second ledger on the same clean baseline with NO standard
anomalies, and plants instead:

* boundary cases just outside a threshold (a duplicate 12 days later, a split at 85% of the limit),
* disguised cases that evade exact matching (a reformatted employee address),
* controls the rules SHOULD catch (so a blanket "everything is missed" bug would show), and
* decoys: legitimate entries that look like anomalies (to measure false alarms on look-alikes).

It is still written by the same author, so it is a stress test, not independent validation.
Every entry's label note starts with ``variant:<name>``.
"""

from __future__ import annotations

import copy
from datetime import timedelta

import pandas as pd

from auditlens import bh_calendar as cal
from auditlens.config import Config
from auditlens.generate import build_journal, build_labels
from auditlens.synth.baseline import ACCRUAL_ACCOUNTS, generate_baseline
from auditlens.synth.context import INVOICE_RE, Entry, GenContext
from auditlens.synth.inject_timing import ORDINARY_DECADES, _non_business_days
from auditlens.synth.inject_vendors import _invoice_with_payment, _new_vendor
from auditlens.synth.master_data import ACCRUED, add_bank_change

# variant -> (anomaly type it imitates, rule codes designed for it, what the design predicts)
VARIANTS: dict[str, tuple[str, list[str], str]] = {
    "dup_late_repeat": (
        "duplicate_payment",
        ["DUP_SAME_INVOICE", "DUP_EXACT_AMOUNT", "DUP_NEAR_AMOUNT"],
        "miss",
    ),
    "dup_amount_3_to_8pct": (
        "duplicate_payment",
        ["DUP_SAME_INVOICE", "DUP_EXACT_AMOUNT", "DUP_NEAR_AMOUNT"],
        "miss",
    ),
    "split_wide_band_80_88pct": ("split_purchase", ["SPLIT_BELOW_LIMIT"], "miss"),
    "split_only_two_parts": ("split_purchase", ["SPLIT_BELOW_LIMIT"], "miss"),
    "split_across_three_clerks": ("split_purchase", ["SPLIT_BELOW_LIMIT"], "miss"),
    "backdated_20_to_26_days": (
        "late_or_backdated_posting",
        ["BACKDATED_POSTING", "POST_CLOSE_POSTING"],
        "miss",
    ),
    "post_close_one_day_over": ("late_or_backdated_posting", ["POST_CLOSE_POSTING"], "detect"),
    "near_round_amounts": ("round_amount", ["ROUND_AMOUNT"], "miss"),
    "manual_just_below_materiality": (
        "large_manual_period_end",
        ["LARGE_MANUAL_PERIOD_END"],
        "miss",
    ),
    "reciprocal_approval_pair": ("same_creator_approver", ["SELF_APPROVED"], "miss"),
    "sequence_gap_30_to_45": ("invoice_sequence_break", ["INVOICE_GAP"], "miss"),
    "sequence_gap_100_to_200": ("invoice_sequence_break", ["INVOICE_GAP"], "detect"),
    "ghost_address_reformatted": ("ghost_vendor", ["GHOST_VENDOR_ADDRESS"], "miss"),
    "ghost_bank_spaced_lowercase": ("ghost_vendor", ["GHOST_VENDOR_BANK"], "detect"),
    "bank_change_payment_20_to_30_days": (
        "bank_change_large_payment",
        ["BANK_CHANGE_LARGE_PAYMENT"],
        "miss",
    ),
    "benford_vendor_only_40_invoices": ("benford_violation", ["BENFORD_VENDOR"], "miss"),
    "decoy_legit_weekend_entries": ("decoy", ["WEEKEND_POSTING"], "decoy"),
    "decoy_legit_large_capex_journal": ("decoy", ["LARGE_MANUAL_PERIOD_END"], "decoy"),
    "decoy_two_genuine_same_amount_invoices": ("decoy", ["DUP_EXACT_AMOUNT"], "decoy"),
    "decoy_contract_round_payments": ("decoy", ["ROUND_AMOUNT"], "decoy"),
}


def _tag(ctx: GenContext, e: Entry, variant: str, atype: str | None = None, role: str = "injected"):
    ctx.label(e, atype or VARIANTS[variant][0], role, note=f"variant:{variant}")


def _bd_after(d, n: int):
    for _ in range(n):
        d = cal.next_business_day(d + timedelta(days=1))
    return d


def _rand_vendor(ctx: GenContext) -> str:
    return str(ctx.rng.choice(ctx.regular_vendors()))


# ---- duplicates ------------------------------------------------------------
def _payment_pool(ctx: GenContext) -> list[Entry]:
    cutoff = ctx.last_posting_day - timedelta(days=60)
    tagged = {lab["uid"] for lab in ctx.labels}
    return [
        e
        for e in ctx.entries
        if e.kind == "payment"
        and e.amount >= 500
        and e.posting_date <= cutoff
        and e.uid not in tagged
    ]


def _clone_payment(ctx: GenContext, orig: Entry, days_later: int, factor: float, variant: str):
    new_date = cal.next_business_day(orig.document_date + timedelta(days=days_later))
    amount = round(orig.amount * factor, 3)
    dup = copy.deepcopy(orig)
    dup.uid, ctx.next_uid = ctx.next_uid, ctx.next_uid + 1
    dup.document_date = new_date
    dup.posting_date, dup.period = ctx.resolve_dates(new_date, "manual", 0)
    dup.lines[0].debit, dup.lines[1].credit = amount, amount
    dup.invoice_number = ctx.invoice_number_for(orig.vendor_id or "", new_date)
    dup.description = f"Payment {ctx.vendor_name(orig.vendor_id or '')} - {dup.invoice_number}"
    dup.approved_by = ctx.approver_for(dup.created_by, amount)
    ctx.entries.append(dup)
    _tag(ctx, dup, variant)
    ctx.label(orig, "duplicate_payment", "counterpart", related=dup, note=f"variant:{variant}")


def plant_duplicates(ctx: GenContext) -> None:
    """Repeat payments that fall outside the duplicate tests' window or tolerance."""
    pool = _payment_pool(ctx)
    picks = ctx.rng.choice(len(pool), size=20, replace=False)
    for k, i in enumerate(picks):
        orig = pool[int(i)]
        if k < 10:  # identical amount, new invoice number, 12-20 days later (window is 7)
            _clone_payment(ctx, orig, int(ctx.rng.integers(12, 21)), 1.0, "dup_late_repeat")
        else:  # 3-8% different amount, 1-3 days later (tolerance is 0.5%)
            factor = float(ctx.rng.uniform(1.03, 1.08))
            _clone_payment(ctx, orig, int(ctx.rng.integers(1, 4)), factor, "dup_amount_3_to_8pct")


# ---- split purchases -------------------------------------------------------
def _split_group(ctx, vendor, limit, parts, lo, hi, creators, variant):
    start = ctx.sample_dates(1, [1] * 10 + [0.001, 0.001])[0]
    for k in range(parts):
        d = _bd_after(start, k)
        amount = round(limit * float(ctx.rng.uniform(lo, hi)), 3)
        inv = ctx.make_invoice(vendor, d, amount, lag=0, creator=creators[k % len(creators)])
        _tag(ctx, inv, variant)


def plant_splits(ctx: GenContext) -> None:
    """Splits that the 90%-100% band, the 3-invoice minimum or the same-creator grouping miss."""
    clerks = ctx.users_with_role("ap_clerk")
    for _ in range(4):
        v = _rand_vendor(ctx)
        _split_group(
            ctx,
            v,
            25000.0,
            4,
            0.80,
            0.88,
            [ctx.md.vendor_meta[v].clerk],
            "split_wide_band_80_88pct",
        )
    for _ in range(6):
        v = _rand_vendor(ctx)
        _split_group(
            ctx, v, 25000.0, 2, 0.93, 0.99, [ctx.md.vendor_meta[v].clerk], "split_only_two_parts"
        )
    for _ in range(4):
        _split_group(
            ctx, _rand_vendor(ctx), 25000.0, 3, 0.93, 0.99, clerks, "split_across_three_clerks"
        )


# ---- timing ----------------------------------------------------------------
def plant_timing(ctx: GenContext) -> None:
    """Backdating just under the limit (caught only by luck) and a post-close entry 1 day over."""
    for _ in range(10):
        days = cal.business_days_in_month(ctx.fy, int(ctx.rng.integers(4, 13)))
        posting = min(days[int(ctx.rng.integers(len(days)))], ctx.last_posting_day)
        doc = cal.previous_business_day(posting - timedelta(days=int(ctx.rng.integers(20, 27))))
        inv = ctx.make_invoice(
            _rand_vendor(ctx),
            doc,
            ctx.benford_amount(ORDINARY_DECADES),
            posting_date=posting,
            period=cal.period_of(posting),
        )
        _tag(ctx, inv, "backdated_20_to_26_days")
    for _ in range(6):
        days = cal.business_days_in_month(ctx.fy, int(ctx.rng.integers(1, 10)))
        doc = days[int(ctx.rng.integers(len(days)))]
        closed = cal.period_close_date(cal.period_of(doc), ctx.close_days)
        posting = cal.next_business_day(closed + timedelta(days=1))
        inv = ctx.make_invoice(
            _rand_vendor(ctx),
            doc,
            ctx.benford_amount(ORDINARY_DECADES),
            posting_date=posting,
            period=cal.period_of(doc),
        )
        _tag(ctx, inv, "post_close_one_day_over")


# ---- amounts and approvals -------------------------------------------------
def plant_amounts(ctx: GenContext) -> None:
    """Near-round amounts, a manual journal just under materiality, and reciprocal approvals."""
    values = [
        19950.0,
        29500.0,
        49900.0,
        14750.0,
        39990.0,
        59500.0,
        9999.0,
        24990.0,
        44950.0,
        79900.0,
    ]
    for d, amount in zip(ctx.sample_dates(len(values), [1] * 12), values, strict=True):
        inv = ctx.make_invoice(_rand_vendor(ctx), d, amount)
        _tag(ctx, inv, "near_round_amounts")
    seniors = ctx.users_with_role("senior_accountant")
    for i in range(6):
        d = cal.business_days_in_month(ctx.fy, i + 2)[-1]
        e = ctx.make_journal(
            int(ctx.rng.choice(ACCRUAL_ACCOUNTS)),
            ACCRUED,
            round(float(ctx.rng.uniform(225000, 245000)), 3),
            d,
            creator=str(ctx.rng.choice(seniors)),
            lag=0,
            kind="accrual",
            description=f"Period-end adjustment {d:%b %Y}",
        )
        _tag(ctx, e, "manual_just_below_materiality")
    a, b = ctx.users_with_role("accountant")[:2]
    for i, d in enumerate(ctx.sample_dates(12, [1] * 12)):
        creator, approver = (a, b) if i % 2 == 0 else (b, a)
        e = ctx.make_journal(
            int(ctx.rng.choice(ACCRUAL_ACCOUNTS)),
            ACCRUED,
            round(float(ctx.rng.uniform(2000, 20000)), 3),
            d,
            creator=creator,
            approver=approver,
            kind="accrual",
            description=f"Accrual {d:%b %Y}",
        )
        _tag(ctx, e, "reciprocal_approval_pair")


# ---- invoice sequences -----------------------------------------------------
def _number(e: Entry) -> int:
    m = INVOICE_RE.match(e.invoice_number or "")
    return int(m.group(1)) if m else 0


def plant_sequence_breaks(ctx: GenContext) -> None:
    """Gaps of 30-45 (under the 50 limit) and a control gap of 100-200 that must be caught."""
    vendors = [
        v
        for v in ctx.regular_vendors()
        if sum(1 for e in ctx.entries if e.vendor_id == v and e.kind == "invoice") >= 15
    ]
    order = ctx.rng.permutation(len(vendors))
    plan = [("sequence_gap_30_to_45", 30, 46)] * 8 + [("sequence_gap_100_to_200", 100, 201)] * 8
    used: set[int] = set()
    for (variant, lo, hi), vi in zip(plan, order, strict=False):
        vid = vendors[int(vi)]
        invs = sorted(
            (e for e in ctx.entries if e.vendor_id == vid and e.kind == "invoice"),
            key=lambda e: (e.document_date, e.uid),
        )
        options = [
            i
            for i in range(5, len(invs) - 3)
            if invs[i].document_date > invs[i - 1].document_date and invs[i].uid not in used
        ]
        if not options:
            continue
        target = invs[options[int(ctx.rng.integers(len(options)))]]
        ctx.shift_invoice_numbers(vid, _number(target), int(ctx.rng.integers(lo, hi)))
        used.add(target.uid)
        _tag(ctx, target, variant)


# ---- vendors ---------------------------------------------------------------
def _reformat_address(addr: str) -> str:
    out = addr.replace("Bldg ", "Building ").replace("Road ", "Rd ").replace("Block ", "Blk ")
    return out.replace(", Kingdom of Bahrain", " Bahrain").replace(",", "")


def _space_bank(account: str) -> str:
    low = account.lower()
    return " ".join(low[i : i + 4] for i in range(0, len(low), 4))


def _ghost(ctx: GenContext, emp: dict, variant: str, **kw) -> None:
    created = cal.next_business_day(
        pd.Timestamp(ctx.fy, int(ctx.rng.integers(1, 7)), int(ctx.rng.integers(1, 28))).date()
    )
    vid = _new_vendor(
        ctx,
        "Professional services",
        created,
        name=f"{ctx.fake.last_name()} Advisory Services W.L.L.",
        **kw,
    )
    start = created + timedelta(days=21)
    for d in ctx.sample_dates(4, [1] * 12):
        if d < start:
            d = cal.next_business_day(start + timedelta(days=int(ctx.rng.integers(0, 40))))
        inv, pay = _invoice_with_payment(
            ctx, vid, min(d, ctx.last_posting_day), ctx.benford_amount({2: 0.5, 3: 0.5})
        )
        for e in (inv, pay):
            if e is not None:
                _tag(ctx, e, variant)


def plant_vendor_risks(ctx: GenContext) -> None:
    """Ghost vendors with reformatted details, a slow bank-change payment, a thin Benford vendor."""
    emps = [
        ctx.md.employees[int(i)] for i in ctx.rng.choice(len(ctx.md.employees), 5, replace=False)
    ]
    for emp in emps[:3]:
        _ghost(ctx, emp, "ghost_address_reformatted", address=_reformat_address(emp["address"]))
    for emp in emps[3:]:
        _ghost(ctx, emp, "ghost_bank_spaced_lowercase", bank=_space_bank(emp["bank_account"]))
    changed = {b["vendor_id"] for b in ctx.md.bank_changes}
    cands = [v for v in ctx.regular_vendors() if v not in changed]
    for i in ctx.rng.choice(len(cands), size=6, replace=False):
        vid = cands[int(i)]
        days = cal.business_days_in_month(ctx.fy, int(ctx.rng.integers(2, 9)))
        change = days[int(ctx.rng.integers(5, len(days)))]
        add_bank_change(ctx.md, ctx.rng, vid, change, ctx.users_with_role("accountant")[0])
        amount = round(float(ctx.rng.uniform(40000, 95000)), 3)
        inv = ctx.make_invoice(vid, cal.previous_business_day(change - timedelta(days=10)), amount)
        pay = ctx.make_payment(
            inv,
            cal.next_business_day(change + timedelta(days=int(ctx.rng.integers(20, 31)))),
            lag=0,
        )
        _tag(ctx, pay, "bank_change_payment_20_to_30_days")
    vid = _new_vendor(
        ctx,
        "Professional services",
        pd.Timestamp(ctx.fy - 3, 5, 14).date(),
        name="Meridian Advisory Services W.L.L.",
    )
    for d in ctx.sample_dates(40, ctx.cfg.generation.purchase_seasonality):
        inv, _ = _invoice_with_payment(ctx, vid, d, round(float(ctx.rng.uniform(7000, 9990)), 3))
        _tag(ctx, inv, "benford_vendor_only_40_invoices")


# ---- decoys ----------------------------------------------------------------
def plant_decoys(ctx: GenContext) -> None:
    """Legitimate entries that look like anomalies; a good system cannot tell them apart by data."""
    weekend, _ = _non_business_days(ctx)
    for _ in range(10):
        d = weekend[int(ctx.rng.integers(len(weekend)))]
        inv = ctx.make_invoice(
            _rand_vendor(ctx), d, ctx.benford_amount(ORDINARY_DECADES), posting_date=d
        )
        _tag(ctx, inv, "decoy_legit_weekend_entries", "decoy", "decoy")
    for i in range(5):
        d = cal.business_days_in_month(ctx.fy, 2 * i + 2)[-1]
        e = ctx.make_journal(
            int(ctx.rng.choice(ACCRUAL_ACCOUNTS)),
            ACCRUED,
            round(float(ctx.rng.uniform(260000, 400000)), 3),
            d,
            creator=ctx.users_with_role("senior_accountant")[0],
            lag=0,
            kind="accrual",
            description=f"Approved capital project accrual {d:%b %Y}",
        )
        _tag(ctx, e, "decoy_legit_large_capex_journal", "decoy", "decoy")
    for _ in range(8):
        v = _rand_vendor(ctx)
        d = ctx.sample_dates(1, [1] * 9 + [0.001] * 3)[0]
        amount = ctx.benford_amount(ORDINARY_DECADES)
        a = ctx.make_invoice(v, d, amount, lag=0)
        b = ctx.make_invoice(v, _bd_after(d, 2), amount, lag=0)
        for inv in (a, b):
            due = cal.next_business_day(inv.posting_date + timedelta(days=30))
            _tag(
                ctx,
                ctx.make_payment(inv, due, lag=0),
                "decoy_two_genuine_same_amount_invoices",
                "decoy",
                "decoy",
            )
    for _ in range(2):
        v = _rand_vendor(ctx)
        for month in (3, 5, 7, 9):
            d = cal.business_days_in_month(ctx.fy, month)[2]
            _tag(
                ctx,
                ctx.make_invoice(v, d, 12000.0, lag=0),
                "decoy_contract_round_payments",
                "decoy",
                "decoy",
            )


def build_challenge(cfg: Config) -> dict[str, pd.DataFrame]:
    """Generate the challenge ledger: clean baseline plus only the challenge cases."""
    c = cfg.model_copy(deep=True)
    c.generation.seed = cfg.evaluation.challenge_seed
    for name in type(c.anomalies).model_fields:
        setattr(c.anomalies, name, 0)
    ctx = GenContext.create(c)
    generate_baseline(ctx)
    for plant in (
        plant_duplicates,
        plant_splits,
        plant_timing,
        plant_amounts,
        plant_sequence_breaks,
        plant_vendor_risks,
        plant_decoys,
    ):
        plant(ctx)
    journal, uid_to_id = build_journal(ctx)
    return {
        "journal_entries": journal,
        "labels": build_labels(ctx, uid_to_id),
        "chart_of_accounts": pd.DataFrame(ctx.md.accounts),
        "users": pd.DataFrame(ctx.md.users),
        "vendors": pd.DataFrame(ctx.md.vendors),
        "employees": pd.DataFrame(ctx.md.employees),
        "vendor_bank_changes": pd.DataFrame(ctx.md.bank_changes),
    }
