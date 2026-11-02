# AuditLens Study Guide

*How and why everything in this project works, written so you can explain and defend every part.*

How to use this guide: read Parts 1 and 2 once straight through. After that, use the later parts as
reference before an interview, and do the hands-on exercises in Part 10, because changing something and
watching the result is the fastest way to really understand it. Every number quoted here was taken from the
real project output (seed 42), and every file and function name exists in the repository.

**Contents**

1. Accounting and audit background (what problem this solves)
2. The big picture: how AuditLens works end to end
3. The data: how the synthetic ledger is built and why
4. The audit tests (rules): one by one
5. Benford's Law in depth
6. The machine learning layer
7. The risk score and the review queue
8. Evaluation: how we know whether it works
9. The dashboard, the upload pipeline and the Excel workpaper
10. Engineering: config, tests, CI, and hands-on exercises
11. Design decisions and trade-offs ("why this and not that")
12. Interview preparation: 30 questions with answers
13. Glossary and quick reference

---

# 1. Accounting and audit background

You do not need to be an accountant to understand this project, but you need these ideas to explain it.

## 1.1 The general ledger and journal entries

A company records every financial event in its **general ledger (GL)**. Each event is a **journal entry**,
made of two or more **lines**. Each line debits or credits an **account** from the **chart of accounts**
(a numbered list such as 1000 Cash, 2000 Accounts Payable, 6300 Professional Fees).

The one rule that makes the whole system checkable: **in every entry, total debits equal total credits.**
That is why the generator and the CSV validator both test that entries balance.

Worked example. The company receives a consultant's invoice for 1,500 BHD:

| Line | Account | Debit | Credit |
|---|---|---|---|
| 1 | 6300 Professional Fees (an expense) | 1,500.000 | |
| 2 | 2000 Accounts Payable (what we owe) | | 1,500.000 |

Thirty days later the company pays it:

| Line | Account | Debit | Credit |
|---|---|---|---|
| 1 | 2000 Accounts Payable (debt cleared) | 1,500.000 | |
| 2 | 1000 Cash at Bank (cash goes out) | | 1,500.000 |

This is exactly how `invoice` and `payment` entries are built in `synth/context.py`
(`make_invoice`, `make_payment`). The code recognises them later purely from the accounts: an **invoice**
credits Accounts Payable (2000); a **payment** debits 2000 and credits Cash (1000). The account numbers are
in `config.yaml` under `accounts:` so another company's chart of accounts can be used.

In this project one journal **line** is a row in `journal_entries.csv`, and one **entry** is all rows sharing
an `entry_id`. About 49,464 lines make 24,714 entries; most entries have two lines, and the 12 monthly payroll
entries have five.

## 1.2 Fields that matter for audit

| Field | Meaning | Why an auditor looks at it |
|---|---|---|
| `document_date` | Date on the source document (invoice date) | Compare with posting date to spot backdating |
| `posting_date` | When it was recorded in the ledger | Weekends, holidays, late postings |
| `period` | Accounting month the entry belongs to (`2025-03`) | Entries into closed periods |
| `source` | `manual` (a person keyed it) or `automated` (system) | Manual entries carry more override risk |
| `created_by`, `approved_by` | Who made it, who approved it | Segregation of duties |
| `vendor_id`, `invoice_number` | Supplier and its document number | Duplicates, sequences, ghost vendors |

**Approval limits.** Staff can only approve up to a limit tied to their role. In this project:
accountant 25,000; senior accountant 100,000; financial controller 500,000; CFO 5,000,000; AP clerks
cannot approve. The generator always picks the *lowest-limit user who outranks the creator and can cover the
amount* (`GenContext.approver_for`), so clean data never breaks the hierarchy.

**Period close.** Each month is "closed" 5 days after month end (`calendar.period_close_days`); after that,
postings to that month are suspicious. March 2025 closes on 5 April 2025.

**Bahrain context.** The weekend is **Friday and Saturday**, not Saturday and Sunday. Public holidays come
from the `holidays` library's Bahrain calendar. The currency is the Bahraini dinar (BHD), which has 3 decimal
places (fils), so amounts look like `1,500.000`. This is handled in `bh_calendar.py`, and it is a detail that
shows you thought about the local context.

## 1.3 What auditors do with journal entries

