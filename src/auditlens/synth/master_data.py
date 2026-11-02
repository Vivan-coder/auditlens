"""Master data for the fictional company: chart of accounts, users, vendors, employees."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
from faker import Faker

from auditlens.config import Config

SYSTEM_USER = "SYSTEM"

# (account, name, type)
ACCOUNTS: list[tuple[int, str, str]] = [
    (1000, "Cash at Bank", "Asset"),
    (1100, "Accounts Receivable", "Asset"),
    (1300, "Prepaid Expenses", "Asset"),
    (1500, "Property, Plant & Equipment", "Asset"),
    (1590, "Accumulated Depreciation", "Asset"),
    (2000, "Accounts Payable", "Liability"),
    (2100, "Accrued Expenses", "Liability"),
    (2500, "Bank Loan", "Liability"),
    (3000, "Share Capital", "Equity"),
    (3100, "Retained Earnings", "Equity"),
    (4000, "Product Sales Revenue", "Revenue"),
    (4100, "Service Revenue", "Revenue"),
    (5000, "Cost of Goods Sold", "Expense"),
    (6000, "Salaries & Wages", "Expense"),
    (6100, "Rent & Leasing", "Expense"),
    (6200, "Utilities & Telecom", "Expense"),
    (6300, "Professional Fees", "Expense"),
    (6400, "Marketing & Advertising", "Expense"),
    (6500, "IT & Software", "Expense"),
    (6600, "Travel & Entertainment", "Expense"),
    (6700, "Office Supplies", "Expense"),
    (6800, "Repairs & Maintenance", "Expense"),
    (6900, "Depreciation", "Expense"),
    (7000, "Insurance", "Expense"),
    (7100, "Bank Charges & Interest", "Expense"),
    (8100, "Suspense", "Expense"),
]

CASH, AR, AP, ACCRUED = 1000, 1100, 2000, 2100
SALARIES, DEPRECIATION, ACCUM_DEPR = 6000, 6900, 1590
SALES_PRODUCT, SALES_SERVICE = 4000, 4100


@dataclass(frozen=True)
class Category:
    """A vendor category: where its invoices are booked and how big they are."""

    account: int
    decade_weights: dict[int, float]  # share of invoices per order of magnitude (10^d..10^(d+1))
    clerk_group: int  # which AP clerk handles this category
    n_share: float  # share of regular vendors
    activity: float  # relative invoice volume per vendor


CATEGORIES: dict[str, Category] = {
    "Goods supplier": Category(5000, {2: 0.25, 3: 0.45, 4: 0.30}, 0, 0.40, 3.0),
    "Office supplies": Category(6700, {1: 0.20, 2: 0.50, 3: 0.30}, 0, 0.08, 1.0),
    "Professional services": Category(6300, {2: 0.20, 3: 0.50, 4: 0.30}, 1, 0.12, 1.0),
    "Marketing": Category(6400, {2: 0.30, 3: 0.50, 4: 0.20}, 1, 0.10, 1.0),
    "IT & software": Category(6500, {2: 0.30, 3: 0.40, 4: 0.30}, 1, 0.10, 1.0),
    "Travel & hospitality": Category(6600, {1: 0.10, 2: 0.50, 3: 0.40}, 2, 0.08, 1.0),
    "Repairs & maintenance": Category(6800, {2: 0.40, 3: 0.40, 4: 0.20}, 2, 0.12, 1.0),
}


@dataclass(frozen=True)
class RecurringSpec:
    """A vendor that bills on a fixed schedule (rent, utilities, ...)."""

    name: str
    category: str
    account: int
    base_amount: float
    rel_sd: float  # relative variation month to month (0 = fixed amount)
    day_of_month: int
    every_n_months: int
    terms_days: int


RECURRING: list[RecurringSpec] = [
    RecurringSpec("Manama Real Estate Holdings W.L.L.", "Rent & leasing", 6100, 4500, 0, 1, 1, 5),
    RecurringSpec("Gulf Fleet Leasing Co.", "Rent & leasing", 6100, 2300, 0, 5, 1, 15),
    RecurringSpec(
        "Bahrain Electricity & Water Authority", "Utilities", 6200, 2800, 0.15, 15, 1, 15
    ),
    RecurringSpec("Gulf Telecom B.S.C.", "Utilities", 6200, 640, 0.05, 10, 1, 15),
    RecurringSpec(
        "BrightClean Facility Services W.L.L.", "Repairs & maintenance", 6800, 1250, 0, 3, 1, 15
    ),
    RecurringSpec(
        "Sentinel Security Services W.L.L.", "Repairs & maintenance", 6800, 3100, 0, 3, 1, 15
    ),
    RecurringSpec("CloudDesk Software Ltd", "IT & software", 6500, 1890, 0.03, 8, 1, 30),
    RecurringSpec("Al Watan Insurance B.S.C.", "Insurance", 7000, 11750, 0, 12, 3, 30),
]
RECURRING_CLERK_GROUP = {6100: 2, 6200: 2, 6800: 2, 6500: 1, 7000: 2}

FIRST_NAMES = [
    "Ahmed",
    "Mohammed",
    "Fatima",
    "Zainab",
    "Hassan",
    "Ali",
    "Khalid",
    "Noor",
    "Layla",
    "Omar",
    "Yousif",
    "Maryam",
    "Ebrahim",
    "Sara",
    "Jassim",
    "Hessa",
    "Priya",
    "Rahul",
    "Anil",
    "Sunita",
    "Maria",
    "Jose",
    "Grace",
    "Ramon",
    "James",
    "Emma",
    "Daniel",
    "Olivia",
    "Tariq",
    "Huda",
]
LAST_NAMES = [
    "Al Khalifa",
    "Hassan",
    "Jaffar",
    "Mansoor",
    "Ebrahim",
    "Salman",
    "Abbas",
    "Yusuf",
    "Nasser",
    "Fakhro",
    "Sharma",
    "Nair",
    "Menon",
    "Pillai",
    "Santos",
    "Reyes",
    "Cruz",
    "Bennett",
    "Clarke",
    "Murray",
    "Alawi",
    "Dawood",
    "Kooheji",
    "Zayani",
    "Matar",
    "Buhijji",
    "Sabt",
    "Rashid",
]
AREAS = [
    "Manama",
    "Muharraq",
    "Riffa",
    "Isa Town",
    "Hamad Town",
    "Sitra",
    "Seef",
    "Juffair",
    "Budaiya",
    "Sanad",
    "Amwaj Islands",
    "Tubli",
    "Adliya",
    "Zallaq",
]
BANK_CODES = ["NBOB", "BBKU", "BMAG", "AUBB", "ABCO", "KHCB", "ALSA", "CITI", "HSBC", "SCBL"]
DEPARTMENTS = ["Sales", "Operations", "Finance", "Administration"]
VENDOR_SUFFIXES = ["W.L.L.", "Co.", "Trading", "B.S.C. (c)", "Group", "& Sons", "International"]


@dataclass
class VendorMeta:
    """Generation-only attributes of a vendor (not written to the dataset)."""

    vendor_id: str
    category: str
    account: int
    decade_weights: dict[int, float]
    activity: float
    clerk: str
    recurring: RecurringSpec | None = None


@dataclass
class MasterData:
    """All master data, as plain rows (turned into DataFrames by the generator)."""

    accounts: list[dict] = field(default_factory=list)
    users: list[dict] = field(default_factory=list)
    employees: list[dict] = field(default_factory=list)
    vendors: list[dict] = field(default_factory=list)
    bank_changes: list[dict] = field(default_factory=list)
    vendor_meta: dict[str, VendorMeta] = field(default_factory=dict)
    users_by_role: dict[str, list[str]] = field(default_factory=dict)


def make_address(rng: np.random.Generator) -> str:
    """A plausible Bahrain-style address."""
    return (
        f"Flat {rng.integers(1, 60)}, Bldg {rng.integers(1, 3000)}, Road {rng.integers(1, 4000)}, "
        f"Block {rng.integers(100, 1100)}, {rng.choice(AREAS)}, Kingdom of Bahrain"
    )


def make_bank_account(rng: np.random.Generator) -> str:
    """A Bahrain IBAN-shaped string (22 chars; check digits are not real)."""
    digits = "".join(str(d) for d in rng.integers(0, 10, size=14))
    return f"BH{rng.integers(10, 99)}{rng.choice(BANK_CODES)}{digits}"


def _person_name(rng: np.random.Generator) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def make_users(cfg: Config, rng: np.random.Generator, md: MasterData) -> None:
    """Create the user table from the role hierarchy in config (plus the SYSTEM user)."""
    used: set[str] = set()
    for role, rcfg in cfg.roles.items():
        md.users_by_role[role] = []
        for _ in range(rcfg.count):
            while True:
                name = _person_name(rng)
                first, last = name.split(" ", 1)
                uid = (first[0] + last.replace(" ", "")).lower()
                if uid not in used:
                    break
            used.add(uid)
            md.users_by_role[role].append(uid)
            md.users.append(
                {
                    "user_id": uid,
                    "full_name": name,
                    "role": role,
                    "approval_limit": rcfg.approval_limit,
                    "department": "Finance",
                }
            )
    md.users.append(
        {
            "user_id": SYSTEM_USER,
            "full_name": "Automated batch / interface",
            "role": "system",
            "approval_limit": 0.0,
            "department": "IT",
        }
    )


def make_employees(cfg: Config, rng: np.random.Generator, md: MasterData) -> None:
    """Employees with a home address and a salary bank account."""
    for i in range(cfg.generation.n_employees):
        md.employees.append(
            {
                "employee_id": f"E{i + 1:04d}",
                "full_name": _person_name(rng),
                "address": make_address(rng),
                "bank_account": make_bank_account(rng),
                "department": str(rng.choice(DEPARTMENTS)),
            }
        )


def _vendor_row(
    vid: str, name: str, address: str, bank: str, created: date, cat: str, terms: int
) -> dict:
    return {
        "vendor_id": vid,
        "vendor_name": name,
        "address": address,
        "bank_account": bank,
        "created_date": created.isoformat(),
        "category": cat,
        "payment_terms_days": terms,
    }


def make_vendors(cfg: Config, rng: np.random.Generator, fake: Faker, md: MasterData) -> None:
    """Regular vendors (by category) plus fixed-schedule recurring vendors."""
    fy_start = date(cfg.company.fiscal_year, 1, 1)
    clerks = md.users_by_role["ap_clerk"]
    counts = {c: max(1, round(cfg.generation.n_vendors * v.n_share)) for c, v in CATEGORIES.items()}
    n = 0
    for cat_name, cat in CATEGORIES.items():
        for _ in range(counts[cat_name]):
            n += 1
            vid = f"V{n:04d}"
            if rng.random() < 0.10:  # a vendor onboarded during the year
                created = fy_start + timedelta(days=int(rng.integers(0, 180)))
            else:
                created = fy_start - timedelta(days=int(rng.integers(30, 3000)))
            name = f"{fake.last_name()} {cat_name.split()[0]} {rng.choice(VENDOR_SUFFIXES)}"
            md.vendors.append(
                _vendor_row(
                    vid,
                    name,
                    make_address(rng),
                    make_bank_account(rng),
                    created,
                    cat_name,
                    int(rng.choice([30, 45, 60])),
                )
            )
            activity = cat.activity * float(rng.lognormal(0.0, 0.5))
            md.vendor_meta[vid] = VendorMeta(
                vid, cat_name, cat.account, cat.decade_weights, activity, clerks[cat.clerk_group]
            )
    for spec in RECURRING:
        n += 1
        vid = f"V{n:04d}"
        created = fy_start - timedelta(days=int(rng.integers(400, 3000)))
        md.vendors.append(
            _vendor_row(
                vid,
                spec.name,
                make_address(rng),
                make_bank_account(rng),
                created,
                spec.category,
                spec.terms_days,
            )
        )
        clerk = clerks[RECURRING_CLERK_GROUP[spec.account]]
        md.vendor_meta[vid] = VendorMeta(vid, spec.category, spec.account, {}, 0.0, clerk, spec)


def add_bank_change(
    md: MasterData, rng: np.random.Generator, vendor_id: str, change_date: date, changed_by: str
) -> None:
    """Record a vendor bank-account change and update the vendor master to the new account."""
    row = next(v for v in md.vendors if v["vendor_id"] == vendor_id)
    new_account = make_bank_account(rng)
    md.bank_changes.append(
        {
            "change_id": f"BC{len(md.bank_changes) + 1:04d}",
            "vendor_id": vendor_id,
            "change_date": change_date.isoformat(),
            "old_bank_account": row["bank_account"],
            "new_bank_account": new_account,
            "changed_by": changed_by,
        }
    )
    row["bank_account"] = new_account


def make_chart_of_accounts(md: MasterData) -> None:
    """Fill the chart of accounts table."""
    md.accounts = [{"account": a, "account_name": n, "account_type": t} for a, n, t in ACCOUNTS]


def build_master_data(cfg: Config, rng: np.random.Generator, fake: Faker) -> MasterData:
    """Create all master data, including a few legitimate vendor bank-account changes."""
    md = MasterData()
    make_chart_of_accounts(md)
    make_users(cfg, rng, md)
    make_employees(cfg, rng, md)
    make_vendors(cfg, rng, fake, md)
    fy = cfg.company.fiscal_year
    goods = [v for v, m in md.vendor_meta.items() if m.category == "Goods supplier"]
    for vid in rng.choice(goods, size=3, replace=False):  # legitimate changes, mid-year
        change = date(fy, int(rng.integers(2, 9)), int(rng.integers(1, 28)))
        add_bank_change(md, rng, str(vid), change, md.users_by_role["accountant"][0])
    return md
