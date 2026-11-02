# Challenge set results

The main evaluation plants every anomaly exactly as its rule defines it, so rule recall there is close to
perfect by construction. This challenge ledger tests the same system on cases **written to stress it**. It
uses the same clean baseline (seed 2025) with no standard anomalies, and plants:

* **boundary** cases just outside a threshold (a duplicate payment 12 days later when the window is 7 days,
  a split at 85% of the limit when the band starts at 90%, a journal of 240,000 when materiality is 250,000),
* **disguised** cases that evade exact matching (an employee's address reformatted),
* **controls** the rules should catch (to prove the tests still work and nothing is silently broken), and
* **decoys**: legitimate entries that look like anomalies (to measure false alarms on look-alikes).

**Caveat.** I wrote this set too, so it is a stress test, not independent validation. A set written by
someone else, or real client data, would be the next step. Boundary cases were designed to be missed, so a
miss there is a *measured limit*, not a surprise; the useful output is knowing exactly where the limits are.

## Results by variant

| Variant | Design | n | Caught by intended rule | Any rule | ML | Combined | Other rules that fired |
|---|---|---|---|---|---|---|---|
| `dup_late_repeat` | boundary: just outside a rule | 10 | 0% | 0% | 0% | 0% | - |
| `dup_amount_3_to_8pct` | boundary: just outside a rule | 10 | 10% | 10% | 0% | 0% | - |
| `split_wide_band_80_88pct` | boundary: just outside a rule | 16 | 0% | 0% | 25% | 19% | - |
| `split_only_two_parts` | boundary: just outside a rule | 12 | 17% | 17% | 33% | 25% | - |
| `split_across_three_clerks` | boundary: just outside a rule | 12 | 0% | 67% | 83% | 75% | RARE_USER_ACCOUNT |
| `backdated_20_to_26_days` | boundary: just outside a rule | 10 | 0% | 0% | 40% | 10% | - |
| `post_close_one_day_over` | control: should be caught | 6 | 100% | 100% | 0% | 100% | - |
| `near_round_amounts` | boundary: just outside a rule | 10 | 0% | 0% | 10% | 10% | - |
| `manual_just_below_materiality` | boundary: just outside a rule | 6 | 0% | 0% | 100% | 100% | - |
| `reciprocal_approval_pair` | boundary: just outside a rule | 12 | 0% | 0% | 25% | 17% | - |
| `sequence_gap_30_to_45` | boundary: just outside a rule | 8 | 38% | 38% | 0% | 38% | - |
| `sequence_gap_100_to_200` | control: should be caught | 8 | 100% | 100% | 0% | 100% | - |
| `ghost_address_reformatted` | boundary: just outside a rule | 23 | 0% | 0% | 0% | 0% | - |
| `ghost_bank_spaced_lowercase` | control: should be caught | 15 | 100% | 100% | 7% | 100% | - |
| `bank_change_payment_20_to_30_days` | boundary: just outside a rule | 6 | 0% | 0% | 0% | 0% | - |
| `benford_vendor_only_40_invoices` | boundary: just outside a rule | 40 | 0% | 0% | 0% | 0% | - |
| `decoy_legit_weekend_entries` | decoy: legitimate look-alike | 10 | 100% | 100% | 10% | 100% | - |
| `decoy_legit_large_capex_journal` | decoy: legitimate look-alike | 5 | 100% | 100% | 100% | 100% | - |
| `decoy_two_genuine_same_amount_invoices` | decoy: legitimate look-alike | 16 | 100% | 100% | 0% | 100% | - |
| `decoy_contract_round_payments` | decoy: legitimate look-alike | 8 | 100% | 100% | 0% | 100% | - |

*Caught by intended rule* = a rule designed for this anomaly fired. *Any rule* also counts incidental hits
by other rules (shown in the last column). Percentages are of the planted entries.

## Reading the results

* **Controls** (should be caught): 100% caught by the intended rule across
  29 entries. The tests still work; the misses below are real limits, not a broken pipeline.
* **Boundary and disguised cases**: only 3% caught by the intended rule
  (175 entries). The rules are **threshold-based**, so an anomaly just inside the threshold passes
  silently. 8% are flagged by *some* rule (mostly incidentally) and
  18% by the ML model. This is the honest answer to "what if a fraudster knows the
  limit": thresholds are known to the person committing the fraud and can be avoided.
* **Decoys**: 100% of legitimate look-alikes reach the combined review queue as
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
