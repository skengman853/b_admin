# 06 — Gmail Integration

## Goal

Connect Gmail, fetch relevant emails, and download PDF attachments reliably.

Push notifications and deep automation are later concerns.

## Local OAuth Setup

For local development:

1. Create a Google Cloud project
2. Enable Gmail API
3. Configure Google Auth Platform
4. Add your Google account as a test user
5. Create a web OAuth client
6. Use this redirect URI exactly:

```text
http://localhost:8000/api/gmail/callback
```

## Scope

```text
https://www.googleapis.com/auth/gmail.readonly
```

Read-only access is enough for this workflow.

## Current Repo Endpoints

The current backend already supports:

- `GET /api/gmail/auth-url`
- `GET /api/gmail/callback`
- `DELETE /api/gmail/disconnect`

The repo also contains a Gmail webhook route for a later automation stage:

- `POST /api/webhooks/gmail`

## Tested Local Flow

1. Create or log into a local user account
2. Call `GET /api/gmail/auth-url`
3. Open the returned Google URL in a browser
4. Consent with a test-user Google account
5. Google redirects to `/api/gmail/callback`
6. Backend stores encrypted Gmail tokens
7. Backend redirects to `FRONTEND_URL/dashboard`

Important:

- the final redirect may fail if no frontend is running on `localhost:3000`
- that redirect failure does not mean Gmail connection failed
- the real check is whether `gmail_connected` becomes `true`

## Verification

After consent:

```bash
curl -s http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

You want:

```json
"gmail_connected": true
```

## Phase 1 Fetch Strategy

Do not begin with push notifications.

Begin with:

- fetch last 7-30 days of emails
- inspect subject, sender, and attachments
- only process messages with relevant PDFs

## Practical Gmail Query Ideas

Start with broad-but-useful queries such as:

```text
newer_than:30d has:attachment filename:pdf
```

Then apply your own include/exclude rules in code.

If needed, narrow further with subject hints:

```text
newer_than:30d has:attachment filename:pdf (invoice OR statement)
```

## Message Retrieval Steps

1. List recent message IDs
2. Fetch each message in full format
3. Read subject and sender headers
4. Walk MIME parts to find attachments
5. Download PDF attachment payloads
6. Pass those PDFs into local classification and storage logic

## Phase 1 Done When

- Gmail auth is stable
- messages can be listed
- attachment metadata can be read
- PDFs can be downloaded for relevant emails

## Later Gmail Work

Move these to later phases:

- incremental sync via Gmail history
- Gmail Pub/Sub push notifications
- scheduled re-scans
- watch renewal

Those are useful only after the local pipeline is already trustworthy.
