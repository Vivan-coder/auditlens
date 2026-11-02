# Methodology

How AuditLens decides what to flag, why each test exists, and how the result is scored and
evaluated. All thresholds named here live in `config.yaml`; none are hardcoded.

## 1. Approach in one paragraph

Auditing standards (for example ISA 240 on fraud) require auditors to test journal entries and
other adjustments for signs of management override of controls. A general ledger has tens of
thousands of entries, so nobody reads them all. AuditLens narrows the population in two ways:
**rule-based tests** that encode what auditors already look for (duplicate payments, split
purchases, weekend postings, ...) and an **unsupervised model** (Isolation Forest) that scores how
statistically unusual each entry is. The two are combined into one **risk score**, producing a
ranked review queue where every entry shows its reasons in plain language.

Unit of analysis: one **journal entry** (a group of balanced lines), because that is what a
reviewer opens and signs off.

## 2. The audit tests

Each test returns flagged entries with a **rule code** and a **human-readable reason**.

### Duplicate payments (`duplicates`)

| Code | Fires when |
|------|-----------|
| `DUP_SAME_INVOICE` | Two payments to one vendor reference the same invoice number (re-key suffixes such as `-R` are ignored) |
| `DUP_EXACT_AMOUNT` | Two payments to one vendor for exactly the same amount within `window_days` |
| `DUP_NEAR_AMOUNT` | Same vendor, amounts within `amount_tolerance_pct`, within `window_days` (weak) |

*Why auditors care.* Paying the same invoice twice is among the most common and costly
accounts-payable errors, and is also a cheap way to extract cash. The near-amount test is weak
evidence by design: large vendors invoice similar amounts by coincidence, so it carries a low weight.

### Approval and segregation of duties (`approval`)

| Code | Fires when |
|------|-----------|
| `SPLIT_BELOW_LIMIT` | At least `min_count` invoices from the same creator to the same vendor, each between `band_low_pct`% and 100% of an approval limit, within `window_days` |
| `SELF_APPROVED` | A manual entry's creator and approver are the same user |
| `NO_APPROVER` | A manual entry has no approver |
| `APPROVER_OVER_LIMIT` | The entry amount exceeds the approving user's limit |

*Why auditors care.* Approval limits are the main preventive control over spending. Splitting one
purchase into several just-under-limit pieces avoids escalation; self-approval removes the second
pair of eyes entirely (a segregation-of-duties failure).

### Timing (`timing`)

