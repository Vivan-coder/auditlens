"""Excel audit workpaper (openpyxl): cover sheet, flagged entries, status summary.

Layout follows common working-paper practice: purpose, scope, procedures, results, conclusion and
sign-off on a cover sheet; the detail on a filterable, print-ready sheet with reviewer status.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

NAVY = "1F3A5F"
HEADER_FILL = PatternFill("solid", fgColor=NAVY)
HEADER_FONT = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
THIN = Side(style="thin", color="D0D4DA")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
TIER_FILLS = {
    "High": PatternFill("solid", fgColor="F8D7D5"),
    "Medium": PatternFill("solid", fgColor="FCEBC4"),
}
STATUS_VALUES = ["Pending", "Reviewed", "False positive"]

# (header, queue column, width, number format)
COLUMNS: list[tuple[str, str, int, str | None]] = [
    ("Rank", "rank", 7, "0"),
    ("Entry ID", "entry_id", 12, None),
    ("Risk score", "risk_score", 11, "0.0"),
    ("Risk tier", "risk_tier", 10, None),
    ("Posting date", "posting_date", 13, "yyyy-mm-dd"),
    ("Amount (BHD)", "amount", 16, "#,##0.000"),
    ("Vendor", "vendor_id", 10, None),
    ("Created by", "created_by", 14, None),
    ("Approved by", "approved_by", 14, None),
    ("Source", "source", 11, None),
    ("Description", "description", 38, None),
    ("Rule codes", "rule_codes", 34, None),
    ("Reasons flagged", "reasons", 90, None),
]
STATUS_COL, NOTES_COL = "Reviewer status", "Reviewer notes"
WRAP_HEADERS = {"Description", "Rule codes", "Reasons flagged", NOTES_COL}

DEFAULT_PROCEDURES = [
    "Duplicate payment tests (same invoice, identical and near-identical amounts)",
    "Approval tests (split purchases below limits, self-approval, missing or weak approver)",
    "Timing tests (weekend and public-holiday postings, post-close and backdated entries)",
    "Amount tests (round sums, large manual journals near period end)",
    "Vendor tests (vendor/employee bank or address match, bank change before large payment)",
    "Invoice-sequence tests (gaps, out-of-order and repeated numbers)",
    "Benford's Law first-digit analysis by vendor (chi-square)",
    "Unusual account pairings and rare user/account combinations",
    "Unsupervised anomaly scoring (Isolation Forest) for unusual entries no rule describes",
]


def _header_row(ws, headers: list[str]) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.fill, cell.font, cell.border = HEADER_FILL, HEADER_FONT, BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30


def _clean(v):
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime().date()
    return None if pd.isna(v) else v


def _write_entries_sheet(ws, queue: pd.DataFrame, status: dict[str, str], notes: dict[str, str]):
    headers = [c[0] for c in COLUMNS] + [STATUS_COL, NOTES_COL]
    _header_row(ws, headers)
    for row in queue.itertuples(index=False):
        values = [_clean(getattr(row, col)) for _, col, _, _ in COLUMNS]
        values += [status.get(row.entry_id, "Pending"), notes.get(row.entry_id, "")]
        ws.append(values)
    for i, (_, _, width, fmt) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
        if fmt:
            for cell in ws[get_column_letter(i)][1:]:
                cell.number_format = fmt
    n = len(COLUMNS)
    ws.column_dimensions[get_column_letter(n + 1)].width = 16
    ws.column_dimensions[get_column_letter(n + 2)].width = 40
    tier_col, score_col = headers.index("Risk tier") + 1, headers.index("Risk score") + 1
    for r in range(2, ws.max_row + 1):
        for c, h in enumerate(headers, start=1):
            cell = ws.cell(r, c)
            cell.border = BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=h in WRAP_HEADERS)
        fill = TIER_FILLS.get(str(ws.cell(r, tier_col).value))
        if fill:
            ws.cell(r, tier_col).fill = fill
            ws.cell(r, score_col).fill = fill
    if ws.max_row > 1:  # drop-down so reviewers cannot mistype a status
        dv = DataValidation(
            type="list", formula1='"' + ",".join(STATUS_VALUES) + '"', allow_blank=True
        )
        ws.add_data_validation(dv)
        col = get_column_letter(n + 1)
        dv.add(f"{col}2:{col}{ws.max_row}")
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(n + 2)}{max(ws.max_row, 1)}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = "1:1"
    ws.oddFooter.center.text = "AuditLens - page &P of &N"


def _write_summary_sheet(ws, queue: pd.DataFrame, status: dict[str, str], dataset_name: str):
    counts = {
        s: sum(1 for e in queue["entry_id"] if status.get(e, "Pending") == s) for s in STATUS_VALUES
    }
    tiers = queue["risk_tier"].value_counts()
    rows = [
        ("Status summary", ""),
        ("Dataset", dataset_name),
        ("Generated", date.today().isoformat()),
        ("Entries in this workpaper", len(queue)),
        ("Total value of listed entries (BHD)", round(float(queue["amount"].sum()), 3)),
        ("", ""),
        *[(f"Risk tier: {t}", int(tiers.get(t, 0))) for t in ("High", "Medium", "Low")],
        ("", ""),
        *[(f"Status: {k}", v) for k, v in counts.items()],
    ]
    for r in rows:
        ws.append(list(r))
    ws["A1"].font = Font(bold=True, size=14, color=NAVY)
    for r in range(2, ws.max_row + 1):
        ws.cell(r, 1).font = Font(bold=True)
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 60
    ws["B5"].number_format = "#,##0.000"


def _section(ws, row: int, title: str) -> int:
    ws.cell(row, 1, title).font = Font(bold=True, size=11, color="FFFFFF")
    for c in (1, 2):
        ws.cell(row, c).fill = HEADER_FILL
    return row + 1


def _kv(ws, r: int, key: str, value, wrap: bool = False) -> int:
    ws.cell(r, 1, key).font = Font(bold=True)
    cell = ws.cell(r, 2, value)
    cell.alignment = Alignment(wrap_text=wrap, vertical="top", horizontal="left")
    return r + 1


def _write_cover_sheet(ws, queue: pd.DataFrame, meta: dict, procedures: list[str], n_scanned):
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 95
    ws["A1"] = "Journal entry analytics: exceptions workpaper"
    ws["A1"].font = Font(bold=True, size=16, color=NAVY)
    ws["A2"] = "Prepared with AuditLens. Screening output for auditor judgement, not a conclusion."
    ws["A2"].font = Font(italic=True, color="52514E")
    r = _section(ws, 4, "Engagement details")
    for k, v in [
        ("Entity", meta["entity"]),
        ("Period", meta["period"]),
        ("Data source", meta["dataset"]),
        ("Prepared by", meta["preparer"]),
        ("Date prepared", date.today().isoformat()),
        ("Reviewed by", meta["reviewer"]),
        ("Date reviewed", ""),
    ]:
        r = _kv(ws, r, k, v)
    r = _section(ws, r + 1, "Purpose")
    r = _kv(
        ws,
        r,
        "Objective",
        "Identify journal entries with characteristics associated with error or management "
        "override of controls, to focus audit procedures (ISA 240).",
        wrap=True,
    )
    r = _section(ws, r + 1, "Scope")
    r = _kv(ws, r, "Entries scanned", n_scanned if n_scanned is not None else "n/a")
    r = _kv(ws, r, "Entries listed in this workpaper", len(queue))
    r = _kv(ws, r, "Total value of listed entries (BHD)", round(float(queue["amount"].sum()), 3))
    ws.cell(r - 1, 2).number_format = "#,##0.000"
    r = _section(ws, r + 1, "Procedures performed")
    for i, p in enumerate(procedures, start=1):
        ws.cell(r, 1, f"{i}.").alignment = Alignment(horizontal="right")
        ws.cell(r, 2, p).alignment = Alignment(wrap_text=True, vertical="top")
        r += 1
    r = _section(ws, r + 1, "Legend")
    r = _kv(
        ws,
        r,
        "Risk tier: High / Medium / Low",
        "Combined risk score bands (rule evidence plus anomaly score). High and Medium warrant "
        "follow-up; Low entries can be sampled.",
        wrap=True,
    )
    r = _kv(
        ws,
        r,
        "Reviewer status",
        "Pending (not yet looked at), Reviewed (follow-up done), False positive (explained and "
        "cleared). Use the drop-down on the entries sheet.",
        wrap=True,
    )
    r = _section(ws, r + 1, "Results and conclusion (to be completed by the auditor)")
    for _ in range(4):
        ws.cell(r, 2).border = Border(bottom=THIN)
        r += 1
    _kv(
        ws,
        r + 1,
        "Limitations",
        "Flags are indicators, not findings. Rules use fixed thresholds and the anomaly model only "
        "detects statistically unusual entries. Each flag needs supporting evidence before any "
        "finding is raised.",
        wrap=True,
    )
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def build_workpaper(
    queue: pd.DataFrame,
    status: dict[str, str] | None = None,
    notes: dict[str, str] | None = None,
    dataset_name: str = "AuditLens dataset",
    *,
    entity: str = "",
    period: str = "",
    preparer: str = "",
    reviewer: str = "",
    n_scanned: int | None = None,
    procedures: list[str] | None = None,
) -> bytes:
    """Return the .xlsx bytes: Cover, Flagged entries (with reviewer status) and Summary sheets."""
    status, notes = status or {}, notes or {}
    q = queue if "risk_tier" in queue else queue.assign(risk_tier="")
    wb = Workbook()
    cover = wb.active
    cover.title = "Cover"
    meta = {
        "entity": entity,
        "period": period,
        "dataset": dataset_name,
        "preparer": preparer,
        "reviewer": reviewer,
    }
    _write_cover_sheet(cover, q, meta, procedures or DEFAULT_PROCEDURES, n_scanned)
    _write_entries_sheet(wb.create_sheet("Flagged entries"), q, status, notes)
    _write_summary_sheet(wb.create_sheet("Summary"), q, status, dataset_name)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