Auditing standards (ISA 240, on the auditor's responsibilities relating to fraud) require auditors to test
journal entries and other adjustments, because **management can override controls** by posting unusual entries.
The traditional approach is to pick a sample by hand. With tens of thousands of entries, that is slow and
misses things. **Journal entry analytics** means testing the whole population with computer tests that mirror
what an auditor would look for, then reviewing the exceptions.

Typical risk indicators (all implemented here): duplicate payments, payments or purchases arranged to sit just
below an approval limit, entries on weekends and holidays, round amounts, the same person creating and
approving, entries into closed periods or backdated, vendors that share details with employees, vendor bank
changes before large payments, gaps in invoice numbers, unusual account combinations, amounts that violate
Benford's Law, and large manual entries near period end.

## 1.4 The key idea to keep repeating

> A flag is a **lead, not a finding.** The system narrows 24,714 entries to a ranked list with reasons; an
> auditor still gathers evidence and uses judgement.

This phrase appears in the app, the Excel cover sheet and the README on purpose. Using it shows you
understand the limits of analytics in an audit.

---

# 2. The big picture: how AuditLens works end to end

## 2.1 The pipeline

```
 config.yaml  (every threshold, weight, limit)
      │
      ▼
 generate.py ── synth/*  ──►  data/journal_entries.csv      (what the tests see)
                          ──►  data/vendors, employees, users, bank changes, accounts
                          ──►  data/labels.csv               (ground truth, evaluation ONLY)
      │
      ▼
 dataset.py   Dataset: journal lines + one-row-per-entry view
      │
      ├──► rules/  (8 families, 23 codes)  ──► flags (entry, code, plain-English reason)
      │
      ├──► ml/features.py ──► ml/model.py (Isolation Forest) ──► ML score + ML flags with reasons
      │
      ▼
 ml/scoring.py   risk = min(100, noisy-OR(rule weights) + ML points)  →  ranked review queue
      │
      ├──► summary.py   executive summary, tiers, suggested procedures
      ├──► dashboard/ (Streamlit)   +   export.py (Excel workpaper)
      │
      ▼
 evaluate.py  compares flags with labels.csv  →  precision, recall, F1, P@K, report, charts
 challenge.py / challenge_eval.py  harder, adversarial test of the same system
```

## 2.2 File map (where to look)

| File or folder | What it does | Key names |
|---|---|---|
| `config.yaml`, `config.py` | All settings; validated by pydantic so typos fail early | `load_config`, `get_config` |
| `bh_calendar.py` | Fri/Sat weekend, Bahrain holidays, period close dates | `is_business_day`, `period_close_date` |
| `generate.py`, `synth/` | Builds the synthetic ledger and plants anomalies | `generate`, `GenContext`, `inject_*` |
| `dataset.py` | Loads data; builds the entry-level table | `Dataset`, `build_entries` |
| `rules/` | One module per test family | `run_all_rules`, `RULE_CODES` |
| `ml/features.py` | 20 numeric features per entry | `build_features` |
| `ml/model.py` | Isolation Forest + explanations | `score_entries`, `ml_flags`, `explain` |
| `ml/scoring.py` | Risk score, tiers, review queue | `rule_score`, `ml_points`, `build_review_queue` |
| `pipeline.py` | One call that runs everything | `analyse`, `AnalysisResult` |
| `summary.py` | Executive summary and finding themes | `headline`, `themes`, `split_attention` |
| `evaluate.py` (+ `eval_report.py`, `eval_charts.py`) | Metrics against labels | `evaluate_result` |
| `challenge.py`, `challenge_eval.py` | Adversarial test ledger and its report | `build_challenge` |
| `schema.py` | Upload validation (pydantic) | `validate_journal`, `strict_dates` |
| `export.py` | Excel workpaper | `build_workpaper` |
| `app.py`, `dashboard/` | The web app | `main`, `render(bundle)` per page |
| `tests/` | The automated test suite | |

## 2.3 The two-minute explanation (memorise the shape, not the words)

"AuditLens is a journal-entry analytics tool. Auditors have to look for fraud and error in tens of thousands
of ledger entries, which is impossible by hand, so I built something that tests the whole ledger.
There are 23 rule-based audit tests in eight families, such as duplicate payments, split purchases just under
approval limits, weekend and holiday postings, and vendors that share a bank account with an employee. On top
of that an unsupervised Isolation Forest scores how statistically unusual each entry is. I combine them into a
risk score and a ranked review queue, and every flag comes with a plain-English reason. Because I had no real
client data, I generated a realistic synthetic ledger for a fictional Bahraini company and planted twelve kinds
of known anomalies, kept in a separate label file, so I could measure precision and recall honestly. The rules
caught everything they were designed for, but I also built an adversarial challenge set and I am upfront about
the limits: threshold-based rules miss cases just outside their thresholds, and the ML model alone is only
about 13% precise. It is a screening tool that gives an auditor a ranked list of leads with reasons."

Then pause. They will ask a follow-up; the rest of this guide prepares you for those.

---

# 3. The data: how the synthetic ledger is built and why

## 3.1 Why synthetic data at all?

Real general ledgers are confidential and I have no access to client data. More importantly, **real data
has no answer key**: you never know which entries are truly fraudulent, so you cannot measure whether a
detector works. A synthetic ledger lets me plant anomalies I know about and then check how many the system
finds. The price is that the result only proves the system works on data like mine (see Part 8 for how
honestly that is handled).

Everything is **reproducible**: `generation.seed: 42` in `config.yaml` feeds one NumPy random generator and one
Faker generator, and no other randomness is used. The same seed always produces byte-identical data (a test
checks this).

## 3.2 How the generator is organised

`generate.py` is a thin orchestrator. The real work is in `synth/`:

| File | Responsibility |
|---|---|
| `master_data.py` | Chart of accounts, users and roles, 110 regular vendors in 7 categories, 8 recurring vendors, 60 employees, and a few legitimate vendor bank changes |
| `context.py` | `GenContext`: shared state (random generator, entries, labels) and helpers such as `approver_for`, `sample_dates`, `resolve_dates`, `make_invoice`, `make_payment`, `make_journal` |
| `baseline.py` | All the clean, normal activity |
| `inject_amounts.py`, `inject_timing.py`, `inject_vendors.py`, `inject_accounts.py` | One injector per anomaly type |

Order of work: build the **clean baseline first**, then **plant anomalies on top**, then number the entries and
write files. Labels are collected in a list while planting and written to a separate `labels.csv`.

## 3.3 The clean baseline (what "normal" looks like)

| Activity | Entries (approx.) | Accounting | Notes |
|---|---|---|---|
| Sales invoices | 5,000 | Dr 1100 Receivables / Cr 4000 or 4100 Revenue | Automated; sequential numbers `SI-000001...` |
| Customer receipts | up to 94% of sales (those due before year end) | Dr 1000 Cash / Cr 1100 | Paid 5-120 days later (average 35); 70% automated |
| Vendor invoices | ~7,700 + 96 recurring | Dr expense (by vendor category) / Cr 2000 | 70% manual (keyed by the vendor's AP clerk), 30% automated |
| Vendor payments | one per invoice due before year end | Dr 2000 / Cr 1000 | Manual; paid at the vendor's terms (30/45/60 days) with a few days' jitter |
| Payroll | 12 | Dr 6000 (one line per department) / Cr 1000 | Automated, last day of the month |
| Depreciation | 12 | Dr 6900 / Cr 1590 | Automated, 18,250.500 each month |
| Accruals and reversals | ~380 accruals + reversals on the next month's first business day | Dr expense / Cr 2100, then the reverse | Manual |
| Reclassifications | ~140 | Dr one expense / Cr another, from three fixed pairs | Manual |

**Realism features, and why each exists**

* **Month-end spike.** `sample_dates` gives the last three business days of each month a weight of 2.6 and the
  first business day 1.4, so volume surges at close, as in real ledgers.
* **Seasonality.** Monthly weights in `config.yaml` (`sales_seasonality`, `purchase_seasonality`): a dip in March
  (Ramadan), a strong Q4.
* **Recurring vendors.** Rent (a constant 4,500.000), electricity, telecom, cleaning, security, software and
  insurance (quarterly) bill on a schedule. This matters because a *contract* amount repeating is normal, and
  the round-amount test must not flag it.
* **Business-day logic.** Documents are dated on business days (Sunday to Thursday, not holidays). Manual
  entries are posted 0-3 days later (probabilities 55%, 25%, 12%, 8%) and rolled to the next business day.
  Automated month-end entries (payroll, depreciation) can fall on a weekend, which is realistic and is why the
  weekend test applies only to manual entries.
* **Posting period rule** (`GenContext.resolve_dates`). An entry belongs to its *document* month if it is posted
  within the close window; otherwise to the *posting* month. So a 31 March invoice posted on 2 April still
  belongs to March (inside the 5-day close window), and clean data never trips the post-close test.
* **Vendor numbering.** Each vendor's invoices get increasing numbers (`INV-000123`) rising by 5-15 each time,
  as the vendor has other customers. `invoice_number_for` finds the right number for a date. If injected
  invoices use up a gap, `shift_invoice_numbers` moves later numbers up (see the bug story in Part 11).

## 3.4 Why amounts follow Benford's Law (the one clever trick)

Benford's Law says the leading digit *d* of many real-world amounts appears with probability log10(1 + 1/d).
To generate normal amounts that follow it **exactly**, the generator uses:

> amount = 10^(d + u), where d is a whole number (an order of magnitude) and u is uniform between 0 and 1.

The first digit of an amount depends only on the fractional part of its log10, which is `u`. If `u` is
uniform, the first digit is exactly Benford-distributed, whatever mix of orders of magnitude `d` you choose. So
each vendor category has its own mix (goods suppliers 100-100,000; office supplies 10-10,000 and so on) but all
conform. Test: the clean invoices pass a chi-square Benford test (p about 0.11). The 3-decimal rounding does not
disturb it.

## 3.5 Master data

* **Users** come from `config.yaml` roles: 3 AP clerks, 3 accountants, 2 senior accountants, 1 financial controller,
  1 CFO, plus a `SYSTEM` user for automated postings.
* **AP clerk portfolios.** Each vendor category belongs to one clerk (clerk 0: goods and office supplies; clerk 1:
  professional services, marketing, IT; clerk 2: travel, repairs and the recurring vendors). So a clerk's pattern
  of accounts is stable, which is what makes "rare user-account" detection meaningful.
* **Vendors and employees** have Bahrain-style addresses and IBAN-shaped bank accounts (`BH` + 2 digits + 4 bank
  letters + 14 digits; the check digits are not real).
* 10% of vendors are onboarded during the year; they never invoice before they exist.
* Three vendors have **legitimate** bank-account changes, so a bank change by itself is not suspicious.

## 3.6 The twelve planted anomaly types

Counts come from `config.yaml` (`anomalies:`). Each planted entry is otherwise ordinary (valid approver,
business-day posting, normal lag) so that the *intended* test, and ideally only that test, should catch it.

| # | Type (`anomaly_type`) | What is planted | Entries labelled (seed 42) |
|---|---|---|---|
| 1 | `duplicate_payment` | 25 payments cloned 1-3 business days later, same or within 0.5% amount; invoice number repeated, suffixed `-R`, or brand new (one third each) | 50 (the duplicate and its original) |
| 2 | `split_purchase` | 12 groups of 3-5 invoices at 90-99.5% of a limit, same vendor and clerk, within a few days | 45 |
| 3 | `weekend_holiday_posting` | 30 manual invoices on Friday/Saturday (two thirds) or a weekday public holiday (one third) | 30 |
| 4 | `round_amount` | 30 manual invoices for exact multiples of 10,000 | 30 |
| 5 | `same_creator_approver` | 30 manual journals approved by their own creator | 30 |
| 6 | `late_or_backdated_posting` | 15 posted after the period closed; 15 posted 45-150 days after the document date | 30 |
| 7 | `ghost_vendor` | 2 vendors sharing a bank account and 1 sharing an address with an employee, each with 8 invoices and payments | 48 |
| 8 | `bank_change_large_payment` | 8 vendors: bank account changed, then a 40,000-95,000 payment 1-5 days later | 8 |
| 9 | `invoice_sequence_break` | 10 numbering gaps (jump 80-400) and 10 out-of-order numbers | 20 |
| 10 | `unusual_account_use` | 24 journals using 8 account pairs never otherwise seen; 25 clerk invoices to accounts outside their portfolio | 49 |
| 11 | `benford_violation` | One vendor with 60 invoices uniform between 7,000 and 9,990 (leading digits 7, 8, 9 only) | 60 |
| 12 | `large_manual_period_end` | 12 manual journals of 260,000-900,000 in the last two business days of a month (materiality is 250,000) | 12 |

Total: **412 labelled entries out of 24,714 (1.7%)**.

**`labels.csv`** has `entry_id`, `anomaly_type`, `role` (`injected`, or `counterpart` for the genuine original of a
duplicated payment), `related_entry_id` and a human `note`. It is a **separate file**, and `rules/` and `ml/` never
read it (a test scans their source for `load_labels`). That separation is the foundation of an honest evaluation:
if labels leaked into the detectors, the results would be meaningless.

## 3.7 Check your understanding

1. Why do planted anomalies need valid approvers and normal posting lags? (So each is caught by *its own* test,
   and a test passing because of a side-effect would not fool us.)
2. Why do automated entries have no approver? (They are system postings; the approval tests target manual ones.)
3. Why does the generator create duplicate payments with a different invoice number a third of the time? (So a
   test that only matches invoice numbers cannot catch them all; the amount-based test must.)

---

# 4. The audit tests (rules): one by one

## 4.1 How every rule is built (the common pattern)

Each module in `rules/` exposes `run(Dataset)` and returns a **flags table** with five columns:
`entry_id`, `family`, `rule_code`, `reason`, `related_entry_id`. The helper `make_flags` in `rules/base.py` builds
it, and `combine` merges tables and removes duplicate (entry, code) pairs. `run_all_rules` in
`rules/__init__.py` calls every family.

Two design rules to be able to state:

* **Thresholds are never hardcoded.** Every number below is read from `config.yaml` under `rules:` (pydantic
  validates it in `config.py`). Change the file, not the code.
* **Every flag explains itself.** The `reason` is a full sentence with the specific numbers, e.g. *"Posted
  2025-05-06 into period 2025-03, which closed 2025-04-05"*.

Rules work on the **entry-level table** built by `dataset.build_entries` (one row per entry with `amount` = total
debit, sets of debit and credit accounts, and `is_invoice` / `is_payment` identified from the accounts). Rules that
need master data (vendors, employees, users, bank changes) silently skip when it is missing, so an uploaded
journal-only CSV still gets the other tests.

## 4.2 Duplicate payments (`rules/duplicates.py`)

**Story.** Paying the same invoice twice is among the most common and expensive accounts-payable errors, and an
easy way to siphon cash.

| Code | Fires when | Weight |
|---|---|---|
| `DUP_SAME_INVOICE` | Two payments to one vendor reference the same invoice number (a trailing re-key suffix such as `-R` is stripped) | 40 |
| `DUP_EXACT_AMOUNT` | Same vendor, identical amount, within 7 days (`window_days`) | 35 |
| `DUP_NEAR_AMOUNT` | Same vendor, amounts within 0.5% (`amount_tolerance_pct`), within 7 days | 8 |

**How it works.** Take all payments (`ds.payments`), self-join them on `vendor_id` (and on the normalised invoice
number for the first test), keep each pair once (`entry_id < entry_id_o`), apply the date and amount conditions,
and flag **both** entries of the pair, each pointing at the other via `related_entry_id`. Normalising the invoice
number is `re.sub(r"\D+$", "", s)`: remove trailing non-digits.

**Real example.** *"Payment of 34,542.874 to vendor V0025 on 2025-03-02 is identical to 34,542.874 paid to the
same vendor on 2025-03-03 (JE002532)."*

**Why three codes?** Evidence strength differs. An identical amount to the fils is very unlikely by chance; "near"
is not (large vendors send similar invoices), so it gets a low weight. I split them after a first run showed 82
near-amount flags with only 20% real hits.

**What it misses.** A repeat after more than 7 days, or an amount more than 0.5% different with a new invoice
number, passes. The challenge set measures exactly this (Part 8).

## 4.3 Approval and segregation of duties (`rules/approval.py`)

**Story.** The approval hierarchy is the main preventive control over spending. Defeating it, or approving
your own work, is a classic fraud and error pathway.

| Code | Fires when | Weight |
|---|---|---|
| `SPLIT_BELOW_LIMIT` | At least 3 (`min_count`) invoices from one creator to one vendor, each 90%-100% of an approval limit (`band_low_pct`), within 10 days (`window_days`) | 35 |
| `SELF_APPROVED` | A manual entry's creator equals its approver | 35 |
| `NO_APPROVER` | A manual entry has no approver | 30 |
| `APPROVER_OVER_LIMIT` | Entry amount exceeds the approver's limit (from the users table) | 25 |

**Split purchases in detail.** Limits come from the roles in `config.yaml` (25,000; 100,000; 500,000; 5,000,000).
For each invoice, `_near_limit` tests whether `0.90 x limit <= amount < limit`. Candidates are grouped by
(vendor, creator) and sorted by date. A **sliding window** with `numpy.searchsorted` finds, for each candidate,
how many fall within 10 days; if at least 3, all of them are flagged. Total value is quoted in the reason:
*"97,757.382 is just under the 100,000 approval limit; 3 such invoices from fdawood to vendor V0011 within 10
days total 294,420.824."* (A 294k purchase that would have needed CFO approval was approved at lower levels.)

**What it misses.** Splits at 80-88% of the limit, only two parts, or spread across several people (all tested
in the challenge set). Collusion (A approves B's entries and B approves A's) does not equal self-approval.

## 4.4 Timing (`rules/timing.py`)

**Story.** Few people have a legitimate reason to key manual entries when the office is closed. Entries slipped
into closed periods or dated far back are a way to move results between periods.

| Code | Fires when | Weight |
|---|---|---|
| `WEEKEND_POSTING` | Manual entry posted on Friday or Saturday | 25 |
| `HOLIDAY_POSTING` | Manual entry posted on a weekday Bahrain public holiday | 25 |
| `POST_CLOSE_POSTING` | Posting date is after the period's close date (month end + 5 days) | 35 |
| `BACKDATED_POSTING` | Posting date is more than 30 days after the document date | 25 |

**How.** Weekend uses `day_of_week in (4, 5)` (Monday = 0, so Friday = 4). Holidays come from
`bh_calendar.bahrain_holidays`. The close date is `PeriodIndex(period).to_timestamp(how="end") + 5 days`.
Only entries with `source` in `rules.timing.weekend_sources` (manual) are tested for weekend and holiday, because
payroll and depreciation legitimately run on the last calendar day.

**Cross-talk to know.** A post-close entry usually also has a long posting lag, so it often gets both
`POST_CLOSE_POSTING` and `BACKDATED_POSTING`. Noisy-OR (Part 7) handles that sensibly.

## 4.5 Amounts (`rules/amounts.py`)

**Story.** Real transactions produce messy amounts; round ones suggest estimates or invention. Large manual
journals near period end are a recognised management-override and earnings-management risk.

| Code | Fires when | Weight |
|---|---|---|
| `ROUND_AMOUNT` | Manual entry of at least 5,000 that is an exact multiple of 1,000, and not a repeating contract amount | 25 |
| `LARGE_MANUAL_PERIOD_END` | Manual entry at or above 250,000 (materiality), posted in the last 3 business days of the month | 40 |
| `LARGE_MANUAL` | Same size, but not near period end | 25 |

**The modulo trick.** Testing `amount % 1000 == 0` with floats is fragile (1000.0000000001). The code uses
`((amount + 500) % 1000) - 500` and checks it is close to 0, which maps every remainder into the range -500 to
+500 so values just below *or* above a multiple both land near 0.

**Contract exemption.** If the same (vendor, amount) pair repeats at least 6 times (`recurring_repeat_exempt`),
it is treated as a contract (rent), not a red flag. The challenge set shows the limit: a contract paid only four
times is flagged.

## 4.6 Vendor master data (`rules/vendors.py`)

**Story.** A vendor that shares an employee's bank account is the textbook fictitious-vendor scheme. A changed
bank account followed quickly by a large payment is the textbook business-email-compromise pattern.

| Code | Fires when | Weight |
|---|---|---|
| `GHOST_VENDOR_BANK` | A vendor's bank account equals an employee's | 45 |
| `GHOST_VENDOR_ADDRESS` | A vendor's address equals an employee's | 35 |
| `BANK_CHANGE_LARGE_PAYMENT` | A payment of at least 20,000 and at least 5x the vendor's median payment, 0-14 days after a bank change | 35 |

**How.** Text is normalised (`lowercase, keep only letters and digits`) and merged on equality, so `bh11 AAAA...`
and `BH11AAAA...` match. **Every entry** posted to a flagged vendor is flagged, because the risk attaches to the
vendor. For bank changes, payments are merged with the change history on vendor, filtered to the window, and
compared with the vendor's median payment. Reason: *"Payment of 90,448.425 to vendor V0071 1 days after its bank
account changed on 2025-02-10 (vendor median payment 2,423.648)."*

**What it misses.** Reformatted addresses ("Bldg" vs "Building") and payments more than 14 days after the change.
A fuzzy-matching upgrade is on the "next steps" list.

## 4.7 Invoice-number sequences (`rules/sequence.py`)

**Story.** Vendor invoices normally arrive in numeric order. A jump may mean documents were removed or numbers
invented; a lower number arriving later suggests backdating or fabrication; a repeated number suggests a duplicate.

| Code | Fires when | Weight |
|---|---|---|
| `INVOICE_GAP` | Number jumps by more than 50 (`max_gap`) from the previous | 25 |
| `INVOICE_OUT_OF_ORDER` | Number is lower than one already received | 30 |
| `DUPLICATE_INVOICE_NUMBER` | The same vendor invoice number booked twice | 30 |

**The cummax trick.** For each vendor, invoices are sorted by document date, then number. `prev_max` is the running
maximum of earlier numbers (`cummax().shift()`), and `step = number - prev_max`. If `step > 50` it is a gap; if
`step < 0` it is out of order. Using the running **maximum** (not just the previous row) means one late low number
flags only itself, not the invoices after it.

## 4.8 Account usage (`rules/pairings.py`)

**Story.** A journal that moves value between accounts never otherwise linked (e.g. Suspense paid from Bank), or a
user posting to an account outside their normal duties, are classic signs of error or override.

| Code | Fires when | Weight |
|---|---|---|
| `RARE_ACCOUNT_PAIR` | The (debit account, credit account) pair appears in at most 3 entries all year | 30 |
| `RARE_USER_ACCOUNT` | A user with at least 50 manual entries posts to an account in at most 3 of them | 25 |

**How.** Count how many entries use each pair (or each user-account combination) and flag the rare ones. Rarity is
judged against the ledger's **own history**, not a fixed list, so it adapts to any company. The 50-entry minimum
stops a new user's few entries being "rare" by definition.

**Real example.** The top entry in the queue, JE007482: *"Debit 6000 / credit 2000 is an unusual account pairing:
seen in only 3 entries all year"* and *"jkooheji posted to account 6000 in only 1 of their 142 manual entries."*

## 4.9 Summary of weights

Weights express **how specific and trustworthy** a test is (0-100). They are judgement calls from audit practice,
not fitted to the labels. The highest are the most specific (ghost vendor bank 45; large period-end journal 40;
duplicate by invoice 40); the lowest are noisy (near-duplicate amount 8; Benford at vendor level 15).

---

# 5. Benford's Law in depth

This is the most mathematical test, and the one interviewers like to probe. Make sure you can explain it from
scratch.

## 5.1 The idea

In many real collections of amounts (invoices, populations, river lengths), the **first digit** is not equally
likely to be 1 through 9. The digit 1 leads about 30% of the time and 9 only about 5%. The exact probability that
the first digit is *d* is:

> P(d) = log10(1 + 1/d)

| Digit | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|
| Expected share | 30.1% | 17.6% | 12.5% | 9.7% | 7.9% | 6.7% | 5.8% | 5.1% | 4.6% |

**Intuition.** Quantities that grow multiplicatively spend a long time starting with 1. To go from 1,000 to 2,000
a quantity must double (100% growth); to go from 8,000 to 9,000 it grows only 12.5%. On a *logarithmic* scale
(which is how multiplicative growth looks), the stretch from 1,000 to 2,000 is much longer than from 9,000 to
10,000, so more values fall there. The formula is just the length of each digit's stretch on a log scale.

**Why it helps auditors.** People who invent numbers tend to spread digits roughly evenly, or favour certain
digits, or cluster just below thresholds (e.g. invoices of 9,900 to stay under 10,000). Those habits break the
pattern.

## 5.2 When it does NOT apply (say this unprompted in an interview)

* Numbers assigned rather than measured (phone numbers, invoice numbers).
* Amounts bounded by contract or price list, or limited to a narrow range (a vendor that always bills 800-1,200).
* Too few observations.
* Data that does not span several orders of magnitude.

That is why a Benford flag is a **lead, not proof**, and why AuditLens tests per vendor only when there are at
least 50 invoices (`rules.benford.min_invoices`).

## 5.3 The test: chi-square goodness of fit

For a vendor with *n* invoices, count how many start with each digit (observed, *O*). Under Benford the expected
count for digit *d* is *E = n x P(d)*. The statistic is:

> chi-square = sum over d=1..9 of (O_d - E_d)^2 / E_d

Big values mean the observed counts are far from expected. With 9 digit categories there are **8 degrees of
freedom** (the counts must add up to n, which removes one). From the chi-square distribution we get a **p-value**:
the probability of a deviation at least this large *if the vendor really followed Benford*. A tiny p-value means
"this would almost never happen by chance."

**The threshold.** We flag when p < 0.001 (`rules.benford.p_threshold`). For 8 degrees of freedom that corresponds
to a chi-square above about **26.1**. It is deliberately strict because we test many vendors (see 5.5).

## 5.4 Worked example: the planted vendor V0122 (real numbers)

V0122 has 60 invoices whose amounts were drawn uniformly between 7,000 and 9,990, so every amount starts with 7,
8 or 9.

| Digit | Benford share | Expected count (E, of 60) | Observed (O) | (O-E)^2 / E |
|---|---|---|---|---|
| 1 | 30.1% | 18.06 | 0 | 18.1 |
| 2 | 17.6% | 10.57 | 0 | 10.6 |
| 3 | 12.5% | 7.50 | 0 | 7.5 |
| 4 | 9.7% | 5.81 | 0 | 5.8 |
| 5 | 7.9% | 4.75 | 0 | 4.8 |
| 6 | 6.7% | 4.02 | 0 | 4.0 |
| 7 | 5.8% | 3.48 | 17 | 52.5 |
| 8 | 5.1% | 3.07 | 21 | 104.8 |
| 9 | 4.6% | 2.75 | 22 | 135.0 |
| **Total** | | | **60** | **343.0** |

chi-square = **343.0**, far above 26.1, so p = **2.8 x 10^-69**: essentially impossible by chance. The **mean absolute
deviation** (MAD, the average gap between observed and expected *shares*) is 0.188. The dashboard's Benford page
shows this chart: blue bars only at 7, 8, 9 against a dotted Benford curve.

## 5.5 Multiple testing (the subtle point)

We run the test on 55 vendors (those with at least 50 invoices). If every vendor were genuinely Benford and we
used p < 0.05, we would expect about 2.75 false alarms (55 x 0.05). With p < 0.001 we expect about **0.055**, i.e.
usually none. In our data exactly one vendor fails: the planted one. This is the reasoning behind the strict
threshold. (A related point: chi-square is an approximation that is best when every expected count is at least
5; at n = 50 the expected count for digit 9 is 2.3, so the p-value is approximate, which is another reason to be
strict and to call the result a lead.)

## 5.6 In the code

`rules/benford.py`:

* `first_digits(amounts)`: for each positive amount, `exponent = floor(log10(a))` and `digit = a // 10**exponent`.
* `digit_counts`: `numpy.bincount` into digits 1-9.
* `benford_table(ds)`: for each vendor with enough invoices, runs `scipy.stats.chisquare(observed, expected)` and
  records n, chi-square, p-value, MAD and the observed share of each digit. It feeds both the rule and the dashboard.
* `run(ds)`: for every vendor with p below the threshold, flags **all** of that vendor's invoices as
  `BENFORD_VENDOR`. The test population is **invoices only** (credits to payables), not payments, because payments
  repeat the same amounts and would double-count.

**Weight 15, and why.** It implicates a whole vendor, not one entry, so the weight is low; flagging 60 invoices at a
high weight would flood the queue with one lead. In the combined view it sits below the alert threshold of 20 by
design (the Benford page is where you read it).

**Challenge result.** A fabricated vendor with only 40 invoices is missed because it is below the 50-invoice minimum.

---

# 6. The machine learning layer

## 6.1 Why add ML to a rules-based tool?

Rules only find what someone thought to write a rule for. An **unsupervised** model, which needs no labelled
fraud, flags entries that are statistically odd compared with the rest, including patterns nobody anticipated.
It is the right type of ML here because in real life you rarely have trustworthy fraud labels (you only know
about frauds that were caught).

## 6.2 Isolation Forest: the intuition

Imagine plotting entries as points. A *normal* entry sits inside a dense crowd; to isolate it from the others you
need many cuts. An *unusual* entry sits alone; a few random cuts separate it.

The algorithm:

1. Build many random binary trees. At each node pick a **random feature** and a **random split value** between that
   feature's min and max (for the sample at that node). Keep splitting until each point is alone.
2. For a given entry, measure its **path length** (number of splits to isolate it) in each tree and average.
3. **Short average path = easy to isolate = anomalous.** Long path = blends in = normal.

The formal score (Liu, Ting and Zhou, 2008) is `s = 2^(-E[h(x)] / c(n))`, where `E[h(x)]` is the average path length
and `c(n) = 2(ln(n-1) + 0.5772) - 2(n-1)/n` is the average path length of an unsuccessful search in a binary
tree, used to normalise. For a subsample of 256, `c = 10.2`. An entry isolated in 4 splits scores about 0.76
(quite anomalous); one needing 10.2 splits scores 0.5 (ordinary).

**Settings used** (`ml:` in `config.yaml`, `ml/model.py`):

* `n_estimators: 300` trees. More trees make the score more stable.
* Each tree is built on a random subsample of **256** entries (scikit-learn's default `max_samples="auto"` is
  `min(256, n)`), which keeps it fast and works well for rare anomalies.
* `random_state = 42`, so results are reproducible.
* `contamination="auto"`. We do **not** use the model's own yes/no prediction; we use the continuous score.

scikit-learn's `score_samples` returns the *negative* of `s`, so the code uses `-score_samples(...)` to make
**higher = more anomalous**.

**From score to percentile.** `ml_score = rank(score, pct=True)` turns the raw score into a percentile between 0
and 1 (1.0 = the most anomalous entry). A percentile is easy to threshold ("top 2%") and to combine with rule
evidence, and it does not depend on the raw scale of the model.

**ML flag.** Entries with `ml_score >= 0.98` (`ml.flag_percentile`) get an `ML_ANOMALY` flag, about 2% of entries
(495 of 24,714).

## 6.3 The 20 features (`ml/features.py`)

The model sees one row of numbers per entry. Trees are insensitive to monotone scaling, so no normalisation is
needed. All features are computed from the journal (and the users table when present); **no labels, and none of
the generator's internal fields, are used**.

| Group | Features | Why they matter |
|---|---|---|
| Size | `log_amount`, `n_lines`, `is_round` | Unusually large, many-line or round entries |
| Account norms | `account_amount_z` | Largest |z-score| of any line's log amount versus other lines on the same account |
| Vendor behaviour | `has_vendor`, `vendor_count_log`, `vendor_amount_z`, `amount_to_vendor_median` | Is this amount typical for this vendor? How established is the vendor? |
| Twin entries | `twin_reldiff`, `twin_gap_days` | How close is the amount (relative difference) and date to the neighbouring entry of the same vendor and type? A duplicate-payment signature. Defaults: 1.0 and 365 when there is no neighbour |
| Time | `day_of_week`, `is_weekend`, `is_holiday`, `day_of_month`, `days_to_month_end` | Odd timing |
| Posting lag | `lag_days` | Backdating |
| Source and people | `is_manual`, `user_account_rarity`, `account_pair_rarity`, `approver_limit_ratio` | Manual entries; rarity = -log10 of how common the user-account combination, or the debit-credit pair, is; amount as a multiple of the approver's limit |

**Deliberately excluded.** The rule signals themselves (self-approved, near-limit, missing approver) are *not*
features. If they were, the model would just rediscover the rules and the "ML versus rules" comparison would be
meaningless. The ML layer is meant to be an **independent second opinion**.

**Z-score reminder.** `z = (x - mean) / standard deviation`: how many standard deviations an amount is from the
average. Amounts span orders of magnitude, so z-scores are computed on the **log** of the amount.

## 6.4 Explaining an ML flag in plain language

A raw anomaly score is useless to an auditor ("why?"). So `explain()` names the three features that deviate most
from **similar entries**:

1. Peers are defined by `(is_manual, has_vendor)`: four groups (manual or automated, vendor or not). Comparing a
   manual vendor invoice with automated payroll would make every manual entry look odd.
2. Within the group, each feature gets a **robust z-score**: `(x - median) / (1.4826 x MAD)`, where MAD is the median
   absolute deviation. Medians and MADs are not distorted by the very outliers we are hunting. The constant 1.4826
   makes MAD comparable to a standard deviation for normal data. If MAD is 0 the code falls back to the standard
   deviation, then to 1.
3. Take the three features with the largest |z| and print value and the peer median.

Real reason text: *"Statistically unusual entry (anomaly score in the top 2%): rarity of this user/account
combination: 2.15 (typical for similar entries 0.18); amount as a multiple of the approver's limit: 0.17 (typical
for similar entries 0.03); ..."*

## 6.5 How good is it? (the honest answer)

* ML alone: 495 flagged, 66 genuinely planted, so **precision 13.3%**, **recall 16.0%** (about 8 times better than
  random at 1.7% prevalence, but still weak).
* It finds entries that are *numerically* odd: 50% of the large period-end journals, 49% of unusual account use,
  31% of split purchases.
* It finds **0%** of duplicate payments, Benford vendors, sequence breaks and weekend postings, and 2% of ghost
  vendors. Why: a duplicated payment looks like any other payment on its own; a ghost vendor's invoices look like
  any invoice. Those anomalies are about *relationships* (this payment versus that one), not about one entry being
  numerically extreme, so a model that looks at one entry at a time cannot see them.
* On the challenge set, it did catch all six journals sitting just under the materiality threshold that the fixed
  rule missed, which is exactly the complementary value ML is meant to add.

So in AuditLens ML is a **second opinion that surfaces odd entries no rule describes**, not a detector to trust
on its own. Saying this plainly is a strength, not a weakness.

---

# 7. The risk score and the review queue

## 7.1 Why combine at all?

Auditors have limited time. They need one ranked list, not 23 separate rule outputs plus a model score. The
score answers "which entries first?".

## 7.2 Rule evidence: the noisy-OR

Each rule has a weight *w* between 0 and 100 (`scoring.rule_weights`), meaning roughly "how much does this
signal alone raise suspicion". When several rules fire on one entry, we combine them with the **noisy-OR**:

> rule_score = 100 x ( 1 - product over fired rules of (1 - w/100) )

Think of each rule as an independent detector that "catches" a true problem with probability w/100. The entry is
suspicious if **at least one** detector would catch it, so we compute the chance that *none* does
(`product of (1 - w/100)`) and subtract from 1.

**Worked example (the top entry, JE007482).** Two rules fired: `RARE_ACCOUNT_PAIR` (w = 30) and `RARE_USER_ACCOUNT`
(w = 25).

* chance neither catches it = 0.70 x 0.75 = 0.525
* rule_score = 100 x (1 - 0.525) = **47.5**

Compare the alternatives: a plain **sum** would give 55 and could exceed 100 with enough rules; the **maximum**
would give only 30 and ignore the second rule. Noisy-OR sits in between: more evidence always raises the score,
with **diminishing returns**, and it can never exceed 100. It is also order-independent and easy to explain.

## 7.3 The weights (judgement, not fitted)

| Weight | Rules | Reasoning |
|---|---|---|
| 45 | `GHOST_VENDOR_BANK` | Very specific and serious: an employee's own bank account on a vendor |
| 40 | `DUP_SAME_INVOICE`, `LARGE_MANUAL_PERIOD_END` | Specific and high impact |
| 35 | `DUP_EXACT_AMOUNT`, `SPLIT_BELOW_LIMIT`, `SELF_APPROVED`, `POST_CLOSE_POSTING`, `GHOST_VENDOR_ADDRESS`, `BANK_CHANGE_LARGE_PAYMENT` | Strong control failures |
| 30 | `NO_APPROVER`, `INVOICE_OUT_OF_ORDER`, `DUPLICATE_INVOICE_NUMBER`, `RARE_ACCOUNT_PAIR` | Meaningful but with innocent explanations |
| 25 | `APPROVER_OVER_LIMIT`, `WEEKEND_POSTING`, `HOLIDAY_POSTING`, `BACKDATED_POSTING`, `ROUND_AMOUNT`, `LARGE_MANUAL`, `INVOICE_GAP`, `RARE_USER_ACCOUNT` | Common risk indicators; often benign alone |
| 15 | `BENFORD_VENDOR` | Vendor-level lead |
| 8 | `DUP_NEAR_AMOUNT` | Weak: coincidences are common |

These are set from audit reasoning and **not tuned on the labels**. If asked "why 40 and not 35?", the honest
answer is that the exact number matters less than the ordering, and the weights are configurable.

## 7.4 ML points

ML only adds points to entries that are already ML-flagged (top 2%):

> ml_points = 30 x (ml_score - 0.98) / (1 - 0.98), clipped at 0

So the most anomalous entry gets the full 30 points, an entry at the 99th percentile gets 15, and everything
below the 98th gets 0. For JE007482 the ML score is essentially 1.0, so about 29.6 points.

> **risk_score = min(100, rule_score + ml_points) = 47.5 + 29.6 = about 77**

**Why only for flagged entries?** Every entry that scores ML points also carries an `ML_ANOMALY` flag and therefore a
written reason. Early in development entries between the 95th and 98th percentile got points but no reason; a test
caught it and the design was changed so that one threshold controls both. **Why cap at 30?** So that rules (specific
and explainable) carry most of the weight, and the model cannot push an entry with no rule evidence above the
Medium tier by itself.

## 7.5 Tiers and the queue

* **Tiers** (`scoring.risk_tiers`): **High** at 50 or more, **Medium** from 20 to 50, **Low** below 20. Two rules fire, or
  one strong rule plus a high ML score, to reach High. A single ML flag at maximum (30 points) is Medium.
* **Queue** (`ml/scoring.py: build_review_queue`): all entries with `risk_score >= 1`, sorted by risk score, then ML
  score, then amount. 903 entries: 71 High, 427 Medium, 405 Low. Columns: rank, risk score and tier, rule score,
  ML score, number of flags, rule codes, concatenated reasons, related entry ids, and the entry's details.

## 7.6 The executive summary (`summary.py`)

* `split_attention` divides the High and Medium entries into **rule-backed** (rule_score above 0: 360 entries) and
  **ML-only** (138). ML-only is shown last and labelled lower-confidence because ML alone is about 13% precise.
* `themes` groups rule-backed High/Medium entries by rule *family*, with an auditor-style **suggested follow-up
  procedure** for each (a dictionary `THEMES`). ML-only entries form their own last theme.
* `headline` writes the paragraph at the top of the Overview.

All of it is derived from flags and scores only; a test checks it never touches the labels.

---

# 8. Evaluation: how we know whether it works

## 8.1 The setup

Because the generator wrote a separate answer key (`labels.csv`), we can score the system like an exam. The
**unit** is one journal entry. A **positive** is any entry that appears in the label file (this includes the
genuine *original* of a duplicated payment, because the test is supposed to flag both). There are 412 positives
among 24,714 entries, so **24,302 are clean**.

For one system (say, "rules alone") each entry falls in one of four boxes:

|  | Truly anomalous | Truly clean |
|---|---|---|
| **Flagged** | True positive (TP) | False positive (FP) |
| **Not flagged** | False negative (FN) | True negative (TN) |

## 8.2 The metrics, with the real numbers

* **Precision** = TP / (TP + FP): "of what we flagged, how much was real?" It is the auditor's wasted-time measure.
* **Recall** = TP / (TP + FN): "of what was real, how much did we find?" It is the missed-risk measure.
* **F1** = 2 x precision x recall / (precision + recall): one number balancing both (the harmonic mean, which
  punishes a system that is good at only one).
* **False-positive rate (FPR)** = FP / (clean entries): the share of clean entries wrongly flagged.

| System | Flagged | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| Rules alone (any rule fired) | 490 | 412 | 78 | 0 | 84.1% | 100% | 0.914 |
| ML alone (top 2% of anomaly score) | 495 | 66 | 429 | 346 | 13.3% | 16.0% | 0.146 |
| Combined (risk score 20 or more) | 498 | 348 | 150 | 64 | 69.9% | 84.5% | 0.765 |

Reading: the rules found everything (they were built for these anomalies) at the cost of 78 false alarms. ML alone
is mostly noise. The combined view misses 64: 60 are the Benford vendor's invoices (weight 15, below the alert
threshold of 20 by design) and 4 are weak near-amount duplicates.

