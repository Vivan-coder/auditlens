"""Shared state and helpers for building journal entries."""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
from faker import Faker

from auditlens import bh_calendar as cal
from auditlens.config import Config
from auditlens.synth.master_data import (
    AP,
    CASH,
    SYSTEM_USER,
    MasterData,
    build_master_data,
)

MANUAL, AUTOMATED = "manual", "automated"
LAG_CHOICES = np.array([0, 1, 2, 3])
LAG_PROBS = np.array([0.55, 0.25, 0.12, 0.08])


@dataclass
class Line:
    """One journal line: exactly one of debit/credit is non-zero."""

    account: int
    debit: float = 0.0
    credit: float = 0.0


@dataclass
class Entry:
    """A balanced journal entry (header + lines). `kind` is internal and never written."""

    uid: int
    kind: str
    document_date: date
    posting_date: date
    period: str
    source: str
    created_by: str
    approved_by: str | None
    vendor_id: str | None
    invoice_number: str | None
    description: str
    lines: list[Line]

    @property
    def amount(self) -> float:
        """Total debits of the entry."""
        return round(sum(line.debit for line in self.lines), 3)


@dataclass
class GenContext:
    """Everything the generator and injectors share."""

    cfg: Config
    rng: np.random.Generator
    fake: Faker
    md: MasterData
    entries: list[Entry] = field(default_factory=list)
    labels: list[dict] = field(default_factory=list)
    vendor_seq: dict[str, list[tuple[date, int]]] = field(default_factory=dict)
    next_uid: int = 1

    # ---- construction -------------------------------------------------------------------
    @classmethod
    def create(cls, cfg: Config) -> GenContext:
        """Build a context with master data from the config seed."""
        rng = np.random.default_rng(cfg.generation.seed)
        fake = Faker("en_US")
        fake.seed_instance(cfg.generation.seed)
        return cls(cfg=cfg, rng=rng, fake=fake, md=build_master_data(cfg, rng, fake))

    @property
    def fy(self) -> int:
        """Fiscal year (calendar year)."""
        return self.cfg.company.fiscal_year

    @property
    def close_days(self) -> int:
        """Days after month end that a period stays open."""
        return self.cfg.calendar.period_close_days

    @property
    def last_posting_day(self) -> date:
        """Last business day of the fiscal year."""
        return cal.previous_business_day(date(self.fy, 12, 31))

    # ---- users --------------------------------------------------------------------------
    def user_rank_limit(self, user_id: str) -> tuple[int, float]:
        """(rank, approval_limit) of a user."""
        for u in self.md.users:
            if u["user_id"] == user_id:
                rcfg = self.cfg.roles.get(u["role"])
                return (rcfg.rank if rcfg else -1), float(u["approval_limit"])
        raise KeyError(user_id)

    def approver_for(self, creator: str, amount: float) -> str:
        """Lowest-limit user who outranks the creator and can approve this amount."""
        rank, _ = self.user_rank_limit(creator)
        pool = []
        for u in self.md.users:
            r, lim = self.user_rank_limit(u["user_id"])
            if r > rank and lim >= amount:
                pool.append((lim, u["user_id"]))
        if not pool:  # above every limit: escalate to the most senior user
            top = max(self.cfg.roles.values(), key=lambda r: r.rank).rank
            pool = [
                (0.0, u["user_id"])
                for u in self.md.users
                if self.user_rank_limit(u["user_id"])[0] == top
            ]
        low = min(p[0] for p in pool)
        return str(self.rng.choice([uid for lim, uid in pool if lim == low]))

    def users_with_role(self, *roles: str) -> list[str]:
        """User ids holding any of the given roles."""
        return [u for r in roles for u in self.md.users_by_role[r]]

    # ---- dates --------------------------------------------------------------------------
    def sample_dates(self, n: int, month_weights: list[float]) -> list[date]:
        """Business days with seasonality and a month-end volume spike, sorted."""
        w = np.array(month_weights, dtype=float)
        counts = self.rng.multinomial(n, w / w.sum())
        out: list[date] = []
        for month, c in enumerate(counts, start=1):
            if c == 0:
                continue
            days = cal.business_days_in_month(self.fy, month)
            wd = np.ones(len(days))
            wd[-3:] = 2.6  # month-end close rush
            wd[0] = 1.4
            idx = self.rng.choice(len(days), size=int(c), p=wd / wd.sum())
            out.extend(days[i] for i in idx)
        return sorted(out)

    def resolve_dates(
        self,
        doc_date: date,
        source: str,
        lag: int | None = None,
        posting_date: date | None = None,
        period: str | None = None,
    ) -> tuple[date, str]:
        """Posting date and period for a document. Automated entries post the same day."""
        if posting_date is None:
            if source == AUTOMATED:
                posting_date = doc_date
            else:
                if lag is None:
                    lag = int(self.rng.choice(LAG_CHOICES, p=LAG_PROBS))
                posting_date = cal.next_business_day(doc_date + timedelta(days=lag))
            posting_date = min(posting_date, self.last_posting_day)
        if period is None:
            doc_period = cal.period_of(doc_date)
            closes = cal.period_close_date(doc_period, self.close_days)
            period = doc_period if posting_date <= closes else cal.period_of(posting_date)
        return posting_date, period

    # ---- amounts and numbers ---------------------------------------------------------------
    def benford_amount(self, decade_weights: dict[int, float]) -> float:
        """Amount 10^(d+u), u~U(0,1): a log-uniform mantissa is exactly Benford-distributed."""
        decades = np.array(list(decade_weights))
        probs = np.array(list(decade_weights.values()), dtype=float)
        d = int(self.rng.choice(decades, p=probs / probs.sum()))
        return max(round(float(10 ** (d + self.rng.random())), 3), 1.0)

    def invoice_number_for(self, vendor_id: str, doc_date: date) -> str:
        """Next plausible vendor invoice number for a document date (keeps sequence monotonic)."""
        seq = self.vendor_seq.setdefault(vendor_id, [])
        i = bisect.bisect_right(seq, (doc_date, 10**12))
        prev = seq[i - 1][1] if i > 0 else None
        nxt = seq[i][1] if i < len(seq) else None
        if prev is None and nxt is None:
            num = int(self.rng.integers(100, 9000))
        elif nxt is None:
            num = prev + int(self.rng.integers(5, 16))
        elif prev is None:
            num = max(1, nxt - int(self.rng.integers(1, 5)))
        else:
            gap = nxt - prev
            num = prev + (int(self.rng.integers(1, gap)) if gap >= 2 else 1)
        bisect.insort(seq, (doc_date, num))
        return f"INV-{num:06d}"

    # ---- entries ------------------------------------------------------------------------------
    def add(self, **kw) -> Entry:
        """Create an entry with a fresh uid and store it."""
        e = Entry(uid=self.next_uid, **kw)
        self.next_uid += 1
        self.entries.append(e)
        return e

    def label(
        self,
        entry: Entry,
        anomaly_type: str,
        role: str = "injected",
        related: Entry | None = None,
        note: str = "",
    ) -> None:
        """Record ground truth (kept in a separate file, keyed by uid until ids are assigned)."""
        self.labels.append(
            {
                "uid": entry.uid,
                "anomaly_type": anomaly_type,
                "role": role,
                "related_uid": related.uid if related else None,
                "note": note,
            }
        )

    def vendor_name(self, vendor_id: str) -> str:
        """Vendor display name."""
        return next(v["vendor_name"] for v in self.md.vendors if v["vendor_id"] == vendor_id)

    def regular_vendors(self) -> list[str]:
        """Vendor ids that are regular (non-recurring) and part of the baseline population."""
        return [
            v for v, m in self.md.vendor_meta.items() if m.recurring is None and m.decade_weights
        ]

    # ---- entry builders ---------------------------------------------------------------------
    def make_invoice(
        self,
        vendor_id: str,
        doc_date: date,
        amount: float,
        *,
        source: str = MANUAL,
        number: str | None = None,
        creator: str | None = None,
        lag: int | None = None,
        posting_date: date | None = None,
        period: str | None = None,
        account: int | None = None,
    ) -> Entry:
        """Vendor invoice: Dr expense / Cr Accounts Payable."""
        meta = self.md.vendor_meta[vendor_id]
        number = number or self.invoice_number_for(vendor_id, doc_date)
        creator = SYSTEM_USER if source == AUTOMATED else (creator or meta.clerk)
        approver = None if source == AUTOMATED else self.approver_for(creator, amount)
        posting, per = self.resolve_dates(doc_date, source, lag, posting_date, period)
        return self.add(
            kind="invoice",
            document_date=doc_date,
            posting_date=posting,
            period=per,
            source=source,
            created_by=creator,
            approved_by=approver,
            vendor_id=vendor_id,
            invoice_number=number,
            description=f"{self.vendor_name(vendor_id)} - invoice {number}",
            lines=[Line(account or meta.account, debit=amount), Line(AP, credit=amount)],
        )

    def make_payment(
        self,
        invoice: Entry,
        pay_date: date,
        *,
        creator: str | None = None,
        lag: int | None = None,
        posting_date: date | None = None,
    ) -> Entry:
        """Payment of a vendor invoice: Dr Accounts Payable / Cr Cash."""
        vid = invoice.vendor_id or ""
        creator = creator or self.md.vendor_meta[vid].clerk
        amount = invoice.amount
        posting, per = self.resolve_dates(pay_date, MANUAL, lag, posting_date)
        return self.add(
            kind="payment",
            document_date=pay_date,
            posting_date=posting,
            period=per,
            source=MANUAL,
            created_by=creator,
            approved_by=self.approver_for(creator, amount),
            vendor_id=vid,
            invoice_number=invoice.invoice_number,
            description=f"Payment {self.vendor_name(vid)} - {invoice.invoice_number}",
            lines=[Line(AP, debit=amount), Line(CASH, credit=amount)],
        )

    def make_journal(
        self,
        debit_acct: int,
        credit_acct: int,
        amount: float,
        doc_date: date,
        *,
        creator: str,
        description: str,
        kind: str = "journal",
        lag: int | None = None,
        posting_date: date | None = None,
        period: str | None = None,
        approver: str | None = None,
    ) -> Entry:
        """Manual two-line journal."""
        posting, per = self.resolve_dates(doc_date, MANUAL, lag, posting_date, period)
        return self.add(
            kind=kind,
            document_date=doc_date,
            posting_date=posting,
            period=per,
            source=MANUAL,
            created_by=creator,
            approved_by=approver or self.approver_for(creator, amount),
            vendor_id=None,
            invoice_number=None,
            description=description,
            lines=[Line(debit_acct, debit=amount), Line(credit_acct, credit=amount)],
        )
