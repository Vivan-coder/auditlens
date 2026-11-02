# Data dictionary

**All data is synthetic.** The company, vendors, employees and users are fictional. Any resemblance to
real people or businesses is coincidence. Generate it with `python -m auditlens.generate`
(seed and size are set in `config.yaml`, or `--seed` / `--lines`).

Currency is Bahraini dinar (BHD). Amounts have 3 decimals (fils). The fiscal year is calendar 2025.
Bahrain's weekend is **Friday and Saturday**; the working week is Sunday to Thursday.

## Files written to `data/`

| File | Contents |
|------|----------|
| `journal_entries.csv` | The general ledger journal, one row per line (the only file the audit tests see) |
| `labels.csv` | **Ground truth** of planted anomalies. Used only by evaluation, never as a feature |
| `chart_of_accounts.csv` | Account codes and names |
| `users.csv` | People who create and approve entries |
| `vendors.csv` | Vendor master data |
| `employees.csv` | Employee master data |
| `vendor_bank_changes.csv` | History of vendor bank-account changes |

## journal_entries.csv

| Column | Type | Description |
|--------|------|-------------|
| `entry_id` | str | Journal entry id (`JE000123`). Groups the lines of one entry; every entry balances |
| `line_id` | str | Unique line id (`JE000123-01`) |
| `document_date` | date | Date on the source document (invoice date, payment date) |
| `posting_date` | date | Date the entry was recorded in the ledger. Never earlier than `document_date` |
| `account` | int | Account code from the chart of accounts |
| `debit` | float | Debit amount (0 if a credit line) |
| `credit` | float | Credit amount (0 if a debit line) |
| `description` | str | Free text, e.g. `"Smith Goods Co. - invoice INV-001234"` |
| `vendor_id` | str | Vendor for purchase invoices and payments; empty for sales, payroll and journals |
| `created_by` | str | `user_id` who keyed the entry (`SYSTEM` for automated postings) |
| `approved_by` | str | `user_id` who approved it. Empty for automated entries |
| `source` | str | `manual` (keyed by a person) or `automated` (system / interface) |
| `invoice_number` | str | Vendor invoice number (`INV-001234`) or our sales invoice number (`SI-000123`); payments and receipts repeat the number they settle |
| `period` | str | Accounting period `YYYY-MM` the entry is booked to |

### How normal activity is built

| Activity | Accounting | Source |
|----------|-----------|--------|
| Sales invoice | Dr 1100 Receivables / Cr 4000 or 4100 Revenue | automated |
| Customer receipt | Dr 1000 Cash / Cr 1100 | 70% automated, 30% manual |
| Vendor invoice | Dr expense (by vendor category) / Cr 2000 Payables | 70% manual, 30% automated |
| Vendor payment | Dr 2000 / Cr 1000 | manual, paid at the vendor's terms (30/45/60 days) |
| Payroll (monthly) | Dr 6000 (one line per department) / Cr 1000 | automated, last day of month |
| Depreciation (monthly) | Dr 6900 / Cr 1590 | automated, last day of month |
| Accrual and next-month reversal | Dr expense / Cr 2100, then the reverse | manual |
| Reclassification | Dr one expense / Cr another, from three fixed pairs | manual |

Realism built in:

* **Seasonality and month-end spikes.** Monthly volume follows `sales_seasonality` /
  `purchase_seasonality` (Ramadan dip in March, strong Q4). The last three business days of each month
  carry roughly 2.6x the normal daily volume.
* **Recurring vendors.** Rent, fleet lease, electricity, telecom, cleaning, security, SaaS and
  insurance are billed on a fixed schedule (rent is a constant 4,500.000 per month; insurance is quarterly).
* **Benford-conforming amounts.** Each amount is `10^(d + u)` with `u` uniform on [0,1), `d` an order of
  magnitude drawn per vendor category. A uniform log mantissa gives exactly Benford first digits.
* **Approvals.** A manual entry is approved by the lowest-limit user who outranks the creator and whose
  `approval_limit` covers the amount, so a clean entry is never self-approved or over the limit.
* **Posting lag and periods.** Manual entries post 0-3 days after the document date, on business
  days. A period closes `period_close_days` (5) days after month end. An entry dated in March but
  posted on 2 April still belongs to period 2025-03 (inside the close window); otherwise the period is the posting month.
