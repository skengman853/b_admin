# 03 — Architecture

## Architecture Principle

The architecture should follow the problem sequence:

`collect -> classify -> store -> extract -> match -> present`

Not:

`auth -> dashboard -> polish`

## Phase 1 Architecture

```text
Google Account
     |
     v
Gmail API
     |
     v
Fetch recent messages
     |
     v
Filter likely document emails
     |
     v
Download PDF attachments
     |
     v
Classify by supplier and type
     |
     v
Rename and save locally
     |
     v
Record processed message IDs
```

## What Matters in Phase 1

- Gmail connectivity
- message filtering
- attachment download
- simple classification
- local filesystem storage
- duplicate protection

## What Does Not Matter Yet

- polished frontend flows
- advanced async orchestration
- full SaaS tenancy
- rich dashboards
- AI-first extraction

## Current Repo Reality

The current codebase already has:

- JWT auth
- Gmail OAuth endpoints
- database models
- invoice and dashboard endpoints
- Celery scaffolding

Those pieces are useful, but they are supporting infrastructure, not the primary product proof.

## Component Responsibilities

### Gmail Connector

- authenticate with Gmail
- list recent messages
- retrieve message metadata
- download attachment payloads

### Filter / Classifier

- decide whether an email is relevant
- detect supplier
- detect document type
- assign output folder

### Local Storage Layer

- create local folders if missing
- save renamed files
- avoid filename collisions
- maintain a local processed-message record

### Later Drive Storage Layer

- mirror the local document structure in Drive
- upload files
- return shareable links

### Later Extraction Layer

- read text from PDFs
- extract fields like date, amount, VAT, and reference
- store structured metadata

### Later Matching Layer

- import bookkeeping records
- suggest document-to-transaction matches
- score confidence

### Later UI Layer

- browse documents
- inspect supplier groupings
- review unmatched transactions
- open files and links quickly

## Recommended Request / Job Flow

### Phase 1 Local Run

```text
1. User connects Gmail
2. System fetches recent messages
3. Non-matching emails are skipped
4. PDFs are downloaded from matching emails
5. Supplier and type are inferred
6. Files are renamed and stored locally
7. Processed message IDs are recorded
```

### Phase 2 Cloud Storage

```text
1. Local file exists
2. Drive folder path is resolved
3. File uploads to Drive
4. Link is stored alongside metadata
```

### Phase 3 Extraction

```text
1. Stored PDF is read
2. Raw text is extracted
3. Rules parse fields
4. Uncertain cases are flagged
```

### Phase 4 Matching

```text
1. Excel or VAT sheet is imported
2. Transactions are normalized
3. Documents are compared on amount, date, and supplier
4. Suggested matches are scored
```

## Proposed Evolution

### First

Keep the system understandable and manual enough to debug quickly.

### Then

Add more persistence, more extraction accuracy, and more automation.

### Last

Turn the proven workflow into a proper product.
