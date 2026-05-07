# 07 — API Endpoints

## Important Context

The current backend API still reflects some earlier invoice-dashboard-first work.

That is fine, but the docs should be explicit about what exists now versus what the next document-centric phases likely need.

## Currently Implemented Endpoints

### Auth

#### `POST /api/auth/signup`

Create a user and return a JWT.

#### `POST /api/auth/login`

Log in and return a JWT.

#### `GET /api/auth/me`

Return the current user and Gmail connection status.

This is currently the easiest way to verify Gmail OAuth worked:

```json
{
  "id": "uuid",
  "email": "test@example.com",
  "gmail_connected": true,
  "created_at": "..."
}
```

### Gmail

#### `GET /api/gmail/auth-url`

Return a Google OAuth URL for the logged-in user.

#### `GET /api/gmail/callback`

Handle the Google OAuth callback, store encrypted tokens, then redirect.

Note:

- this endpoint is not meant to be opened directly
- it expects `code` and `state` query params from Google
- the current implementation redirects to `FRONTEND_URL/dashboard`

#### `DELETE /api/gmail/disconnect`

Remove the stored Gmail connection for the current user.

### Pipeline

#### `POST /api/pipeline/scan-recent`

Scan recent Gmail messages for the current user, process matching PDFs, and return a debug-friendly result set.

The current response includes:

- scanned, processed, skipped, and saved counts
- per-supplier and per-type counts
- per-file extracted metadata
- `needs_review` flags and `review_reasons`

#### `GET /api/pipeline/summary`

Return the accumulated tracking summary for the current user from `processed_emails.json`.

This is the quickest way to see:

- how many messages have been tracked
- how many were processed vs skipped
- how many files need review
- counts by supplier
- counts by document type

#### `GET /api/pipeline/review-queue`

Return files currently flagged for manual review.

This is useful when supplier detection or document type classification falls back to `Other` or `unknown`.

### Current Scaffolding Endpoints from Earlier Direction

These still exist in the repo:

#### `GET /api/invoices`
#### `GET /api/invoices/{id}`
#### `PATCH /api/invoices/{id}`
#### `POST /api/invoices/{id}/reject`
#### `GET /api/dashboard/summary`
#### `POST /api/webhooks/gmail`

These endpoints are part of the earlier invoice-review direction. They are not the primary proof of the revised roadmap, but they can still be useful while the document pipeline is being built.

## Recommended Next Endpoints

The immediate reporting and scan endpoints now exist. The next likely additions are:

### Documents

#### `GET /api/documents`

List stored documents with filters like:

- supplier
- type
- date range
- source (`local` or `drive`)

#### `GET /api/documents/{id}`

Return metadata for a single document.

#### `POST /api/documents/reclassify`

Allow manual correction of supplier or document type.

### Suppliers

#### `GET /api/suppliers`

List known suppliers and document counts.

### Matching

#### `POST /api/transactions/import`

Import an Excel or CSV bookkeeping file.

#### `GET /api/matches`

Return suggested document-to-transaction matches.

## Recommendation

Do not redesign the entire API before the pipeline works.

The immediate priority is:

- use the current auth, Gmail, scan, summary, and review endpoints
- keep the interface debug-friendly
- add document-management endpoints only once the local pipeline feels stable

The API should evolve from "invoice dashboard endpoints" to "document pipeline endpoints" only as the workflow becomes real.
