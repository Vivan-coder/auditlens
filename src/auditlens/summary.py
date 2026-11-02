"""Plain-English executive summary of an analysis, with suggested follow-up procedures.

Everything is derived from the flags and scores (never from labels), so it works for uploaded
data too. The wording is deliberately cautious: flags are leads for judgement, not conclusions.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from auditlens.config import Config
from auditlens.pipeline import AnalysisResult

# family -> (theme heading, suggested follow-up procedure)
THEMES: dict[str, tuple[str, str]] = {
    "duplicates": (
        "Possible duplicate payments",
        "Agree each pair to the supporting invoice and bank statement; request recovery of any "
        "confirmed overpayment and review the payment-run controls.",
    ),
    "approval": (
        "Approval and segregation-of-duties exceptions",
        "Inspect authorisation evidence; for self-approved entries obtain explanations and test "
        "whether the control is bypassed systematically. For split purchases, vouch to the "
        "underlying order and compare with the approval policy.",
    ),
    "timing": (
        "Entries posted outside normal timing",
        "Obtain support for weekend, holiday, post-close and backdated postings; confirm "
        "who authorised access to closed periods and whether cut-off is affected.",
    ),
    "amounts": (
        "Round-sum and large manual entries",
        "Vouch material manual journals to supporting calculations and approval; consider "
        "management-override risk (ISA 240) and discuss business rationale with management.",
    ),
    "vendors": (
        "Vendor master-data risks",
        "Verify vendor existence independently (registration, site visit or callback to a known "
        "number); confirm bank-detail changes were authorised and validated before payment.",
    ),
    "sequence": (
        "Invoice-number sequence anomalies",
        "Request the vendor statement and the missing or out-of-order invoices; confirm "
        "completeness and that no documents were removed or fabricated.",
    ),
    "benford": (
        "Vendors whose amounts deviate from Benford's Law",
        "Treat as a lead: review the vendor's invoices for clustering below thresholds, "
        "rounding or fabricated patterns, and compare with contract pricing.",
    ),
    "pairings": (
        "Unusual account usage",
        "Review the journals' business purpose and the user's authority to post to those "
        "accounts; reclassify or correct where the posting is an error.",
    ),
    "ml": (
        "Statistically unusual entries (no specific rule)",
        "Review the stated reasons; most will be benign, but unexplained outliers deserve a "
        "quick enquiry of the preparer.",
    ),
}


@dataclass
class Theme:
    """One finding theme in the executive summary."""

    family: str
    title: str
    entries: int
    value: float
    top_codes: list[str]
    procedure: str


def tier_counts(queue: pd.DataFrame) -> dict[str, int]:
    """Number of queued entries per risk tier."""
    c = queue["risk_tier"].value_counts()
    return {t: int(c.get(t, 0)) for t in ("High", "Medium", "Low")}


def attention(queue: pd.DataFrame) -> pd.DataFrame:
    """High and medium risk entries."""
    return queue[queue["risk_tier"].isin(["High", "Medium"])]


def split_attention(queue: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(rule-backed, ML-only) parts of the high/medium entries.

    Rule-backed entries match at least one specific audit test. ML-only entries are flagged purely
    as statistically unusual, which is a weaker, lower-confidence signal.
    """
    a = attention(queue)
    return a[a["rule_score"] > 0], a[a["rule_score"] <= 0]


def themes(result: AnalysisResult, cfg: Config, min_tier: str = "Medium") -> list[Theme]:
    """Finding themes among entries at or above `min_tier`.

    Rule-based themes come first, largest exposure first. The ML theme is listed last and counts
    only entries that no specific test explains.
    """
    q = result.queue
    keep = ("High",) if min_tier == "High" else ("High", "Medium")
    sel = q[q["risk_tier"].isin(keep)].set_index("entry_id")
    f = result.flags[result.flags["entry_id"].isin(sel.index)]
    out: list[Theme] = []
    for fam, g in f.groupby("family"):
        if fam not in THEMES:
            continue
        ids = g["entry_id"].unique()
        if fam == "ml":
            ids = [e for e in ids if sel.loc[e, "rule_score"] <= 0]
            if not ids:
                continue
        title, proc = THEMES[fam]
        codes = g["rule_code"].value_counts().head(3).index.tolist()
        out.append(Theme(fam, title, len(ids), float(sel.loc[ids, "amount"].sum()), codes, proc))
    return sorted(out, key=lambda t: (t.family == "ml", -t.value, -t.entries))


def headline(result: AnalysisResult, cfg: Config) -> str:
    """One-paragraph summary for the top of the Overview page."""
    q = result.queue
    n = len(result.dataset.entries)
    tc = tier_counts(q)
    backed, ml_only = split_attention(q)
    attn = len(backed) + len(ml_only)
    return (
        f"AuditLens scanned **{n:,}** journal entries. **{attn:,}** "
        f"({100 * attn / max(n, 1):.1f}%) warrant follow-up: **{tc['High']:,}** high risk and "
        f"**{tc['Medium']:,}** medium risk. **{len(backed):,}** of these match at least one "
        f"specific audit test, with a combined entry value of **{cfg.company.currency} "
        f"{backed['amount'].sum():,.0f}**; the other **{len(ml_only):,}** are flagged only as "
        "statistically unusual and are a lower-confidence lead. A further "
        f"{tc['Low']:,} low-risk entries carry a single weak signal and can be sampled rather than "
        "reviewed one by one."
    )
