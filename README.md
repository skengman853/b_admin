# B Admin Reconciliation Engine

This repo is now a **document-first reconciliation system** for month-close bookkeeping.

It is built to answer one question well:

> what document chain explains this transaction?

The system is no longer just a Gmail downloader or folder organizer. It now imports documents and transactions, extracts structured financial data, stores statement rows and reconciliation suggestions, and gives an operator a fast audit/review flow.

## What The System Is

The current product has five layers:

1. `Ingestion`
- Gmail document ingestion
- staged local archive import from `backend/import_sources/`
- bank-statement import
- VAT-book import

2. `Storage`
- metadata in Postgres
- PDFs in local storage and Cloudflare R2
- extraction history, financial facts, financial rows, and persisted suggestions in the DB

3. `Extraction`
- invoices, credit notes, receipts, and statements become structured data
- statement extraction is now moving to an **AI-first** path
- extracted facts and rows are stored permanently so the app does not need to rethink the same PDF from scratch every time

4. `Reconciliation`
- documents are normalized into a shared ledger shape
- transactions are compared against stored financial rows and persisted suggestions
- deterministic verifier checks keep suggestions explainable

5. `Operator Workflow`
- `/month-audit` for fast monthly scanning
- `/review` for final row resolution
- `/supplier-documents` for document inventory and repair
- `/statement-workbench` for statement-first investigation

## Core Flow

`Document -> Extraction Run -> Financial Facts -> Financial Rows -> Reconciliation Suggestion -> Verifier -> Audit/Review UI`

That is the direction of the system now.

## Main Pages

- `/month-audit`
  - compact monthly ledger
  - main operator page
- `/review`
  - full reconciliation detail and final actions
- `/supplier-documents`
  - supplier document inventory
  - inline inspect / re-extract
- `/statement-workbench`
  - statement-first view
  - statement refs, settlement groups, missing pieces

## Current Data Layer

Important persisted models now include:

- `documents`
- `transactions`
- `transaction_document_links`
- `transaction_rules`
- `document_extraction_runs`
- `document_financial_facts`
- `document_financial_rows`
- `reconciliation_suggestions`
- `reconciliation_suggestion_items`

This means the app is moving away from raw PDF text and ad hoc page-time parsing, and toward a proper stored reconciliation engine.

## Current Direction

The main strategy is:

1. import the document archive
2. extract structured rows reliably
3. persist match suggestions
4. verify those suggestions deterministically
5. keep the UI simple for the operator

The biggest remaining product problem is still **statement extraction quality**, especially for suppliers like:

- `Diageo`
- `Heineken`
- `Connacht Bottlers`
- `Bulmers`

## Quick Start

```bash
# Start everything
 docker compose up -d --build

# Run migrations
 docker compose exec api alembic upgrade head

# Health checks
 curl http://localhost:8000/health
 curl http://localhost:8000/ready
```

## Production Baseline

```bash
 docker compose -f docker-compose.prod.yml up -d --build
 docker compose -f docker-compose.prod.yml exec api alembic upgrade head
 curl http://localhost:8000/ready
```

Minimum production env expectations:

```env
app_env=production
jwt_secret=replace-with-a-long-random-secret
encryption_key=replace-with-a-long-random-secret
frontend_url=https://your-frontend.example.com
google_redirect_uri=https://your-api.example.com/api/gmail/callback
```

## Statement Extraction Quality

Statements are self-verifying: extracted rows must reconcile against the statement's own
control totals (opening/closing balance or total due). Every statement extraction now gets a
persisted arithmetic verdict on `document_financial_facts`
(`arithmetic_mode`, `arithmetic_status`, `arithmetic_delta`).

```bash
# Arithmetic verdict distribution per supplier
 docker compose exec db psql -U postgres -d invoice_organizer -c "
 select supplier_canonical, arithmetic_status, count(*)
 from document_financial_facts where document_type='statement'
 group by 1,2 order by 1,3 desc;"

# Re-sync facts/rows from stored extractions (no AI cost)
 # POST /documents/backfill-financial-state {"limit": 10000, "force": true}

# Golden-corpus extraction eval (see app/eval/extraction_eval.py docstring)
 docker compose exec api python -m app.eval.extraction_eval seed --supplier Diageo --limit 5
 docker compose exec api python -m app.eval.extraction_eval run            # replay stored payloads, free
 docker compose exec api python -m app.eval.extraction_eval run --live-ai  # real model calls, disk-cached
 docker compose exec api python -m app.eval.extraction_eval run --write-baseline
```

Fixtures live in `backend/tests/golden/statements/<family>/<case>/`. Seeded fixtures are
drafts (`"verified": false`); verify each `expected.json` against the PDF before trusting its
scores. Every extraction bug an operator finds should become a fixture before it is fixed.

## Useful Commands

```bash
# API logs
 docker compose logs -f api

# Restart API after env changes
 docker compose restart api

# Postgres shell
 docker compose exec db psql -U postgres -d invoice_organizer

# Redis CLI
 docker compose exec redis redis-cli
```

## Recommended Docs

Start here:

- statement trust implementation (latest): [docs/25-statement-trust-implementation.md](docs/25-statement-trust-implementation.md)
- system overview: [docs/23-system-overview.md](docs/23-system-overview.md)
- roadmap ahead: [docs/24-roadmap-ahead.md](docs/24-roadmap-ahead.md)
- current product state: [docs/16-current-product.md](docs/16-current-product.md)
- architecture: [docs/03-architecture.md](docs/03-architecture.md)
- data model: [docs/04-database-schema.md](docs/04-database-schema.md)
- AI reconciliation data plan: [docs/22-ai-reconciliation-data-plan.md](docs/22-ai-reconciliation-data-plan.md)

The older phase docs are still useful as history, but they are no longer the best description of the current system.
