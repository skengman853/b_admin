# 03 — Architecture

## High-Level Architecture

```
┌──────────────┐       ┌──────────────────┐       ┌─────────────┐
│   React UI   │◄─────►│   FastAPI (API)   │◄─────►│  PostgreSQL │
└──────────────┘       └──────────────────┘       └─────────────┘
                              │      ▲
                              │      │
                              ▼      │
                       ┌──────────────────┐
                       │  Celery Workers   │
                       └──────────────────┘
                              │      │
                    ┌─────────┼──────┼─────────┐
                    ▼         ▼      ▼         ▼
              ┌─────────┐ ┌──────┐ ┌──────┐ ┌─────┐
              │Gmail API│ │OpenAI│ │ S3   │ │Redis│
              └─────────┘ └──────┘ └──────┘ └─────┘
```

## Component Responsibilities

### FastAPI (API Server)
- User authentication (signup/login via JWT)
- Gmail OAuth flow
- REST endpoints for dashboard data
- Receives Gmail push notification webhooks
- Triggers Celery tasks

### Celery Workers
- Scan user inboxes for new emails
- Detect invoice emails
- Extract text from PDFs
- Call OpenAI for structured extraction
- Store results in PostgreSQL
- Upload raw PDFs to S3

### PostgreSQL
- User accounts
- Gmail tokens (encrypted)
- Invoice records
- Processing status/logs

### Redis
- Celery message broker
- Task result backend
- Rate limiting (optional)

### S3 / Object Storage
- Raw PDF/attachment storage
- Referenced by invoice record for audit trail

## Request Flow: New Invoice Detected

```
1. Gmail sends push notification → /api/webhooks/gmail
2. API validates notification, enqueues Celery task
3. Celery worker fetches new emails via Gmail API
4. Worker checks subject/body for invoice keywords
5. If match: download attachments
6. Extract text (pdfplumber → Vision API fallback)
7. Send to OpenAI for structured extraction
8. Store invoice record in DB + raw PDF in S3
9. Invoice appears on user's dashboard (next page load)
```

## API Structure

```
POST   /api/auth/signup
POST   /api/auth/login
GET    /api/auth/me

GET    /api/gmail/auth-url
GET    /api/gmail/callback
POST   /api/webhooks/gmail

GET    /api/invoices
GET    /api/invoices/:id
PATCH  /api/invoices/:id          (user confirms/edits)
POST   /api/invoices/:id/reject   (not an invoice)

GET    /api/dashboard/summary     (monthly total, count)
```
