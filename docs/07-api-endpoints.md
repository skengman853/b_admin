# 07 — API Endpoints

## Important Context

The current backend API still reflects some earlier invoice-dashboard-first work.

That is fine, but the docs should be explicit about what exists now versus what the next document-centric phases likely need.

## Currently Implemented Endpoints

### Auth

#### `POST /api/auth/signup`

Create a user and return a JWT.

#### `POST /api/auth/login`

Log in and return a JWT.

#### `GET /api/auth/me`

Return the current user and Gmail connection status.

This is currently the easiest way to verify Gmail OAuth worked:

```json
{
  "id": "uuid",
  "email": "test@example.com",
  "gmail_connected": true,
  "created_at": "..."
}
```

### Gmail

#### `GET /api/gmail/auth-url`

Return a Google OAuth URL for the logged-in user.

#### `GET /api/gmail/callback`

Handle the Google OAuth callback, store encrypted tokens, then redirect.

Note:

- this endpoint is not meant to be opened directly
- it expects `code` and `state` query params from Google
- the current implementation redirects to `FRONTEND_URL/dashboard`

#### `DELETE /api/gmail/disconnect`

Remove the stored Gmail connection for the current user.

### Pipeline

#### `POST /api/pipeline/scan-recent`

Scan recent Gmail messages for the current user, process matching PDFs, and return a debug-friendly result set.

The current response includes:

- scanned, processed, skipped, and saved counts
- per-supplier and per-type counts
- per-file extracted metadata
- `needs_review` flags and `review_reasons`
- Drive auto-sync counts:
  - `drive_sync_requested`
  - `drive_sync_synced`
  - `drive_sync_skipped`
- dedupe count:
  - `deduped_documents`

The request also supports:

- `force`
- `sync_drive`

#### `GET /api/pipeline/summary`

Return the accumulated tracking summary for the current user from `processed_emails.json`.

This is the quickest way to see:

- how many messages have been tracked
- how many were processed vs skipped
- how many files need review
- counts by supplier
- counts by document type

#### `GET /api/pipeline/review-queue`

Return files currently flagged for manual review.

This is useful when supplier detection or document type classification falls back to `Other` or `unknown`.

### Documents

#### `GET /api/documents`

List document records stored in the database.

By default, split parent packets with `extraction_status = split` are hidden from this list so derived child invoices behave as the real document rows.

The current filters include:

- `needs_review`
- `synced`
- `document_type`
- `extraction_status`
- `parent_document_id`
- `include_split_containers`
- `min_confidence`
- `max_confidence`

Each record can include:

- local path
- Drive file ID
- Drive web link
- synced timestamp
- `parent_document_id`
- `derivation_index`

Useful review queries:

```bash
curl -s "http://localhost:8000/api/documents?extraction_status=review" \
  -H "Authorization: Bearer $TOKEN"

curl -s "http://localhost:8000/api/documents?parent_document_id=PARENT_DOCUMENT_ID" \
  -H "Authorization: Bearer $TOKEN"

curl -s "http://localhost:8000/api/documents?include_split_containers=true" \
  -H "Authorization: Bearer $TOKEN"

curl -s "http://localhost:8000/api/documents?max_confidence=0.7" \
  -H "Authorization: Bearer $TOKEN"

curl -s "http://localhost:8000/api/documents?extraction_status=review&max_confidence=0.7" \
  -H "Authorization: Bearer $TOKEN"
```

#### `GET /api/documents/review`

Return a single review queue that combines:

- `needs_review = true`
- `extraction_status = review`
- low-confidence documents below a threshold

The main query param is:

- `confidence_below` with a default of `0.7`

Useful example:

```bash
curl -s "http://localhost:8000/api/documents/review" \
  -H "Authorization: Bearer $TOKEN"

curl -s "http://localhost:8000/api/documents/review?confidence_below=0.6" \
  -H "Authorization: Bearer $TOKEN"
```

#### `GET /api/documents/{document_id}`

Return one full document record, including:

- `extracted_text`
- `extraction_candidates`
- `statement_analysis`
- `ledger_analysis`
- `parent_document`
- `child_documents`

For statement and account-style documents, `ledger_analysis` now also includes normalized settlement groups. That gives the UI a way to show:

- the payment line on the statement
- the invoices and credit notes that net to that payment
- the grouped settlement math behind one bank transaction

`extraction_candidates` is mainly for multi-invoice PDFs. It returns the per-invoice candidates the extractor can see inside one attachment, for example:

- `reference`
- `document_date`
- `amount`
- `vat_amount`
- `currency`

For split packets:

- a parent packet returns its `child_documents`
- a derived child invoice returns its `parent_document`

