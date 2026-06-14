# 27 — VAT Book Automation (turning reconciliation into the deliverable)

**Date:** 2026-06-12
**Goal:** the operator stops hand-making the VAT book. The system generates it
from bank transactions + their matched documents, and the operator only reviews.

This is not a new subsystem. The VAT book is the *output view* of the
reconciliation engine that already exists. Everything below leans on data the
system already produces.

## What a VAT book row is

For each bank transaction, the hand-made VAT book records two things:

1. **A category** — examples seen in the historical data:
   - `Resale - Diageo - Careys`, `Resale - Heineken - Canal` (drink suppliers)
   - `Renovation`, `Maintenance`, `Fuel`, `Software`, `Security`, `Insurance - Pub`
   - a person's name (`Michael Farrell`, `Eamon Carey`) — wages / drawings
   - `Lodgement - Careys - BOI Card` — income
2. **A VAT split** across rate bands: resale 23%, non-resale 23%, 13.5%, 9%, 0%.

## How each is derived (and from what we already have)

### Category
- **Resale lines** → `Resale - {matched supplier} - {pub}`. Reconciliation
  already identifies the supplier (from the matched invoice/statement) and the
  pub (from the transaction). These are the highest-value, fully-automatable rows.
- **Recurring payees and costs** (wages, fuel, insurance, software, security) →
  stable description → category. The `transaction_rules` table and the
  apply-rule / create-rule endpoints already exist as the categorisation
  primitive; this is extending them, not building from scratch.
- **Lodgements / income** → description pattern, no VAT band.

### VAT split
- **Resale** → the 23% VAT comes straight from the **matched document's
  `vat_amount`**, which the statement-trust work now extracts accurately. This
  is the key connection: a verified document chain yields the exact VAT figure.
- **Fixed-treatment categories** → defaults learned from history
  (`Insurance - Pub` → 0%, `Fuel` → non-resale 23%, `Renovation` →
  23% / 13.5% split).
- **Genuinely ambiguous** → flagged for the operator, never guessed.

## Build stages (each measurable before the next)

- **Stage A — VAT book view + accuracy proof.** Generate VAT-book rows from
  bank transactions for a month we already have a hand-made book for
  (March/April), and show them **side by side with the hand-made version**.
  Report % of rows the system gets right (category correct, VAT band correct).
  This tells us how much is already free off reconciliation before we build any
  rules.
- **Stage B — category rules.** Learn from the existing hand-categorised rows
  (~960 of them, plus months of history) to auto-assign category. Operator
  corrects misses; corrections improve the rules.
- **Stage C — VAT split derivation.** Resale from matched documents; fixed
  categories from defaults; ambiguous flagged.
- **Stage D — export.** Produce the operator's existing xlsx VAT-book format so
  the output drops into their current workflow unchanged.

## Validation: the historical VAT books are the ground truth

The operator has **months of hand-made VAT books**. These are not input to the
running system — they are the labelled answer key. The exact pattern that worked
for statement extraction applies here:

- generate the VAT book for a historical month,
- diff against the operator's hand-made one,
- report category accuracy and VAT-band accuracy per month,
- only trust automation for a category once its number is high enough.

**Action:** import the historical VAT books as a reference/validation dataset
(clearly separated from live transactions — they are not bank-statement
transactions and must never enter the reconciliation path). They become the
VAT-book equivalent of the golden corpus.

## Why this is the right next step

The whole reconciliation engine — document extraction, statement arithmetic,
matching, the two-pub logic — exists to answer "what explains this transaction?"
The VAT book is that answer, written in the operator's format. Automating it is
not a new direction; it is the payoff of everything already built.
