"""Smoke tests: every dashboard page renders without an exception (Streamlit AppTest)."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")
PAGES = [
    "Overview",
    "Review queue",
    "Entry detail",
    "Benford analysis",
    "Evaluation",
    "Data upload",
]


def run_page(page: str, timeout: int = 180) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=timeout)
    at.session_state["_goto"] = page
    return at.run()


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_exception(page):
    at = run_page(page)
    assert not at.exception, [e.value for e in at.exception]


def test_overview_shows_kpis_and_synthetic_notice():
    at = run_page("Overview")
    html = " ".join(m.value for m in at.markdown)
    assert "Entries scanned" in html and "Value at risk" in html and "synthetic" in html


def test_entry_detail_lists_reasons_for_top_entry():
    at = run_page("Entry detail")
    html = " ".join(m.value for m in at.markdown)
    assert "al-reason" in html and "al-tag" in html


def test_review_status_can_be_set_from_detail_page():
    at = run_page("Entry detail")
    radio = next(r for r in at.radio if r.label == "Review status")
    radio.set_value("False positive").run()
    assert not at.exception
    entry = at.selectbox[0].value
    review = at.session_state["reviews"]
    assert any(v["status"].get(entry) == "False positive" for v in review.values())


def test_queue_filters_reduce_the_table():
    at = run_page("Review queue")
    assert not at.exception
    slider = next(s for s in at.slider if s.label == "Minimum risk score")
    slider.set_value(60).run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "entries match" in text
