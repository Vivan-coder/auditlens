"""Anomaly injectors about vendors and invoice numbers (types 7, 8, 9, 11)."""

from __future__ import annotations

import re
from datetime import date, timedelta

from auditlens import bh_calendar as cal
from auditlens.synth.context import Entry, GenContext
from auditlens.synth.master_data import (
    CATEGORIES,
    VendorMeta,
    _vendor_row,
    add_bank_change,
    make_address,
    make_bank_account,
)

INVOICE_RE = re.compile(r"^INV-(\d+)(.*)$")
SMALL_DECADES = {2: 0.5, 3: 0.5}


def _new_vendor(
    ctx: GenContext,
    category: str,
    created: date,
    *,
    name: str,
    address: str | None = None,
    bank: str | None = None,
) -> str:
    """Add a vendor (master row + generation metadata) and return its id."""
    vid = f"V{len(ctx.md.vendors) + 1:04d}"
    cat = CATEGORIES[category]
    ctx.md.vendors.append(
        _vendor_row(
            vid,
            name,
            address or make_address(ctx.rng),
            bank or make_bank_account(ctx.rng),
            created,
            category,
            30,
        )
    )
    clerk = ctx.users_with_role("ap_clerk")[cat.clerk_group]
    ctx.md.vendor_meta[vid] = VendorMeta(vid, category, cat.account, {}, 0.0, clerk)
    return vid


def _invoice_with_payment(ctx: GenContext, vid: str, d: date, amount: float, *, pay: bool = True):
    inv = ctx.make_invoice(vid, d, amount)
    if pay:
        due = cal.next_business_day(inv.posting_date + timedelta(days=30))
        if due <= ctx.last_posting_day:
            return inv, ctx.make_payment(inv, due)
    return inv, None


def inject_ghost_vendors(ctx: GenContext, n_bank: int, n_address: int) -> None:
    """Vendors that share a bank account or address with an employee."""
    emps = ctx.rng.choice(len(ctx.md.employees), size=n_bank + n_address, replace=False)
    for k, ei in enumerate(emps):
        emp = ctx.md.employees[int(ei)]
        by_bank = k < n_bank
        created = date(ctx.fy, int(ctx.rng.integers(1, 7)), int(ctx.rng.integers(1, 28)))
        cat = "Professional services"
        vid = _new_vendor(
            ctx,
            cat,
            created,
            name=f"{ctx.fake.last_name()} Advisory Services W.L.L.",
            address=None if by_bank else emp["address"],
            bank=emp["bank_account"] if by_bank else None,
        )
        shared = "bank account" if by_bank else "address"
        start = created + timedelta(days=21)
        for d in ctx.sample_dates(8, [1] * 12):
            if d < start:
                d = cal.next_business_day(start + timedelta(days=int(ctx.rng.integers(0, 40))))
            inv, pay = _invoice_with_payment(
                ctx, vid, min(d, ctx.last_posting_day), ctx.benford_amount(SMALL_DECADES)
            )
            for e in (inv, pay):
                if e is not None:
                    ctx.label(
                        e,
                        "ghost_vendor",
                        note=f"vendor {vid} shares {shared} with {emp['employee_id']}",
                    )


def inject_bank_change_payments(ctx: GenContext, n: int) -> None:
    """Change a vendor's bank account, then pay it a large amount a few days later."""
    changed = {b["vendor_id"] for b in ctx.md.bank_changes}
    candidates = [v for v in ctx.regular_vendors() if v not in changed]
    picks = ctx.rng.choice(len(candidates), size=min(n, len(candidates)), replace=False)
    for i in picks:
        vid = candidates[int(i)]
        month = int(ctx.rng.integers(2, 11))
        days = cal.business_days_in_month(ctx.fy, month)
        change_date = days[int(ctx.rng.integers(5, len(days)))]
        add_bank_change(ctx.md, ctx.rng, vid, change_date, ctx.users_with_role("accountant")[0])
        amount = round(float(ctx.rng.uniform(40000, 95000)), 3)
        inv = ctx.make_invoice(
            vid, cal.previous_business_day(change_date - timedelta(days=10)), amount
        )
        pay_date = cal.next_business_day(change_date + timedelta(days=int(ctx.rng.integers(1, 6))))
        pay = ctx.make_payment(inv, pay_date, lag=0)
        ctx.label(
            pay,
            "bank_change_large_payment",
            note=f"{vid}: bank changed {change_date}, paid {amount:,.0f} on {pay_date}",
        )


