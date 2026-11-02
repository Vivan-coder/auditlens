"""CSV validator: valid files pass, each kind of problem produces a clear, located error."""

from __future__ import annotations

from io import StringIO

import pandas as pd

from auditlens.schema import (
    JournalLine,
    apply_mapping,
    suggest_mapping,
    template_csv,
    validate_journal,
)


def good() -> pd.DataFrame:
    """A minimal valid two-line entry using only the required columns."""
    return pd.DataFrame(
        {
            "entry_id": ["E1", "E1"],
            "posting_date": ["2025-03-02", "2025-03-02"],
            "account": [6300, 2000],
            "debit": [100.0, 0],
            "credit": [0, 100.0],
        }
    )


def problems(res) -> str:
    return " | ".join(f"{e['row']}:{e['column']}:{e['problem']}" for e in res.errors)


def test_template_is_valid_and_fully_populated():
    res = validate_journal(pd.read_csv(StringIO(template_csv())))
    assert res.ok and res.n_entries == 1 and res.n_rows == 2
    assert res.journal["posting_date"].dtype.kind == "M"
    assert res.journal["source"].iloc[0] == "manual"


def test_minimal_file_gets_defaults_and_warnings():
    res = validate_journal(good())
    assert res.ok
    j = res.journal
    assert list(j["line_id"]) == ["E1-01", "E1-02"]
    assert (j["document_date"] == j["posting_date"]).all()
    assert (j["period"] == "2025-03").all() and (j["source"] == "manual").all()
    text = " ".join(res.warnings)
    assert "document_date missing" in text and "vendor_id not provided" in text


def test_missing_required_column_is_reported():
    res = validate_journal(good().drop(columns=["credit"]))
    assert not res.ok and "credit" in res.errors[0]["column"]
    assert "required" in res.errors[0]["problem"]


def test_empty_file():
    res = validate_journal(good().iloc[0:0])
    assert not res.ok and "no rows" in problems(res)


def test_bad_values_are_located_by_csv_row_and_column():
    df = good()
    df["account"] = df["account"].astype(object)  # as read from a messy CSV
    df.loc[0, "posting_date"] = "not a date"
    df.loc[1, "account"] = "abc"
    res = validate_journal(df)
    msgs = problems(res)
    assert not res.ok
    assert "2:posting_date:'not a date' is not a valid date" in msgs
    assert "3:account:account must be a number" in msgs


def test_negative_amounts_both_sides_and_zero_lines_rejected():
    df = good()
    df.loc[0, "debit"] = -5
    assert "must not be negative" in problems(validate_journal(df))
    both = good()
    both.loc[0, "credit"] = 50
    assert "both a debit and a credit" in problems(validate_journal(both))
    zero = good()
    zero.loc[0, "debit"] = 0
    assert "must have a debit or a credit" in problems(validate_journal(zero))


def test_unbalanced_entry_rejected_with_amounts():
    df = good()
    df.loc[1, "credit"] = 90.0
    res = validate_journal(df)
    assert not res.ok
    assert "entry E1 does not balance: debits 100.00 vs credits 90.00" in problems(res)


def test_unknown_source_value_rejected_and_synonyms_accepted():
    df = good().assign(source=["manual", "robot"])
    assert "source must be 'manual' or 'automated'" in problems(validate_journal(df))
    ok = validate_journal(good().assign(source=["System", "batch"]))
    assert ok.ok and set(ok.journal["source"]) == {"automated"}


def test_dayfirst_dates_and_thousand_separators():
    df = good().assign(
        posting_date=["13/03/2025", "13/03/2025"], debit=["1,250.50", "0"], credit=["0", "1,250.50"]
    )
    res = validate_journal(df, dayfirst=True)
    assert res.ok and res.journal["posting_date"].iloc[0].month == 3
    assert res.journal["debit"].iloc[0] == 1250.5


def test_repeated_line_ids_rejected():
    df = good().assign(line_id=["L1", "L1"])
    assert "repeated line_id" in problems(validate_journal(df))


def test_suggest_and_apply_mapping_on_foreign_column_names():
    raw = pd.DataFrame(
        {
            "Journal ID": ["E1"],
            "GL Date": ["2025-03-02"],
            "GL Account": [6300],
            "Dr": [5.0],
            "Cr": [0.0],
            "Memo": ["x"],
            "Prepared By": ["u1"],
            "Junk": [1],
        }
    )
    m = suggest_mapping(list(raw.columns))
    assert m["entry_id"] == "Journal ID" and m["posting_date"] == "GL Date"
    assert m["account"] == "GL Account" and m["debit"] == "Dr" and m["credit"] == "Cr"
    assert m["description"] == "Memo" and m["created_by"] == "Prepared By"
    assert m["vendor_id"] is None
    mapped = apply_mapping(raw, m)
    assert "Junk" not in mapped.columns and "entry_id" in mapped.columns


def test_model_accepts_float_style_account_and_rejects_fractional():
    assert (
        JournalLine.model_validate(
            {"entry_id": "E", "posting_date": "2025-01-01", "account": "6300.0", "debit": 1}
        ).account
        == 6300
    )
    res = validate_journal(good().assign(account=[6300.5, 2000]))
    assert "whole number" in problems(res)


def test_error_list_is_capped():
    df = pd.DataFrame(
        {
            "entry_id": ["E"] * 500,
            "posting_date": ["bad"] * 500,
            "account": [1] * 500,
            "debit": [1.0] * 500,
            "credit": [0] * 500,
        }
    )
    assert len(validate_journal(df, max_errors=50).errors) == 50


def test_generated_dataset_is_valid_when_uploaded(journal):
    res = validate_journal(
        journal.head(2000).copy().pipe(lambda d: d[d["entry_id"].isin(d["entry_id"].unique()[:-1])])
    )
    assert res.ok, problems(res)


def test_dates_are_never_silently_swapped():
    from auditlens.schema import strict_dates

    s = pd.Series(["2025-03-13", "13/03/2025", "05/03/2025", "31-12-2025", "bad", None])
    day = strict_dates(s, dayfirst=True)
    assert day[1] == pd.Timestamp("2025-03-13") and day[2] == pd.Timestamp("2025-03-05")
    assert day[3] == pd.Timestamp("2025-12-31") and pd.isna(day[4]) and pd.isna(day[5])
    month = strict_dates(s, dayfirst=False)
    assert pd.isna(month[1])  # 13 is not a month: rejected, not swapped
    assert month[2] == pd.Timestamp("2025-05-03")  # same text, different (explicit) reading
    assert month[0] == pd.Timestamp("2025-03-13")  # ISO always fine
