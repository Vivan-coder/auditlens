"""Excel workpaper export."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
from openpyxl import load_workbook

from auditlens.export import COLUMNS, build_workpaper


def sample_queue() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rank": [1, 2],
            "entry_id": ["JE1", "JE2"],
            "risk_score": [72.5, 12.0],
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


def test_workbook_has_formatted_header_reasons_and_status():
    wb = load(build_workpaper(sample_queue(), {"JE1": "Reviewed"}, {"JE1": "checked invoice"}))
    ws = wb["Flagged entries"]
    headers = [c.value for c in ws[1]]
    assert headers[: len(COLUMNS)] == [c[0] for c in COLUMNS]
    assert headers[-2:] == ["Reviewer status", "Reviewer notes"]
    assert ws["A1"].font.bold and ws["A1"].fill.fgColor.rgb.endswith("1F3A5F")
    assert ws.freeze_panes == "C2" and ws.auto_filter.ref.startswith("A1:")
    row2 = {h: ws.cell(2, i + 1).value for i, h in enumerate(headers)}
    assert row2["Entry ID"] == "JE1" and row2["Reviewer status"] == "Reviewed"
    assert row2["Reviewer notes"] == "checked invoice"
    assert "same user" in row2["Reasons flagged"]
    row3 = {h: ws.cell(3, i + 1).value for i, h in enumerate(headers)}
    assert row3["Reviewer status"] == "Pending" and row3["Vendor"] is None


def test_formats_and_risk_shading():
    ws = load(build_workpaper(sample_queue()))["Flagged entries"]
    assert ws["E2"].number_format == "#,##0.000" and ws["D2"].number_format == "yyyy-mm-dd"
    assert ws["C2"].fill.fgColor.rgb.endswith("F8D7D5")  # 72.5 -> high
    assert ws["C3"].fill.fill_type is None  # 12 -> no shading
    assert ws.column_dimensions["L"].width >= 80


def test_summary_sheet_counts_statuses_and_value():
    ws = load(build_workpaper(sample_queue(), {"JE1": "False positive"}, dataset_name="Demo"))[
        "Summary"
    ]
    cells = {ws.cell(r, 1).value: ws.cell(r, 2).value for r in range(1, ws.max_row + 1)}
    assert cells["Dataset"] == "Demo"
    assert cells["Entries in this workpaper"] == 2
    assert cells["Status: False positive"] == 1 and cells["Status: Pending"] == 1
    assert abs(cells["Total value of listed entries (BHD)"] - 25480.125) < 1e-6


def test_empty_queue_still_produces_a_valid_workbook():
    empty = sample_queue().iloc[0:0]
    wb = load(build_workpaper(empty))
    assert wb["Flagged entries"].max_row == 1