def inject_benford_vendor(ctx: GenContext, n_invoices: int) -> None:
    """A vendor whose invoice amounts are fabricated: leading digits cluster on 7, 8 and 9."""
    if n_invoices <= 0:
        return
    vid = _new_vendor(
        ctx,
        "Professional services",
        date(ctx.fy - 3, 5, 14),
        name="Apex Consulting Services W.L.L.",
    )
    for d in ctx.sample_dates(n_invoices, ctx.cfg.generation.purchase_seasonality):
        amount = round(float(ctx.rng.uniform(7000, 9990)), 3)
        inv, _ = _invoice_with_payment(ctx, vid, d, amount)
        ctx.label(inv, "benford_violation", note=f"vendor {vid}: amounts concentrated in 7000-9990")


def _vendor_invoices(ctx: GenContext, vid: str) -> list[Entry]:
    """Invoice entries of a vendor in document-date order (credits to Accounts Payable)."""
    inv = [e for e in ctx.entries if e.vendor_id == vid and e.kind == "invoice"]
    return sorted(inv, key=lambda e: (e.document_date, e.uid))


def _renumber(ctx: GenContext, vid: str, old: str, new: str) -> None:
    """Change an invoice number on the invoice and on any payment that references it."""
    for e in ctx.entries:
        if e.vendor_id == vid and e.invoice_number == old:
            e.invoice_number = new
            e.description = e.description.replace(old, new)


def _shift_from(ctx: GenContext, vid: str, from_number: int, jump: int) -> None:
    """Add `jump` to every numeric invoice number >= from_number for a vendor."""
    for e in ctx.entries:
        m = INVOICE_RE.match(e.invoice_number or "") if e.vendor_id == vid else None
        if m and int(m.group(1)) >= from_number:
            old = e.invoice_number
            e.invoice_number = f"INV-{int(m.group(1)) + jump:06d}{m.group(2)}"
            e.description = e.description.replace(old or "", e.invoice_number)


def inject_invoice_sequence_breaks(ctx: GenContext, n_gap: int, n_ooo: int) -> None:
    """Create numbering gaps (missing invoices) and out-of-order invoice numbers."""
    labelled = {lab["uid"] for lab in ctx.labels}
    vendors = [v for v in ctx.regular_vendors() if len(_vendor_invoices(ctx, v)) >= 15]
    order = ctx.rng.permutation(len(vendors))
    plan = ["gap"] * n_gap + ["ooo"] * n_ooo
    for kind, vi in zip(plan, order, strict=False):
        vid = vendors[int(vi)]
        invs = _vendor_invoices(ctx, vid)
        pos = int(ctx.rng.integers(5, len(invs) - 3))
        target = invs[pos]
        if target.uid in labelled:
            continue
        num = int(INVOICE_RE.match(target.invoice_number or "").group(1))  # type: ignore[union-attr]
        if kind == "gap":
            jump = int(ctx.rng.integers(80, 400))
            _shift_from(ctx, vid, num, jump)
            ctx.label(target, "invoice_sequence_break", note=f"gap: numbers jump by {jump}")
        else:
            prev = int(INVOICE_RE.match(invs[pos - 1].invoice_number or "").group(1))  # type: ignore[union-attr]
            new = prev - int(ctx.rng.integers(1, 4))
            existing = {e.invoice_number for e in ctx.entries if e.vendor_id == vid}
            while f"INV-{new:06d}" in existing:
                new -= 1
            _renumber(ctx, vid, target.invoice_number or "", f"INV-{new:06d}")
            ctx.label(target, "invoice_sequence_break", note="out of order: lower than previous")
        labelled.add(target.uid)