**Confidence intervals.** A proportion measured on a finite sample is uncertain. The report gives 95% Wilson score
intervals, which behave well for small samples and for values near 0 or 100%. With *p* = k/n and *z* = 1.96:

> centre = (p + z^2/2n) / (1 + z^2/n); half-width = z x sqrt(p(1-p)/n + z^2/4n^2) / (1 + z^2/n)

For the rules' precision (412/490) this gives 81% to 87%.

## 8.3 Per-type metrics and how they are defined

The project specification asks for precision, recall and F1 **per anomaly type**. The definitions (stated in the report too):

* **Recall for a type** = share of that type's planted entries that the system flagged at all.
* **Precision for a type (rules and combined)** = of the flagged entries that carry a rule *designed* for that type,
  the share that really are that type. The mapping from type to rule codes is `TYPE_CODES` in `evaluate.py`.
* **Precision for ML** = its *yield*: the share of all ML flags that are that type (ML has no designed type).

Recall by type for the rules is 100% everywhere; for ML it ranges from 0% to 50%; for the combined score it is
100% except duplicates (92%, the 4 near-amount-only cases) and Benford (0%).

## 8.4 Precision at K (the auditor-capacity view)

If reviewers can only look at K entries, what matters is how clean the *top K* of the ranked list is.
**Precision@K** = (real anomalies among the top K) / K.

