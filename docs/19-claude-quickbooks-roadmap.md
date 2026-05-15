# 19 — Claude + QuickBooks Integration Roadmap

## Purpose

This document defines the next product layer on top of the current reconciliation system.

The goal is not to replace the existing backend.

The goal is to combine:

- this app as the reconciliation engine
- Claude as the operator / workflow layer
- QuickBooks as the accounting system of record

## Target Architecture

### 1. This App

This app remains responsible for:

- document ingestion
- local archive import
- PDF extraction
- pub splitting
- invoice / statement / credit-note parsing
- transaction ingestion
- deterministic reconciliation logic
- review states
- audit trail

This is where the hard bookkeeping logic lives.

### 2. Claude

Claude becomes the workflow layer that:

- reads the review queue
- explains suggested matches in plain English
- asks follow-up questions
- requests missing documents
- proposes final actions
- triggers approved actions into downstream systems

Claude should not be the source of truth for reconciliation state.

Claude should consume and operate on structured data from this app.

### 3. QuickBooks

QuickBooks becomes the final bookkeeping destination for:

- bills
- vendors
- bank-side bookkeeping records
- bill payments
- reporting
- VAT / accounting workflows

QuickBooks should receive approved outcomes, not raw unresolved queue items.

## Strategic Principles

### What We Should Not Do

- do not rebuild accounting inside Claude
- do not push unresolved transactions directly into QuickBooks
- do not make Claude guess from raw PDFs when this app can provide structured reconciliation data
- do not create a separate reconciliation logic path for Claude

### What We Should Do

- expose clean operator APIs from this app
- let Claude act on those APIs
- keep review and approval state inside this app
- push only approved accounting events into QuickBooks
- improve structured extraction with AI before asking Claude to review noisy raw PDFs

## Phase 1 — API Endpoints

### Goal

Make this app a stable operator backend that Claude or any future workflow layer can use safely.

### Current Status

Phase 1 has started.

The first implemented slice is:

- canonical transaction detail at `GET /api/transactions/{transaction_id}/detail`
- canonical transaction review history at `GET /api/transactions/{transaction_id}/history`
- review/link audit persistence in `transaction_review_events`
- canonical document inspection remains `GET /api/documents/{document_id}`

### Why This Comes First

Before Claude or QuickBooks integration, this app needs a clean, explicit interface for:

- queue access
- transaction review
- document inspection
- operator actions
- audit visibility

### What Already Exists

The backend already has working endpoints for:

- reconciliation report
- review queue
- transaction links
- transaction review state updates
- document detail
- local archive import

### What Phase 1 Should Add Or Tighten

#### A. Stable Review Queue API

Required outputs:

- transaction summary
- resolution bucket
- recommended review status
- reason text
- expected supplier hint
- suggested invoice candidates
- supporting document candidates
- persisted links

Required filters:

- month
- source type
- pub
- review status
- resolution bucket
- show resolved

Acceptance criteria:

- same filters used by `/review` are available cleanly through the API
- queue payload shape is documented and stable

#### B. Transaction Detail API

Required outputs:

- full transaction metadata
- current review status
- review note
- expected supplier
- suggested invoices
- support documents
- persisted links
- ledger-backed explanation text

Acceptance criteria:

- one request can hydrate the full right-hand review panel

#### C. Document Detail API

Required outputs:

- document metadata
- supplier
- type
- date
- reference
- amount
- VAT
- local/source metadata
- parsed statement analysis
- normalized ledger entries

Acceptance criteria:

- a workflow agent can inspect one document without scraping the UI

#### D. Review Action API

Required actions:

- confirm invoice link
- reject link
- resolve as supporting docs only
- mark awaiting document
- mark no document expected
- reset to pending
- save expected supplier hint

Acceptance criteria:

- every action available in `/review` is available through the API
- actions are idempotent where practical
- action results return updated transaction state

#### E. Audit / History API

Required outputs:

- who changed a transaction
- when it changed
- previous review state
- current review state
- linked document ids
- rejected link history

