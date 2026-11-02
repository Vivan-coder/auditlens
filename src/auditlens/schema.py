"""Schema and validation for uploaded journal CSVs (column mapping, pydantic row checks).

Required columns: entry_id, posting_date, account, debit, credit. Everything else is optional;
rules that need missing columns simply do not run. Errors are specific (row, column, problem) so a
user can fix the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

REQUIRED_FIELDS = ["entry_id", "posting_date", "account", "debit", "credit"]
OPTIONAL_FIELDS = [
    "line_id",
    "document_date",
    "description",
    "vendor_id",
    "created_by",
    "approved_by",
    "source",
    "invoice_number",
    "period",
]
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS
DATE_FIELDS = ["posting_date", "document_date"]
TEXT_FIELDS = ["description", "vendor_id", "created_by", "approved_by", "invoice_number", "period"]
BALANCE_TOLERANCE = 0.01

SYNONYMS: dict[str, list[str]] = {
    "entry_id": [
        "entryid",
        "entry",
        "journalid",
        "journalentry",
        "jeid",
        "jenumber",
        "documentnumber",
        "docno",
        "voucher",
        "transactionid",
    ],
    "line_id": ["lineid", "line", "lineno", "linenumber", "lineitem"],
    "posting_date": ["postingdate", "postdate", "gldate", "bookingdate", "date", "entrydate"],
    "document_date": ["documentdate", "docdate", "invoicedate", "transactiondate", "effectivedate"],
    "account": [
        "account",
        "accountcode",
        "accountno",
        "accountnumber",
        "glaccount",
        "glcode",
        "acct",
    ],
    "debit": ["debit", "dr", "debitamount", "amountdr"],
    "credit": ["credit", "cr", "creditamount", "amountcr"],
    "description": ["description", "memo", "narration", "text", "details", "narrative"],
    "vendor_id": ["vendorid", "vendor", "vendorcode", "supplier", "supplierid", "suppliercode"],
    "created_by": ["createdby", "preparedby", "user", "userid", "enteredby", "creator", "poster"],
    "approved_by": ["approvedby", "approver", "authorisedby", "authorizedby", "reviewedby"],
    "source": ["source", "entrytype", "sourcetype", "origin", "manualauto"],
    "invoice_number": ["invoicenumber", "invoiceno", "invoice", "invno", "reference", "refno"],
    "period": ["period", "fiscalperiod", "accountingperiod", "glperiod"],
}


def normalise_name(name: str) -> str:
    """Lowercase letters and digits only, for matching column names."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def suggest_mapping(columns: list[str]) -> dict[str, str | None]:
    """Guess which uploaded column holds each standard field (None when no good match)."""
    by_norm = {normalise_name(c): c for c in columns}
    used: set[str] = set()
    mapping: dict[str, str | None] = {}
    for f in ALL_FIELDS:
        found = None
        for candidate in [f.replace("_", ""), *SYNONYMS.get(f, [])]:
            col = by_norm.get(candidate)
            if col is not None and col not in used:
                found = col
                break
        mapping[f] = found
        if found:
            used.add(found)
    return mapping


def apply_mapping(df: pd.DataFrame, mapping: dict[str, str | None]) -> pd.DataFrame:
    """Rename mapped columns to the standard names and drop the rest."""
    chosen = {v: k for k, v in mapping.items() if v}
    return df[list(chosen)].rename(columns=chosen)