| Code | Fires when |
|------|-----------|
| `WEEKEND_POSTING` | A manual entry is posted on a Friday or Saturday (Bahrain's weekend) |
| `HOLIDAY_POSTING` | A manual entry is posted on a Bahrain public holiday |
| `POST_CLOSE_POSTING` | The posting date is after the entry's period closed (`period_close_days` after month end) |
| `BACKDATED_POSTING` | Posting date is more than `backdate_days` after the document date |

*Why auditors care.* Few people have a legitimate reason to key manual entries when the office is
shut. Entries slipped into a closed period change reported results after management has seen them,
and long document-to-posting gaps are a way to move amounts between periods. Automated batches
(payroll, depreciation) legitimately run at month end, even on weekends, so the weekend test applies to
manual entries only (`rules.timing.weekend_sources`).

### Amounts (`amounts`)

| Code | Fires when |
|------|-----------|
| `ROUND_AMOUNT` | A manual entry of at least `min_amount` is an exact multiple of `multiple` (and is not a repeating contract amount) |
| `LARGE_MANUAL_PERIOD_END` | A manual entry at or above materiality is posted in the last `period_end_business_days` business days of a month |
| `LARGE_MANUAL` | Same, but not near period end |

*Why auditors care.* Real transactions produce messy numbers; round ones suggest estimates or
invention. Large manual journals near period end are a recognised management-override risk, so
they are always examined whatever their wording.

### Vendor master data (`vendors`)

| Code | Fires when |
|------|-----------|
| `GHOST_VENDOR_BANK` / `GHOST_VENDOR_ADDRESS` | A vendor's bank account or address matches an employee's (after normalising case and punctuation). Every entry posted to that vendor is flagged |
| `BANK_CHANGE_LARGE_PAYMENT` | A payment of at least `min_amount` and `median_multiple` times the vendor's median payment is made within `window_days` of a bank-account change |

*Why auditors care.* A vendor that shares an employee's bank account is the textbook fictitious-vendor
scheme. A bank-detail change followed quickly by a large payment is the textbook business-email-compromise
pattern, where a fraudster redirects a genuine vendor's payments.

### Invoice number sequences (`sequence`)

| Code | Fires when |
|------|-----------|
| `INVOICE_GAP` | A vendor's invoice number jumps by more than `max_gap` from the previous one |
| `INVOICE_OUT_OF_ORDER` | An invoice number is lower than one already received from that vendor |
| `DUPLICATE_INVOICE_NUMBER` | The same vendor invoice number is booked twice |

*Why auditors care.* Vendor invoices normally arrive in numerical order. A jump can mean documents
were removed or numbers invented; a lower number arriving late suggests a backdated or fabricated invoice.

### Benford's Law (`benford`)

In many naturally occurring sets of financial amounts the leading digit *d* appears with
probability log10(1 + 1/d): about 30.1% for 1, 17.6% for 2, down to 4.6% for 9. Invented numbers
tend not to follow this. For each vendor with at least `min_invoices` invoices (the chi-square test is
unreliable below that), AuditLens compares the observed digit counts with the expected counts using a
chi-square test with 8 degrees of freedom and also reports the mean absolute deviation (MAD) of the digit
shares. Vendors with a p-value below `p_threshold` get `BENFORD_VENDOR` on every one of their invoices.

*Caveats.* Benford is a **lead, not proof**. Amounts bound by contract or price lists legitimately
deviate, and testing many vendors will occasionally flag a conforming one by chance, which is why the
threshold is strict (0.001). Because it implicates a whole vendor rather than one entry, it carries a
low weight and is best read on the Benford page.

### Account usage (`pairings`)

| Code | Fires when |
|------|-----------|
| `RARE_ACCOUNT_PAIR` | An entry debits and credits an account pair seen in at most `rare_pair_max_count` entries all year |
| `RARE_USER_ACCOUNT` | A manual-entry user with at least `user_min_entries` entries posts to an account they used at most `rare_user_account_max_count` times |

*Why auditors care.* Moving value between accounts that are never otherwise linked (for example Suspense
paid from Bank), or a user working outside their usual accounts, are classic signs of error or override.
Rarity is judged against the ledger's own history, not a fixed list.

## 3. The machine-learning layer

**Model.** An Isolation Forest builds many random trees that repeatedly split the data on a random
feature at a random value. Unusual points are separated from the rest in few splits, so a short average path
length means "more anomalous". It needs no labels, scales to this volume in about a second, and has few
tuning knobs (`ml.n_estimators`, `ml.seed`).

**Features** (one row per entry; `src/auditlens/ml/features.py`): amount and its z-score against the
other lines on the same account; number of lines; round-amount flag; for vendor entries, how many entries
the vendor has, the amount's z-score against the vendor's history, its ratio to the vendor's median, and
how close it is to the neighbouring entry of the same vendor in amount and days (a duplicate signature);
day of week, weekend and holiday flags, day of month, days to month end; document-to-posting lag;
manual or automated; rarity of the user/account combination and of the debit/credit pair
(-log10 of their frequency); and the amount as a multiple of the approver's limit.

**What is deliberately left out.** No labels are used, ever. The rule signals themselves (self-approval,
near-limit amounts, missing approver) are not features, so the model gives an independent view instead of
repeating the rules.

**Output.** The raw score is converted to a percentile in [0, 1]. Entries in the top
`1 - ml.flag_percentile` (2%) get an `ML_ANOMALY` flag whose reason names the three features that deviate
most from *similar* entries (same source, vendor or non-vendor), for example "posted on a weekend: 1.00
(typical for similar entries 0.00)". Comparing against similar entries avoids the useless explanation that
every manual entry differs from automated payroll.

## 4. The risk score

```
rule_score  = 100 * (1 - prod over fired rules of (1 - weight/100))        # noisy-OR
ml_points   = ml_max_points * (ml_percentile - flag_percentile) / (1 - flag_percentile),  only if ML-flagged
risk_score  = min(100, rule_score + ml_points)
```

* **Noisy-OR** treats each rule as independent evidence of different strength: two moderate hits beat one,
  but the score saturates below 100 and a single strong test cannot be outvoted by many weak ones.
* **Weights** (`scoring.rule_weights`) reflect how specific a test is. A ghost-vendor bank match (45) or a
  large period-end manual journal (40) weighs more than a near-duplicate amount (8) or a vendor-level Benford
  result (15).
* **ML points** are capped (`ml_max_points`, 30) and given only to ML-flagged entries, so rules carry most of
  the weight, the model can lift an unusual entry no rule describes, and every queued entry has a reason.

The weights are a judgement, informed by audit practice; they were not fitted to the labels.

**Risk tiers.** For readers, the score is banded using `scoring.risk_tiers`: **High** (50 or more),
**Medium** (20 to 50) and **Low** (below 20). High and Medium warrant follow-up; Low entries carry a single
weak signal and can be sampled.

**Rule-backed versus ML-only.** The executive summary separates entries that match at least one specific
audit test from entries flagged *only* as statistically unusual. The evaluation shows ML-only flags are far
less precise (about 13%), so they are reported as a lower-confidence lead, listed last and excluded from the
"value to follow up" figure. Each finding theme carries a suggested follow-up procedure (see
`src/auditlens/summary.py`); these are prompts for the auditor, not conclusions.

## 5. Evaluation

The generator plants 12 labelled anomaly types and writes the labels to a separate file that no test
or model reads. `python -m auditlens.evaluate` reports precision, recall and F1 overall and per type for
rules alone, ML alone and the combined score (risk of at least `evaluation.combined_threshold`), plus
precision at the top 50 and 100 entries (reviewer capacity), threshold sensitivity, 95% Wilson confidence
intervals and a repeat on freshly generated datasets with different seeds. The conventions for per-type
precision are stated in the report. See `docs/evaluation_report.md` for results and a candid list of
weaknesses, chiefly: the rules and the generator share definitions (so recall is flattered), the anomaly
rate is far above real life (so precision is flattered), and the ML layer finds only statistically odd
entries.