Example:

```bash
curl -s "http://localhost:8000/api/documents/DOCUMENT_ID" \
  -H "Authorization: Bearer $TOKEN"
```

#### `PATCH /api/documents/{document_id}`

Manually correct document metadata and optionally resolve a review item.

Useful fields include:

- `supplier`
- `document_type`
- `document_date`
- `reference`
- `amount`
- `vat_amount`
- `currency`
- `confidence_score`
- `needs_review`
- `review_reasons`
- `mark_reviewed`

Example:

```bash
curl -s -X PATCH "http://localhost:8000/api/documents/DOCUMENT_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "supplier": "Chris Lynch Skip Hire & Waste Management Services",
    "reference": "PFINV-121",
    "mark_reviewed": true
  }'
```

Note:

- replace `DOCUMENT_ID` with the real `id` returned by `GET /api/documents` or `GET /api/documents/review`
- if the corrected metadata changes the target folder or filename, the local file is moved too
- if the document already has a Drive file, the existing Drive file is renamed and moved into the matching Drive folder

#### `POST /api/documents/{document_id}/approve`

Approve a review item as-is without changing any metadata fields.

This is the quick path for documents that are acceptable even though they were flagged for:

- low confidence
- missing dates
- other non-blocking review reasons

Example:

```bash
curl -s -X POST "http://localhost:8000/api/documents/DOCUMENT_ID/approve" \
  -H "Authorization: Bearer $TOKEN"
```

This clears:

- `needs_review`
- `review_reasons`

And sets:

- `extraction_status = reviewed`

#### `POST /api/documents/{document_id}/split`

Split one multi-invoice packet into derived child document rows.

This is for cases where one attachment contains many invoice records and the system can already see those candidates in `extraction_candidates`.

Behavior:

- the parent row stays as the source packet
- the parent row is marked `extraction_status = split`
- the parent row leaves the review queue
- child rows are created or updated with:
  - `parent_document_id`
  - `derivation_index`
  - invoice-level `reference`
  - `document_date`
  - `amount`
  - `vat_amount`

The child rows reuse the same source PDF and Drive file as the parent packet. The PDF is not physically split yet.

Example:

```bash
curl -s -X POST "http://localhost:8000/api/documents/DOCUMENT_ID/split" \
  -H "Authorization: Bearer $TOKEN"
```

#### `POST /api/documents/sync-drive`

Manually sync unsynced or selected document rows to Google Drive.

The current response includes:

- requested count
- synced count
- skipped count
- deduped count
- per-document sync result

#### `POST /api/documents/extract`

Run extraction against pending or selected document rows.

Useful when:

- documents were imported from a non-Gmail source
- you want to re-extract a specific set after metadata or rule changes

The extraction pass now works in layers:

- PDF text extraction
- rules-based metadata extraction
- optional AI fallback for weak invoices and statements when `openai_api_key` is configured
- invoice projection refresh for touched documents

#### `POST /api/documents/import-local`

Import PDFs from a staged local archive that sits inside `backend/`.

This endpoint is designed for cases like a downloaded supplier archive. It:

- walks a local folder
- infers supplier and document type from the folder structure
- copies files into the managed `Documents/` tree
- creates `documents` rows
- optionally runs extraction immediately

Important runtime note:

- the API container can only see paths inside `backend/`
- so host folders like `/Users/...` must be copied or staged under something like `backend/import_sources/`

Useful request fields:

- `source_path`
- `limit`
- `supplier_filters`
- `document_types`
- `pub_filters`
- `month=YYYY-MM`
- `include_archives`
- `extract_after_import`

Example:

```bash
curl -s -X POST "http://localhost:8000/api/documents/import-local" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_path": "backend/import_sources/Invoices - Pubs",
    "supplier_filters": ["Diageo", "Little Luxuries", "MoodMaster", "Heavins"],
    "month": "2026-04",
    "include_archives": false,
    "extract_after_import": true,
    "limit": 300
  }'
```

The response includes:

- `scanned_files`
- `eligible_files`
- `imported_documents`
- `extracted_documents`
- `skipped_files`
- per-file statuses such as `imported`, `deduped`, or `skipped`

#### `POST /api/documents/import-statement-context`

Import only statement documents for suppliers that appear in a review month’s transactions, while automatically looking across the previous, current, and next months.

This is intended for month-end statement suppliers such as:

- `Heineken`
- `Diageo`
- `Bulmers`
- `Connacht Bottlers`

The endpoint:

- inspects transactions for the requested month
- detects suppliers that belong to statement parser families
- expands the search window to adjacent months
- imports only statement PDFs from the staged local archive
- filters by pub when provided
- runs the normal extraction flow after import