* **Vendor invoice numbers** rise by 5-15 per invoice in document-date order (the vendor also bills
  other customers). Automated month-end postings (payroll, depreciation) may fall on a weekend, which is
  why weekend tests should look at manual entries.

## labels.csv (ground truth, separate file)

| Column | Description |
|--------|-------------|
| `entry_id` | The labelled entry |
| `anomaly_type` | One of the 12 types below |
| `role` | `injected` (the planted entry) or `counterpart` (the genuine entry it duplicates) |
| `related_entry_id` | The other entry in a pair (duplicates) |
| `note` | Human-readable description of what was planted |

An entry can carry more than one label. Evaluation works at **entry level**: each journal entry is one review item.

| `anomaly_type` | What is planted | Entries labelled |
|----------------|-----------------|------------------|
| `duplicate_payment` | Second payment to the same vendor, same or within 0.5% amount, 1-3 business days later; half re-keyed with a `-R` invoice suffix | the duplicate (`injected`) and the original (`counterpart`) |
| `split_purchase` | 3-5 invoices of 90-99.5% of an approval limit, same vendor and clerk, within a few days | each invoice |
| `weekend_holiday_posting` | Manual invoice posted on a Friday/Saturday or a Bahrain public holiday | the invoice |
| `round_amount` | Manual invoice for an exact multiple of 10,000 | the invoice |
| `same_creator_approver` | Manual journal approved by the person who created it | the journal |
| `late_or_backdated_posting` | (a) posted after its period closed, or (b) posted 45-150 days after the document date | the invoice |
| `ghost_vendor` | Vendor sharing a bank account (2) or an address (1) with an employee, with 8 invoices and payments | every invoice and payment of that vendor |
| `bank_change_large_payment` | Vendor bank account changed, then a 40,000-95,000 payment 1-5 days later | the payment |
| `invoice_sequence_break` | A numbering gap (jump of 80-400) or an invoice number lower than the previous one | the invoice |
| `unusual_account_use` | (a) a debit/credit pair never otherwise seen, or (b) an AP clerk booking to an account outside their normal portfolio | the entry |
| `benford_violation` | One vendor whose invoices are uniform in 7,000-9,990 (digits 7-9 only) | the vendor's invoices (payments are not labelled) |
| `large_manual_period_end` | Manual journal of 260,000-900,000 (materiality is 250,000) on one of the last two business days of a month | the journal |

Planted entries are otherwise ordinary (valid approver, business-day posting, normal lag) so each one
should be caught by its own test and not by accident. Some cross-talk still happens naturally (for
example a planted entry may have a rare user/account pair), and that is intentional: it makes the
evaluation honest.

Injected invoices for split purchases, round amounts, timing and account anomalies do not get payments.
That is a simplification: the receivable side of the story is not simulated for them.

## chart_of_accounts.csv

`account`, `account_name`, `account_type` (Asset / Liability / Equity / Revenue / Expense).
Account 8100 (Suspense) is deliberately unused in normal activity.

## users.csv

| Column | Description |
|--------|-------------|
| `user_id` | Login id (first initial + surname) or `SYSTEM` |
| `full_name` | Fictional name |
| `role` | `ap_clerk`, `accountant`, `senior_accountant`, `financial_controller`, `cfo`, `system` |
| `approval_limit` | Largest entry the user can approve (BHD); clerks cannot approve |
| `department` | Department |

Limits come from `config.yaml`: accountant 25,000, senior accountant 100,000, financial controller 500,000, CFO 5,000,000.

## vendors.csv

| Column | Description |
|--------|-------------|
| `vendor_id` | `V0001`... |
| `vendor_name` | Fictional name |
| `address` | Bahrain-style address |
| `bank_account` | Current IBAN-shaped account (`BH` + 2 digits + 4-letter bank code + 14 digits; check digits are not real) |
| `created_date` | When the vendor was set up; about 10% are created during the year, and a vendor never invoices before it exists |
| `category` | Vendor category (drives the expense account) |
| `payment_terms_days` | Days from invoice to payment |

## employees.csv

`employee_id` (`E0001`...), `full_name`, `address`, `bank_account`, `department`.

## vendor_bank_changes.csv

`change_id`, `vendor_id`, `change_date`, `old_bank_account`, `new_bank_account`, `changed_by`.
`vendors.csv` holds the current account. Three legitimate changes are included alongside the planted ones.
