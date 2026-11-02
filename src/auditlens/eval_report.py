"""Markdown evaluation report, with the weaknesses stated in numbers rather than adjectives."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from auditlens.config import Config
from auditlens.evaluate import SYSTEM_LABEL, SYSTEMS, Evaluation


def pct(x: float, digits: int = 1) -> str:
    """Format a proportion as a percentage."""
    return f"{100 * x:.{digits}f}%"


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    """GitHub-flavoured markdown table."""
    line = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join("---" for _ in headers) + "|"
    body = ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join([line, sep, *body])


def overall_section(ev: Evaluation) -> str:
    """Headline table: overall precision, recall, F1 per system."""
    rows = []
    for s in SYSTEMS:
        r = ev.overall.loc[s]
        plo, phi = r["precision_ci"]
        rlo, rhi = r["recall_ci"]
        rows.append(
            [
                SYSTEM_LABEL[s],
                f"{int(r['flagged']):,}",
                f"{int(r['true_positives']):,}",
                f"{pct(r['precision'])} ({pct(plo, 0)}-{pct(phi, 0)})",
                f"{pct(r['recall'])} ({pct(rlo, 0)}-{pct(rhi, 0)})",
                f"{r['f1']:.3f}",
                pct(r["flag_rate"], 2),
            ]
        )
    head = [
        "System",
        "Entries flagged",
        "True positives",
        "Precision (95% CI)",
        "Recall (95% CI)",
        "F1",
        "Share of ledger flagged",
    ]
    return md_table(head, rows)


def ranking_section(ev: Evaluation) -> str:
    """Precision/recall at the auditor-capacity K values."""
    ks = sorted(ev.ranking["k"].unique())
    head = ["System"] + [f"Precision@{k}" for k in ks] + [f"Recall@{k}" for k in ks]
    rows = []
    for s in SYSTEMS:
        sub = ev.ranking[ev.ranking["system"] == s].set_index("k")
        rows.append(
            [SYSTEM_LABEL[s]]
            + [pct(sub.loc[k, "precision_at_k"], 0) for k in ks]
            + [pct(sub.loc[k, "recall_at_k"], 0) for k in ks]
        )
    return md_table(head, rows)


def per_type_section(ev: Evaluation) -> str:
    """Per anomaly type precision / recall / F1 for the three systems."""
    head = ["Anomaly type", "n"]
    for s in SYSTEMS:
        head += [f"{SYSTEM_LABEL[s]} P", "R", "F1"]
    rows = []
    for t, r in ev.per_type.iterrows():
        row = [str(t).replace("_", " "), str(int(r["n_positives"]))]
        for s in SYSTEMS:
            row += [pct(r[f"{s}_precision"], 0), pct(r[f"{s}_recall"], 0), f"{r[f'{s}_f1']:.2f}"]
        rows.append(row)
    return md_table(head, rows)


def stability_section(stab: pd.DataFrame | None, ev: Evaluation) -> str:
    """Mean and spread of the headline metrics over freshly generated datasets."""
    if stab is None:
        return "_Skipped (run without `--no-stability` to include it)._"
    rows = []
    for s in SYSTEMS:
        d = stab[stab["system"] == s]
        cells = [
            f"{pct(d[m].mean())} +/- {pct(d[m].std(ddof=0))}"
            for m in ("precision", "recall", "f1", "p_at_100")
        ]
        rows.append([SYSTEM_LABEL[s]] + cells)
    n = stab["seed"].nunique()
    table = md_table(["System", "Precision", "Recall", "F1", "Precision@100"], rows)
    return (
        f"Each of {n} extra datasets was generated with a different seed and analysed with the "
        f"same settings (mean +/- standard deviation across seeds):\n\n{table}"
    )


def sensitivity_section(ev: Evaluation, cfg: Config) -> str:
    """Combined-system metrics across alert thresholds."""
    rows = []
    for r in ev.sensitivity.itertuples():
        mark = " (used)" if r.threshold == cfg.evaluation.combined_threshold else ""
        rows.append(
            [
                f"{r.threshold:g}{mark}",
                f"{r.flagged:,}",
                pct(r.precision),
                pct(r.recall),
                f"{r.f1:.3f}",
            ]
        )
    return md_table(["Risk threshold", "Entries flagged", "Precision", "Recall", "F1"], rows)


def false_positive_section(ev: Evaluation) -> str:
    """Rule codes that put the most clean entries in front of an auditor."""
    top = ev.cross_type.head(8)
    rows = [
        [f"`{code}`", f"{int(r['flagged']):,}", f"{int(r['clean']):,}", pct(r["precision"], 0)]
        for code, r in top.iterrows()
    ]
    return md_table(["Flag source", "Entries flagged", "Of which clean", "Precision"], rows)


def weaknesses_section(ev: Evaluation, cfg: Config) -> str:
    """Honest limitations, computed from the results where possible."""
    o = ev.overall
    clean_total = ev.n_entries - ev.n_positives
    fpr = {s: (o.loc[s, "flagged"] - o.loc[s, "true_positives"]) / clean_total for s in SYSTEMS}
    pi = cfg.evaluation.assumed_real_prevalence
    rr = o.loc["rules", "recall"]
    real_precision = rr * pi / (rr * pi + fpr["rules"] * (1 - pi))
    ml_weak = [t.replace("_", " ") for t, r in ev.per_type.iterrows() if r["ml_recall"] < 0.10]
    comb_weak = [
        t.replace("_", " ") for t, r in ev.per_type.iterrows() if r["combined_recall"] < 0.5
    ]
    near = (
        ev.cross_type.loc["DUP_NEAR_AMOUNT"] if "DUP_NEAR_AMOUNT" in ev.cross_type.index else None
    )
    items = [
        "**The test is partly circular.** I wrote the generator and the rules, and each rule "
        "implements the same definition as the anomaly it targets. Recall close to 100% for the "
        "rules shows the implementation works, not how it would perform on a real ledger, where "
        "frauds are less tidy and are not labelled.",
        f"**The anomaly rate is unrealistic.** {pct(ev.n_positives / ev.n_entries)} of entries are "
        f"planted anomalies. At a real-world rate of {pct(pi)} the same rules "
        f"(recall {pct(rr, 0)}, "
        f"false-positive rate {pct(fpr['rules'], 2)} of clean entries) would have a precision of "
        f"about {pct(real_precision, 0)}; most of the queue would be false alarms. Precision "
        f"numbers here are therefore optimistic.",
        f"**ML alone is weak as a detector.** It flags "
        f"{int(o.loc['ml', 'flagged']):,} entries with "
        f"{pct(o.loc['ml', 'precision'])} precision, and finds under 10% of: "
        f"{', '.join(ml_weak) if ml_weak else 'none'}. Many audit anomalies are not statistically "
        "unusual entry by entry (a ghost vendor's invoices look like any other invoice). Its value "
        "is as a second opinion that surfaces odd entries no rule describes.",
        f"**Some types are under-served at the alert threshold.** The combined system (risk >= "
        f"{cfg.evaluation.combined_threshold:g}) surfaces under half of: "
        f"{', '.join(comb_weak) if comb_weak else 'none'}. Benford is a vendor-level lead that "
        "implicates every invoice of a vendor, so it carries a low weight; it belongs on the "
        "Benford page as one lead per vendor rather than in the entry queue.",
        "**Single synthetic company, one year.** Seasonality, vendor behaviour and approval "
        "patterns are simplified (no VAT, no multi-currency, no intercompany, no reversals other "
        "than accruals). Thresholds were chosen by reasoning about audit practice, but I did "
        "inspect this dataset while building: after a first run showed many coincidental matches I "
        "tightened the near-duplicate tolerance (1% to 0.5%) and split duplicates into exact and "
        "near codes. Nothing was tuned on held-out data; the multi-seed table above is the check "
        "that the settings are not specific to one random draw.",
        "**Per-type numbers rest on small counts.** Several types have 8-30 planted entries, so a "
        "single missed entry moves recall by several points. Treat differences of a few points "
        "between systems as noise.",
        "**Planted anomalies are isolated.** Each planted entry breaks one rule and is otherwise "
        "ordinary. Real misstatements tend to be disguised and may break several controls at once "
        "or none that a rule can see.",
    ]
    if near is not None:
        items.insert(
            3,
            f"**Near-duplicate amounts are mostly noise.** `DUP_NEAR_AMOUNT` flags "
            f"{int(near['flagged'])} entries but only {pct(near['precision'], 0)} are planted; "
            "coincidences between genuinely different invoices are common among large vendors. "
            "It is given a low weight and only matters alongside other evidence.",
        )
    return "\n".join(f"{i}. {t}" for i, t in enumerate(items, start=1))


def render_report(
    ev: Evaluation, cfg: Config, stability: pd.DataFrame | None, charts_dir: str = "charts"
) -> str:
    """Assemble the full markdown report."""
    thr = cfg.evaluation.combined_threshold
    return f"""# AuditLens evaluation report