Acceptance criteria:

- operator and Claude actions can be audited later

#### F. Authentication / Access Shape

Required decisions:

- whether Claude will call the app as a local desktop client or through a remote connector
- whether auth stays user-token based or gets a service/operator token model

Acceptance criteria:

- one supported auth path for local operator workflows
- one supported auth path for future remote connector workflows

### Phase 1 Deliverables

- stable queue schema
- stable transaction detail schema
- stable document detail schema
- stable action endpoints
- audit/history support
- refreshed API documentation

### Phase 1 Non-Goals

- no QuickBooks sync yet
- no Claude connector yet
- no workflow orchestration yet

## Phase 2 — Claude Connector

### Goal

Let Claude use this app as an operator tool instead of reading the browser manually.

### Preferred Shape

#### Local / Desktop Path

Use Claude Desktop or a local tool layer for:

- local file access
- PDF inspection
- local archive access
- local dev review workflows

#### Remote Connector Path

Expose a clean public API or remote MCP surface for:

- queue listing
- transaction inspection
- document inspection
- review actions

### Claude Responsibilities

Claude should be able to:

- fetch queue items
- summarize the next most useful rows to review
- explain why a match is suggested
- ask for a missing document
- propose an action
- execute the approved action through the API

### Phase 2 Deliverables

- Claude-facing tool surface
- clear action contracts
- permission boundaries
- test workflow for one operator account

### Phase 2 Non-Goals

- no automatic posting into QuickBooks yet
- no autonomous bulk-resolution without approval

## Phase 3 — QuickBooks Sync

### Goal

Push approved bookkeeping outcomes into QuickBooks in a controlled way.

### Core Rule

Only approved and resolved outcomes should sync.

Do not push unresolved or ambiguous rows into QuickBooks automatically.

### Recommended Sync Scope

#### Initial Sync Scope

- vendors / supplier mapping
- bills from approved invoice documents
- bill payments from confirmed bank-to-invoice links
- support-doc-only resolution notes as attachments or references

#### Later Sync Scope

- credit notes
- statement-backed grouped settlements
- bank-rule enrichment
- reconciliation status feedback from QuickBooks back into this app

### Required Mapping Layer

- local supplier -> QuickBooks vendor
- pub / location -> tracking class or location field
- document type -> QuickBooks object type
- approved link -> bill payment or matched transaction event

### Phase 3 Deliverables

- vendor mapping model
- export payload builders
- sync job logging
- failure handling and retry logic
- sync status visibility in the UI/API

### Phase 3 Non-Goals

- no live QuickBooks writes from ambiguous queue states
- no “Claude guesses and posts directly” flow

## Phase 4 — Operator Workflow

### Goal

Turn the current reconciliation workbench into a proper month-close workflow.

### Operator Flow

1. import docs and transactions
2. open monthly queue
3. let Claude summarize high-confidence actions
4. confirm / reject / defer
5. chase missing documents
6. resolve support-doc-only rows
7. sync approved outcomes into QuickBooks
8. close the month

### UI / UX Work

- better document preview
- clearer statement math
- grouped settlement views
- resolved/unresolved workflow lanes
- sync status visibility
- Claude action suggestions in context

### Phase 4 Deliverables

- operator dashboard for monthly close
- Claude-assisted review actions
- QuickBooks sync review step
- month-close reporting

## Recommended Build Order

### Immediate

1. finish Phase 1 API stabilization
2. document payloads and action contracts
3. add audit trail where missing

### After That

4. build Claude connector around those APIs
5. prove one narrow operator flow end to end
6. add QuickBooks sync for approved invoice matches only
7. expand from direct invoice matches into statement-led settlements

## Success Criteria

The architecture is working when:

- this app owns reconciliation truth
- Claude can operate the queue without scraping the UI
- QuickBooks only receives approved outcomes
- month-close work becomes faster without losing auditability

## Best Short Version

The intended product stack is:

> this app for reconciliation logic, Claude for workflow, QuickBooks for final books
