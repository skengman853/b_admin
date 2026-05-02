# 13 — Project Structure

```
invoice-organizer/
├── docs/                           # You are here
│   ├── 01-project-overview.md
│   ├── 02-tech-stack.md
│   ├── 03-architecture.md
│   ├── 04-database-schema.md
│   ├── 05-pdf-extraction.md
│   ├── 06-gmail-integration.md
│   ├── 07-api-endpoints.md
│   ├── 08-background-tasks.md
│   ├── 09-frontend-spec.md
│   ├── 10-security-auth.md
│   ├── 11-deployment.md
│   ├── 12-build-phases.md
│   └── 13-project-structure.md
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app, CORS, lifespan
│   │   ├── config.py               # Pydantic settings (env vars)
│   │   ├── db.py                   # Async SQLAlchemy session
│   │   ├── models.py               # SQLAlchemy models
│   │   ├── schemas.py              # Pydantic request/response schemas
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py             # Signup, login, me
│   │   │   ├── gmail.py            # OAuth flow, disconnect
│   │   │   ├── invoices.py         # CRUD + confirm/reject
│   │   │   ├── dashboard.py        # Summary endpoint
│   │   │   └── webhooks.py         # Gmail push notifications
│   │   │
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── gmail_client.py     # Gmail API wrapper
│   │   │   ├── extractor.py        # AI extraction (text + vision)
│   │   │   ├── pdf.py              # PDF text extraction
│   │   │   ├── detector.py         # Invoice keyword detection
│   │   │   ├── encryption.py       # Fernet encrypt/decrypt tokens
│   │   │   └── storage.py          # S3 upload/download
│   │   │
│   │   ├── tasks/
│   │   │   ├── __init__.py
│   │   │   ├── celery_app.py       # Celery configuration
│   │   │   ├── email_scanner.py    # Scan inbox tasks
│   │   │   └── maintenance.py      # Watch renewal, fallback scan
│   │   │
│   │   └── deps.py                 # Dependency injection (get_db, get_current_user)
│   │
│   ├── alembic/
│   │   ├── alembic.ini
│   │   ├── env.py
│   │   └── versions/               # Migration files
│   │
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_auth.py
│   │   ├── test_invoices.py
│   │   └── test_extractor.py
│   │
│   ├── Dockerfile
│   ├── requirements.txt
│   └── pyproject.toml
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── api.ts                  # Axios instance + interceptors
│   │   ├── pages/
│   │   │   ├── Login.tsx
│   │   │   └── Dashboard.tsx
│   │   ├── components/
│   │   │   ├── SummaryCards.tsx
│   │   │   ├── InvoiceTable.tsx
│   │   │   ├── InvoiceRow.tsx
│   │   │   ├── MonthSelector.tsx
│   │   │   └── GmailConnect.tsx
│   │   └── hooks/
│   │       ├── useAuth.ts
│   │       └── useInvoices.ts
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── Dockerfile
│
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
├── .gitignore
└── README.md
```
