# 16 — Current Product State

## What This Product Is Now

The system is now a working finance-document ingestion and reconciliation tool.

It is no longer just:

- Gmail download automation
- or a folder organizer

It now covers the full path from inbound documents to a real transaction review queue.

## Current Core Workflow

### 1. Document Ingestion

The backend can:

- connect to Gmail
- scan recent emails
- filter for finance-related PDF attachments
- classify documents by supplier and type
- store them locally in a structured folder tree
- sync them to Google Drive
- import staged local supplier archives from inside `backend/`

#### Local Archive Import

The backend now also supports importing a downloaded supplier archive through:

- `POST /api/documents/import-local`

This is intended for cases where documents already exist outside Gmail, for example:

- a downloaded Google Drive archive
- a manually maintained supplier folder tree
- historical invoice backfills

The importer:

- walks a staged path under `backend/import_sources/`
- infers supplier and document type from the folder structure
- filters by supplier, pub, month, and archive-folder inclusion
- dedupes linked/unlinked file twins such as `file.pdf` and `file - Linked.pdf`
- runs the normal extraction + invoice projection flow after import

The backend also supports statement-context import through:

- `POST /api/documents/import-statement-context`

This is the standardized way to preload statement-family suppliers for a review month. It looks at the transactions in that month, detects suppliers like `Heineken`, `Diageo`, `Bulmers`, and `Connacht Bottlers`, then imports their statement PDFs from the previous, current, and next months so the review queue is not dependent on manual one-off imports.

### 2. Document Extraction

The backend can extract and persist:

- supplier
- document type
- document date
- reference / invoice number
- gross amount
- VAT amount
- currency
- confidence score

The extractor also supports:

- review flags for uncertain records
- multi-invoice packet detection
- packet splitting into child document rows

### 3. Invoice Projection

Invoice-type documents are projected into the invoice layer so:

- `/api/invoices` shows extracted invoice records
- split child invoices behave like real invoices
- dashboard totals use the projected invoice set

### 4. Transaction Ingestion

The backend now supports two transaction sources:

- `vatbook`
- `bank_statement`

#### VAT Book Import

The VAT workbook importer can parse the current mixed-sheet layout where:

- bookkeeping transactions are the main rows
- invoice / statement / receipt notes are attached underneath

#### Bank Statement Import

The bank statement importer can parse AIB text PDFs and store:

- debit / credit rows
- payee details
- reference details
- account metadata
- pub inference where possible

### 5. Reconciliation Layer

Transactions can now be compared to extracted documents with:

- exact reference-note matches
- supplier-aware invoice suggestions
- grouped invoice suggestions
- supporting document suggestions such as statements or credit notes
- resolution buckets that turn unresolved rows into actionable bookkeeping categories

Under the hood, invoices, credit notes, receipts, and parsed supplier-statement lines are now normalized into one shared ledger-entry model before reconciliation.

That means the engine can reason about:

- direct invoice matches
- invoice minus credit-note settlements
- statement payment rows that explain bank debits
- support-document-only rows where the statement is the real settlement record

This is exposed through:

- `/api/transactions/reconciliation-report`
- `/api/transactions/review-queue`
- `/api/transactions/{id}/links`

### 6. Review Workflow

Transactions now have a persistent review state.

Supported `review_status` values:

- `pending`
- `linked`
- `supporting_docs_only`
- `awaiting_document`
- `no_document_expected`

This means the queue is now more than analysis output. It can hold actual bookkeeping decisions.

It also now classifies queue rows into action buckets such as:

- `confirm_match`
- `review_supporting_docs`
- `awaiting_document`
- `needs_matcher_improvement`

### 7. Review UI

The backend now also serves a thin reconciliation workbench at:

- `/review`

This UI is intended for operator review work, not a polished end-user product.

It currently supports:

- email/password login
- month/source/pub queue filters
- resolution-bucket queue filtering
- a standardized reconciliation flow per row
  - supplier
  - statement
  - invoices / credit notes
  - resolve
- transaction detail inspection
- transaction audit/history inspection through the API
- confirming suggested invoice matches
- linking supporting documents and resolving rows
- setting review states such as `awaiting_document` or `no_document_expected`
- inspecting normalized ledger entries for invoices and statements

## What Works Well Right Now

- Gmail-to-document ingestion works
- staged local-archive import works
- document extraction works on real supplier data
- multi-invoice Lovell packet splitting works
- invoice projection is live
- VAT book import works for the current workbook format
- AIB bank statement import works for the current PDF format
- the reconciliation queue is now supplier-aware enough to avoid obvious amount-only false positives
- the backend now has one common parsed-entry model for invoices and statement-led supplier settlements

## What The System Can Do Operationally

For a real month such as April 2026, you can now:

1. ingest supplier documents from Gmail
2. import staged local supplier folders from a downloaded archive
3. extract invoice data
4. split packet PDFs into child invoices
5. import VAT workbook rows
6. import bank statement PDFs
7. compare transactions against extracted documents
8. inspect invoice suggestions and support documents
9. manually link documents to transactions
10. mark transactions as awaiting documents or resolved without documents
11. inspect canonical transaction detail and review-history payloads through the API

## Operator API Layer

The backend now has the start of the operator-safe API layer needed for the Claude and QuickBooks roadmap.

That currently includes:

- canonical transaction detail at `GET /api/transactions/{transaction_id}/detail`
- canonical document inspection at `GET /api/documents/{document_id}`
- transaction review history at `GET /api/transactions/{transaction_id}/history`
- persisted audit events for review and link actions

This means operator and future Claude actions are no longer just changing live state. They are also leaving an audit trail.

## Current Weak Points

The main bottleneck is no longer API structure.

The main bottlenecks are:

- supplier-specific OCR/layout extraction coverage for missing suppliers
- missing source documents for some real bank transactions
- unresolved transaction rows where the supplier exists in the bank statement but the corresponding invoice is not yet in the document set

Examples from current April testing:

- `Diageo`
- `M&J Gleeson`
- `Athlone Furnit`
- `Topline Heavin`

## Latest April Calibration Result

April 2026 has now been worked with:

- Gmail-ingested documents
- bank-statement imports
- VAT-book imports
- staged local-archive backfills from the downloaded supplier folders

The local archive backfill has already imported two useful slices:

### Batch 1

- `Diageo`
- `Little Luxuries`
- `Automatic Amusements` (via `MoodMaster`)

Result:

- `19` unique April documents imported
- `19` extracted

### Batch 2

- `BOC Gases`
- `EIR`
- `Heineken`
- `JJ Mahon and Sons`
- `Bulmers Ireland`
- `Cosmic Algorithm`
- `Dojo`

Result:

- `39` April documents imported
- `39` extracted
- `13` linked/unlinked archive twins deduped cleanly

### Current April Bank-Statement Position

After the latest archive import and matcher improvements, the April 2026 bank-statement reconciliation is now showing:

- `12` suggested rows
- `81` unmatched rows
- `89` invoice documents in the selected month

Important product learning:

- importing missing supplier folders does materially improve live coverage
- statement-led suppliers can now move from dead-end unmatched rows into useful suggestions
- `Heineken` is now producing real bank-to-invoice suggestions
- `Diageo` rows are now treated as likely statement/account-settlement cases rather than forced one-invoice matches
- some suppliers still remain unresolved because the available documents do not support a clean one-to-one invoice match

## Product Positioning

The product is now best described as:

> a document-first bookkeeping reconciliation assistant

It is not yet a finished accounting system or a polished SaaS product.

Its current strength is:

- collecting the right documents
- structuring them
- projecting invoice data
- helping reconcile real transaction activity against that document set