| System | Precision@50 | Precision@100 |
|---|---|---|
| Rules alone (ranked by rule score, ties by amount) | 100% | 100% |
| ML alone (ranked by anomaly score) | 28% | 21% |
| Combined (ranked by risk score) | 100% | 100% |

So the top 100 of the queue are all real. Recall@100 is only 24%, simply because there are 412 anomalies and K = 100
(the maximum possible is 100/412).

## 8.5 The base-rate problem (the most important caveat)

In the synthetic data, 1.7% of entries are anomalous. In a real ledger the rate of true problems is far lower
(assume 0.1%). **Precision depends on how common positives are.** Use the rules' own numbers: recall about 100% and
FPR = 78 / 24,302 = 0.32%. Per 100,000 real entries:

* 100 true problems -> about 100 caught,
* 99,900 clean entries x 0.32% = about 321 false alarms.

> precision = 100 / (100 + 321) = **about 24%**

That is the formula `precision = R x pi / (R x pi + FPR x (1 - pi))` with pi = 0.001. The same system that looks 84%
precise here would hand an auditor roughly three false alarms per real problem. This is the single most honest
thing in the project; say it before anyone asks.

## 8.6 Stability across seeds and the threshold choice

* **Seeds.** Regenerating with four other seeds (1001-1004) and re-running everything gave rules 84.9% +/- 4.0%
  precision and 100% recall; ML 13.9% +/- 2.4% and 16.7% +/- 2.8%; combined 71.7% +/- 1.3% and 83.7% +/- 1.0%.
  So the results are not a fluke of one random draw (although the data come from the same generator).
