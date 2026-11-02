"""Clean (non-anomalous) journal activity: sales, receipts, purchases, payments, payroll, ..."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from auditlens import bh_calendar as cal
from auditlens.synth.context import AUTOMATED, MANUAL, Entry, GenContext, Line
from auditlens.synth.master_data import (
    ACCRUED,
    ACCUM_DEPR,
    AR,
    CASH,
    DEPRECIATION,
    SALARIES,
    SALES_PRODUCT,
    SALES_SERVICE,
    SYSTEM_USER,
)

SALES_DECADES = {2: 0.25, 3: 0.45, 4: 0.30}
JOURNAL_DECADES = {2: 0.35, 3: 0.45, 4: 0.20}
ACCRUAL_ACCOUNTS = [6200, 6300, 6400, 6600, 6800, 7000]
RECLASS_PAIRS = [(6600, 6400), (6700, 6500), (6800, 6200)]  # (debit, credit)

# Base counts for target_lines = 50,000; scaled linearly.
BASE_SALES = 5000
BASE_INVOICES = 7700
BASE_ACCRUALS = 380
BASE_RECLASS = 140
AUTOMATED_INVOICE_SHARE = 0.30
AUTOMATED_RECEIPT_SHARE = 0.70
RECEIPT_PAID_SHARE = 0.94


def scale(ctx: GenContext) -> float:
    """Volume scale relative to the 50,000-line reference."""
    return ctx.cfg.generation.target_lines / 50000


def gen_sales_and_receipts(ctx: GenContext) -> None:
    """Automated sales invoices (Dr AR / Cr Revenue) and the customer receipts that clear them."""
    n = round(BASE_SALES * scale(ctx))
    dates = ctx.sample_dates(n, ctx.cfg.generation.sales_seasonality)
    sales: list[Entry] = []
    for i, d in enumerate(dates, start=1):
        amount = ctx.benford_amount(SALES_DECADES)
        revenue = SALES_PRODUCT if ctx.rng.random() < 0.75 else SALES_SERVICE
        number = f"SI-{i:06d}"
        cust = f"C{int(ctx.rng.integers(1, 400)):04d}"
        sales.append(
            ctx.add(
                kind="sale",
                document_date=d,
                posting_date=d,
                period=cal.period_of(d),
                source=AUTOMATED,
                created_by=SYSTEM_USER,
                approved_by=None,
                vendor_id=None,
                invoice_number=number,
                description=f"Sales invoice {number} - customer {cust}",
                lines=[Line(AR, debit=amount), Line(revenue, credit=amount)],
            )
        )
    accountants = ctx.users_with_role("accountant")
    for s in sales:
        if ctx.rng.random() > RECEIPT_PAID_SHARE:
            continue
        days = int(np.clip(ctx.rng.normal(35, 15), 5, 120))
        pay = cal.next_business_day(s.document_date + timedelta(days=days))
        if pay > ctx.last_posting_day:
            continue
        amount = s.amount
        manual = ctx.rng.random() > AUTOMATED_RECEIPT_SHARE
        creator = str(ctx.rng.choice(accountants)) if manual else SYSTEM_USER
        posting, per = ctx.resolve_dates(pay, MANUAL if manual else AUTOMATED)
        ctx.add(
            kind="receipt",
            document_date=pay,
            posting_date=posting,
            period=per,
            source=MANUAL if manual else AUTOMATED,
            created_by=creator,
            approved_by=ctx.approver_for(creator, amount) if manual else None,
            vendor_id=None,
            invoice_number=s.invoice_number,
            description=f"Receipt for {s.invoice_number}",
            lines=[Line(CASH, debit=amount), Line(AR, credit=amount)],
        )


def _clip_to_created(ctx: GenContext, vendor_id: str, d: date) -> date:
    """A vendor cannot invoice before it was created."""
    created = date.fromisoformat(
        next(v["created_date"] for v in ctx.md.vendors if v["vendor_id"] == vendor_id)
    )
    if d <= created:
        d = cal.next_business_day(created + timedelta(days=int(ctx.rng.integers(7, 60))))
    return min(d, ctx.last_posting_day)


def gen_regular_invoices(ctx: GenContext) -> list[Entry]:
    """Vendor invoices for regular vendors; amounts follow Benford within each category."""
    ids = ctx.regular_vendors()
    weights = np.array([ctx.md.vendor_meta[v].activity for v in ids])
    total = round(BASE_INVOICES * scale(ctx))
    counts = ctx.rng.multinomial(total, weights / weights.sum())
    invoices: list[Entry] = []
    for vid, n in zip(ids, counts, strict=True):
        meta = ctx.md.vendor_meta[vid]
        dates = sorted(
            _clip_to_created(ctx, vid, d)
            for d in ctx.sample_dates(int(n), ctx.cfg.generation.purchase_seasonality)
        )
        for d in dates:
            source = AUTOMATED if ctx.rng.random() < AUTOMATED_INVOICE_SHARE else MANUAL
            invoices.append(
                ctx.make_invoice(vid, d, ctx.benford_amount(meta.decade_weights), source=source)
            )
    return invoices


def gen_recurring_invoices(ctx: GenContext) -> list[Entry]:
    """Rent, utilities, insurance, ... billed on a fixed schedule."""
    invoices: list[Entry] = []
    for vid, meta in ctx.md.vendor_meta.items():
        spec = meta.recurring
        if spec is None:
            continue
        for month in range(1, 13, spec.every_n_months):
            d = cal.next_business_day(date(ctx.fy, month, spec.day_of_month))
            amount = spec.base_amount * (1 + (ctx.rng.normal(0, spec.rel_sd) if spec.rel_sd else 0))
            invoices.append(ctx.make_invoice(vid, d, round(float(amount), 3), lag=0))
    return invoices


def gen_payments(ctx: GenContext, invoices: list[Entry]) -> None:
    """Pay each invoice once, at its vendor's terms (unpaid if due after year end)."""
    terms = {v["vendor_id"]: int(v["payment_terms_days"]) for v in ctx.md.vendors}
    for inv in invoices:
        vid = inv.vendor_id or ""
        due = inv.posting_date + timedelta(days=terms[vid] + int(ctx.rng.integers(-3, 6)))
        pay = cal.next_business_day(due)
        if pay <= ctx.last_posting_day:
            ctx.make_payment(inv, pay)


