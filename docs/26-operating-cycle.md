# 26 — The Operating Cycle (how the system is used)

**Date:** 2026-06-12
**Audience:** anyone building or changing the operator-facing flow.

This document describes the *rhythm* the system is built around. Every feature
should serve this cycle. If a feature does not help one of these steps, it does
not belong on the operator's path.

## The core principle

**The system proposes, the operator approves.** The operator never assembles
data by hand. They upload one thing a week, glance at what the system worked
out, fix the few things it got wrong, and sign off. The end product — the VAT
book — falls out of that sign-off automatically.

It has to *feel* simple: one screen per job, transactions as rows you click,
no clutter, nothing on screen that isn't part of the decision in front of you.

## The rhythm

### Continuous (no operator action)
- Invoices, credit notes, and statements arrive by Gmail and land in the
  document store (`documents`), get extracted into financial facts/rows, and
  are pushed to R2. This already runs.

### Weekly (two inputs)
- **Money out:** the operator uploads **that week's bank statement**. Bank
  statements are the source of truth for transactions — nothing else creates a
  transaction. On import the system auto-matches each to its documents (direct
  invoice, statement settlement, supporting docs).
- **Money in:** the operator provides the **week's takings, per night**. This is
  the sales side — it drives output VAT.
- Both are quick inputs; the matching and categorisation happen automatically.

### Working a period (the only real "work")
The organizing unit is the **week**, aligned to the weekly upload. The operator
goes into a week and works through its transactions. They might do this every
couple of weeks — but it can happen at any time; the cadence is theirs, not the
system's. For each week:

1. **Review the matches.** A clean list of that week's bank transactions, each
   showing its status and, on click, its documents. Most are already matched —
   the operator is scanning for the handful that aren't, or that matched wrong.
2. **Fix what's wrong.** Confirm a suggested match, reject a bad one, point a
   transaction at the right document, or mark "no document expected" (bank fees,
   wages, drawings).
3. **Check the VAT view.** The same transactions, shown the way the VAT book
   shows them: transaction + its documents + category + VAT treatment. This is
   the deliverable taking shape. The operator confirms the categories and VAT
   splits look right (most are auto-derived — see [27](27-vat-book-automation.md)).
4. **Mark transactions complete.** As each transaction looks right, the operator
   marks it complete. When every transaction in the week is complete, **the week
   shows complete** — a clear "this week is done" signal.

## What "complete" means (design)

Completion is a **soft marker, not a lock**:
- A transaction can be marked **complete** at any time. It rolls up: when all of
  a week's transactions are complete, the week reads as complete.
- **Completed items stay fully visible and editable.** Nothing is hidden or
  archived away. The operator can open any week — done or not — see its
  transactions and documents, and change anything whenever they want.
- The marker is a **progress signal**, not a freeze. Its only system-side effect:
  the system will not *silently* re-match or re-categorise a completed
  transaction behind the operator's back. Only the operator changes a completed
  item — and they always can.

This is a status on a transaction (`complete` / not), surfaced per week. It is
not an archive, not a lock, not a separate place things disappear into.

## The pages, mapped to the cycle

| Step | Page | Job |
|------|------|-----|
| Weekly upload | (import) | Drop in the week's bank statement |
| Work a week | `/transactions` | Rows → click → documents; mark complete; week rolls up |
| Fix matches | `/review` | Confirm / reject / relink, with full context |
| Check VAT | VAT book view *(to build)* | Transaction + docs + category + VAT type |
| Export | VAT book view *(to build)* | Produce the VAT book for the period |

`/transactions` is organized by week: the operator opens a week, works its rows,
and marks them complete. `/review` is the worklist for items needing a decision.
The VAT book view shows the same transactions as the deliverable and exports it.
Completed weeks remain open to revisit at any time.

## Non-negotiables

- **One upload a week.** Never ask the operator to enter a transaction by hand.
- **No screen does two jobs.** Reviewing and categorising can share data but the
  operator should always know which question they are answering.
- **Complete never means hidden or locked.** A completed transaction or week
  stays visible and editable forever. Completion is a progress signal; the only
  guarantee is that the *system* won't silently change a completed item — the
  operator always can.
- **The VAT book is output, never input.** The operator stops maintaining it;
  the system produces it. (Historical hand-made VAT books are kept only as
  validation ground truth — see [27](27-vat-book-automation.md).)
