# Invoice Auto-Organizer

Collect invoice-related documents from Gmail, classify them, and store them cleanly.
The build now follows a local-pipeline-first approach:

`Gmail -> PDF -> classify -> local folders -> Drive -> extracted data -> Excel matching -> UI`

## Current Direction

- Phase 1 proves the document pipeline locally
- Phase 2 syncs the organized files to Google Drive
- Phase 3 extracts structured document data
- Phase 4 matches documents to Excel or VAT records
- Phase 5 adds a usable UI
- Phase 6 hardens the system for multi-user SaaS use

Current status:
- Phase 1 is complete
- completion note: [docs/14-phase-1-completion.md](docs/14-phase-1-completion.md)
- Phase 2 MVP is complete
- completion note: [docs/15-phase-2-completion.md](docs/15-phase-2-completion.md)

The current repo still contains backend auth, database, and Gmail OAuth scaffolding from an earlier direction. That scaffolding is useful, but it is no longer the primary definition of success.

## Quick Start

1. Create a local `.env` file with the settings the backend expects
2. Start the stack
3. Run migrations
4. Create a test user and connect Gmail
5. Start building the local document pipeline

```bash
# Start everything
docker compose up -d --build

# Run database migrations
docker compose exec api alembic upgrade head

# Health check
curl http://localhost:8000/health
```

## Useful Commands

```bash
# API logs
docker compose logs -f api

# Restart the API after env changes
docker compose restart api

# Open Postgres shell
docker compose exec db psql -U postgres -d invoice_organizer

# Open Redis CLI
docker compose exec redis redis-cli
```

Postgres and Redis are only exposed inside the Compose network by default, which avoids conflicts with local services already using `5432` or `6379`.

## Gmail OAuth Smoke Test

After creating a user and exporting a JWT token:

```bash
curl -s http://localhost:8000/api/gmail/auth-url \
  -H "Authorization: Bearer $TOKEN"
```

Open the returned Google URL in a browser, complete consent, then verify:

```bash
curl -s http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

You want `"gmail_connected": true`.

## What Success Looks Like Now

The immediate goal is not a polished dashboard. The immediate goal is a reliable pipeline that:

- scans recent Gmail messages
- downloads relevant PDFs
- classifies them as invoice, statement, credit note, receipt, or review-needed
- routes them into a clean local folder structure
- records what has already been processed
- persists document rows in the database
- syncs documents into Google Drive
- stores reusable Drive links

## Current Pipeline Checks

Run a scan:

```bash
curl -s -X POST http://localhost:8000/api/pipeline/scan-recent \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"days":30,"max_messages":25,"force":true}'
```

Check the accumulated pipeline summary:

```bash
curl -s http://localhost:8000/api/pipeline/summary \
  -H "Authorization: Bearer $TOKEN"
```

Check files that need manual review:

```bash
curl -s http://localhost:8000/api/pipeline/review-queue \
  -H "Authorization: Bearer $TOKEN"
```

Check stored document records:

```bash
curl -s http://localhost:8000/api/documents \
  -H "Authorization: Bearer $TOKEN"
```

Manual Drive sync is still available if needed:

```bash
curl -s -X POST http://localhost:8000/api/documents/sync-drive \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"limit":100}'
```

## Roadmap

The current source of truth is [docs/12-build-phases.md](docs/12-build-phases.md).
