"""Loading the data the audit tests run on, and building the one-row-per-entry view."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from auditlens.config import DATA_DIR, Config

HEADER_COLS = [
    "document_date",
    "posting_date",
    "period",
    "source",
    "created_by",
    "approved_by",
    "vendor_id",
    "invoice_number",
    "description",
]


def build_entries(journal: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Collapse journal lines to one row per entry, with amount and account sets.

    `amount` is the total debit. `is_invoice` / `is_payment` identify vendor invoices
    (credit to payables) and vendor payments (debit payables, credit cash) from the account
    codes in config.accounts, so they work without any internal generator knowledge.
    """
    g = journal.groupby("entry_id", sort=False)
    entries = g[HEADER_COLS].first()
    entries["amount"] = g["debit"].sum().round(3)
    entries["n_lines"] = g.size()
    debit_accts = (
        journal[journal["debit"] > 0]
        .groupby("entry_id")["account"]
        .agg(lambda s: tuple(sorted(set(s))))
    )
    credit_accts = (
        journal[journal["credit"] > 0]
        .groupby("entry_id")["account"]
        .agg(lambda s: tuple(sorted(set(s))))
    )
    entries["debit_accounts"] = debit_accts
    entries["credit_accounts"] = credit_accts
    pay, cash = cfg.accounts.payables, cfg.accounts.cash
    has_vendor = entries["vendor_id"].notna()
    entries["is_invoice"] = (
        has_vendor
        & entries["invoice_number"].notna()
        & entries["credit_accounts"].map(lambda t: pay in t)
        & ~entries["debit_accounts"].map(lambda t: pay in t)
    )
    entries["is_payment"] = (
        has_vendor
        & entries["debit_accounts"].map(lambda t: pay in t)
        & entries["credit_accounts"].map(lambda t: cash in t)
    )
    return entries.reset_index()


@dataclass
class Dataset:
    """Journal plus optional master data. Rules that need absent master data simply skip."""

    journal: pd.DataFrame
    cfg: Config
    vendors: pd.DataFrame = field(default_factory=pd.DataFrame)
    employees: pd.DataFrame = field(default_factory=pd.DataFrame)
    users: pd.DataFrame = field(default_factory=pd.DataFrame)
    bank_changes: pd.DataFrame = field(default_factory=pd.DataFrame)
    accounts: pd.DataFrame = field(default_factory=pd.DataFrame)
    entries: pd.DataFrame = field(init=False)

    def __post_init__(self) -> None:
        self.entries = build_entries(self.journal, self.cfg)

    @classmethod
    def from_dir(cls, cfg: Config, data_dir: Path | str = DATA_DIR) -> Dataset:
        """Load journal_entries.csv and any master data files found in the directory."""
        d = Path(data_dir)
        journal = pd.read_csv(
            d / "journal_entries.csv", parse_dates=["document_date", "posting_date"]
        )
        extras = {}
        for name, attr in [
            ("vendors", "vendors"),
            ("employees", "employees"),
            ("users", "users"),
            ("vendor_bank_changes", "bank_changes"),
            ("chart_of_accounts", "accounts"),
        ]:
            path = d / f"{name}.csv"
            if path.exists():
                extras[attr] = pd.read_csv(path)
        if "bank_changes" in extras:
            extras["bank_changes"]["change_date"] = pd.to_datetime(
                extras["bank_changes"]["change_date"]
            )
        return cls(journal=journal, cfg=cfg, **extras)

    @property
    def invoices(self) -> pd.DataFrame:
        """Vendor invoice entries."""
        return self.entries[self.entries["is_invoice"]]

    @property
    def payments(self) -> pd.DataFrame:
        """Vendor payment entries."""
        return self.entries[self.entries["is_payment"]]


def load_labels(data_dir: Path | str = DATA_DIR) -> pd.DataFrame:
    """Ground-truth labels. Only evaluation code and the Evaluation page may call this."""
    return pd.read_csv(Path(data_dir) / "labels.csv")
