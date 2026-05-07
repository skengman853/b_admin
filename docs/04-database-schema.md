# 04 — Data Model & Persistence

## Key Shift

Phase 1 does not require a database to prove value.

The first proof is:

- Gmail messages can be scanned
- PDFs can be downloaded
- documents can be classified
- files can be stored in the correct local folders

The initial system of record can be the filesystem plus a lightweight tracking file.

## Phase 1 Persistence

### Local Folders

```text
Documents/
  Supplier/
    Invoices/
    Statements/
    Credit Notes/
    Other/
```

### Tracking File

```text
data/processed_emails.json
```

Suggested fields:

```json
{
  "gmail_message_id": "18c9...",
  "sender": "billing@example.com",
  "subject": "Invoice INV-1002",
  "attachments_saved": 2,
  "status": "processed",
  "processed_at": "2026-05-05T17:30:00Z"
}
```

## Current Repo Schema

The current repo already contains earlier scaffolding for:

- `users`
- `gmail_connections`
- `invoices`
- `processed_emails`

That schema is still useful for experimentation, but it is biased toward the earlier invoice-dashboard-first plan.

## Recommended Phase 2 Target Schema

Once Google Drive and metadata storage matter, move toward a document-centric schema.

### gmail_connections

Keep this concept:

```sql
CREATE TABLE gmail_connections (
    id UUID PRIMARY KEY,
    user_id UUID,
    gmail_email VARCHAR(255) NOT NULL,
    access_token_encrypted TEXT NOT NULL,
    refresh_token_encrypted TEXT NOT NULL,
    token_expiry TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### documents

Prefer a generic document table over an invoice-only table:

```sql
CREATE TABLE documents (
    id UUID PRIMARY KEY,
    user_id UUID,
    supplier_name VARCHAR(255),
    document_type VARCHAR(50),         -- invoice | statement | credit_note | other
    source_email_id VARCHAR(255),
    source_attachment_name TEXT,
    file_name TEXT NOT NULL,
    local_path TEXT,
    drive_file_id TEXT,
    drive_link TEXT,
    document_date DATE,
    reference TEXT,
    amount DECIMAL(12, 2),
    vat_amount DECIMAL(12, 2),
    currency VARCHAR(3) DEFAULT 'GBP',
    extracted_text TEXT,
    confidence_score FLOAT,
    status VARCHAR(50) DEFAULT 'stored',
    processed_at TIMESTAMP DEFAULT NOW()
);
```

### processed_messages

```sql
CREATE TABLE processed_messages (
    id UUID PRIMARY KEY,
    user_id UUID,
    gmail_message_id VARCHAR(255) NOT NULL,
    sender_email VARCHAR(255),
    subject TEXT,
    status VARCHAR(50),                -- skipped | processed | failed
    notes TEXT,
    processed_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, gmail_message_id)
);
```

## Phase 4 Additions

When Excel matching arrives, add:

### transactions

```sql
CREATE TABLE transactions (
    id UUID PRIMARY KEY,
    user_id UUID,
    source_file TEXT,
    transaction_date DATE,
    description TEXT,
    amount DECIMAL(12, 2),
    imported_at TIMESTAMP DEFAULT NOW()
);
```

### document_matches

```sql
CREATE TABLE document_matches (
    id UUID PRIMARY KEY,
    user_id UUID,
    transaction_id UUID,
    document_id UUID,
    confidence VARCHAR(20),            -- high | medium | low
    score FLOAT,
    match_reason TEXT,
    status VARCHAR(20) DEFAULT 'suggested',
    created_at TIMESTAMP DEFAULT NOW()
);
```

## Design Notes

- The long-term storage model should be `document`-centric, not `invoice`-centric
- Statements and credit notes are first-class entities in the new workflow
- Filesystem paths and Drive links should both be storable
- Processed Gmail message IDs must remain unique to avoid duplicates
- If the system remains single-user for a while, `user_id` can be simplified operationally, even if auth scaffolding remains in the repo
