"""Excel workpaper export."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
from openpyxl import load_workbook

from auditlens.export import COLUMNS, DEFAULT_PROCEDURES, build_workpaper


def sample_queue() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rank": [1, 2],
            "entry_id": ["JE1", "JE2"],
            "risk_score": [72.5, 12.0],
            "risk_tier": ["High", "Low"],
            "posting_date": pd.to_datetime(["2025-03-02", "2025-04-10"]),
            "amount": [25000.125, 480.0],
            "vendor_id": ["V1", None],
            "created_by": ["clerk1", "acct1"],
            "approved_by": ["clerk1", None],
            "source": ["manual", "automated"],
            "description": ["Invoice", "Payroll"],
            "rule_codes": ["SELF_APPROVED;ROUND_AMOUNT", "ML_ANOMALY"],
            "reasons": ["Created and approved by the same user (clerk1) | Amount is round", "odd"],
        }
    )


def load(data: bytes):
    return load_workbook(BytesIO(data))


def row_dict(ws, r: int) -> dict:
    headers = [c.value for c in ws[1]]
    return {h: ws.cell(r, i + 1).value for i, h in enumerate(headers)}


def test_workbook_sheets_in_order():
    wb = load(build_workpaper(sample_queue()))
    assert wb.sheetnames == ["Cover", "Flagged entries", "Summary"]


def test_entries_sheet_header_reasons_status_and_notes():
    wb = load(build_workpaper(sample_queue(), {"JE1": "Reviewed"}, {"JE1": "checked invoice"}))
    ws = wb["Flagged entries"]
    headers = [c.value for c in ws[1]]
    assert headers[: len(COLUMNS)] == [c[0] for c in COLUMNS]
    assert headers[-2:] == ["Reviewer status", "Reviewer notes"]
    assert ws["A1"].font.bold and ws["A1"].fill.fgColor.rgb.endswith("1F3A5F")
    assert ws.freeze_panes == "C2" and ws.auto_filter.ref.startswith("A1:")
    r2, r3 = row_dict(ws, 2), row_dict(ws, 3)
    assert r2["Entry ID"] == "JE1" and r2["Reviewer status"] == "Reviewed"
    assert r2["Reviewer notes"] == "checked invoice" and "same user" in r2["Reasons flagged"]
    assert r3["Reviewer status"] == "Pending" and r3["Vendor"] is None


def test_formats_tier_shading_and_status_dropdown():
    ws = load(build_workpaper(sample_queue()))["Flagged entries"]
    h = {c.value: c.column_letter for c in ws[1]}
    assert ws[f"{h['Amount (BHD)']}2"].number_format == "#,##0.000"
    assert ws[f"{h['Posting date']}2"].number_format == "yyyy-mm-dd"
    assert ws[f"{h['Risk tier']}2"].fill.fgColor.rgb.endswith("F8D7D5")  # High
    assert ws[f"{h['Risk tier']}3"].fill.fill_type is None  # Low: no shading
    assert ws.column_dimensions[h["Reasons flagged"]].width >= 80
    dv = ws.data_validations.dataValidation[0]
    assert "False positive" in dv.formula1 and dv.sqref is not None


def test_print_setup():
    ws = load(build_workpaper(sample_queue()))["Flagged entries"]
    assert ws.page_setup.orientation == "landscape" and ws.print_title_rows == "$1:$1"


def test_cover_sheet_has_scope_procedures_and_signoff():
    wb = load(
        build_workpaper(
            sample_queue(),
            entity="Gulf Meridian",
            period="FY2025",
            preparer="A. Preparer",
            reviewer="B. Reviewer",
            n_scanned=24714,
        )
    )
    ws = wb["Cover"]
    cells = {ws.cell(r, 1).value: ws.cell(r, 2).value for r in range(1, ws.max_row + 1)}
    assert cells["Entity"] == "Gulf Meridian" and cells["Period"] == "FY2025"
    assert cells["Prepared by"] == "A. Preparer" and cells["Reviewed by"] == "B. Reviewer"
    assert cells["Entries scanned"] == 24714 and cells["Entries listed in this workpaper"] == 2
    text = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    assert all(p[:25] in text for p in DEFAULT_PROCEDURES)
    assert "Limitations" in text and "ISA 240" in text
    assert "Results and conclusion" in text


def test_summary_sheet_counts_statuses_tiers_and_value():
    ws = load(build_workpaper(sample_queue(), {"JE1": "False positive"}, dataset_name="Demo"))[
        "Summary"
    ]
    cells = {ws.cell(r, 1).value: ws.cell(r, 2).value for r in range(1, ws.max_row + 1)}
    assert cells["Dataset"] == "Demo" and cells["Entries in this workpaper"] == 2
    assert cells["Status: False positive"] == 1 and cells["Status: Pending"] == 1
    assert cells["Risk tier: High"] == 1 and cells["Risk tier: Low"] == 1
    assert abs(cells["Total value of listed entries (BHD)"] - 25480.125) < 1e-6


def test_empty_queue_still_produces_a_valid_workbook():
    wb = load(build_workpaper(sample_queue().iloc[0:0]))
    assert wb["Flagged entries"].max_row == 1
