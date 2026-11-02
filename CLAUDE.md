# AuditLens

Audit analytics tool for journal entries: rule-based audit tests + unsupervised ML (Isolation Forest),
ranked into a review queue and evaluated against planted ground-truth anomalies. Portfolio project for a
KPMG Bahrain internship application. **All data is synthetic.** Free tools only, no paid APIs.

## Status

- [x] Phase 1: synthetic data generator, data dictionary, tests
- [ ] Phase 2: rule-based audit tests (`src/auditlens/rules/`)
- [ ] Phase 3: ML features, Isolation Forest, combined risk score (`src/auditlens/ml/`)
- [ ] Phase 4: evaluation (`src/auditlens/evaluate.py`)
- [ ] Phase 5: Streamlit dashboard (`app.py`, `dashboard/`)
- [ ] Phase 6: CI, README, methodology, deployment notes

## Commands (Windows, repo root, venv active: `.venv\Scripts\activate`)

| Task | Command |
|------|---------|
| Generate data | `python -m auditlens.generate` (`--seed N`, `--lines N`, `--out DIR`) |
| Evaluate | `python -m auditlens.evaluate` |
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
  rules/                 (Phase 2) one module per test family
  ml/                    (Phase 3) features, model, scoring
  evaluate.py            (Phase 4) metrics against labels.csv
docs/                    data_dictionary.md, methodology.md (later), deployment notes (later)
tests/                   pytest
data/, outputs/          generated, gitignored
```

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
- Run `pytest` and `ruff check .` before every commit.

## Domain notes

- Automated month-end postings (payroll, depreciation) can land on weekends legitimately; weekend
  tests apply to manual entries.
- Benford needs enough invoices per vendor (about 50 or more) for the chi-square test to mean anything.
- Normal payments settle an invoice exactly once; a second payment to the same vendor for the same
  amount within days is the duplicate signal.
