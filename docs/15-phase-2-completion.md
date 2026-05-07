# 15 — Phase 2 Completion Note

## Status

Phase 2 MVP is complete as of May 7, 2026.

The goal of Phase 2 was to extend the proven local pipeline with database-backed document records and Google Drive sync:

`local documents -> document records -> Drive upload -> stored links`

That goal has been met on real inbox data.

## What Was Built

### Document Registry

- a generic `documents` table now exists
- document rows are created from pipeline output
- each row stores:
  - supplier
  - document type
  - date
  - reference
  - amount
  - local path
  - review state
  - source email metadata
- Drive metadata is stored on the same document rows

### Google Drive Integration

- Google OAuth now requests both:
  - Gmail read access
  - Drive file access
- the Google Drive API is used through the same stored connection
- local folder structure is mirrored into Drive
- files are uploaded successfully and return Drive file IDs and web links

### Document APIs

- `GET /api/documents` lists document records from the database
- `POST /api/documents/sync-drive` uploads unsynced documents to Drive
- synced rows store:
  - `drive_file_id`
  - `drive_web_link`
  - `drive_folder_path`
  - `synced_at`

### Auto-Sync and Dedupe

- pipeline scans now auto-sync touched documents to Drive by default
- manual sync is still available
- duplicate document rows are deduped by canonical local path
- synced rows are preferred as the canonical record when duplicates exist
- `Needs Review` documents are preserved in both local storage and Drive

## Acceptance Criteria Met

Phase 2 MVP is considered complete because all of the following are true:

- scanned documents are persisted in the database
- Drive uploads succeed from real inbox data
- Drive links are stored and can be reused later
- the local supplier/type structure is mirrored into Drive
- `Needs Review` files remain separated
- reruns no longer require a separate manual Drive step in the normal path

## Current Expected Operator Flow

1. Connect Gmail and Google Drive through the existing OAuth flow
2. Run a pipeline scan
3. Let the scan save files locally and sync them to Drive
4. Inspect `/api/documents` for stored metadata and links
5. Use Drive links to open the synced files directly

## Important Phase 2 Decisions

### Drive Mirrors the Local Structure

Phase 2 mirrors the local structure already proven in Phase 1.

It does not yet introduce a different year/month Drive hierarchy.

### `documents` Is the New Source of Truth

Phase 2 does not reuse the older `invoices` table as the main document registry.

The system now stores invoices, statements, credit notes, receipts, and review-needed documents in the generic `documents` table.

### Drive Sync Should Not Replace Local Storage

Drive is an additional storage and sharing layer.

The local pipeline still matters because it is:

- easier to debug
- the first place classification happens
- the source path mirrored into Drive

## Intentionally Deferred to Later Phases

Phase 2 MVP does not include:

- richer Drive folder hierarchy such as year/month nesting
- manual review UI
- manual reclassification endpoints
- formal extracted data fields such as VAT and confidence score
- Excel matching
- production-grade background sync orchestration

## Phase 3 Start Point

Phase 3 should begin with structured extraction from the `documents` records already stored.

The immediate handoff assumptions are:

- local files and Drive links now exist
- the `documents` table is the record to enrich
- extraction should store structured fields, not just use them for filenames

## Validation Commands

```bash
docker compose exec api alembic upgrade head

curl -s -X POST http://localhost:8000/api/pipeline/scan-recent \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"days":30,"max_messages":50,"force":true}'

curl -s http://localhost:8000/api/documents \
  -H "Authorization: Bearer $TOKEN"

curl -s -X POST http://localhost:8000/api/documents/sync-drive \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"limit":100}'

python3 -m unittest discover -s backend/tests
```
