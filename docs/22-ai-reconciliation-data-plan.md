# 22 — AI Reconciliation Data Plan

This document is the detailed data-layer plan behind the current product direction.

For the plain-English system summary and roadmap, start with:

- [23-system-overview.md](23-system-overview.md)
- [24-roadmap-ahead.md](24-roadmap-ahead.md)

## Goal

Build the data layer so AI can:

- read documents once
- store structured financial rows permanently
- suggest reconciliation groups
- be checked by deterministic accounting logic
- be audited later without guesswork

This is **not** a rewrite.

We keep the current product shape:

- `documents`
- `transactions`
- `transaction_document_links`
- `transaction_rules`
- review pages
- R2 storage

We add the missing structured persistence under that.

## Core Principle

Do not make the app re-think a PDF from scratch every time.

Instead:

1. import the file
2. extract structured facts
3. store those facts
4. build match suggestions from stored facts
5. verify the suggestions
6. let the user approve exceptions

## Target Data Model

### Keep

- `documents`
- `transactions`
- `transaction_document_links`
- `transaction_review_events`
- `transaction_rules`

### Add

#### `document_extraction_runs`

One row per extraction attempt.

Purpose:

- track extractor version
- keep AI/rule output history
- compare old vs new extraction
- support safe re-extraction

Suggested fields:

- `id`
- `document_id`
- `extractor_family`
  - `invoice`
  - `statement`
  - `credit_note`
  - `receipt`
- `extractor_profile`
  - `generic`
  - `diageo`
  - `heineken`
  - `connacht`
  - `bulmers`
- `extractor_version`
- `source_kind`
  - `rules`
  - `ai`
  - `hybrid`
- `status`
  - `extracted`
  - `review`
  - `failed`
- `confidence_score`
- `review_reasons`
- `raw_payload_json`
- `created_at`

#### `document_financial_facts`

One canonical structured fact row per document.

Purpose:

- store the extracted “header” facts for a document
- separate stable facts from raw PDF text

Suggested fields:

- `document_id`
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
- `is_primary_version`
- `extraction_run_id`
- `updated_at`

#### `document_financial_rows`

One row per extracted financial line.

This is the most important table for AI reconciliation.

Purpose:

- statement invoice rows
- statement payment rows
- credit note rows
- invoice line-derived totals if needed later

Suggested fields:

- `id`
- `document_id`
- `extraction_run_id`
- `row_index`
- `row_type`
  - `invoice`
  - `credit_note`
  - `payment`
  - `receipt`
  - `adjustment`
  - `other`
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

#### `reconciliation_suggestions`

One AI/rule suggestion per transaction.

Purpose:

- persist match suggestions instead of rebuilding them as ad hoc page logic only
- support re-ranking and review later

Suggested fields:

- `id`
- `transaction_id`
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
  - `failed`
  - `partial`
- `extractor_version`
- `matcher_version`
- `created_at`

#### `reconciliation_suggestion_items`

Join rows under one suggestion.

Purpose:

- record which documents and rows make up a suggestion
- keep settlement groups explicit

Suggested fields:

- `id`
- `suggestion_id`
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

## Build Plan

## Phase 1 — Stabilize the Current Document Layer

Goal:

- make the existing `documents` table reliable enough to support the next tables

Work:

1. finish duplicate handling
2. ensure every document has one canonical storage location
3. make `supplier`, `document_type`, `document_date`, `reference`, `amount` consistent
4. keep re-extraction available from the UI

Success:

- documents stop drifting between stale and fresh states
- operator can repair a bad doc from the UI

## Phase 2 — Add Extraction Run History

Goal:

- version extraction instead of mutating docs with no history

Work:

1. create `document_extraction_runs`
2. write one run row every time extraction happens
3. store the raw extractor payload there
4. mark which run is currently active for the document

Why:

- lets us improve AI extraction safely
- lets us compare old vs new outputs
- makes bulk re-extract explainable

Success:

- every extracted doc has a visible extraction history

## Phase 3 — Persist Canonical Financial Facts

Goal:

- stop relying on raw text + blob parsing at page render time

Work:

1. create `document_financial_facts`
2. create `document_financial_rows`
3. write extracted statement rows into those tables
4. write invoice/credit header facts there too
5. use `extraction_run_id` to trace where every fact came from

Why:

- statements become first-class structured data
- matching stops depending on regex and page-by-page reconstruction

Success:

- a statement’s invoice rows and payment rows can be queried directly from SQL

## Phase 4 — Backfill Existing Documents

Goal:

- upgrade the current document set without breaking the app

Work:

1. backfill the four main statement families first:
   - `Diageo`
   - `Heineken`
   - `Connacht`
   - `Bulmers`
2. backfill invoices and credits for the active months
3. compare old page output vs stored-row output
4. flag documents whose old and new values disagree

Success:

- active review months are running off stored facts, not just legacy fields

## Phase 5 — Build a Real Matcher Layer

Goal:

- move from page-time heuristics to persisted suggestions

Work:

1. create `reconciliation_suggestions`
2. create `reconciliation_suggestion_items`
3. build matchers that consume:
   - transactions
   - `document_financial_facts`
   - `document_financial_rows`
4. support:
   - direct invoice match
   - credit note adjustment
   - statement settlement group
   - support-only context

Success:

- the same suggestion can be reused by:
  - `/review`
  - `/month-audit`
  - `/statement-workbench`

## Phase 6 — Add the Verifier Layer

Goal:

- make AI suggestions safe

Work:

1. verify amount math
2. verify supplier consistency
3. verify pub consistency
4. verify duplicate suppression
5. verify one document is not over-applied across transactions

Important:

- AI can suggest the group
- verifier decides whether the suggestion is:
  - `passed`
  - `partial`
  - `failed`

Success:

- no suggestion is trusted just because AI sounded confident

## Phase 7 — Simplify the UI Around the New Data

Goal:

- make pages consume the same structured suggestion layer

Work:

1. `/month-audit`
   - one statement
   - one invoice/credit block
   - linked docs only if confirmed
2. `/review`
   - primary evidence only
3. `/statement-workbench`
   - plain “invoice coverage vs payment statement” language

Success:

- the operator stops reading matcher prose
- the product becomes a fast month-close tool again

## Phase 8 — Learn From Operator Decisions

Goal:

- make the system sharper over time

Work:

1. store accepted vs rejected suggestion outcomes
2. store hidden-document feedback
3. store “supporting docs only” by supplier pattern
4. improve ranking from repeated human choices

Important:

- do not auto-learn silently
- keep suggestions explainable

## Delivery Order

This is the best order:

1. `document_extraction_runs`
2. `document_financial_facts`
3. `document_financial_rows`
4. backfill `Diageo / Heineken / Connacht / Bulmers`
5. `reconciliation_suggestions`
6. `reconciliation_suggestion_items`
7. verifier layer
8. UI simplification

## What We Do Not Do

- do not let AI directly write final accounting truth
- do not skip persisted rows and rely on raw text forever
- do not keep piling more heuristics into page rendering
- do not rebuild the whole product first

## First Concrete Build Slice

The next real implementation slice should be:

1. add `document_extraction_runs`
2. add `document_financial_rows`
3. write statement rows there for:
   - `Diageo`
   - `Heineken`
   - `Connacht`
   - `Bulmers`
4. make `/statement-workbench` read from stored rows first

That is the point where the system starts becoming a real AI-assisted reconciliation engine instead of a smart PDF matcher.
