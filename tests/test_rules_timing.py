"""Timing rules: weekend/holiday, closed periods, backdating (Bahrain calendar)."""

from __future__ import annotations

from auditlens.rules import timing
from helpers import codes, entry, make_ds


def test_friday_and_saturday_flagged_sunday_not():
    ds = make_ds(
        [
            entry("FRI", "2025-03-07"),
            entry("SAT", "2025-03-08"),
            entry("SUN", "2025-03-09"),  # Sunday is a working day in Bahrain
            entry("WED", "2025-03-05"),
        ]
    )
    assert codes(timing.weekend_holiday(ds))["WEEKEND_POSTING"] == {"FRI", "SAT"}


def test_public_holiday_on_a_weekday_flagged():
    ds = make_ds([entry("NAT", "2025-12-16"), entry("NORMAL", "2025-12-18")])
    c = codes(timing.weekend_holiday(ds))
    assert c["HOLIDAY_POSTING"] == {"NAT"}
    assert "public holiday" in timing.weekend_holiday(ds).iloc[0]["reason"]


def test_automated_weekend_batches_are_not_flagged():
    ds = make_ds([entry("AUTO", "2025-03-07", source="automated", created="SYSTEM", approved=None)])
    assert timing.weekend_holiday(ds).empty


def test_post_close_posting():
    ds = make_ds(
        [
            entry("LATE", "2025-03-20", "2025-04-20", period="2025-03"),  # closed 5 April
            entry("EDGE", "2025-03-31", "2025-04-05", period="2025-03"),  # last day of close window
            entry("OK", "2025-03-20", "2025-03-21", period="2025-03"),
        ]
    )
    flags = timing.post_close(ds)
    assert set(flags["entry_id"]) == {"LATE"}
    assert "closed 2025-04-05" in flags.iloc[0]["reason"]


def test_backdated_posting():
    ds = make_ds(
        [
            entry("OLD", "2025-02-01", "2025-04-01", period="2025-04"),  # 59 days
            entry("FINE", "2025-02-01", "2025-02-12", period="2025-02"),  # 11 days
            entry("LIMIT", "2025-02-01", "2025-03-03", period="2025-03"),  # 30 days: not over
        ]
    )
    assert set(timing.backdated(ds)["entry_id"]) == {"OLD"}
