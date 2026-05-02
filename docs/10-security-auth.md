# 10 — Security & Auth

## User Authentication

### Password Handling
- Hash with **bcrypt** (via passlib)
- Minimum password length: 8 characters
- Never store plaintext passwords
- Never log passwords

### JWT Tokens
- Algorithm: HS256
- Expiry: 7 days
- Payload: `{ "user_id": "uuid", "exp": timestamp }`
- Secret key: from environment variable (`JWT_SECRET`)
- Sent via `Authorization: Bearer <token>` header

### Session Flow
1. User logs in → receives JWT
2. Frontend stores JWT in memory (not localStorage for XSS protection)
3. All API requests include JWT in header
4. Backend validates JWT on every request
5. Expired token → 401 → frontend redirects to login

## Gmail OAuth Security

### Token Storage
- Access tokens and refresh tokens encrypted with **Fernet** (symmetric encryption)
- Encryption key stored as environment variable (`ENCRYPTION_KEY`)
- Never log tokens
- Tokens only decrypted in memory when making Gmail API calls

### Scope Minimisation
- Only request `gmail.readonly`
- Never request send/modify/delete permissions

### Token Lifecycle
- Access token expires after 1 hour → auto-refresh using refresh token
- If refresh fails → mark connection inactive, prompt user to reconnect
- User can disconnect at any time → tokens deleted from DB

## Webhook Security

### Gmail Pub/Sub Webhook
- Validate that requests come from Google Pub/Sub
- Check `Authorization` header contains valid Google-issued token
- Verify audience claim matches your project
- Reject requests from unknown origins

## API Security

### Input Validation
- All inputs validated via Pydantic schemas
- Reject unexpected fields
- Sanitise strings (no SQL injection via ORM, but validate lengths)

### Authorisation
- Every endpoint checks `user_id` from JWT
- Users can only access their own data
- Invoice queries always filter by `user_id`

### Rate Limiting
- Login endpoint: 5 attempts per minute per IP
- API endpoints: 100 requests per minute per user
- Webhook endpoint: 1000 requests per minute (Google can burst)

## Data Protection

### What We Store
| Data | Encrypted at rest? | Retention |
|------|-------------------|-----------|
| User email + password hash | No (hash is sufficient) | Until account deleted |
| Gmail tokens | Yes (Fernet) | Until disconnected |
| Invoice data | No | Until account deleted |
| Raw PDFs (S3) | Yes (S3 server-side encryption) | Until account deleted |
| Email body text | No (stored as extracted_text) | Until account deleted |

### What We DON'T Store
- Full email content (only subject + extracted text relevant to invoice)
- Emails that aren't invoices (only message ID stored in processed_emails)
- User's password in any recoverable form

## Environment Variables (Secrets)

```
JWT_SECRET=<random 64-char string>
ENCRYPTION_KEY=<Fernet key - generate with Fernet.generate_key()>
DATABASE_URL=postgresql+asyncpg://user:pass@host/db
REDIS_URL=redis://host:6379/0
GOOGLE_CLIENT_ID=<from Google Cloud Console>
GOOGLE_CLIENT_SECRET=<from Google Cloud Console>
OPENAI_API_KEY=<from OpenAI>
S3_BUCKET=<bucket name>
AWS_ACCESS_KEY_ID=<if using S3>
AWS_SECRET_ACCESS_KEY=<if using S3>
SENTRY_DSN=<from Sentry>
```

In production: use a secrets manager (AWS Secrets Manager, GCP Secret Manager, or Doppler). Never commit `.env` files.

## CORS

- Allow frontend origin only (e.g. `https://app.yourdomain.com`)
- No wildcard `*` in production
- Allow credentials (for cookie-based auth if added later)

## HTTPS

- All traffic over HTTPS in production
- Redirect HTTP → HTTPS
- HSTS header enabled

## Account Deletion

When user deletes account:
1. Delete all invoices
2. Delete Gmail connection + tokens
3. Delete processed_emails records
4. Delete raw PDFs from S3
5. Delete user record
6. This is irreversible — confirm with user before proceeding
