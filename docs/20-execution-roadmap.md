# 20 — Execution Roadmap

This document is still useful as a historical execution plan.

For the current high-level direction, start with:

- [23-system-overview.md](23-system-overview.md)
- [24-roadmap-ahead.md](24-roadmap-ahead.md)

## Product Definition

This product is not a general accounting system.

It is a:

> month-close reconciliation workbench for messy hospitality bookkeeping

Its job is to answer:

> what document chain explains this transaction?

That means the core flow stays:

1. ingest documents and transactions
2. extract structured finance data
3. build the evidence chain
4. let an operator resolve or defer

Anything that does not improve that flow is lower priority.

## Where We Are Now

The system already has the right backbone:

- document ingestion from Gmail and staged local archives
- VAT-book and bank-statement import
- extraction of invoices, statements, credit notes, and receipts
- transaction-led review workbench at `/review`
- supplier document inventory at `/supplier-documents`
- persistent review states
- reusable transaction rules
- AI-assisted extraction fallback
- object storage support for documents through Cloudflare R2

The main problem is no longer “can the app store and show the data?”

The main problem is:

> can it reliably build the right statement / invoice / credit chain for hard supplier payments?

## What We Should Do Next

### 1. Stabilize Document Visibility

Goal:

- stop guessing what the app actually has

Work:

- add storage visibility in the dashboard and review flows
  - local only
  - R2 synced
  - Drive synced
- add supplier inventory counts by:
  - invoices
  - statements
  - credit notes
  - receipts
- add quick “missing evidence” indicators by supplier/month/pub

Why this comes first:

- if we cannot see what is already in the DB and bucket, we will keep confusing parser issues with missing-document issues

### 2. Improve Statement Row Extraction

Goal:

- make statement-heavy suppliers produce real settlement chains instead of vague support-doc suggestions

Work:

- improve AI extraction for table-heavy statements
- keep the output normalized into:
  - invoice lines
  - credit-note lines
  - payment / receipt lines
  - balances
- prioritize supplier families, not one-off supplier hacks:
  - statement summary
  - trade statement
  - ERP-style account statement

Why this is the real bottleneck:

- most of the remaining hard rows are not failing because the UI is bad
- they are failing because the statement rows are not being extracted cleanly enough

### 3. Make Settlement Chains First-Class

Goal:

- show one coherent explanation per transaction

Work:

- strengthen the canonical reconciliation flow:
  - supplier
  - statement
  - invoices / credits
  - resolve
- auto-group statement rows, invoices, and credits where the math is clear
- surface what is missing when the chain is incomplete:
  - missing invoice
  - missing statement
  - missing credit note
  - missing line amounts

Why:

- the operator should not need to mentally reconstruct the settlement from raw cards

### 4. Harden The Rule And Category Layer

Goal:

- make recurring transaction handling predictable

Work:

- keep common outcomes standardized:
  - `Wages`
  - `Contract`
  - `Hard Copy Available`
  - `No Document Expected`
  - `Invoice Match`
  - `Statement Settlement`
- improve rule management in the UI
- make rule reuse clearer across similar counterparties where safe

Why:

- the more recurring bookkeeping patterns we absorb into rules, the less time gets wasted on non-document rows

### 5. Use April 2026 As The Operating Month

Goal:

- finish one month in a way the operator trusts

Operational rule:

- only resolve rows where the evidence chain is actually coherent
- do not force ambiguous rows just to reduce the queue

Work:

- clear obvious invoice matches
- clear obvious statement settlements
- mark genuine hard-copy rows
- mark genuine no-document rows
- treat `awaiting_document` as a missing-evidence list, not a cleanup bucket

Success condition:

- April becomes a controlled, understandable month-close queue

### 6. Run March 2026 As The Blind Test

Goal:

- prove the system generalizes

Rule:

- do not tune first
- run March with the current engine and see what breaks

Why:

- April has been a calibration month
- March is the real systems test

### 7. Do Integrations Only After The Core Flow Is Stable

This includes:

- Claude operator workflows
- QuickBooks sync

Those are valuable, but they are downstream of the evidence chain being trustworthy.

The right order is:

1. trustworthy reconciliation engine
2. stable operator API
3. workflow / connector layer
4. accounting system sync

## What We Should Not Do

- do not keep adding broad UI surface area without improving the evidence chain
- do not keep making one-off supplier reconciliation branches
- do not force unresolved transactions into fake matches
- do not turn the app into a full accounting package

## Best Immediate Work Order

If we want the highest-value sequence from here, it is:

1. add storage/document visibility
2. improve statement row extraction
3. strengthen settlement grouping
4. finish April
5. run March blind

## Work I Can Safely Do Without Operator Input

While the operator is away, the safest useful work is:

- storage visibility and sync indicators
- statement extraction improvements
- settlement-chain improvements
- supplier-family parser hardening
- API and UI cleanup that does not alter live review decisions

I should avoid without explicit review:

- bulk-resolving live transactions
- changing operator decisions
- force-importing large new supplier batches that have not been chosen intentionally

## What Success Looks Like

The next real milestone is:

> one month where the transaction register mostly shows clear green or yellow evidence states, and the hard rows are genuinely hard rather than hidden parser failures

That is the point where this becomes a dependable bookkeeping product instead of a promising prototype.
