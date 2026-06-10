# 03 — Architecture

## Core Principle

The architecture now follows this sequence:

`import -> extract -> store -> suggest -> verify -> resolve`

Not:

`download PDFs -> guess on the page -> resolve manually`

The system is now built as a **reconciliation engine with a stored data layer**, not just a document pipeline.

## Product Shape

The product has five main layers:

### 1. Ingestion

Inputs:

- Gmail attachments
- staged local archive folders under `backend/import_sources/`
- bank statement imports
- VAT-book imports

Outputs:

- `documents`
- `transactions`

### 2. Document Storage

The file and metadata layers are separated.

- PDFs live in local storage and Cloudflare R2
- document metadata lives in Postgres

This keeps the review flow fast and avoids treating the DB as a blob store.

### 3. Extraction Layer

Each document is extracted into structured bookkeeping data.

Current direction:

- invoices / credit notes / receipts use rule extraction with AI help when needed
- statements are moving to an **AI-first** extraction path

Each extraction attempt is persisted in:

- `document_extraction_runs`

The current extracted state is persisted in:

- `document_financial_facts`
- `document_financial_rows`

This is the key architecture shift. The system should not need to rethink the same PDF from scratch every time a user opens a page.

### 4. Reconciliation Layer

Documents are normalized into a shared ledger model.

Examples:

- invoice
- credit note
- payment
- receipt
- statement row

Transactions are then compared against:

- financial facts
- financial rows
- persisted document links
- persisted reconciliation suggestions
- transaction rules

Suggestions are stored in:

- `reconciliation_suggestions`
- `reconciliation_suggestion_items`

The verifier layer then checks whether the suggestion math and evidence actually hold.

### 5. Operator Layer

The UI is intentionally split by job:

- `/month-audit`
  - fast monthly scan
- `/review`
  - full row resolution
- `/supplier-documents`
  - inventory and repair
- `/statement-workbench`
  - statement-first investigation

The UI should become thinner over time, because more of the reasoning is being pushed into stored rows and persisted suggestions.

## Current Pipeline

### Document Pipeline

`PDF -> extraction run -> financial facts -> financial rows`

### Transaction Pipeline

`transaction import -> reconciliation suggestion -> verifier -> operator resolution`

### Final Resolution

Transactions are finalized into persistent states such as:

- `linked`
- `supporting_docs_only`
- `hard_copy_available`
- `handled_by_rule`
- `awaiting_document`
- `no_document_expected`

## Why The Architecture Changed

The older shape was too dependent on:

- raw PDF text
- one-off parser output
- page-time heuristics

That made it hard to:

- improve extraction safely
- compare old vs new extraction
- explain why a match was suggested
- keep the UI simple

The new shape fixes that by storing:

- extraction history
- structured financial rows
- persisted suggestion groups
- deterministic verifier results

## Statement Strategy

The matching logic should stay general.

Supplier differences should mostly be handled in extraction.

That means:

- AI can be supplier-family aware for statement layout recovery
- the matcher should still work over one common row schema

So the architecture is:

- supplier-aware extraction
- general reconciliation

Not:

- supplier-specific accounting rules everywhere

## What The Architecture Is Optimizing For

The system is trying to make one thing easy:

> show one trustworthy evidence chain for each transaction quickly enough that month close stops feeling forensic

That is the real architecture target.
