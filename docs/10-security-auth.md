# 10 — Security & Auth

## Security Priorities by Phase

The security model should match the maturity of the product.

## Phase 1 — Local Pipeline Security

### Gmail Access

- request only `gmail.readonly`
- keep the app in Google testing mode while developing
- only approved test users should connect

### Token Handling

- encrypt Gmail access and refresh tokens at rest
- keep encryption keys in environment variables
- never log raw tokens

### Local File Storage

- keep `Documents/` and temp folders out of git
- avoid writing files to world-readable locations
- do not expose local file paths publicly

### Tracking Data

- `processed_emails.json` should not be committed
- treat message IDs and sender data as private operational data

## Current Repo Auth

The current repo already includes:

- password-based signup and login
- JWT authentication
- current-user endpoint

That is useful scaffolding, but it is not the main value proof for the revised roadmap.

## JWT Guidance

If JWT auth remains in use:

- keep secrets in `.env`, not source control
- keep tokens short-lived enough for local testing hygiene
- do not treat user JWTs as permanent credentials

## Phase 2 and 3 Security

### Google Drive

- use the minimum Drive permissions required
- do not generate overly broad public sharing links by default
- prefer predictable folder ownership over ad hoc sharing

### Extraction Data

- avoid logging full document text unless necessary
- be cautious with VAT numbers, totals, and supplier details in debug logs

## Phase 6 Production Security

When the product becomes multi-user and internet-facing:

- enforce HTTPS everywhere
- move secrets into a real secret manager
- add rate limiting
- add structured audit logging
- add backups
- add error tracking
- tighten CORS
- define data deletion and retention rules

## Environment Variables

Typical current secrets:

```text
JWT_SECRET
ENCRYPTION_KEY
DATABASE_URL
REDIS_URL
GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET
OPENAI_API_KEY
SENTRY_DSN
```

## Practical Rule

Do not over-design auth before the document workflow works.

But do protect:

- Gmail tokens
- local document files
- bookkeeping data
- anything that could expose customer financial records
