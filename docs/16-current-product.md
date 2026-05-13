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

## What Works Well Right Now

- Gmail-to-document ingestion works
- staged local-archive import works
- document extraction works on real supplier data
- multi-invoice Lovell packet splitting works
- invoice projection is live
- VAT book import works for the current workbook format
- AIB bank statement import works for the current PDF format
- the reconciliation queue is now supplier-aware enough to avoid obvious amount-only false positives

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

## Current Weak Points

The main bottleneck is no longer API structure.

The main bottlenecks are:

- supplier-specific extraction coverage for missing suppliers
- missing source documents for some real bank transactions
- unresolved transaction rows where the supplier exists in the bank statement but the corresponding invoice is not yet in the document set

Examples from current April testing:

- `Diageo`
- `M&J Gleeson`
- `Athlone Furnit`
- `Topline Heavin`

## Latest April Calibration Result

Using the staged local archive import, the system has already pulled additional April documents for:

- `Diageo`
- `Little Luxuries`
- `Automatic Amusements` (via `MoodMaster`)

That increased live coverage from:

- `84` documents to `103`
- `72` invoices to `86`

The important product learning from this is:

- adding missing invoices improves document coverage immediately
- but bank-payment reconciliation still often depends on statements or supplier-account documents, not only invoice rows
- `D/D DIAGEO IRELAND` is a good example: after the import, the system can surface Diageo support docs, but that row still is not a simple one-invoice match

## Product Positioning

The product is now best described as:

> a document-first bookkeeping reconciliation assistant

It is not yet a finished accounting system or a polished SaaS product.

Its current strength is:

- collecting the right documents
- structuring them
- projecting invoice data
- helping reconcile real transaction activity against that document set