* **Alert threshold.** The combined view uses risk >= 20. The report shows what other thresholds would do:

| Threshold | Flagged | Precision | Recall | F1 |
|---|---|---|---|---|
| 1 (whole queue) | 903 | 45.6% | 100% | 0.627 |
| 10 | 700 | 58.3% | 99.0% | 0.734 |
| **20 (used)** | 498 | 69.9% | 84.5% | 0.765 |
| 30 | 268 | 95.1% | 61.9% | 0.750 |
| 40 | 141 | 100% | 34.2% | 0.510 |
| 50 | 71 | 100% | 17.2% | 0.294 |

  The threshold was fixed in advance from the scoring design and **not tuned afterwards**; the table shows the
  precision-recall trade-off honestly. A higher threshold means fewer, more certain leads.

## 8.7 The challenge set (breaking our own system)

The main test is circular: the rules implement the same definitions the generator planted. So
`challenge.py` builds a second ledger with **no standard anomalies** and plants 20 variants of four kinds:

* **Boundary cases** just outside a threshold: a duplicate payment 12 days later (window is 7), a split at 80-88% of
  the limit (band starts at 90%), a journal of 225,000-245,000 (materiality 250,000), a gap of 30-45 (limit 50),
  backdating by 20-26 days (limit 30), only two split invoices (minimum is 3), and so on.
