"""Excel audit workpaper of flagged entries (openpyxl): header, reasons, reviewer status."""

from __future__ import annotations

from datetime import date
from io import BytesIO

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
THIN = Side(style="thin", color="D0D4DA")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
RISK_FILLS = {
    "high": PatternFill("solid", fgColor="F8D7D5"),
    "medium": PatternFill("solid", fgColor="FCEBC4"),
}
STATUS_VALUES = ["Pending", "Reviewed", "False positive"]

# (header, queue column, width, number format)
COLUMNS: list[tuple[str, str, int, str | None]] = [
    ("Rank", "rank", 7, "0"),
    ("Entry ID", "entry_id", 12, None),
    ("Risk score", "risk_score", 11, "0.0"),
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


def _risk_fill(score: float) -> PatternFill | None:
    """Shade the risk cell: red at 50+, amber at 25+."""
    if score >= 50:
        return RISK_FILLS["high"]
    if score >= 25:
        return RISK_FILLS["medium"]
    return None


def _write_entries_sheet(ws, queue: pd.DataFrame, status: dict[str, str], notes: dict[str, str]):
    headers = [c[0] for c in COLUMNS] + [STATUS_COL, NOTES_COL]
    ws.append(headers)
    for cell in ws[1]:
        cell.fill, cell.font, cell.border = HEADER_FILL, HEADER_FONT, BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30
    for row in queue.itertuples(index=False):
        values = []
        for _, col, _, _ in COLUMNS:
            v = getattr(row, col)
            if isinstance(v, pd.Timestamp):
                v = v.to_pydatetime().date()
            elif pd.isna(v):
                v = None
            values.append(v)
        eid = row.entry_id
        values += [status.get(eid, "Pending"), notes.get(eid, "")]
        ws.append(values)
    for i, (_, _, width, fmt) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
        if fmt:
            for cell in ws[get_column_letter(i)][1:]:
                cell.number_format = fmt
    n = len(COLUMNS)
    ws.column_dimensions[get_column_letter(n + 1)].width = 16
    ws.column_dimensions[get_column_letter(n + 2)].width = 40
    risk_col = [c[1] for c in COLUMNS].index("risk_score") + 1
    for r in range(2, ws.max_row + 1):
        for c in range(1, n + 3):
            cell = ws.cell(r, c)
            cell.border = BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=c in (10, 11, 12, n + 2))
        fill = _risk_fill(float(ws.cell(r, risk_col).value or 0))
        if fill:
            ws.cell(r, risk_col).fill = fill
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(n + 2)}{max(ws.max_row, 1)}"


def _write_summary_sheet(ws, queue: pd.DataFrame, status: dict[str, str], dataset_name: str):
    counts = {
        s: sum(1 for e in queue["entry_id"] if status.get(e, "Pending") == s) for s in STATUS_VALUES
    }
    rows = [
        ("AuditLens workpaper", ""),
        ("Dataset", dataset_name),
        ("Generated", date.today().isoformat()),
        ("Entries in this workpaper", len(queue)),
        ("Total value of listed entries (BHD)", round(float(queue["amount"].sum()), 3)),
        ("", ""),
        *[(f"Status: {k}", v) for k, v in counts.items()],
        ("", ""),
        (
            "Note",
            "Risk scores are screening indicators, not conclusions. Each flag needs auditor "
            "judgement and supporting evidence before any finding is raised.",
        ),
    ]
    for r in rows:
        ws.append(list(r))
    ws["A1"].font = Font(bold=True, size=14, color="1F3A5F")
    for r in range(2, ws.max_row + 1):
        ws.cell(r, 1).font = Font(bold=True)
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 80
    ws["B5"].number_format = "#,##0.000"
    ws["B" + str(ws.max_row)].alignment = Alignment(wrap_text=True, vertical="top")


def build_workpaper(
    queue: pd.DataFrame,
    status: dict[str, str] | None = None,
    notes: dict[str, str] | None = None,
    dataset_name: str = "AuditLens dataset",
) -> bytes:
    """Return the .xlsx bytes for the given queue rows with reviewer status and notes."""
    status, notes = status or {}, notes or {}
    wb = Workbook()
    ws = wb.active
    ws.title = "Flagged entries"
    _write_entries_sheet(ws, queue, status, notes)
    _write_summary_sheet(wb.create_sheet("Summary"), queue, status, dataset_name)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
