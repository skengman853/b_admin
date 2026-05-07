# 13 — Project Structure

## Current Repo Structure

```text
b_admin/
├── README.md
├── docker-compose.yml
├── .env
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── Documents/
│   ├── temp_pdfs/
│   ├── data/
│   │   └── processed_emails.json
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── db.py
│       ├── deps.py
│       ├── models.py
│       ├── schemas.py
│       ├── api/
│       │   ├── auth.py
│       │   ├── documents.py
│       │   ├── gmail.py
│       │   ├── pipeline.py
│       │   ├── invoices.py
│       │   ├── dashboard.py
│       │   └── webhooks.py
│       ├── services/
│       │   ├── document_classifier.py
│       │   ├── document_dedupe.py
│       │   ├── document_metadata.py
│       │   ├── document_pipeline.py
│       │   ├── document_registry.py
│       │   ├── document_serialization.py
│       │   ├── document_sync.py
│       │   ├── drive_client.py
│       │   ├── drive_paths.py
│       │   ├── email_filter.py
│       │   ├── encryption.py
│       │   ├── file_namer.py
│       │   ├── gmail_client.py
│       │   ├── google_oauth.py
│       │   ├── local_storage.py
│       │   ├── pdf_text.py
│       │   ├── supplier_rules.py
│       │   └── tracking.py
│       └── tasks/
│           └── celery_app.py
│   └── tests/
└── docs/
```

## What This Structure Means

The repo currently reflects an earlier backend-first direction:

- auth exists
- Gmail OAuth exists
- invoice and dashboard endpoints exist
- database scaffolding exists

That is fine, and the repo now also contains both:

- the Phase 1 local document pipeline
- the Phase 2 document registry and Drive sync layer

## Phase 1 Runtime Shape

The current local pipeline writes operational artifacts under `backend/`:

```text
backend/
  Documents/
    Supplier/
      Invoices/
      Statements/
      Credit Notes/
      Receipts/
      Other/
    Needs Review/
      Supplier/
        Invoices/
        Statements/
        Credit Notes/
        Receipts/
        Other/
  temp_pdfs/
  data/
    processed_emails.json
```

## Phase 2 Runtime Shape

Phase 2 adds a database-backed document registry and Drive sync on top of the Phase 1 filesystem flow:

```text
backend/app/
  api/
    documents.py
  services/
    document_registry.py
    document_serialization.py
    document_sync.py
    document_dedupe.py
    drive_client.py
    drive_paths.py
    google_oauth.py
```

The important runtime relationship is now:

`Gmail -> local file -> document row -> Drive file -> stored link`

## Recommended Next Additions

### Local Document Pipeline

```text
backend/app/services/
  gmail_client.py
  email_filter.py
  supplier_rules.py
  document_classifier.py
  document_metadata.py
  document_pipeline.py
  file_namer.py
  local_storage.py
  tracking.py
```

### Document Registry and Drive Sync

```text
backend/app/api/
  documents.py

backend/app/services/
  document_registry.py
  document_serialization.py
  document_sync.py
  document_dedupe.py
  drive_client.py
  drive_paths.py
  google_oauth.py
```

### Parsing / Extraction

```text
backend/app/services/
  pdf_text.py
  field_extractors.py
  supplier_extractors.py
```

### Matching

```text
backend/app/services/
  excel_import.py
  matching_engine.py
```

### Local Operational Data

```text
backend/temp_pdfs/
backend/Documents/
backend/data/
  processed_emails.json
```

## Suggested Future Shape

```text
b_admin/
├── backend/
│   ├── Documents/
│   ├── temp_pdfs/
│   ├── data/
│   └── app/
│       ├── api/
│       ├── services/
│       │   ├── gmail_client.py
│       │   ├── email_filter.py
│       │   ├── supplier_rules.py
│       │   ├── document_classifier.py
│       │   ├── document_metadata.py
│       │   ├── document_pipeline.py
│       │   ├── file_namer.py
│       │   ├── local_storage.py
│       │   ├── pdf_text.py
│       │   ├── tracking.py
│       │   ├── drive_storage.py
│       │   ├── field_extractors.py
│       │   └── matching_engine.py
│       └── tasks/
└── docs/
```

## Design Intention

The structure should gradually shift from:

`auth + dashboard + invoices`

to:

`gmail + documents + extraction + matching`

without throwing away the useful scaffolding already in the repo.