* **Disguised** cases: an employee's address reformatted ("Bldg" to "Building"), reciprocal approvals (A approves B,
  B approves A).
* **Controls**: cases the rules *should* catch, to prove nothing is silently broken.
* **Decoys**: legitimate entries that look like anomalies, to measure false alarms on look-alikes.

**Results** (`docs/challenge_report.md`):

* Controls: **100%** caught by the intended rule (29 entries).
* Boundary and disguised cases: only **3%** caught by the intended rule (175 entries). Thresholds are known to a
  fraudster and can be avoided.
* **ML rescues one gap:** all six journals just under materiality were flagged by ML and reached the queue.
* Decoys: **100%** reached the queue. By data alone, a legitimate large capex accrual looks identical to a
  suspicious one.

**What this proves and does not.** It proves where the limits are, with numbers, and that the tests still work. It
does not prove real-world performance, because I wrote this set too; the next step is a set written by someone
else or real client data.

## 8.8 In the code

`evaluate.py`: `prf`, `wilson`, `flagged_sets` (rules = any rule flag; ML = ML flags; combined = risk at or above
the threshold), `rankings` (the order each system would give an auditor), `overall_table`, `per_type_table`,
`ranking_tables`, `false_positive_sources` (which rule codes produce the most false alarms), `evaluate_result`,
`seed_stability`. `eval_report.py` writes the markdown; `eval_charts.py` the PNGs (colours from a validated
colour-blind-safe palette). `python -m auditlens.evaluate --publish-docs` refreshes `docs/`.

---

# 9. The dashboard, the upload pipeline and the Excel workpaper

## 9.1 App structure (Streamlit)

* `app.py` is the **shell**: page config, CSS, sidebar navigation, then calls the chosen page's `render(bundle)`.
* `dashboard/state.py` defines `Bundle` (dataset + analysis + labels + name) and `active_bundle()`. The demo bundle
  is built once by `load_demo_bundle()` decorated with `@st.cache_resource`, so every visitor shares one analysed
  dataset. It uses `data/` if present and otherwise generates in memory (that is why Streamlit Cloud works with no
  data files).
* Pages: `overview.py`, `queue.py`, `detail.py`, `benford_page.py`, `evaluation_page.py`, `upload.py`.
* `dashboard/style.py`: CSS, KPI cards (a responsive CSS grid), pills, Plotly layout.

**Streamlit's execution model (crucial to understand).** Streamlit reruns the whole script on every click. State that
must survive lives in `st.session_state`. Keys used here: `nav` (current page), `_goto` (a navigation request),
`detail_entry`, `reviews` (statuses and notes per dataset), `active_dataset`, `upload_bundle`, `upload_result`.

**The `_goto` pattern.** Streamlit forbids changing a widget's state after the widget has been created in the same
run. A button callback or the upload page therefore stores the desired page in `_goto`; at the very top of the next
run `app.py` copies it into `nav` *before* the sidebar radio exists. The current page is also written to the URL
(`?page=Review queue`), so a browser refresh stays on the page and deep links work.

**Smoothness techniques.** The queue filters sit inside `st.form` (nothing reruns until "Apply filters"). The review
status panel on the detail page is an `st.fragment`, so changing status reruns only that panel. The Excel file is
produced lazily when the download button is clicked (`data` is a callable `functools.partial`, run on another thread
from plain snapshots, never touching `session_state`).

## 9.2 The pages

| Page | What it shows | Notes |
|---|---|---|
| Overview | Executive summary, tier KPIs, key findings with suggested procedures, supporting charts | Rule-backed and ML-only separated |
| Review queue | Filters (tier, code, status, user, vendor, account, date, amount, risk), table with selection, bulk actions, Excel export | `filtered_queue` is a pure, tested function |
| Entry detail | All reasons (rule tags blue, ML tag orange), journal lines with account names, related entries, vendor panel, review status and notes | `related_entries` finds the matching duplicate |
| Benford analysis | Observed vs expected digit chart per vendor, statistics, all-vendor table | Vendors under 50 invoices flagged as indicative |
| Evaluation | Metrics, P@K, recall by type, threshold sensitivity, false-positive sources, weaknesses | Demo data only (needs labels) |
| Data upload | Template download, column mapping, validation, analysis | Described next |

**Related entries** (`detail.related_entries`): entries named in flags' `related_entry_id` (in both directions), plus
same-vendor entries within 14 days and 2% of the amount, plus same vendor and invoice number.

## 9.3 The upload pipeline (`schema.py`, `dashboard/upload.py`)

1. **Read** the CSV with every column as text (`dtype=str`) so nothing is silently converted.
2. **Map columns.** `suggest_mapping` normalises names (lowercase letters and digits only) and matches them to
   standard fields through a synonym list ("GL Account" -> `account`, "Dr" -> `debit`). The user can correct each
   choice. Five fields are required: `entry_id`, `posting_date`, `account`, `debit`, `credit`.
3. **Parse dates strictly** (`strict_dates`). Only explicit formats are accepted: ISO always; slash or dash dates in
   the chosen order (day-first or month-first). A bug fixed during development: pandas' guessing quietly turned
   `13/03/2025` into 13 March even when "month first" was selected, and would silently *swap* `05/03/2025`. Now an
   impossible reading is an error.
4. **Validate each row with pydantic** (`JournalLine`): whole-number account; numeric non-negative amounts (commas
   allowed); `source` is manual or automated (synonyms accepted); a line has a debit **or** a credit, not both and not
   neither. Errors list the **CSV row** (index + 2, because row 1 is the header), the column and a plain-English
   problem. At most 200 are collected.
5. **Entry-level checks**: every entry must **balance** (difference at most 0.01); line ids must be unique.
6. **Defaults and warnings.** Missing optional columns get defaults (document date = posting date, period from
   the posting date, source = manual) and the user is told which tests will be blind as a result.
7. **Analyse.** The same pipeline runs; rules needing master data skip; the Evaluation page explains there are no
   labels for uploaded data.

## 9.4 The Excel workpaper (`export.py`)

Built with openpyxl: **Cover** (entity, period, data source, preparer, reviewer, purpose, scope, procedures
performed, legend, a blank "results and conclusion" box, limitations); **Flagged entries** (formatted header,
frozen panes, filter, risk-tier shading, number formats, a status drop-down that rejects typos, landscape print
setup with the header repeated); **Summary** (counts by tier and status). It reads reviewer statuses and notes
from the session, so work done in the app lands in the file.

## 9.5 A real bug story worth telling

After the first version, you noticed that once the sidebar was collapsed there was no way to bring it back. The
cause was my own CSS: to hide Streamlit's "Deploy" button I had hidden the entire toolbar, and in this Streamlit
version the control that re-opens a collapsed sidebar lives inside that toolbar. I found it by inspecting the live
page in a headless browser (the control existed but its visibility was `hidden`), fixed it by hiding only the Deploy
button, menu and footer, and verified with a *real mouse click* at the control's position (not a programmatic
click, which works even on invisible elements). I added a test that fails if CSS ever hides those controls, then
audited every page at desktop and narrow widths and found and fixed four more small issues (squeezed KPI cards,
truncated date filter, refresh returning to Overview, stale upload state).

---

# 10. Engineering: config, tests, CI, and hands-on exercises

## 10.1 `config.yaml`: the control panel

Every number that could be argued about lives here, not in code. `config.py` loads it into pydantic models with
`extra="forbid"`, so a typo in a key name fails immediately instead of being silently ignored.

| Section | Controls |
|---|---|
| `company`, `calendar` | Name, currency, fiscal year; days after month end before a period closes (5) |
| `roles` | Role rank, approval limit and head count (drives users, approvals, and the split-purchase limits) |
| `generation` | Seed, target line count, number of vendors and employees, seasonality curves |
| `anomalies` | How many of each of the 12 types are planted |
| `accounts` | Account codes the tests rely on (payables 2000, cash 1000) so another chart of accounts can be used |
| `rules` | Every threshold of every test (windows, tolerances, materiality, minimum counts, p-value) |
| `ml` | Number of trees, seed, flag percentile (0.98), number of features quoted in a reason |
| `scoring` | The 23 rule weights, ML point cap (30), queue minimum, risk tiers (50 and 20) |
| `evaluation` | Combined alert threshold (20), top-K values, seeds for the stability check, challenge seed |