All data is synthetic. Ground truth comes from the separate `labels.csv`; it was never used as a
feature or by any rule. Unit of analysis: one journal entry.

**Dataset:** {ev.n_entries:,} entries, {ev.n_positives} planted anomaly entries
({pct(ev.n_positives / ev.n_entries)} of the ledger).

## Overall results

{overall_section(ev)}

* **Rules alone** = any audit test fired. **ML alone** = Isolation Forest score in the top
  {pct(1 - cfg.ml.flag_percentile, 0)}. **Combined** = risk score >= {thr:g}
  (a specific rule hit, or a very unusual entry, or several weak signals together).
* Intervals are 95% Wilson intervals for the proportions.

## Auditor capacity: precision at the top of the queue

{ranking_section(ev)}

If reviewers can only look at the top K entries, this is what they would find. Recall@K is capped by
how many anomalies exist (K / {ev.n_positives} at best).

![Precision at K]({charts_dir}/precision_at_k.png)

## Per anomaly type

{per_type_section(ev)}

How to read it: *R* is the share of that type's planted entries the system flagged at all. *P* for
Rules and Combined counts only entries carrying a rule designed for that type. ML has no designed
type, so its *P* is its yield: the share of all ML flags that are this type. *F1* is derived from
the two.

![Recall by anomaly type]({charts_dir}/recall_by_type.png)

![Risk score distribution]({charts_dir}/risk_distribution.png)

## Choosing the alert threshold

The threshold of {thr:g} was set in advance from the scoring design (a single specific rule
passes it; a single weak rule, such as a near-duplicate amount, does not). It was not tuned
afterwards. Moving it trades precision for recall:

{sensitivity_section(ev, cfg)}

## Where the false positives come from

{false_positive_section(ev)}

## Stability across random seeds

{stability_section(stability, ev)}

## Weaknesses and caveats

{weaknesses_section(ev, cfg)}
"""


def write_report(text: str, path: Path) -> None:
    """Write the report to disk."""
    path.write_text(text, encoding="utf-8")
