# 23 — System Overview

## Plain-English Summary

This system takes supplier documents and bookkeeping transactions and tries to answer:

> what evidence chain explains this payment?

The answer might be:

- one invoice
- invoice plus credit note
- supplier statement settlement
- hard copy only
- wages / contract / no-document rule

The system is being built so that answer comes from **stored structured data**, not from reading raw PDFs live every time.

## End-To-End Flow

### 1. A document comes in

Sources:

- Gmail
- staged local archive import

The file becomes a `document` row.

### 2. The document is extracted

The extractor reads the PDF and produces structured bookkeeping data.

For statements, the direction is now:

- **AI-first**
- fallback rules for gap-filling

Every extraction writes:

- `document_extraction_runs`
- `document_financial_facts`
- `document_financial_rows`

### 3. Transactions come in

Sources:

- bank statement
- VAT book

The rows become `transactions`.

### 4. The matcher builds suggestions

The matcher compares transactions against:

- document facts
- financial rows
- persisted links
- saved rules

It creates suggestions like:

- `direct_invoice_match`
- `statement_settlement`
- `supporting_docs_only`
- `rule_resolution`

These are stored in:

- `reconciliation_suggestions`
- `reconciliation_suggestion_items`

### 5. The verifier checks them

The verifier then asks:

- does the amount math work?
- do the dates make sense?
- do the supporting rows exist?
- is this exact, partial, or weak?

So a suggestion gets a verifier state:

- `passed`
- `partial`
- `failed`

### 6. The operator resolves the row

The operator uses:

- `/month-audit`
- `/review`

Final row states include:

- `linked`
- `supporting_docs_only`
- `hard_copy_available`
- `handled_by_rule`
- `awaiting_document`
- `no_document_expected`

## What Makes The System Different

The important shift is this:

### Old shape

`PDF text -> UI heuristics -> manual interpretation`

### New shape

`PDF -> extraction run -> stored rows -> stored suggestions -> verifier -> operator`

That is the core product improvement.

## Why AI Matters Here

At the foundation, suppliers are not conceptually different.

The general problem is always:

1. extract invoice / credit / payment rows from the statement
2. store them
3. match them against imported invoices and transactions

Supplier differences mostly live in:

- PDF layout
- OCR quality
- how refs and dates are written

So the right model is:

- AI helps with extraction
- matching stays general

Not:

- hardcoded accounting logic for every supplier

## Main Operator Workflow

### `/month-audit`

Use this first.

Purpose:

- fast monthly scan
- see primary suggestion
- see main statement / invoice / linked docs
- decide if a row is clear

### `/review`

Use this second.

Purpose:

- finalize the row
- confirm invoice match
- confirm statement settlement
- set rule / hard copy / no-document states

### `/supplier-documents`

Use this when:

- you need to know whether the PDF is actually in the system
- a doc needs inspect / re-extract

### `/statement-workbench`

Use this for:

- hard statement suppliers
- missing statement rows
- missing refs
- weak settlement grouping

## Current Truth

The system is now strong enough to support a real reconciliation workflow.

The main remaining weakness is not “what is the product?”

It is:

> can the statement extraction become good enough that the stored rows are consistently trustworthy?

That is the core technical problem left.
