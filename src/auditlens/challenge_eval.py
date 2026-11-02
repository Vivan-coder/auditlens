"""Evaluate AuditLens on the challenge ledger: `python -m auditlens.challenge_eval`."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pandas as pd

from auditlens.challenge import VARIANTS, build_challenge
from auditlens.config import OUTPUT_DIR, ROOT, Config, load_config
from auditlens.dataset import dataset_from_tables
from auditlens.eval_report import md_table, pct
from auditlens.evaluate import flagged_sets
from auditlens.pipeline import AnalysisResult, analyse

DESIGN_TEXT = {
    "detect": "control: should be caught",
    "miss": "boundary: just outside a rule",
    "decoy": "decoy: legitimate look-alike",
}


def variant_table(result: AnalysisResult, labels: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """One row per variant: how many entries each system flagged, and by which rules."""
    flagged = flagged_sets(result, cfg)
    codes_by_entry = result.rule_flags.groupby("entry_id")["rule_code"].agg(list)
    rows = []
    for variant, (imitates, intended, design) in VARIANTS.items():
        lab = labels[
            (labels["note"] == f"variant:{variant}") & labels["role"].isin(["injected", "decoy"])
        ]
        ids = set(lab["entry_id"])
        if not ids:
            continue
        hit_intended = {e for e in ids if set(codes_by_entry.get(e, [])) & set(intended)}
        other = pd.Series(
            [c for e in ids - hit_intended for c in codes_by_entry.get(e, []) if c not in intended]
        )
        rows.append(
            {
                "variant": variant,
                "imitates": imitates,
                "design": design,
                "n": len(ids),
                "intended_rule": len(hit_intended) / len(ids),
                "rules_any": len(ids & flagged["rules"]) / len(ids),
                "ml_any": len(ids & flagged["ml"]) / len(ids),
                "combined": len(ids & flagged["combined"]) / len(ids),
                "other_codes": ", ".join(other.value_counts().head(2).index) if len(other) else "",
            }
        )
    return pd.DataFrame(rows)


def summarise(t: pd.DataFrame) -> dict[str, float]:
    """Entry-weighted headline numbers by design group."""
    out = {}
    for design in ("detect", "miss", "decoy"):
        g = t[t["design"] == design]
        n = g["n"].sum()
        for col in ("intended_rule", "rules_any", "ml_any", "combined"):
            out[f"{design}_{col}"] = float((g[col] * g["n"]).sum() / n) if n else 0.0
        out[f"{design}_n"] = int(n)
    return out


def render_report(t: pd.DataFrame, cfg: Config) -> str:
    """Markdown report: what the challenge set is, results per variant, honest reading."""
    s = summarise(t)
    rows = [
        [
            f"`{r.variant}`",
            DESIGN_TEXT[r.design],
            str(r.n),
            pct(r.intended_rule, 0),
            pct(r.rules_any, 0),
            pct(r.ml_any, 0),
            pct(r.combined, 0),
            r.other_codes or "-",
        ]
        for r in t.itertuples()
    ]
    table = md_table(
        [
            "Variant",
            "Design",
            "n",
            "Caught by intended rule",
            "Any rule",
            "ML",
            "Combined",
            "Other rules that fired",
        ],
        rows,
    )
    return f"""# Challenge set results

The main evaluation plants every anomaly exactly as its rule defines it, so rule recall there is close to
perfect by construction. This challenge ledger tests the same system on cases **written to stress it**. It
uses the same clean baseline (seed {cfg.evaluation.challenge_seed}) with no standard anomalies, and plants:

* **boundary** cases just outside a threshold (a duplicate payment 12 days later when the window is 7 days,
  a split at 85% of the limit when the band starts at 90%, a journal of 240,000 when materiality is 250,000),
* **disguised** cases that evade exact matching (an employee's address reformatted),
* **controls** the rules should catch (to prove the tests still work and nothing is silently broken), and
* **decoys**: legitimate entries that look like anomalies (to measure false alarms on look-alikes).

**Caveat.** I wrote this set too, so it is a stress test, not independent validation. A set written by
someone else, or real client data, would be the next step. Boundary cases were designed to be missed, so a
miss there is a *measured limit*, not a surprise; the useful output is knowing exactly where the limits are.

## Results by variant

{table}

*Caught by intended rule* = a rule designed for this anomaly fired. *Any rule* also counts incidental hits
by other rules (shown in the last column). Percentages are of the planted entries.

## Reading the results

* **Controls** (should be caught): {pct(s["detect_intended_rule"], 0)} caught by the intended rule across
  {s["detect_n"]} entries. The tests still work; the misses below are real limits, not a broken pipeline.
* **Boundary and disguised cases**: only {pct(s["miss_intended_rule"], 0)} caught by the intended rule
  ({s["miss_n"]} entries). The rules are **threshold-based**, so an anomaly just inside the threshold passes
  silently. {pct(s["miss_rules_any"], 0)} are flagged by *some* rule (mostly incidentally) and
  {pct(s["miss_ml_any"], 0)} by the ML model. This is the honest answer to "what if a fraudster knows the
  limit": thresholds are known to the person committing the fraud and can be avoided.
* **Decoys**: {pct(s["decoy_combined"], 0)} of legitimate look-alikes reach the combined review queue as
  high or medium risk. The system cannot tell a legitimate large capex accrual from a suspicious one using the
  data alone; that is what the auditor's follow-up is for, and why the output is a *lead*, not a finding.

## What would reduce the misses

| Gap | Possible improvement |
|---|---|
| Fixed thresholds (windows, bands, minimum counts) | Learn thresholds per client from history; add graduated scores near the boundary instead of a hard cut |
| Exact matching of vendor and employee details | Fuzzy matching (normalised addresses, edit distance, phone numbers) |
| Same-creator grouping for splits and self-approval | Look across users: reciprocal approvals, vendor-level totals regardless of creator |
| Benford needs about 50 invoices | Use a vendor-level amount test that works on small samples, or pool by category |
| Decoys indistinguishable by data | Attach evidence (approvals, project codes) so legitimate entries can be excluded |

Reproduce with `python -m auditlens.challenge_eval`.
"""


def run(cfg: Config) -> tuple[pd.DataFrame, str]:
    """Build, analyse and evaluate the challenge ledger; returns (table, markdown)."""
    tables = build_challenge(cfg)
    result = analyse(dataset_from_tables(tables, cfg), cfg)
    table = variant_table(result, tables["labels"], cfg)
    return table, render_report(table, cfg)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    p = argparse.ArgumentParser(
        description="Evaluate AuditLens on the adversarial challenge ledger."
    )
    p.add_argument("--out", type=Path, default=OUTPUT_DIR)
    p.add_argument(
        "--publish-docs", action="store_true", help="also write docs/challenge_report.md"
    )
    args = p.parse_args(argv)
    table, report = run(load_config())
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "challenge_report.md").write_text(report, encoding="utf-8")
    print(report.split("## What would reduce")[0])
    if args.publish_docs:
        shutil.copy(args.out / "challenge_report.md", ROOT / "docs" / "challenge_report.md")
        print("Published docs/challenge_report.md")


if __name__ == "__main__":
    main()
