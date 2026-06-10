# 16 — Current Product State

## What The Product Is Now

The product is now a **month-close reconciliation workbench**.

It is built for this job:

> show the document chain that explains each transaction, let an operator trust it, and let the operator resolve or defer it

It is no longer best described as:

- a Gmail automation tool
- a PDF organizer
- an invoice-only dashboard

Those are supporting parts now, not the product definition.

## What Is Working

### Document Ingestion

The system can ingest:

- Gmail attachments
- staged local archive folders
- historical supplier backfills

The local archive import is now the main way to bring in large supplier history cleanly.

### Transaction Ingestion

The system supports:

- bank statement imports
- VAT-book imports

### Extraction

The system can extract and persist:

- supplier
- document type
- document date
- reference
- amount
- VAT amount
- confidence and review flags

It now also persists:

- extraction runs
- financial facts
- financial rows

Statements are moving to an **AI-first** extraction path.

### Reconciliation

The reconciliation layer now has:

- stored financial rows
- persisted reconciliation suggestions
- verifier pass / partial / fail states
- reusable transaction rules

This means the system is moving away from page-time heuristics and toward a stored reconciliation engine.

### Operator Workflow

The main operator surfaces are now:

- `/month-audit`
- `/review`
- `/supplier-documents`
- `/statement-workbench`

Recommended use:

- `/month-audit` first
- `/review` only to finalize rows
- `/supplier-documents` to verify inventory and repair docs
- `/statement-workbench` for hard statement suppliers

## What The Data Layer Looks Like Now

The important persisted layers now are:

- `documents`
- `transactions`
- `transaction_document_links`
- `transaction_rules`
- `document_extraction_runs`
- `document_financial_facts`
- `document_financial_rows`
- `reconciliation_suggestions`
- `reconciliation_suggestion_items`

This is the real backbone of the product now.

## Current Archive Position

The staged local archive is now mostly imported.

Current broad position:

- total docs in DB: roughly `2964`
- local-archive docs: roughly `2880`

So the system now has most of the supplier archive in it, not just a thin working slice.

## Current Working Supplier Position

The main March-May statement suppliers have been re-extracted recently:

- `Bulmers`
- `Heineken`
- `Connacht Bottlers`
- `Diageo`

Operationally:

- `Bulmers`, `Heineken`, and `Connacht Bottlers` are in much better shape
- `Diageo` is still the weakest statement family

## What Still Feels Weak

The main bottleneck is now clearly:

- statement extraction quality

Not:

- basic storage
- basic import
- basic UI routing

More specifically:

- `Diageo` still needs stronger statement row recovery
- some statement-heavy rows still fall back to support-only because the line-level math is incomplete
- the UI still depends on a few old concepts and can be tightened further as the stored suggestion layer becomes dominant

## Current Product Direction

The direction is now:

1. import documents and transactions
2. extract structured rows reliably
3. persist suggestions
4. verify those suggestions
5. keep the audit flow simple

That is the current product direction.

## What The Product Is Not Yet

It is not yet:

- a finished accounting platform
- a fully autonomous reconciliation engine
- a polished multi-tenant SaaS product

It is already:

- a serious bookkeeping reconciliation system
- with a real data model
- a real operator workflow
- and a credible path to AI-assisted reconciliation
