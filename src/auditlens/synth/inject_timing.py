"""Anomaly injectors about timing (types 3, 6, 12)."""

from __future__ import annotations

from datetime import date, timedelta

from auditlens import bh_calendar as cal
from auditlens.synth.baseline import ACCRUAL_ACCOUNTS
from auditlens.synth.context import GenContext
from auditlens.synth.master_data import ACCRUED

ORDINARY_DECADES = {2: 0.4, 3: 0.4, 4: 0.2}


def _non_business_days(ctx: GenContext) -> tuple[list[date], list[date]]:
    """(weekend days, public holidays that fall on a weekday) in the fiscal year."""
    first = date(ctx.fy, 1, 1)
    days = [first + timedelta(days=i) for i in range((date(ctx.fy, 12, 31) - first).days + 1)]
    weekend = [d for d in days if cal.is_weekend(d) and not cal.is_holiday(d)]
    holiday = [d for d in days if cal.is_holiday(d) and not cal.is_weekend(d)]
    return weekend, holiday


def inject_weekend_holiday(ctx: GenContext, n: int) -> None:
    """Manual invoices posted on Friday/Saturday or on a Bahrain public holiday."""
    weekend, holiday = _non_business_days(ctx)
    vendors = ctx.regular_vendors()
    for i in range(n):
        pool = holiday if i % 3 == 2 else weekend  # about one third on public holidays
        d = pool[int(ctx.rng.integers(len(pool)))]
        vid = str(ctx.rng.choice(vendors))
        inv = ctx.make_invoice(vid, d, ctx.benford_amount(ORDINARY_DECADES), posting_date=d)
        kind = "public holiday" if cal.is_holiday(d) else "weekend"
        ctx.label(inv, "weekend_holiday_posting", note=f"posted on {kind} {d:%a %Y-%m-%d}")


def inject_post_close(ctx: GenContext, n: int) -> None:
    """Entries posted into a period after it was closed."""
    vendors = ctx.regular_vendors()
    for _ in range(n):
        days = cal.business_days_in_month(ctx.fy, int(ctx.rng.integers(1, 9)))
        doc = days[int(ctx.rng.integers(len(days)))]
        closed = cal.period_close_date(cal.period_of(doc), ctx.close_days)
        posting = cal.next_business_day(closed + timedelta(days=int(ctx.rng.integers(7, 90))))
        vid = str(ctx.rng.choice(vendors))
        inv = ctx.make_invoice(
            vid,
            doc,
            ctx.benford_amount(ORDINARY_DECADES),
            posting_date=posting,
            period=cal.period_of(doc),
        )
        ctx.label(
            inv,
            "late_or_backdated_posting",
            note=f"post-close: period {inv.period} closed {closed}, posted {posting}",
        )


def inject_backdated(ctx: GenContext, n: int) -> None:
    """Entries whose document date is far earlier than the posting date (period still open)."""
    vendors = ctx.regular_vendors()
    for _ in range(n):
        days = cal.business_days_in_month(ctx.fy, int(ctx.rng.integers(5, 13)))
        posting = min(days[int(ctx.rng.integers(len(days)))], ctx.last_posting_day)
        gap = int(ctx.rng.integers(45, 151))
        doc = cal.previous_business_day(posting - timedelta(days=gap))
        vid = str(ctx.rng.choice(vendors))
        inv = ctx.make_invoice(
            vid,
            doc,
            ctx.benford_amount(ORDINARY_DECADES),
            posting_date=posting,
            period=cal.period_of(posting),
        )
        ctx.label(
            inv,
            "late_or_backdated_posting",
            note=f"backdated: document {doc}, posted {posting} ({(posting - doc).days} days)",
        )


def inject_large_period_end(ctx: GenContext, n: int) -> None:
    """Large manual journals above materiality in the last two business days of a period."""
    creators = ctx.users_with_role("senior_accountant")
    for i in range(n):
        month = (i % 12) + 1
        d = cal.business_days_in_month(ctx.fy, month)[-int(ctx.rng.integers(1, 3))]
        amount = round(float(ctx.rng.uniform(260000, 900000)), 3)
        acct = int(ctx.rng.choice(ACCRUAL_ACCOUNTS))
        e = ctx.make_journal(
            acct,
            ACCRUED,
            amount,
            d,
            creator=str(ctx.rng.choice(creators)),
            lag=0,
            kind="accrual",
            description=f"Period-end adjustment {d:%b %Y}",
        )
        ctx.label(e, "large_manual_period_end", note=f"manual {amount:,.0f} on {d}")
