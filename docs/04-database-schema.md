# 04 — Database Schema

## Tables

### users
```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### gmail_connections
```sql
CREATE TABLE gmail_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    gmail_email VARCHAR(255) NOT NULL,
    access_token_encrypted TEXT NOT NULL,
    refresh_token_encrypted TEXT NOT NULL,
    token_expiry TIMESTAMP,
    history_id VARCHAR(50),          -- Gmail history ID for incremental sync
    last_synced_at TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, gmail_email)
);
```

### invoices
```sql
CREATE TABLE invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    supplier_name VARCHAR(255),
    amount DECIMAL(10, 2),
    currency VARCHAR(3) DEFAULT 'GBP',
    invoice_date DATE,
    source_email_id VARCHAR(255),    -- Gmail message ID
    source_email_subject TEXT,
    attachment_path TEXT,             -- S3 path to raw PDF
    extracted_text TEXT,              -- Raw text used for extraction
    confidence_score FLOAT,          -- AI confidence (0-1)
    status VARCHAR(20) DEFAULT 'pending',  -- pending | confirmed | rejected
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_invoices_user_id ON invoices(user_id);
CREATE INDEX idx_invoices_user_status ON invoices(user_id, status);
CREATE INDEX idx_invoices_user_date ON invoices(user_id, invoice_date);
CREATE INDEX idx_invoices_source_email ON invoices(source_email_id);
```

### processed_emails
```sql
CREATE TABLE processed_emails (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    gmail_message_id VARCHAR(255) NOT NULL,
    is_invoice BOOLEAN DEFAULT FALSE,
    processed_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, gmail_message_id)
);

CREATE INDEX idx_processed_emails_lookup ON processed_emails(user_id, gmail_message_id);
```

## Status Values for Invoices

| Status | Meaning |
|--------|---------|
| `pending` | AI extracted data, awaiting user confirmation |
| `confirmed` | User confirmed the data is correct |
| `rejected` | User said this is not an invoice |

## Notes

- Tokens are encrypted at rest using Fernet symmetric encryption (key from env var)
- `history_id` enables incremental Gmail sync (only fetch new emails since last check)
- `extracted_text` stored for re-processing if prompts improve later
- `source_email_id` used for deduplication (never process same email twice)
- `confidence_score` drives the UI — low confidence items shown first for review
