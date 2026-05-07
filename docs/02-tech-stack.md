# 02 — Tech Stack

## Guiding Rule

The stack should follow the workflow, not the other way around.

This means:

- local pipeline first
- cloud storage second
- structured extraction third
- matching fourth
- UI later
- SaaS concerns last

## Current Repository Stack

The current repo already contains:

- **Backend framework:** FastAPI
- **Database:** PostgreSQL
- **ORM:** SQLAlchemy async
- **Migrations:** Alembic
- **Queue scaffolding:** Celery + Redis
- **Gmail auth:** Google OAuth + Gmail API
- **PDF tooling:** pdfplumber, pdf2image
- **Containerisation:** Docker Compose

That scaffolding is fine to keep, but it is not the proof of product value.

## Phase 1 Stack — Local Document Pipeline

The first phase should rely on the simplest useful pieces:

- **Gmail access:** Google Gmail API
- **Execution model:** manual script, API-triggered run, or simple service call
- **Local storage:** filesystem folders
- **Tracking:** JSON file or other lightweight local record
- **PDF text scan:** pdfplumber
- **Rules engine:** simple subject, filename, sender, and text matching

### Phase 1 Output

The main outputs are:

- saved local PDFs
- clean folder structure
- predictable filenames
- a record of processed message IDs

## Phase 2 Additions — Cloud Storage

When the local pipeline works, add:

- **Google Drive API** for document storage and shared links
- **Basic DB** such as SQLite or Postgres for stored metadata

## Phase 3 Additions — Structured Extraction

When the storage pipeline is reliable, add:

- **Regex / rules-based parsing** for dates, totals, VAT, and references
- **Supplier-specific parsing logic** where formats are stable
- **OCR fallback** only where necessary
- **OpenAI** only when rules stop being good enough

## Phase 4 Additions — Matching

For matching documents to bookkeeping records:

- **Spreadsheet parsing:** openpyxl, pandas, or direct CSV parsing
- **Matching rules:** amount, date window, supplier similarity

## Phase 5 Additions — UI

Only after the document workflow is solid:

- **Frontend:** React or another lightweight UI
- **Views:** documents, suppliers, unlinked transactions, summary

## Phase 6 Additions — SaaS / Production

Only after the workflow works for real users:

- multi-user auth and permissions
- background jobs and push notifications
- production-grade storage, monitoring, and backups

## Python Dependencies in This Repo Today

```text
fastapi
uvicorn
sqlalchemy[asyncio]
asyncpg
alembic
celery[redis]
pdfplumber
pdf2image
python-docx
google-auth
google-api-python-client
python-jose[cryptography]
passlib[bcrypt]
pydantic-settings
```

## Likely Future Dependencies

```text
google-api-python-client      # Drive usage beyond Gmail
openpyxl or pandas            # Excel matching
rapidfuzz                     # supplier / transaction matching
openai                        # only if extraction needs it
```
