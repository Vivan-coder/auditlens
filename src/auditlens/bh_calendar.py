"""Bahrain business calendar: weekend (Fri/Sat), public holidays, period close dates."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from functools import lru_cache

import holidays

WEEKEND_WEEKDAYS = (4, 5)  # Monday=0 ... Friday=4, Saturday=5 (Bahrain weekend)


@lru_cache(maxsize=16)
def bahrain_holidays(year: int) -> dict[date, str]:
    """Public holidays for a year, as {date: name}."""
    return dict(holidays.country_holidays("BH", years=year).items())


def is_weekend(d: date) -> bool:
    """True on Friday or Saturday."""
    return d.weekday() in WEEKEND_WEEKDAYS


def is_holiday(d: date) -> bool:
    """True on a Bahrain public holiday."""
    return d in bahrain_holidays(d.year)


def is_business_day(d: date) -> bool:
    """Business day = Sunday to Thursday and not a public holiday."""
    return not is_weekend(d) and not is_holiday(d)


def next_business_day(d: date) -> date:
    """Return d if it is a business day, otherwise the next one."""
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def previous_business_day(d: date) -> date:
    """Return d if it is a business day, otherwise the previous one."""
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


def month_end(year: int, month: int) -> date:
    """Last calendar day of the month."""
    return date(year, month, calendar.monthrange(year, month)[1])


def business_days_in_month(year: int, month: int) -> list[date]:
    """All business days of a month, in order."""
    last = month_end(year, month).day
    return [d for day in range(1, last + 1) if is_business_day(d := date(year, month, day))]


def period_of(d: date) -> str:
    """Accounting period label 'YYYY-MM' for a calendar date."""
    return f"{d.year:04d}-{d.month:02d}"


def period_close_date(period: str, close_days: int) -> date:
    """Last date on which a period may still receive postings."""
    year, month = int(period[:4]), int(period[5:7])
    return month_end(year, month) + timedelta(days=close_days)
