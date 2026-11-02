"""Synthetic general-ledger generator: `python -m auditlens.generate`.

Builds a clean year of activity for a fictional Bahraini company, plants labelled anomalies,
and writes the journal plus master data. Ground-truth labels go to a SEPARATE file.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from auditlens.config import DATA_DIR, Config, load_config
from auditlens.synth.baseline import generate_baseline
from auditlens.synth.context import GenContext
from auditlens.synth.inject_accounts import inject_rare_user_accounts, inject_unusual_pairings
from auditlens.synth.inject_amounts import (
    inject_duplicate_payments,
    inject_round_amounts,
    inject_same_creator_approver,
    inject_split_purchases,
)
from auditlens.synth.inject_timing import (
    inject_backdated,
    inject_large_period_end,
    inject_post_close,
    inject_weekend_holiday,
)
from auditlens.synth.inject_vendors import (
    inject_bank_change_payments,
    inject_benford_vendor,
    inject_ghost_vendors,
    inject_invoice_sequence_breaks,
)

JOURNAL_COLUMNS = [
    "entry_id",
    "line_id",
    "document_date",
    "posting_date",
    "account",
    "debit",
    "credit",
    "description",
    "vendor_id",
    "created_by",
    "approved_by",
    "source",
    "invoice_number",
    "period",
]


def plant_anomalies(ctx: GenContext) -> None:
    """Inject every anomaly type. Sequence breaks go last because they renumber invoices."""
    a = ctx.cfg.anomalies
    inject_duplicate_payments(ctx, a.duplicate_payment)
    inject_split_purchases(ctx, a.split_purchase_groups)
    inject_weekend_holiday(ctx, a.weekend_holiday_posting)
    inject_round_amounts(ctx, a.round_amount)
    inject_same_creator_approver(ctx, a.same_creator_approver)
    inject_post_close(ctx, a.post_close_posting)
    inject_backdated(ctx, a.backdated_posting)
    inject_ghost_vendors(ctx, a.ghost_vendor_bank, a.ghost_vendor_address)
    inject_bank_change_payments(ctx, a.bank_change_large_payment)
    inject_unusual_pairings(ctx, a.unusual_pairing)
    inject_rare_user_accounts(ctx, a.rare_user_account)
    inject_benford_vendor(ctx, a.benford_vendor_invoices)
    inject_large_period_end(ctx, a.large_manual_period_end)
    inject_invoice_sequence_breaks(ctx, a.invoice_sequence_gap, a.invoice_sequence_out_of_order)


def build_journal(ctx: GenContext) -> tuple[pd.DataFrame, dict[int, str]]:
    """Flatten entries to journal lines; returns (journal, uid -> entry_id)."""
    ordered = sorted(ctx.entries, key=lambda e: (e.posting_date, e.uid))
    uid_to_id: dict[int, str] = {}
    rows: list[dict] = []
    for n, e in enumerate(ordered, start=1):
        entry_id = f"JE{n:06d}"
        uid_to_id[e.uid] = entry_id
        for k, line in enumerate(e.lines, start=1):
            rows.append(
                {
                    "entry_id": entry_id,
                    "line_id": f"{entry_id}-{k:02d}",
                    "document_date": e.document_date,
                    "posting_date": e.posting_date,
                    "account": line.account,
                    "debit": line.debit,
                    "credit": line.credit,
                    "description": e.description,
                    "vendor_id": e.vendor_id,
                    "created_by": e.created_by,
                    "approved_by": e.approved_by,
                    "source": e.source,
                    "invoice_number": e.invoice_number,
                    "period": e.period,
                }
            )
    df = pd.DataFrame(rows, columns=JOURNAL_COLUMNS)
    for col in ("document_date", "posting_date"):
        df[col] = pd.to_datetime(df[col])
    return df, uid_to_id


def build_labels(ctx: GenContext, uid_to_id: dict[int, str]) -> pd.DataFrame:
    """Ground-truth labels keyed by entry_id (written to a separate file)."""
    rows = [
        {
            "entry_id": uid_to_id[lab["uid"]],
            "anomaly_type": lab["anomaly_type"],
            "role": lab["role"],
            "related_entry_id": uid_to_id.get(lab["related_uid"]) if lab["related_uid"] else None,
            "note": lab["note"],
        }
        for lab in ctx.labels
    ]
    cols = ["entry_id", "anomaly_type", "role", "related_entry_id", "note"]
    return (
        pd.DataFrame(rows, columns=cols)
        .sort_values(["entry_id", "anomaly_type"])
        .reset_index(drop=True)
    )


def generate(cfg: Config) -> dict[str, pd.DataFrame]:
    """Run the full generator and return all tables."""
    ctx = GenContext.create(cfg)
    generate_baseline(ctx)
    plant_anomalies(ctx)
    journal, uid_to_id = build_journal(ctx)
    return {
        "journal_entries": journal,
        "labels": build_labels(ctx, uid_to_id),
        "chart_of_accounts": pd.DataFrame(ctx.md.accounts),
        "users": pd.DataFrame(ctx.md.users),
        "vendors": pd.DataFrame(ctx.md.vendors),
        "employees": pd.DataFrame(ctx.md.employees),
        "vendor_bank_changes": pd.DataFrame(ctx.md.bank_changes),
    }


def write_tables(tables: dict[str, pd.DataFrame], out_dir: Path) -> None:
    """Write each table to <out_dir>/<name>.csv."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(out_dir / f"{name}.csv", index=False)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    p = argparse.ArgumentParser(description="Generate the synthetic AuditLens dataset.")
    p.add_argument("--config", type=Path, default=None, help="path to config.yaml")
    p.add_argument("--seed", type=int, default=None, help="override generation.seed")
    p.add_argument("--lines", type=int, default=None, help="override generation.target_lines")
    p.add_argument("--out", type=Path, default=DATA_DIR, help="output directory")
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    if args.seed is not None:
        cfg.generation.seed = args.seed
    if args.lines is not None:
        cfg.generation.target_lines = args.lines
    tables = generate(cfg)
    write_tables(tables, args.out)
    j, lab = tables["journal_entries"], tables["labels"]
    print(f"Wrote {len(j):,} journal lines ({j['entry_id'].nunique():,} entries) to {args.out}")
    print(f"Planted {lab['entry_id'].nunique():,} labelled entries (labels.csv is separate):")
    print(lab.groupby("anomaly_type")["entry_id"].nunique().to_string())


if __name__ == "__main__":
    main()