def gen_payroll_and_depreciation(ctx: GenContext) -> None:
    """Monthly automated payroll (one line per department) and depreciation, on the last day."""
    salaries = ctx.rng.lognormal(7.2, 0.4, size=len(ctx.md.employees))
    dept_totals: dict[str, float] = {}
    for emp, sal in zip(ctx.md.employees, salaries, strict=True):
        dept_totals[emp["department"]] = dept_totals.get(emp["department"], 0.0) + float(sal)
    for month in range(1, 13):
        d = cal.month_end(ctx.fy, month)
        lines = [
            Line(SALARIES, debit=round(total * (1 + ctx.rng.normal(0, 0.01)), 3))
            for _, total in sorted(dept_totals.items())
        ]
        lines.append(Line(CASH, credit=round(sum(line.debit for line in lines), 3)))
        ctx.add(
            kind="payroll",
            document_date=d,
            posting_date=d,
            period=cal.period_of(d),
            source=AUTOMATED,
            created_by=SYSTEM_USER,
            approved_by=None,
            vendor_id=None,
            invoice_number=None,
            description=f"Payroll {d:%B %Y}",
            lines=lines,
        )
        ctx.add(
            kind="depreciation",
            document_date=d,
            posting_date=d,
            period=cal.period_of(d),
            source=AUTOMATED,
            created_by=SYSTEM_USER,
            approved_by=None,
            vendor_id=None,
            invoice_number=None,
            description=f"Depreciation {d:%B %Y}",
            lines=[Line(DEPRECIATION, debit=18250.5), Line(ACCUM_DEPR, credit=18250.5)],
        )


def _journal_creator(ctx: GenContext) -> str:
    """Manual journals are keyed mostly by accountants, sometimes by senior accountants."""
    role = "accountant" if ctx.rng.random() < 0.7 else "senior_accountant"
    return str(ctx.rng.choice(ctx.users_with_role(role)))


def gen_manual_journals(ctx: GenContext) -> None:
    """Month-end accruals with next-month reversals, and a few reclassifications."""
    n_accruals = round(BASE_ACCRUALS * scale(ctx))
    for d in _month_end_dates(ctx, n_accruals):
        acct = int(ctx.rng.choice(ACCRUAL_ACCOUNTS))
        amount = ctx.benford_amount(JOURNAL_DECADES)
        creator = _journal_creator(ctx)
        ctx.make_journal(
            acct,
            ACCRUED,
            amount,
            d,
            creator=creator,
            kind="accrual",
            description=f"Month-end accrual {d:%b %Y} - {acct}",
        )
        if d.month < 12:
            first = cal.business_days_in_month(ctx.fy, d.month + 1)[0]
            ctx.make_journal(
                ACCRUED,
                acct,
                amount,
                first,
                creator=creator,
                kind="reversal",
                lag=0,
                description=f"Reversal of accrual {d:%b %Y} - {acct}",
            )
    dates = ctx.sample_dates(round(BASE_RECLASS * scale(ctx)), [1] * 12)
    for d in dates:
        debit, credit = RECLASS_PAIRS[int(ctx.rng.integers(len(RECLASS_PAIRS)))]
        ctx.make_journal(
            debit,
            credit,
            ctx.benford_amount(JOURNAL_DECADES),
            d,
            creator=_journal_creator(ctx),
            kind="reclass",
            description=f"Reclassification {credit} to {debit}",
        )


def _month_end_dates(ctx: GenContext, n: int) -> list[date]:
    """Dates in the last three business days of random months."""
    out: list[date] = []
    for month in ctx.rng.integers(1, 13, size=n):
        days = cal.business_days_in_month(ctx.fy, int(month))[-3:]
        out.append(days[int(ctx.rng.integers(len(days)))])
    return sorted(out)


def generate_baseline(ctx: GenContext) -> None:
    """Build all clean activity in the context."""
    gen_sales_and_receipts(ctx)
    invoices = gen_regular_invoices(ctx) + gen_recurring_invoices(ctx)
    gen_payments(ctx, invoices)
    gen_payroll_and_depreciation(ctx)
    gen_manual_journals(ctx)