Example:

```bash
curl -s -X POST "http://localhost:8000/api/documents/import-statement-context" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_path": "backend/import_sources/Invoices - Pubs",
    "month": "2026-04",
    "source_type": "bank_statement",
    "pub": "Careys",
    "adjacent_months": 1,
    "limit": 250
  }'
```

The response includes:

- `months_considered`
- `suppliers_considered`
- `pubs_considered`
- `imported_documents`
- `extracted_documents`
- per-file statuses for the imported statement PDFs

### Current Scaffolding Endpoints from Earlier Direction

These still exist in the repo:

#### `GET /api/invoices`
#### `GET /api/invoices/{id}`
#### `PATCH /api/invoices/{id}`
#### `POST /api/invoices/{id}/reject`
#### `GET /api/dashboard/summary`
#### `GET /api/dashboard/document-inventory`
#### `GET /api/dashboard/storage-summary`
#### `GET /api/dashboard/statement-workbench`
#### `GET /api/dashboard/suppliers`
#### `POST /api/webhooks/gmail`

The invoice endpoints now project from `documents` rows so the invoice/dashboard layer can consume the document workflow directly.

Current behavior:

- invoice-type documents are synced into `invoices`
- split parent packets are excluded from that projection
- derived child invoices created by `POST /api/documents/{document_id}/split` are included
- `GET /api/invoices` refreshes that projection before listing rows
- `GET /api/dashboard/summary` refreshes that projection before calculating totals
- `GET /api/dashboard/document-inventory` exposes the supplier document set currently in the DB for a supplier/month window
  - accepts `month=YYYY-MM` with `window_months`
  - or `months=YYYY-MM,YYYY-MM,...` to show an explicit multi-month set instead
- `GET /api/dashboard/storage-summary` exposes the month/window storage mix currently in the DB
  - returns counts for `local_only`, `r2_only`, `drive_only`, and `r2_and_drive`
  - accepts the same `month`, `months`, `pub`, and `window_months` filtering shape as the supplier inventory endpoint
- `GET /api/dashboard/statement-workbench` exposes supplier statement docs as statement-first review material
  - returns parsed statement refs, imported vs missing refs, settlement groups, and likely bank transactions
  - accepts `supplier`, `month`, `months`, `pub`, `window_months`, and `limit`
- `GET /api/dashboard/suppliers` returns the distinct supplier list currently represented in documents
  - supports an optional `pub` filter
- `POST /api/documents/sync-storage` uploads existing document files into the configured S3-compatible bucket and stores `storage_provider`, `storage_bucket`, and `storage_key` on the document record

This means the invoice and dashboard views now pick up split child invoices automatically.

### Transactions

#### `POST /api/transactions/import`

Import either:

- a VAT workbook with `source_type = vatbook`
- a bank statement PDF with `source_type = bank_statement`

Examples:

```bash
curl -s -X POST "http://localhost:8000/api/transactions/import" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'

curl -s -X POST "http://localhost:8000/api/transactions/import" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source_type": "bank_statement",
    "statement_path": "bankstatements/estatement.pdf"
  }'
```

#### `GET /api/transactions`

List imported transaction rows.

Useful filters:

- `month=YYYY-MM`
- `source_type=vatbook|bank_statement|all`
- `pub=Careys`
- `annotated_only=true`

#### `GET /api/transactions/reconciliation-report`

Return the transaction-vs-document reconciliation analysis for one month.

This includes:

- `matched`, `partial`, `suggested`, and `unmatched` counts
- `resolution_bucket_counts` so unresolved work is grouped into action buckets
- candidate invoice matches
- supporting document matches such as statements or credit notes when invoice matches do not exist
- `analysis_note` to explain unresolved-but-informative rows

The reconciliation layer now runs on a shared normalized ledger model:

- invoice documents normalize to ledger entries
- credit notes normalize to negative ledger entries
- receipts normalize to payment ledger entries
- parsed supplier statement lines normalize to the same entry model

That lets the engine reason about statement settlements such as:

- invoice + credit note = receipt
- statement payment row = bank payment
- support-document rows without direct invoice PDFs

#### `GET /api/transactions/review-queue`

Return the actionable transaction queue.

By default this excludes transactions whose persistent `review_status` is already resolved:

- `linked`
- `supporting_docs_only`
- `hard_copy_available`
- `handled_by_rule`
- `no_document_expected`

Useful filters:

- `status=partial,suggested,unmatched`
- `resolution_bucket=confirm_match,review_supporting_docs,awaiting_document`
- `review_status=awaiting_document`
- `source_type=bank_statement`
- `month=2026-04`

