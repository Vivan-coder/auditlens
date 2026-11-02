"""Shared app state: the active dataset bundle, navigation, and the reviewer workflow."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import streamlit as st

from auditlens.config import DATA_DIR, get_config
from auditlens.dataset import Dataset, dataset_from_tables, load_labels
from auditlens.evaluate import Evaluation, evaluate_result
from auditlens.generate import generate
from auditlens.pipeline import AnalysisResult, analyse

STATUSES = ["Pending", "Reviewed", "False positive"]
DEMO, UPLOADED = "Demo data", "Uploaded data"


@dataclass
class Bundle:
    """A dataset together with its analysis (and ground truth, for synthetic data only)."""

    name: str
    dataset: Dataset
    result: AnalysisResult
    labels: pd.DataFrame | None = None
    synthetic: bool = True
    _cache: dict = field(default_factory=dict)

    @property
    def queue(self) -> pd.DataFrame:
        """Ranked review queue."""
        return self.result.queue

    @property
    def account_names(self) -> dict[int, str]:
        """Account code -> name, when the chart of accounts is available."""
        a = self.dataset.accounts
        return dict(zip(a["account"], a["account_name"], strict=True)) if len(a) else {}

    def evaluation(self) -> Evaluation | None:
        """Evaluation against the planted labels (None for uploaded data)."""
        if self.labels is None:
            return None
        if "evaluation" not in self._cache:
            self._cache["evaluation"] = evaluate_result(self.result, self.labels, self.dataset.cfg)
        return self._cache["evaluation"]

    def entry_accounts(self) -> dict[str, set[int]]:
        """Entry id -> accounts it touches (for the account filter)."""
        if "entry_accounts" not in self._cache:
            e = self.dataset.entries.set_index("entry_id")
            self._cache["entry_accounts"] = {
                eid: set(dr) | set(cr)
                for eid, dr, cr in zip(
                    e.index, e["debit_accounts"], e["credit_accounts"], strict=True
                )
            }
        return self._cache["entry_accounts"]


@st.cache_resource(show_spinner="Preparing the demo ledger (first load only)...")
def load_demo_bundle() -> Bundle:
    """Demo bundle: use data/ if it has been generated, otherwise generate in memory."""
    cfg = get_config()
    if (DATA_DIR / "journal_entries.csv").exists() and (DATA_DIR / "labels.csv").exists():
        ds = Dataset.from_dir(cfg, DATA_DIR)
        labels = load_labels(DATA_DIR)
    else:
        tables = generate(cfg)
        ds, labels = dataset_from_tables(tables, cfg), tables["labels"]
    return Bundle("Synthetic demo ledger FY2025", ds, analyse(ds, cfg), labels, synthetic=True)


def make_uploaded_bundle(name: str, journal: pd.DataFrame) -> Bundle:
    """Analyse an uploaded (already validated) journal. No master data, no labels."""
    cfg = get_config()
    ds = Dataset(journal=journal, cfg=cfg)
    return Bundle(f"Uploaded: {name}", ds, analyse(ds, cfg), None, synthetic=False)


def active_bundle() -> Bundle:
    """The bundle selected in the sidebar."""
    if st.session_state.get("active_dataset") == UPLOADED and "upload_bundle" in st.session_state:
        return st.session_state["upload_bundle"]
    return load_demo_bundle()


# ---- navigation --------------------------------------------------------------------------------
def goto(page: str) -> None:
    """Request navigation to a page (applied at the start of the next run; safe in callbacks)."""
    st.session_state["_goto"] = page


def open_entry(entry_id: str) -> None:
    """Callback: open an entry on the Entry detail page."""
    st.session_state["detail_entry"] = entry_id
    goto("Entry detail")


# ---- reviewer workflow ---------------------------------------------------------------------
def _store(bundle: Bundle) -> dict:
    reviews = st.session_state.setdefault("reviews", {})
    return reviews.setdefault(bundle.name, {"status": {}, "notes": {}})


def statuses(bundle: Bundle) -> dict[str, str]:
    """entry_id -> reviewer status for entries that have been touched."""
    return _store(bundle)["status"]


def notes(bundle: Bundle) -> dict[str, str]:
    """entry_id -> reviewer note."""
    return _store(bundle)["notes"]


def status_of(bundle: Bundle, entry_id: str) -> str:
    """Status of one entry (Pending by default)."""
    return statuses(bundle).get(entry_id, "Pending")


def set_status(bundle: Bundle, entry_ids: list[str], status: str) -> None:
    """Mark entries as Reviewed / False positive / Pending."""
    store = statuses(bundle)
    for e in entry_ids:
        if status == "Pending":
            store.pop(e, None)
        else:
            store[e] = status
