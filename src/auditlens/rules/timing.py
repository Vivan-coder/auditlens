"""Posting-date tests: weekends, public holidays, closed periods, backdating.

Why auditors care: legitimate staff rarely post manual entries when the office is shut, and
entries slipped into a closed period or dated far in the past are a classic way to manage results.
"""

from __future__ import annotations

import pandas as pd

from auditlens import bh_calendar as cal
from auditlens.dataset import Dataset
from auditlens.rules.base import combine, make_flags

FAMILY = "timing"


def weekend_holiday(ds: Dataset) -> pd.DataFrame:
    """WEEKEND_POSTING / HOLIDAY_POSTING: posted on a Friday/Saturday or a Bahrain holiday."""
    e = ds.entries[ds.entries["source"].isin(ds.cfg.rules.timing.weekend_sources)]
    dates = e["posting_date"]
    weekend = dates.dt.day_of_week.isin(cal.WEEKEND_WEEKDAYS)
    holidays = {d for y in dates.dt.year.unique() for d in cal.bahrain_holidays(int(y))}
    holiday = dates.dt.date.isin(holidays) & ~weekend
    wk, hl = e[weekend], e[holiday]
    return combine(
        [
            make_flags(
                wk["entry_id"],
                FAMILY,
                "WEEKEND_POSTING",
                [f"Posted on {d:%A %Y-%m-%d} (Bahrain weekend)" for d in wk["posting_date"]],
            ),
            make_flags(
                hl["entry_id"],
                FAMILY,
                "HOLIDAY_POSTING",
                [
                    f"Posted on {d:%A %Y-%m-%d}, a Bahrain public holiday"
                    for d in hl["posting_date"]
                ],
            ),
        ]
    )


def post_close(ds: Dataset) -> pd.DataFrame:
    """POST_CLOSE_POSTING: posted after the entry's accounting period had closed."""
    e = ds.entries
    month_end = pd.PeriodIndex(e["period"], freq="M").to_timestamp(how="end").normalize()
    close = pd.Series(
        month_end + pd.Timedelta(days=ds.cfg.calendar.period_close_days), index=e.index
    )
    hit = e[e["posting_date"] > close]
    reasons = [
        f"Posted {r.posting_date:%Y-%m-%d} into period {r.period}, which closed "
        f"{close[r.Index]:%Y-%m-%d}"
        for r in hit.itertuples()
    ]
    return make_flags(hit["entry_id"], FAMILY, "POST_CLOSE_POSTING", reasons)


def backdated(ds: Dataset) -> pd.DataFrame:
    """BACKDATED_POSTING: posting date is far later than the document date."""
    e = ds.entries
    limit = ds.cfg.rules.timing.backdate_days
    lag = (e["posting_date"] - e["document_date"]).dt.days
    hit = e[lag > limit]
    reasons = [
        f"Posted {lag[r.Index]} days after the document date {r.document_date:%Y-%m-%d} "
        f"(limit {limit})"
        for r in hit.itertuples()
    ]
    return make_flags(hit["entry_id"], FAMILY, "BACKDATED_POSTING", reasons)


def run(ds: Dataset) -> pd.DataFrame:
    """All timing tests."""
    return combine([weekend_holiday(ds), post_close(ds), backdated(ds)])