Each queue item also returns:

- `resolution_bucket`
- `recommended_review_status`
- `resolution_reason`

Current resolution buckets:

- `confirm_match`
- `complete_partial_match`
- `review_supporting_docs`
- `awaiting_document`
- `no_document_expected`
- `needs_matcher_improvement`

#### `GET /api/documents/{document_id}`

Document detail now includes two useful analysis blocks for the review UI:

- `statement_analysis`
  - supplier-statement-specific parsed metadata and line recovery
- `ledger_analysis`
  - the normalized financial entry view used by reconciliation

`ledger_analysis.entries` can contain common entry kinds such as:

- `invoice`
- `credit_note`
- `payment`
- `other`

This is now the canonical document-inspection endpoint for operator tools and future Claude connector work.

#### `GET /api/transactions/{transaction_id}/detail`

Return the canonical transaction detail payload for operator tools.

This includes:

- the transaction row
- `reconciliation_flow`
  - a standardized supplier -> statement -> invoices / credits -> resolve chain
- persisted links
- exact matches
- suggested invoice matches
- supporting document matches
- resolution bucket guidance
- `history_count` for the transaction audit trail

This is the preferred transaction-detail endpoint for future workflow integrations.

#### `GET /api/transactions/{transaction_id}/links`

Return:

- the transaction
- persisted links
- exact matches
- suggested invoice matches
- supporting document matches
- resolution bucket guidance for that row

This remains available for backward compatibility with the current review UI.

#### `GET /api/transactions/{transaction_id}/history`

Return the transaction review audit trail.

Each event includes:

- `event_type`
- `actor_email`
- `previous_review_status`
- `current_review_status`
- `document_id`
- `link_id`
- `payload`
- `created_at`

This is intended for:

- operator auditability
- future Claude action tracing
- debugging why a row moved between review states

#### `PATCH /api/transactions/{transaction_id}/review`

Persist a bookkeeping decision on a transaction.

Allowed `review_status` values:

- `pending`
- `linked`
- `supporting_docs_only`
- `hard_copy_available`
- `handled_by_rule`
- `awaiting_document`
- `no_document_expected`

This endpoint also accepts:

- `category`
- `review_note`
- `expected_supplier`

Canonical review categories now used by the UI/backend are:

- `Invoice Match`
- `Statement Settlement`
- `Hard Copy Available`
- `No Document Expected`

Each update now records a review-history event.

Example:

```bash
curl -s -X PATCH "http://localhost:8000/api/transactions/TRANSACTION_ID/review" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "review_status": "awaiting_document",
    "review_note": "supplier invoice not received yet"
  }'
```

#### `POST /api/transactions/{transaction_id}/rule`

Save a reusable transaction-handling rule from a real row.

This is intended for recurring patterns such as:

- wages / payroll
- contract charges billed on a different cadence
- owner-handled rows that should stop surfacing as missing-document work

The saved rule currently matches on the cleaned transaction counterparty for the same source type and, by default, the same pub. When saved, it:

- updates the current transaction
- bulk-applies to similar existing transactions
- auto-applies to future imports

Useful fields:

- `category_override`
- `review_status`
- `document_expectation`
- `owner_note`
- `expected_supplier`

The standard rule categories are:

- `Wages`
- `Contract`
- `Hard Copy Available`
- `No Document Expected`

#### `GET /api/transactions/rules`

List saved transaction-handling rules for the current user.

Useful filters:

- `source_type=bank_statement`
- `pub=Careys`

This is intended for admin/operator UI use when the user wants to pick an existing rule for a transaction instead of creating another one.

#### `POST /api/transactions/{transaction_id}/apply-rule`

Apply one existing saved rule to one transaction.

This is the lightweight operator action used by the review UI when:

- the admin already created a rule earlier
- the current transaction should reuse that rule immediately

If the selected rule does not already match the current payee, it is now treated as a template and stamped into a payee-specific rule for that transaction.

#### `POST /api/transactions/{transaction_id}/links`

Create or upsert a manual transaction-to-document link.

Confirmed invoice links now promote the transaction review state to `linked`.

Each link create or update now records a transaction review-history event.

#### `PATCH /api/transactions/links/{link_id}`

Update an existing manual or persisted transaction link.

If a previously confirmed invoice link is rejected and no other confirmed invoice links remain, the transaction falls back to `pending`.

## Recommendation

Use the API in this order:

1. ingest and extract documents
2. import VAT book or bank statement transactions
3. inspect `reconciliation-report`
4. work the `review-queue`
5. confirm links or set transaction review states

The main remaining gap is not endpoint coverage. It is supplier/document coverage for the still-unmatched bank transactions.
