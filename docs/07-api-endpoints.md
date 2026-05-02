# 07 — API Endpoints

## Authentication

### POST /api/auth/signup
Create a new user account.

**Request:**
```json
{
    "email": "user@example.com",
    "password": "securepassword123"
}
```

**Response (201):**
```json
{
    "id": "uuid",
    "email": "user@example.com",
    "token": "jwt-token"
}
```

### POST /api/auth/login
**Request:**
```json
{
    "email": "user@example.com",
    "password": "securepassword123"
}
```

**Response (200):**
```json
{
    "token": "jwt-token"
}
```

### GET /api/auth/me
Get current user info. Requires auth header.

**Response (200):**
```json
{
    "id": "uuid",
    "email": "user@example.com",
    "gmail_connected": true,
    "created_at": "2026-01-15T10:00:00Z"
}
```

---

## Gmail Connection

### GET /api/gmail/auth-url
Get the Google OAuth URL to redirect the user to.

**Response (200):**
```json
{
    "url": "https://accounts.google.com/o/oauth2/v2/auth?..."
}
```

### GET /api/gmail/callback?code=XXX&state=YYY
OAuth callback. Exchanges code for tokens, stores them, triggers initial sync.

**Response:** Redirects to frontend dashboard.

### DELETE /api/gmail/disconnect
Revoke Gmail access and delete stored tokens.

**Response (200):**
```json
{
    "message": "Gmail disconnected"
}
```

---

## Invoices

### GET /api/invoices
List invoices for the current user.

**Query params:**
- `status` — filter by status: `pending`, `confirmed`, `rejected` (optional)
- `month` — filter by month: `2026-04` (optional)
- `page` — page number, default 1
- `limit` — items per page, default 50

**Response (200):**
```json
{
    "invoices": [
        {
            "id": "uuid",
            "supplier_name": "J Smith Plumbing",
            "amount": 450.00,
            "currency": "GBP",
            "invoice_date": "2026-04-28",
            "confidence_score": 0.87,
            "status": "pending",
            "source_email_subject": "Invoice #1234",
            "created_at": "2026-04-28T14:30:00Z"
        }
    ],
    "total": 42,
    "page": 1,
    "pages": 1
}
```

### GET /api/invoices/:id
Get single invoice with full details.

**Response (200):**
```json
{
    "id": "uuid",
    "supplier_name": "J Smith Plumbing",
    "amount": 450.00,
    "currency": "GBP",
    "invoice_date": "2026-04-28",
    "confidence_score": 0.87,
    "status": "pending",
    "source_email_subject": "Invoice #1234",
    "attachment_url": "https://s3.../invoice.pdf",
    "extracted_text": "...",
    "created_at": "2026-04-28T14:30:00Z"
}
```

### PATCH /api/invoices/:id
User confirms or edits invoice data.

**Request:**
```json
{
    "supplier_name": "J Smith Plumbing Ltd",
    "amount": 450.00,
    "invoice_date": "2026-04-28",
    "status": "confirmed"
}
```

**Response (200):** Updated invoice object.

### POST /api/invoices/:id/reject
Mark as not an invoice.

**Response (200):**
```json
{
    "message": "Invoice rejected"
}
```

---

## Dashboard

### GET /api/dashboard/summary
Get summary stats for the current user.

**Query params:**
- `month` — optional, defaults to current month (e.g. `2026-04`)

**Response (200):**
```json
{
    "month": "2026-04",
    "total_spend": 3420.50,
    "invoice_count": 18,
    "pending_review": 3,
    "currency": "GBP"
}
```

---

## Webhooks

### POST /api/webhooks/gmail
Receives Gmail Pub/Sub push notifications. Not authenticated by JWT — validated by Google Pub/Sub signature.

**Request:** Google Pub/Sub message format.

**Response (200):**
```json
{"status": "ok"}
```

---

## Error Responses

All errors follow this format:
```json
{
    "detail": "Human-readable error message"
}
```

| Status | Meaning |
|--------|---------|
| 400 | Bad request (validation error) |
| 401 | Not authenticated |
| 403 | Not authorised (accessing another user's data) |
| 404 | Resource not found |
| 429 | Rate limited |
| 500 | Server error |

## Auth Header Format
```
Authorization: Bearer <jwt-token>
```

JWT contains: `user_id`, `exp` (expiry). Tokens expire after 7 days.
