# 04 — Data Model & Persistence

## Purpose

The database is now the system of record for:

- document metadata
- transaction imports
- extraction history
- structured financial rows
- reconciliation suggestions
- operator decisions

The filesystem and R2 hold the PDFs.
Postgres holds the bookkeeping state.

## Main Tables

### `documents`

One row per imported document.

Purpose:

- canonical document record
- supplier/type/date/reference/amount metadata
- storage location pointers
- extracted text
- AI extraction payload

Important fields include:

- `supplier`
- `document_type`
- `document_date`
- `reference`
- `amount`
- `vat_amount`
- `currency`
- `local_path`
- `storage_provider`
- `storage_bucket`
- `storage_key`
- `drive_file_id`
- `drive_web_link`
- `extraction_status`
- `confidence_score`
- `review_reasons`
- `ai_extraction_status`
- `ai_extraction_payload`

### `transactions`

One row per imported bookkeeping transaction.

Current sources:

- `bank_statement`
- `vatbook`

Important fields include:

- `source_type`
- `pub`
- `transaction_date`
- `description1`
- `description2`
- `debit_amount`
- `credit_amount`
- `category`
- `review_status`
- `review_note`
- `expected_supplier`

### `transaction_document_links`

Operator and system document-to-transaction links.

Purpose:

- exact invoice links
- support-document links
- rejected / hidden links
- persisted context decisions

### `transaction_review_events`

Audit trail for row decisions.

Purpose:

- record who changed what
- keep review history explainable

### `transaction_rules`

Reusable operator rules.

Examples:

- wages
- contract
- hard copy available
- no document expected

Purpose:

- reduce recurring manual review

## Extraction Persistence

### `document_extraction_runs`

One row per extraction attempt.

Purpose:

- keep extraction history
- store extractor family/profile/version
- preserve raw payloads
- support safe re-extraction

Important fields:

- `extractor_family`
- `extractor_profile`
- `extractor_version`
- `source_kind`
  - `rules`
  - `hybrid`
  - `ai_primary`
- `status`
- `confidence_score`
- `review_reasons`
- `raw_payload_json`

### `document_financial_facts`

One canonical structured fact row per document.

Purpose:

- hold the stable “header” data for a document
- avoid re-reading raw PDFs for basic facts

Important fields:

- `supplier_canonical`
- `pub_hint`
- `document_type`
- `statement_kind`
- `reference`
- `document_date`
- `period_start`
- `period_end`
- `amount`
- `vat_amount`
- `currency`
- `account_number`
- `account_name`
- `is_financial`
- `extraction_run_id`

### `document_financial_rows`

One row per extracted financial line.

This is the most important table for reconciliation.

Purpose:

- store statement invoice rows
- store statement payment rows
- store statement credit rows
- store line-level structured evidence permanently

Important fields:

- `row_type`
- `reference`
- `clearing_reference`
- `event_date`
- `due_date`
- `amount`
- `signed_amount`
- `currency`
- `description`
- `raw_text`
- `confidence_score`
- `is_financial`

## Reconciliation Persistence

### `reconciliation_suggestions`

One persisted suggestion per transaction outcome candidate.

Purpose:

- store the matcher result instead of rebuilding everything only in memory
- support stable review surfaces
- support versioned matching later

Important fields:

- `suggestion_type`
  - `direct_invoice_match`
  - `statement_settlement`
  - `supporting_docs_only`
  - `rule_resolution`
- `status`
  - `suggested`
  - `accepted`
  - `rejected`
  - `superseded`
- `confidence_score`
- `reason_summary`
- `reason_json`
- `verifier_status`
  - `passed`
  - `partial`
  - `failed`

### `reconciliation_suggestion_items`

Join rows under one suggestion.

Purpose:

- keep the suggestion composition explicit
- show which documents and rows support a settlement

Important fields:

- `document_id`
- `financial_row_id`
- `item_role`
  - `statement`
  - `invoice`
  - `credit_note`
  - `payment_row`
  - `support_doc`
- `reference`
- `amount`
- `signed_amount`

## Persistence Philosophy

The important rule is:

> do not rely on raw PDF text or temporary parser output as the long-term reconciliation layer

Instead:

1. import the document
2. extract structured data
3. store the structured data
4. build suggestions from stored rows
5. verify and review from stored rows

That is the direction of the schema now.

## Current Weak Point

The schema shape is now broadly correct.

The main remaining weak point is still **statement extraction quality**, especially for supplier statement rows.

That is no longer a schema problem.
It is now mostly an extraction-quality problem.