class JournalLine(BaseModel):
    """One journal line after mapping. Validation messages are written for end users."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    entry_id: str
    posting_date: date
    account: int
    debit: float = 0.0
    credit: float = 0.0
    line_id: str | None = None
    document_date: date | None = None
    description: str | None = None
    vendor_id: str | None = None
    created_by: str | None = None
    approved_by: str | None = None
    source: Literal["manual", "automated"] | None = None
    invoice_number: str | None = None
    period: str | None = None

    @field_validator("entry_id", mode="before")
    @classmethod
    def _entry_id(cls, v: object) -> object:
        if v is None or str(v).strip() == "":
            raise ValueError("entry_id is required")
        return str(v)

    @field_validator("account", mode="before")
    @classmethod
    def _account(cls, v: object) -> object:
        if v is None or str(v).strip() == "":
            raise ValueError("account is required")
        try:
            f = float(str(v).replace(",", ""))
        except ValueError as exc:
            raise ValueError(f"account must be a number, got '{v}'") from exc
        if f != int(f):
            raise ValueError(f"account must be a whole number, got '{v}'")
        return int(f)

    @field_validator("debit", "credit", mode="before")
    @classmethod
    def _amount(cls, v: object) -> object:
        if v is None or str(v).strip() == "":
            return 0.0
        try:
            x = float(str(v).replace(",", ""))
        except ValueError as exc:
            raise ValueError(f"amount must be a number, got '{v}'") from exc
        if x < 0:
            raise ValueError("amounts must not be negative (use the other column for reversals)")
        return x

    @field_validator("source", mode="before")
    @classmethod
    def _source(cls, v: object) -> object:
        if v is None or str(v).strip() == "":
            return None
        s = str(v).strip().lower()
        if s in {"manual", "m", "man", "user", "keyed"}:
            return "manual"
        if s in {"automated", "automatic", "auto", "a", "system", "interface", "batch"}:
            return "automated"
        raise ValueError(f"source must be 'manual' or 'automated', got '{v}'")

    @field_validator(*TEXT_FIELDS, "line_id", mode="before")
    @classmethod
    def _text(cls, v: object) -> object:
        if v is None or str(v).strip() == "":
            return None
        return str(v)

    @model_validator(mode="after")
    def _one_side(self) -> JournalLine:
        if self.debit > 0 and self.credit > 0:
            raise ValueError("a line cannot have both a debit and a credit amount")
        if self.debit == 0 and self.credit == 0:
            raise ValueError("a line must have a debit or a credit amount")
        return self


@dataclass
class ValidationResult:
    """Outcome of validating an uploaded file."""

    journal: pd.DataFrame | None
    errors: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    n_rows: int = 0
    n_entries: int = 0

    @property
    def ok(self) -> bool:
        """True when the file can be analysed."""
        return self.journal is not None and not self.errors


def strict_dates(values: pd.Series, dayfirst: bool) -> pd.Series:
    """Parse dates with an explicit list of formats; never guess a day/month swap.

    ISO (2025-03-31) is always accepted. Slash and dash dates follow the chosen order only, so
    a day-first file read as month-first fails loudly instead of silently swapping day and month.
    """
    s = values.astype("string").str.strip()
    order = ["%d", "%m"] if dayfirst else ["%m", "%d"]
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d",
        f"{order[0]}/{order[1]}/%Y",
        f"{order[0]}-{order[1]}-%Y",
        f"{order[0]}/{order[1]}/%Y %H:%M:%S",
    ]
    out = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    for fmt in formats:
        todo = out.isna() & s.notna()
        if not todo.any():
            break
        out[todo] = pd.to_datetime(s[todo], format=fmt, errors="coerce")
    return out


def _parse_dates(df: pd.DataFrame, dayfirst: bool, errors: list[dict], max_errors: int) -> None:
    """Convert date columns in place to python dates, recording unparseable values."""
    for col in DATE_FIELDS:
        if col not in df.columns:
            continue
        raw = df[col]
        parsed = strict_dates(raw, dayfirst)
        bad = parsed.isna() & raw.notna() & (raw.astype(str).str.strip() != "")
        hint = "day first" if dayfirst else "month first (or ISO year-first)"
        for idx in df.index[bad][: max(0, max_errors - len(errors))]:
            errors.append(
                {
                    "row": int(idx) + 2,
                    "column": col,
                    "problem": f"'{raw[idx]}' is not a valid date for the chosen format ({hint})",
                    "value": str(raw[idx]),
                }
            )
        df[col] = parsed.dt.date.where(parsed.notna(), None)


def _validate_rows(df: pd.DataFrame, errors: list[dict], max_errors: int) -> list[dict | None]:
    """Run the pydantic model over every row; returns validated dicts (None where invalid)."""
    out: list[dict | None] = []
    records = df.astype(object).where(df.notna(), None).to_dict("records")
    for idx, rec in zip(df.index, records, strict=True):
        try:
            out.append(JournalLine.model_validate(rec).model_dump())
        except ValidationError as exc:
            out.append(None)
            for err in exc.errors():
                if len(errors) >= max_errors:
                    break
                loc = str(err["loc"][0]) if err["loc"] else "(row)"
                msg = str(err["msg"]).removeprefix("Value error, ")
                errors.append(
                    {
                        "row": int(idx) + 2,
                        "column": loc,
                        "problem": msg,
                        "value": str(rec.get(loc, "")),
                    }
                )
    return out


def _entry_checks(journal: pd.DataFrame, errors: list[dict], warnings: list[str]) -> None:
    """Entry-level checks: balance, repeated line ids, date order, thin columns."""
    sums = journal.groupby("entry_id")[["debit", "credit"]].sum()
    off = sums[(sums["debit"] - sums["credit"]).abs() > BALANCE_TOLERANCE]
    for eid, r in off.head(50).iterrows():
        errors.append(
            {
                "row": None,
                "column": "entry_id",
                "problem": f"entry {eid} does not balance: debits {r['debit']:,.2f} "
                f"vs credits {r['credit']:,.2f}",
                "value": str(eid),
            }
        )
    if len(off) > 50:
        errors.append(
            {
                "row": None,
                "column": "entry_id",
                "problem": f"... and {len(off) - 50} more unbalanced entries",
                "value": "",
            }
        )
    dup = journal["line_id"][journal["line_id"].duplicated()]
    if len(dup):
        errors.append(
            {
                "row": None,
                "column": "line_id",
                "problem": f"{len(dup)} repeated line_id values (first: {dup.iloc[0]})",
                "value": str(dup.iloc[0]),
            }
        )
    late = (journal["document_date"] > journal["posting_date"]).sum()
    if late:
        warnings.append(f"{late} lines have a document date after the posting date.")


def _fill_defaults(journal: pd.DataFrame, warnings: list[str]) -> pd.DataFrame:
    """Add missing optional columns with sensible defaults and say what was assumed."""
    j = journal.copy()
    if "line_id" not in j or j["line_id"].isna().any():
        seq = j.groupby("entry_id").cumcount() + 1
        base = j["line_id"] if "line_id" in j else pd.Series(None, index=j.index)
        j["line_id"] = base.fillna(j["entry_id"] + "-" + seq.astype(str).str.zfill(2))
    if "document_date" not in j or j["document_date"].isna().any():
        base = j["document_date"] if "document_date" in j else pd.Series(None, index=j.index)
        j["document_date"] = base.fillna(j["posting_date"])
        warnings.append(
            "document_date missing: posting date used (lag and backdating tests are blind)."
        )
    j["posting_date"] = pd.to_datetime(j["posting_date"])
    j["document_date"] = pd.to_datetime(j["document_date"])
    if "period" not in j or j["period"].isna().any():
        base = j["period"] if "period" in j else pd.Series(None, index=j.index)
        j["period"] = base.fillna(j["posting_date"].dt.strftime("%Y-%m"))
    if "source" not in j or j["source"].isna().any():
        base = j["source"] if "source" in j else pd.Series(None, index=j.index)
        j["source"] = base.fillna("manual")
        warnings.append(
            "source missing: entries assumed to be manual (so weekend/round tests apply)."
        )
    for col in ["description", "vendor_id", "created_by", "approved_by", "invoice_number"]:
        if col not in j:
            j[col] = None
        if j[col].isna().all():
            warnings.append(f"{col} not provided: tests that rely on it will not run.")
    cols = [
        "entry_id",
        "line_id",
        "document_date",
        "posting_date",
        "account",
        "debit",
        "credit",
        "description",
        "vendor_id",
        "created_by",
        "approved_by",
        "source",
        "invoice_number",
        "period",
    ]
    return j[cols].reset_index(drop=True)


def validate_journal(
    df: pd.DataFrame, dayfirst: bool = False, max_errors: int = 200
) -> ValidationResult:
    """Validate a (mapped) journal DataFrame; returns the standardised journal when valid."""
    errors: list[dict] = []
    warnings: list[str] = []
    missing = [f for f in REQUIRED_FIELDS if f not in df.columns]
    if missing:
        errors.append(
            {
                "row": None,
                "column": ", ".join(missing),
                "problem": "required column(s) not mapped",
                "value": "",
            }
        )
        return ValidationResult(None, errors, warnings, len(df), 0)
    if df.empty:
        errors.append(
            {"row": None, "column": "(file)", "problem": "the file has no rows", "value": ""}
        )
        return ValidationResult(None, errors, warnings, 0, 0)
    work = df.copy()
    _parse_dates(work, dayfirst, errors, max_errors)
    rows = _validate_rows(work, errors, max_errors)
    if any(r is None for r in rows):
        return ValidationResult(None, errors, warnings, len(df), 0)
    journal = pd.DataFrame([r for r in rows if r is not None])
    journal = journal[[c for c in ALL_FIELDS if c in journal.columns]]
    journal = _fill_defaults(journal, warnings)
    _entry_checks(journal, errors, warnings)
    n_entries = journal["entry_id"].nunique()
    return ValidationResult(None if errors else journal, errors, warnings, len(df), n_entries)


def template_csv() -> str:
    """A small valid example file users can download and adapt."""
    return (
        "entry_id,line_id,document_date,posting_date,account,debit,credit,description,vendor_id,"
        "created_by,approved_by,source,invoice_number,period\n"
        "JE000001,JE000001-01,2025-03-02,2025-03-02,6300,1500.000,0,Consulting invoice,V0001,"
        "clerk1,acct1,manual,INV-000101,2025-03\n"
        "JE000001,JE000001-02,2025-03-02,2025-03-02,2000,0,1500.000,Consulting invoice,V0001,"
        "clerk1,acct1,manual,INV-000101,2025-03\n"
    )
