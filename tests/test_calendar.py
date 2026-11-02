"""Tests for the Bahrain business calendar."""

from __future__ import annotations

from datetime import date

from auditlens import bh_calendar as cal


def test_weekend_is_friday_and_saturday():
    assert cal.is_weekend(date(2025, 3, 7))  # Friday
    assert cal.is_weekend(date(2025, 3, 8))  # Saturday
    assert not cal.is_weekend(date(2025, 3, 9))  # Sunday is a working day in Bahrain


def test_public_holidays():
    assert cal.is_holiday(date(2025, 12, 16))  # National Day
    assert cal.is_holiday(date(2025, 1, 1))
    assert not cal.is_business_day(date(2025, 12, 16))
    assert cal.is_business_day(date(2025, 12, 18))


def test_next_and_previous_business_day():
    assert cal.next_business_day(date(2025, 3, 7)) == date(2025, 3, 9)
    assert cal.previous_business_day(date(2025, 3, 8)) == date(2025, 3, 6)


def test_period_close_date():
    assert cal.period_close_date("2025-03", 5) == date(2025, 4, 5)
    assert cal.period_close_date("2025-12", 5) == date(2026, 1, 5)
    assert cal.period_of(date(2025, 3, 31)) == "2025-03"
