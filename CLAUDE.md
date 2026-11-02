# AuditLens

Audit analytics tool for journal entries: rule-based audit tests + unsupervised ML (Isolation Forest),
ranked into a review queue and evaluated against planted ground-truth anomalies. Portfolio project for a
KPMG Bahrain internship application. **All data is synthetic.** Free tools only, no paid APIs.

## Status

- [x] Phase 1: synthetic data generator, data dictionary, tests
- [x] Phase 2: rule-based audit tests (`src/auditlens/rules/`)
- [x] Phase 3: ML features, Isolation Forest, combined risk score (`src/auditlens/ml/`, `pipeline.py`)
- [x] Phase 4: evaluation (`src/auditlens/evaluate.py`, `eval_report.py`, `eval_charts.py`)
- [x] Phase 5: Streamlit dashboard (`app.py`, `dashboard/`, `schema.py`, `export.py`)
- [x] Phase 6: CI (`.github/workflows/ci.yml`), README, `docs/methodology.md`, `docs/deployment.md`

## Commands (Windows, repo root, venv active: `.venv\Scripts\activate`)

| Task | Command |
|------|---------|
| Generate data | `python -m auditlens.generate` (`--seed N`, `--lines N`, `--out DIR`) |
| Analyse (review queue) | `python -m auditlens.pipeline` |
| Evaluate | `python -m auditlens.evaluate` (`--no-stability`, `--publish-docs` copies report+charts to docs/) |
| Run app | `streamlit run app.py` |
| Test | `pytest` |
| Lint | `ruff check .` (format with `ruff format .`) |

Setup: `py -3.13 -m venv .venv`, `.venv\Scripts\activate`, `pip install -r requirements.txt`, `pip install -e .`

## Structure

```
config.yaml              all thresholds, approval roles, anomaly counts (validated by src/auditlens/config.py)
src/auditlens/
  bh_calendar.py         Bahrain calendar: weekend = Fri/Sat, public holidays, period close dates
  generate.py            orchestrator + CLI; writes data/*.csv
  synth/                 master_data, context (entry builders), baseline, inject_* (one per anomaly family)
  dataset.py             Dataset (journal + master data) and the one-row-per-entry view
  rules/                 one module per test family; each run(Dataset) -> flags table
  ml/                    features (no labels), Isolation Forest + explanations, risk score + review queue
  pipeline.py            analyse(Dataset) -> AnalysisResult (rules + ML + queue); CLI writes outputs/
  summary.py             executive summary: risk tiers, rule-backed vs ML-only, themes + suggested procedures
  schema.py              CSV column mapping + pydantic validation (strict dates, balance check)
  export.py              Excel audit workpaper (openpyxl)
  evaluate.py            metrics vs labels.csv (entry level); eval_report.py / eval_charts.py render report + PNGs
app.py                   Streamlit shell (sidebar radio nav; pages in dashboard/, each exposes render(bundle))
dashboard/               state (Bundle, review status), style, overview, queue, detail, benford_page, evaluation_page, upload
docs/                    data_dictionary.md, methodology.md, evaluation_report.md, deployment.md, images/
tests/                   pytest
data/, outputs/          generated, gitignored
```

## Rule codes (flags table: entry_id, family, rule_code, reason, related_entry_id)

duplicates: `DUP_SAME_INVOICE`, `DUP_EXACT_AMOUNT`, `DUP_NEAR_AMOUNT` (weak) | approval: `SPLIT_BELOW_LIMIT`,
`SELF_APPROVED`, `NO_APPROVER`, `APPROVER_OVER_LIMIT` | timing: `WEEKEND_POSTING`, `HOLIDAY_POSTING`,
`POST_CLOSE_POSTING`, `BACKDATED_POSTING` | amounts: `ROUND_AMOUNT`, `LARGE_MANUAL_PERIOD_END`, `LARGE_MANUAL` |
vendors: `GHOST_VENDOR_BANK`, `GHOST_VENDOR_ADDRESS`, `BANK_CHANGE_LARGE_PAYMENT` | sequence: `INVOICE_GAP`,
`INVOICE_OUT_OF_ORDER`, `DUPLICATE_INVOICE_NUMBER` | benford: `BENFORD_VENDOR` | pairings: `RARE_ACCOUNT_PAIR`,
`RARE_USER_ACCOUNT`. Rules that need master data (vendors, employees, users, bank changes) skip when it is absent,
so an uploaded journal-only CSV still runs the rest.

