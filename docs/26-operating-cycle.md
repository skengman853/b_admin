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

### Weekly (one action)
- The operator uploads **that week's bank transactions** (the bank statement).
  Bank statements are the source of truth for transactions — nothing else
  creates a transaction.
- On import the system automatically matches each transaction to its
  documents: direct invoice matches, statement settlements, supporting docs.
  The operator does nothing here — they just upload.

### Fortnightly (the close cycle — the only real "work")
Every two weeks the operator sits down and goes through the period once:

1. **Review the matches.** A clean list of the period's bank transactions, each
   showing its status and, on click, its documents. Most are already matched —
   the operator is scanning for the handful that aren't, or that matched wrong.
2. **Fix what's wrong.** Confirm a suggested match, reject a bad one, point a
   transaction at the right document, or mark "no document expected" (bank fees,
   wages, drawings).
3. **Check the VAT view.** The same transactions, now shown the way the VAT book
   shows them: transaction + its documents + category + VAT treatment. This is
   the deliverable taking shape. The operator confirms the categories and VAT
   splits look right (most are auto-derived — see [27](27-vat-book-automation.md)).
4. **Complete the cycle.** When happy, the operator signs off the two-week
   period. Those transactions are locked, the VAT book for that period is final,
   and the system moves on. The next cycle starts clean.

## What "complete the cycle" means (design)

A **close period** is a date range the operator has signed off. Once completed:
- its transactions are frozen (no silent re-matching changes a closed period),
- its VAT book rows are final and exportable,
- the operator's attention moves to the next open period.

This is the one new concept the cycle needs that does not exist yet. It is a
sign-off boundary, not a new data model — a completed period is just a marker
plus frozen review state on the transactions inside it.

## The pages, mapped to the cycle

| Step | Page | Job |
|------|------|-----|
| Weekly upload | (import) | Drop in the week's bank statement |
| Review matches | `/transactions` | Rows → click → that transaction's documents |
| Fix matches | `/review` | Confirm / reject / relink, with full context |
| Check VAT | VAT book view *(to build)* | Transaction + docs + category + VAT type |
| Sign off | VAT book view *(to build)* | Complete the period, export |

`/transactions` is deliberately the calm "read the month" view. `/review` is the
worklist for the items that need a decision. The VAT book view is where the two
weeks get turned into the deliverable and closed.

## Non-negotiables

- **One upload a week.** Never ask the operator to enter a transaction by hand.
- **No screen does two jobs.** Reviewing and categorising can share data but the
  operator should always know which question they are answering.
- **Closed stays closed.** A signed-off period does not change underneath the
  operator because extraction improved later.
- **The VAT book is output, never input.** The operator stops maintaining it;
  the system produces it. (Historical hand-made VAT books are kept only as
  validation ground truth — see [27](27-vat-book-automation.md).)