## 10.2 The test suite (162 tests)

Tests are what let you change things without fear, and they show a reviewer the project is trustworthy.

| Test file | What it protects |
|---|---|
| `test_generate.py` (26) | Every entry balances; same seed gives identical data; labels are separate and complete; each planted anomaly really has its property; clean data really does not (e.g. no clean manual entry on a weekend); Benford conformity |
| `test_calendar.py` | Friday/Saturday weekend, Bahrain holidays, period close dates |
| `test_rules_*.py` (one per family) | On tiny hand-built ledgers: one planted case is caught, one clean case is not. Plus an integration test on the full data: each planted type is caught at 95% or more, and under 1% of clean entries are flagged |
| `test_ml_pipeline.py`, `test_ml_scoring.py` | Features complete and finite; scores deterministic and in [0,1]; ML flag share matches config; the noisy-OR arithmetic; ML points only above the floor; queue ranked and explained; **no source file in `rules/` or `ml/` reads the labels** |
| `test_evaluate.py` | The metric formulas on tiny examples (`prf`, Wilson intervals, per-type definitions); report and charts are produced |
| `test_schema.py`, `test_upload_flow.py` | Upload validation (each kind of error is located by row and column; strict dates never swap day and month); a foreign-format CSV maps, validates and analyses end to end |
| `test_export.py` | The Excel workbook structure, formats, drop-down, cover sheet |
| `test_summary.py` | Risk tiers; rule-backed versus ML-only; the summary never touches labels |
| `test_challenge.py` | Controls caught; boundary variants missed as documented; ML catches the below-materiality journals; decoys reach the queue |
| `test_app.py` | Every dashboard page renders (including for uploaded data), status changes work, filters apply on submit, the page stays in the URL, and **the CSS never hides the sidebar controls** |

**Pattern worth explaining: tiny ledgers.** `tests/helpers.py` builds a handful of entries by hand (`entry`,
`invoice`, `payment`, `make_ds`). A test for a rule then reads like a story: "two payments, same invoice, 2 days
apart: both flagged; same amount 47 days apart: not flagged."

## 10.3 Quality gates

* **ruff** (`ruff check .`) lints and `ruff format .` formats; line length 100.
* **GitHub Actions** (`.github/workflows/ci.yml`) runs ruff and pytest on every push and pull request, on Linux with
  Python 3.13, after `pip install -r requirements.txt` (versions are pinned). A green badge shows it works on a
  clean machine, not just yours.
* **Commit history** has one commit per phase plus focused fix commits, with messages that explain *why*.

## 10.4 Commands (Windows Command Prompt, from the project folder)

```bat
.venv\Scripts\activate
python -m auditlens.generate         :: build data\*.csv
python -m auditlens.pipeline         :: analyse; outputs\review_queue.csv
python -m auditlens.evaluate         :: metrics report + charts
python -m auditlens.challenge_eval   :: the adversarial challenge set
streamlit run app.py                 :: the dashboard
pytest                               :: 162 tests
ruff check .                         :: lint
```

## 10.5 Hands-on exercises (do these; they teach more than reading)

After each, undo with `git checkout config.yaml` (or `git checkout .`).

1. **Move a threshold.** In `config.yaml` set `rules.round_amount.multiple` from 1000 to 500. Run
   `python -m auditlens.pipeline` and compare how many `ROUND_AMOUNT` flags there are (`outputs\flags.csv`). Open a few
   new ones: are they sensible? *Learns:* thresholds trade sensitivity for noise.
2. **Widen a window.** Set `rules.duplicates.window_days` to 14, then run `python -m auditlens.challenge_eval`. Look
   at `dup_late_repeat` (repeats 12-20 days later). Which now get caught? What else changes (false alarms)?
3. **Lower the Benford minimum.** Set `rules.benford.min_invoices` to 40 and rerun the challenge: the 40-invoice
   fabricated vendor should now be tested. Then look at the main Benford page: does a new vendor fail?
   *Learns:* small samples make chi-square less reliable.
4. **Change a weight.** Raise `DUP_NEAR_AMOUNT` from 8 to 30 and run `python -m auditlens.evaluate --no-stability`.
   Watch precision and the combined recall move. Why did precision drop?
5. **Change the ML cut-off.** Set `ml.flag_percentile` to 0.95 and rerun the evaluation. ML recall rises; what happens
   to its precision and to the size of the queue?
6. **New seed.** `python -m auditlens.generate --seed 7`, then evaluate. Do the numbers stay close to the stability
   table in the report?
7. **Break a rule on purpose.** In `rules/timing.py` change `cal.WEEKEND_WEEKDAYS` usage to Saturday/Sunday (5, 6) and
   run `pytest`. Which tests fail and why? *Learns:* what the tests protect. Undo it.
8. **Upload errors.** Download the template in the app, change one amount so the entry no longer balances, upload,
   validate, and read the error. Then put a `13/03/2025` date in with "year first" selected.
9. **Trace one entry end to end.** Pick a queue entry. Find which rule codes fired (`flags.csv`), open the function that
   produced the reason, compute its noisy-OR score by hand, and compare with the dashboard.
10. **Write a new rule** (recipe below).

**Recipe for adding a rule.** Example: "a payment posted on the same day as its invoice by the same user".

1. Add a function in the right module (e.g. `rules/approval.py`) taking `ds: Dataset`, returning
   `make_flags(entry_ids, FAMILY, "SAME_DAY_PAYMENT", reasons)`. Write the reason as a full sentence with numbers.
2. Call it from that module's `run` (inside `combine([...])`).
3. Add the code to `RULE_CODES` in `rules/__init__.py` and a weight in `config.yaml` `scoring.rule_weights` (a test
   fails if a code has no weight).
4. Put any threshold in `config.yaml` and `config.py`; never in the function.
5. If it targets one of the 12 types, add the code to `TYPE_CODES` in `evaluate.py`.
6. Write a unit test with a tiny ledger: one case caught, one clean case not.
7. Run `pytest`, `ruff check .`, and `python -m auditlens.evaluate --publish-docs`, then update the README table.

---

# 11. Design decisions and trade-offs ("why this and not that")

| Decision | The alternative | Why this choice |
|---|---|---|
| Rules **and** ML | Rules only, or ML only | Rules are specific and explainable (what auditors trust); ML finds what nobody wrote a rule for. The evaluation shows each one's real strengths |
| Unsupervised ML | Supervised classifier | Real data has no reliable fraud labels. A supervised model would also be trained on my own planted labels and just relearn my generator |
| Isolation Forest | LOF, one-class SVM, autoencoder | Fast, no scaling needed, few settings, works on mixed numeric features, easy to explain ("easy to isolate = unusual"). An autoencoder would be harder to explain and tune |
| Entry-level unit | Line-level | Auditors review whole entries; many findings are properties of the entry (approver, timing) |
| Noisy-OR combination | Sum, max, or logistic regression | Bounded at 100, diminishing returns, order-independent, explainable with one formula; a learned model would need labels |
| ML points capped at 30 and only for ML-flagged entries | Add the raw score | Keeps rules in charge; guarantees every queued entry has a reason |
| Rule signals excluded from ML features | Include them | Keeps ML an independent second opinion and the comparison meaningful |
| All thresholds in `config.yaml` | Constants in code | Auditors tune per client; changes are visible in version control; pydantic catches typos |
| Percentile for the ML score | Raw score | Easy to threshold ("top 2%"), independent of the model's internal scale |
| Separate `labels.csv` plus a test that scans source for label access | Labels as a column | Prevents leakage; shows the evaluation is honest |
| Challenge set and base-rate analysis | Report only the flattering numbers | Credibility: the limits are measured and stated |
| ML-only findings shown last, excluded from "value to follow up" | Treat all High/Medium alike | The evaluation says ML alone is about 13% precise, so presenting it as equal would mislead |
| Strict date parsing | Let pandas guess | A silent day/month swap would corrupt every date-based test without any error |
| Streamlit | Flask/React, Power BI | Python end to end, fast to build, deployable free; good fit for a portfolio data app |
| Synthetic Bahraini company | Public dataset | No suitable public GL with known anomalies exists; this also shows local context (Fri/Sat weekend, BHD) |

**Bugs found by the tests and the checks, and what they taught** (good stories for an interview)

1. *Invoice-number collisions.* Injecting several invoices into one gap in a vendor's numbering used up the
   numbers and reused existing ones, producing accidental duplicates and out-of-order numbers that looked like real
   findings. Fix: shift later numbers up. Lesson: unexplained false positives often mean your *data generator* is
   wrong, not your rule.
2. *Benford contamination.* One vendor received three split-purchase groups, so a clean vendor failed Benford.
   Fix: choose vendors without replacement. Lesson: cross-talk between planted anomalies.
3. *ML entries without a reason.* Entries between the 95th and 98th ML percentile earned points but had no flag.
   Fix: one threshold controls both. Lesson: every queued entry must be explainable.
4. *Silent date swap.* Described in 9.3. Lesson: validation must be strict, and a wrong setting must fail loudly.
5. *Sidebar that could not be re-opened.* Described in 9.5. Lesson: test with real user actions.
6. *A threshold tuned after seeing results.* I tightened the near-duplicate tolerance after a first run showed many
   coincidences, and the report says so. Lesson: disclose any tuning.

---

# 12. Interview preparation: 30 questions with answers

Answer in your own words; the bold phrases are the key ideas.

**The project**

