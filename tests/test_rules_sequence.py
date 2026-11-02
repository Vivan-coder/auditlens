"""Invoice-number sequence rules."""

from __future__ import annotations

from auditlens.rules import sequence
from helpers import codes, invoice, make_ds


def _clean():
    return [invoice(f"I{i}", f"2025-04-{6 + i:02d}", "V1", 100 + 8 * i) for i in range(6)]


def test_clean_sequence_not_flagged():
    assert sequence.run(make_ds(_clean())).empty


def test_gap_flags_the_invoice_after_the_jump():
    ds = make_ds([*_clean(), invoice("JUMP", "2025-04-20", "V1", 700)])
    flags = sequence.run(ds)
    assert codes(flags)["INVOICE_GAP"] == {"JUMP"}
    assert "jumps by" in flags.iloc[0]["reason"]


def test_out_of_order_number_flagged():
    ds = make_ds([*_clean(), invoice("LOW", "2025-04-20", "V1", 120)])  # last was 140
    flags = sequence.run(ds)
    assert codes(flags)["INVOICE_OUT_OF_ORDER"] == {"LOW"}
    assert "lower than invoice" in flags.iloc[0]["reason"]


def test_repeated_number_flagged_for_both_invoices():
    ds = make_ds([*_clean(), invoice("DUP", "2025-04-21", "V1", 108)])  # 108 used by I1
    assert codes(sequence.repeated_numbers(ds))["DUPLICATE_INVOICE_NUMBER"] == {"I1", "DUP"}


def test_sequences_are_judged_per_vendor():
    ds = make_ds(
        [
            invoice("A1", "2025-04-06", "V1", 100),
            invoice("A2", "2025-04-07", "V1", 108),
            invoice("B1", "2025-04-06", "V2", 9000),
            invoice("B2", "2025-04-07", "V2", 9008),
        ]
    )
    assert sequence.run(ds).empty