## Scoring

`risk = min(100, rule_score + ml_points)`. `rule_score` = noisy-OR of per-rule weights (`scoring.rule_weights`),
so several hits add up but saturate below 100. `ml_points` (0 to `ml_max_points`) go only to entries in the top
`ml.flag_percentile` of Isolation Forest scores, so every queued entry has a reason. ML features exclude the rule
signals (self-approval, near-limit, missing approver) so the model is an independent view.

## Evaluation conventions

Positive = any entry in labels.csv (including the genuine counterpart of a planted duplicate). Recall per type =
share of that type's entries flagged at all. Precision per type for Rules/Combined counts only entries carrying a
rule designed for that type (`TYPE_CODES` in evaluate.py); ML precision is its yield. Combined = risk >=
`evaluation.combined_threshold`. The report must state weaknesses in numbers (circularity, unrealistic base rate,
ML weakness, small n). Do not tune thresholds against labels; if one changes, say so in the report.

## Dashboard notes

- Navigation: sidebar radio with key `nav`. To change page from a callback or after a rerun, call
  `state.goto(page)`; `app.py` applies it before the radio is created (setting a widget key after it exists errors).
- Data: uses `data/` if generated, otherwise generates the demo ledger in memory on first load (cached), so it
  works on Streamlit Community Cloud with no data files. Uploaded data has no labels, so no Evaluation page.
- Reviewer status/notes live in `st.session_state["reviews"][bundle.name]`; the Excel export reads them.
- `app.py` adds `src/` to `sys.path`, so no `pip install -e .` is needed to deploy.
- Smoke tests use `streamlit.testing.v1.AppTest` (`tests/test_app.py`); set `session_state["_goto"]` to pick a page.

## Presentation conventions

- Risk tiers (`scoring.risk_tiers`): High >= 50, Medium >= 20, Low below. Queue rows carry `risk_tier`.
- Never present ML-only entries as equal to rule-backed ones: they are listed last, labelled lower-confidence, and
  excluded from "value to follow up" (evaluation shows ~13% precision for ML alone).
- Styling is restrained and original (navy palette). Do not use any firm's logo, name or brand assets.
- Excel workpaper (`export.py`): Cover (scope, procedures, legend, conclusion, sign-off), Flagged entries, Summary.
- Queue filters live in an `st.form`; review controls on the detail page are an `st.fragment`.

## Rules for working in this repo

- **Labels never leak.** `data/labels.csv` is read only by evaluation code and the dashboard's
  Evaluation page. Never use it (or the internal `kind` of an entry) as a feature or in a rule.
- **No hardcoded thresholds.** Materiality, approval limits, round-number rules and date windows
  live in `config.yaml` and are read through `auditlens.config`.
- Keep functions small, typed, with docstrings. No giant files (split by concern).
- Every rule returns flagged rows with a reason code and a human-readable reason.
- Evaluation is at **entry level** (one journal entry = one review item).
- Generation is deterministic from `generation.seed`. Do not use unseeded randomness.
- Bahrain weekend is Friday/Saturday, not Saturday/Sunday.
- Git: commit once per phase after tests pass, push to `origin main`. Commits carry only the user's
  identity (no co-author trailers).
- Run `pytest` and `ruff check .` before every commit (CI runs both on every push).
- After changing generator, rules, ML or scoring, re-run `python -m auditlens.evaluate --publish-docs` and update
  the results table in README.md so the published numbers match the code.
- Tests that exercise one rule use tiny hand-built ledgers (`tests/helpers.py`), one planted case and one clean case.

## Domain notes

- Automated month-end postings (payroll, depreciation) can land on weekends legitimately; weekend
  tests apply to manual entries.
- Benford needs enough invoices per vendor (about 50 or more) for the chi-square test to mean anything.
- Normal payments settle an invoice exactly once; a second payment to the same vendor for the same
  amount within days is the duplicate signal.