1. **What is AuditLens in one sentence?** A journal-entry analytics tool that combines 23 explainable audit tests
   with an unsupervised anomaly model into a ranked review queue, evaluated against planted ground-truth anomalies.
2. **Why did you build it?** Auditors must look for fraud and error in tens of thousands of entries; analytics
   tests the whole population and focuses human time on the riskiest entries (ISA 240 expects journal-entry testing).
3. **Why synthetic data?** Real ledgers are confidential, and real data has no answer key. Synthetic data lets me
   plant known anomalies and measure precision and recall. The price is that results show the system works on data
   like mine, which I state openly.
4. **How is your data realistic?** Month-end spikes, seasonal revenue (Ramadan dip), recurring vendors, an approval
   hierarchy, vendor invoice numbering, the Bahrain Friday/Saturday weekend and public holidays, BHD with three
   decimals, and Benford-conforming amounts.
5. **What was the hardest part?** Making the evaluation honest: preventing label leakage, avoiding generator
   artefacts that looked like findings, and being candid that the test is partly circular.

**Audit and rules**

6. **Explain a split purchase.** Someone splits one large purchase into several invoices each just under their
   approval limit, so no higher approval is needed. I flag three or more invoices at 90-100% of a limit from the same
   creator to the same vendor within 10 days.
7. **Why test weekend postings only for manual entries?** Payroll and depreciation run automatically on the last day
   of the month, even on a weekend. People rarely have a reason to key entries when the office is shut.
8. **What does the post-close test catch?** Entries posted after the period closed (month end plus 5 days); they
   change reported results after management has seen them.
9. **How do you detect a ghost vendor?** Match vendor bank account or address to employees after normalising text.
   I flag every entry of that vendor because the risk attaches to the vendor.
10. **Why a bank-change test?** A changed bank account followed quickly by a large payment is the classic
    business-email-compromise pattern. I flag payments of at least 20,000 and 5 times the vendor's median within 14
    days of a change.
11. **Why three duplicate tests?** Evidence strength differs: the same invoice paid twice is strongest, an identical
    amount next, a near amount weakest (coincidences are common), so they carry weights 40, 35 and 8.

**Benford**

12. **What is Benford's Law?** In many natural datasets the leading digit is 1 about 30% of the time and 9 about 5%;
    P(d) = log10(1 + 1/d). Invented numbers often break it.
13. **How do you test it?** Chi-square goodness of fit with 8 degrees of freedom on a vendor's leading digits, flagged
    at p below 0.001, only with at least 50 invoices.
14. **When does Benford fail?** Assigned numbers, capped or contract amounts, narrow ranges, small samples. So a
    flag is a lead, not proof.
15. **Why such a strict p-value?** I test about 55 vendors; at p < 0.001 I expect about 0.05 false alarms, at 0.05 I
    would expect nearly three.

**Machine learning**

16. **How does Isolation Forest work?** It builds random trees by splitting on random features and values; unusual
    entries are isolated in fewer splits, so a short average path length means anomalous.
17. **Why not supervised learning?** No trustworthy labels in real life, and my planted labels would only teach it my
    generator.
18. **What are your features?** Twenty: amount and account z-scores, vendor frequency and amount statistics,
    closeness to neighbouring vendor entries, time features, posting lag, manual or automated, user-account and
    account-pair rarity, and amount relative to the approver's limit.
19. **Why leave the rule signals out of the features?** So the ML layer is an independent second opinion; otherwise it
    would just rediscover the rules.
20. **How do you explain an ML flag?** Compare each feature with entries of the same kind (source and vendor group)
    using a robust z-score (median and MAD), and name the three most unusual features in plain language.
21. **Why is ML precision only 13%?** It finds entries that are numerically unusual, but most audit anomalies are
    relational (a duplicate looks like any payment on its own). It also flags many legitimate large or rare entries.
    It is a second opinion, and I score it that way.

**Scoring and evaluation**

22. **Explain the risk score.** Rule weights combine by noisy-OR (100 x (1 - product of (1 - w/100)), so more
    evidence raises the score with diminishing returns and never exceeds 100), plus up to 30 points for
    ML-flagged entries. It maps to High (50+), Medium (20+) and Low.
23. **Walk through precision and recall.** Of what the rules flagged, 84% were real (precision); of what was real, the
    rules found 100% (recall). F1 balances both. At the top 100 of the queue precision is 100%.
24. **Your recall is 100%. Isn't that suspicious?** Yes, and I say so: I wrote the rules and the generator from the
    same definitions, so it shows correct implementation, not real-world strength. That is why I built an
    adversarial challenge set.
25. **What does the challenge set show?** Controls are caught 100%; boundary cases just outside a threshold only 3%;
    ML rescues the journals just under materiality; legitimate look-alikes all reach the queue. So thresholds are
    avoidable and the output is a lead.
26. **What would precision be in a real ledger?** With a 0.1% anomaly rate and my 0.32% false-positive rate, about
    24%, i.e. roughly three false alarms per real problem. The synthetic 84% is optimistic.
27. **How would you reduce false positives?** Feedback loop from reviewers' decisions to re-weight rules, per-client
    thresholds, fuzzy matching, evidence attachments so legitimate entries can be excluded, and graduated scores
    near thresholds.

**Engineering and deployment**

28. **How do you know it works on a fresh machine?** GitHub Actions runs ruff and 162 tests on Linux for every
    push, with pinned dependencies.
29. **How does the upload feature protect against bad data?** Column mapping, strict date formats, pydantic row
    validation with row and column error messages, a balance check on every entry, and warnings about which tests
    become blind when columns are missing.
30. **How would it scale to millions of lines?** The rules are vectorised pandas; the duplicate test does a
    self-join per vendor, which would need windowed joins or a database at that scale. Move the pipeline to a
    warehouse or Spark, keep the same logic, and process by period.

**Curveballs**

* *"What if the fraudster knows your thresholds?"* They can stay just under them; the challenge set measures
  exactly that. Mitigations: randomised or graduated thresholds, vendor-level totals regardless of creator, and
  the ML layer, which caught the below-materiality journals.
* *"What did you get wrong?"* The six stories in Section 11.
* *"Is this production-ready?"* No: single synthetic company, no VAT or multi-currency, no audit trail or access
  control. It is a credible prototype with honest limits.
* *"Does it replace an auditor?"* No: it narrows the population and explains why; judgement and evidence remain
  with the auditor.

---

# 13. Glossary and quick reference

## 13.1 Glossary

| Term | Meaning |
|---|---|
| General ledger (GL) | The company's master record of all financial transactions |
| Journal entry | One recorded transaction; its debits equal its credits |
| Chart of accounts | The numbered list of accounts |
| Accounts payable (AP) | Money owed to suppliers (account 2000) |
| Posting date / document date | When it was recorded / the date on the source document |
| Period close | The cut-off after which a month should not receive postings |
| Manual / automated entry | Keyed by a person / generated by a system |
| Segregation of duties | Different people create and approve |
| Materiality | The size above which an error would matter to users of the accounts (250,000 here) |
| Management override | Management bypassing controls, often via unusual journals (ISA 240) |
| Ghost vendor | A fictitious vendor set up to receive payments |
| Benford's Law | Expected distribution of leading digits |
| Chi-square, p-value | A measure of deviation from expected counts; the chance of a deviation that large by luck |
| MAD | Mean absolute deviation of digit shares; also median absolute deviation (robust z-score) |
| Z-score | How many standard deviations a value is from average |
| Isolation Forest | An anomaly detector that isolates unusual points with random splits |
| Percentile | A value's rank as a fraction (0.98 = top 2%) |
| Noisy-OR | Probability-style combination: 1 minus the product of (1 - weight) |
| False positive / false negative | Flagged but fine / missed but real |
| Precision, recall, F1 | Share of flags that are real; share of real that are flagged; their balance |
| Precision@K | Precision among the top K ranked entries |
| Base rate (prevalence) | How common true positives are in the population |
| Wilson interval | A confidence interval for a proportion |
| Label leakage | Using the answer key when building the detector |
| Boundary case / decoy / control | Just outside a threshold / legitimate look-alike / should-be-caught case |
| Rule-backed / ML-only | Matches a specific audit test / flagged only as statistically unusual |
| Workpaper | An auditor's documented record of work done |

## 13.2 Numbers to know cold

| Item | Value |
|---|---|
| Ledger | 49,464 lines, 24,714 entries, 1 fictional company, FY2025 |
| Planted anomalies | 412 entries (1.7%), 12 types |
| Rules | 23 codes in 8 families |
| ML | Isolation Forest, 300 trees, 20 features, top 2% flagged |
| Queue | 903 entries: 71 High, 427 Medium, 405 Low |
| Rules alone | precision 84.1%, recall 100%, F1 0.914 |
| ML alone | precision 13.3%, recall 16.0%, F1 0.146 |
| Combined (risk 20+) | precision 69.9%, recall 84.5%, F1 0.765 |
| Precision@50 / @100 | 100% / 100% (rules and combined) |
| Realistic precision at 0.1% prevalence | about 24% |
| Challenge set | controls 100%, boundary cases 3% (intended rule) |
| Tests | 162 passing; CI green |

## 13.3 Key thresholds (all in `config.yaml`)

Duplicate window 7 days, near tolerance 0.5%; split band 90-100% of limit, 3 invoices in 10 days; backdating over 30
days; period closes 5 days after month end; round amounts: multiples of 1,000, at least 5,000, contract exempt at 6
repeats; materiality 250,000, last 3 business days; bank change window 14 days, 20,000 and 5 times median;
sequence gap over 50; Benford at least 50 invoices, p below 0.001; rare pair at most 3 entries; rare user-account at
most 3 with at least 50 user entries; ML flag at the 98th percentile, at most 30 points; tiers 50 and 20.
