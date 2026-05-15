# 17 — Current Roadmap

## Where The Project Is Now

Phase 1 and the practical Phase 2 work are complete.

Phase 3 is advanced and already handling real data:

- extraction
- review
- packet splitting
- invoice projection
- transaction import
- reconciliation queue

The project is now in the transition between:

- late Phase 3
- and the real beginning of Phase 4

## Immediate Goal

Use April 2026 as the calibration month and make the system trustworthy on real bookkeeping work.

That means:

- fewer false positives
- clear unresolved queues
- better supplier coverage
- persistent operator decisions
- controlled use of local supplier-archive backfills

## Current Near-Term Plan

### 1. Close Supplier Coverage Gaps

Highest-value unmatched supplier groups right now:

- `Diageo`
- `M&J Gleeson`
- `Athlone Furnit`
- `Topline Heavin`
- `Connacht Bottlers`

Work needed:

- confirm whether source documents actually exist
- improve extraction for those suppliers where documents exist but are not being captured well
- add targeted alias / supplier rules where the bank payee name differs from the document supplier name
- use `POST /api/documents/import-local` to backfill only the supplier/month slices that matter instead of bulk-importing the full archive

### 2. Use Support Documents Intentionally

The system can now surface:

- statements
- credit notes
- receipts

Next step:

- decide when those are enough to mark a transaction `supporting_docs_only`
- keep those rows out of the active queue once the operator has made that decision
- improve statement-aware matching for supplier payment rows like `D/D DIAGEO IRELAND`

### 3. Work The April Queue To A Real Outcome

The target is not abstract “better matching.”

The target is:

- April queue reviewed
- obvious links confirmed
- non-document cases marked explicitly
- missing-document cases marked explicitly
- support-doc-only cases resolved intentionally

Latest real result from the staged archive import:

- `19` unique April documents were imported and extracted cleanly from the local archive
- live totals moved from `84` to `103` documents
- live invoice projection moved from `72` to `86` invoices

That proves the local archive is a valid backfill source. It also confirms the next problem is not “how do we import documents,” but “how do we resolve payment-vs-statement relationships cleanly.”

## After April

### 4. Run March As A Blind Validation Month

Once April is reasonably clean:

- do not tune the matcher first
- run March as-is
- measure what breaks

This is the real test of whether the system generalizes.

## What Still Needs Building

### High Priority

- supplier-specific extraction improvements for missing April suppliers
- better support for non-invoice reconciliation cases
- statement/sub-account-statement aware matching for supplier payment rows
- review-state usage in the frontend / operator workflow
- explicit reporting on:
  - linked rows
  - awaiting-document rows
  - no-document-expected rows
  - supporting-docs-only rows

### Medium Priority

- stronger supplier alias management
- better grouped-payment handling
- better statement-to-invoice relationship handling
- OCR fallback for image-only PDFs

### Later

- polished UI for reconciliation work
- cleaner audit/reporting views
- SaaS hardening and multi-user polish

## What Success Looks Like

The next meaningful milestone is:

> one full real month reconciled with a queue that a human can trust

That means:

- imported transactions are complete
- extracted invoice coverage is good enough
- false positive suggestions are low
- unresolved items are genuinely unresolved, not just parser mistakes
- manual decisions persist cleanly in the system

## Strategic Next Layer

After the current April calibration work, the next architectural layer is the hybrid workflow:

- this app as reconciliation engine
- Claude as workflow/operator layer
- QuickBooks as accounting system of record

That plan is detailed in:

- `docs/19-claude-quickbooks-roadmap.md`
