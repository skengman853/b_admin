# 27 — VAT Book Automation (turning reconciliation into the deliverable)

**Date:** 2026-06-12
**Goal:** the operator stops hand-making the VAT book. The system generates it
from bank transactions + their matched documents, and the operator only reviews.

This is not a new subsystem. The VAT book is the *output view* of the
reconciliation engine that already exists. Everything below leans on data the
system already produces.

## Confirmed file format (from the real Mar–Apr book)

Columns, left to right:
- **B** Posted Account · **C** Pub · **D** Date · **E** Description1 ·
  **F** Description2 · **G** Debit · **H** Credit · **I** Transaction Type ·
  **J** Category
- **K** Resale @ 23% · **L** Non-Resale @ 23% · **M** Non-Resale @ 13.5% ·
  **N** Non-Resale @ 9% · **O** Non-Resale @ 0%
- Bottom row: column totals per band (feeds the return).
- Annotation rows sit under each transaction (Invoice / Statement / Credit Note /
  flags like "Hard copy available", "Awaited", "To be reconciled").

Confirmed behaviours (verified against the file):
- **Input/purchases only.** Income/lodgement rows carry no VAT band; the sales /
  output-VAT side is not in this file (see open question).
- **Whole gross amount, one band per transaction.** The book classifies the
  gross debit into a single band; it does not split a payment or net out VAT.
- **Category ≈ determines band.** 49 of 55 categories map to one band cleanly.
  The exceptions need the invoice's actual VAT lines: Misc, Renovation,
  Maintenance, Software, Electricity, and the occasional 0% resale (e.g.
  M&J Gleeson / Bulmers bottle-return / deposit refund).

## VAT bands — meaning (from John, the bookkeeper)

- **23% Resale (K)** — stock bought to resell at standard VAT: bottled drinks,
  snacks, cigarettes, retail merchandise. The core drink-supplier purchases.
- **23% Non-Resale (L)** — standard-rate costs that aren't resale stock
  (most overheads, sundries, fuel, etc.).
- **13.5% Non-Resale (M)** — hospitality/service rate: some food service,
  accommodation, certain hospitality services, and reduced-rate works.
- **9% Non-Resale (N)** — legacy reduced hospitality rate (e.g. food during
  reduced-rate periods); few transactions, kept for continuity.
- **0% Non-Resale (O)** — no VAT: lottery, tips, exempt income,
  deposits/refunds, bottle returns.

## Why the documents matter (from Jack)

Every matched document is kept for two reasons: **audit defence** (Revenue can
ask for proof of any transaction) and **price verification** (catching when a
supplier has overcharged). The document chain the reconciliation engine builds
*is* that proof — which is why the deliverable is a "VAT File – **Audit
Report**".

## Sales side — in scope via weekly takings (Jack, confirmed)

The VAT book file is purchases/input only, but **sales are in scope**: Jack will
provide the **weekly takings, per night**, alongside the bank statement. So the
weekly input is two streams — **money out** (bank statement → purchases) and
**money in** (nightly takings → sales). Output VAT comes from takings, input VAT
from categorised purchases; the system can show the full VAT position.

Open detail for John: how do takings split for VAT (drink @23% vs food
@13.5%/9%)? Are nightly takings a single figure or already broken down? This sets
how output VAT is computed.

## Codes taxonomy = the category master

The MAY-JUN file carries a **"Codes" sheet** — the canonical chart of accounts:
each Category, its pub prefix (CAR-), its group (009 Resale, 010 Wages,
004 Power & Heat, 006 Maintenance & Renov, 011 Govt, 001 Bank, 002 Comms, …),
and the full validation list. The automation should adopt this taxonomy directly
rather than inferring categories — it is the operator's own answer key, and new
suppliers (Bulmers Direct, Counterpoint, Primeline) already appear in it.

## Stage A result (cross-period, honest)

Trained category rules on MAR-APR, tested on the unseen MAY data (95 txns):
- **category correct: 81%** (93% of those a rule existed for),
- **13 unknowns** → correctly routed to review; all new payees/staff
  (the evolving-staff case),
- band accuracy is the weak spot **by description alone** — the ambiguous
  categories need the matched invoice's VAT lines, which this test did not use.

This is the floor: description-only, no document-matching signal yet. The
document layer raises both category (supplier confirmation) and band (actual
invoice VAT) from here.

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
