# 14 — Phase 1 Completion Note

## Status

Phase 1 is complete as of May 7, 2026.

The goal of Phase 1 was to prove the local document pipeline works end to end:

`Gmail -> PDF -> classify -> local folders`

That goal has been met on real inbox data.

## What Was Built

### Gmail Ingestion

- Gmail OAuth connection works
- the pipeline reads the connected inbox
- scans are limited to inbox mail
- scans support configurable time windows and message limits

### Email Filtering

- invoice-related include rules are in place
- obvious noise and non-document mail is skipped
- invoice, credit, statement, and receipt patterns are handled

### Attachment Processing

- PDF attachments are fetched from Gmail
- multi-attachment emails are handled
- temporary files are staged locally before final placement

### Classification and Extraction

- supplier detection uses sender, subject, forwarded body, attachment name, and PDF text
- document types include:
  - `invoice`
  - `statement`
  - `credit_note`
  - `receipt`
- filename metadata extraction includes:
  - date
  - reference
  - amount

### Local Storage

- files are stored under supplier/type folders
- reruns are idempotent for unchanged files
- duplicate filenames are handled safely
- uncertain files are routed to:

```text
Documents/Needs Review/
```

### Reporting

- `POST /api/pipeline/scan-recent` returns a detailed scan result
- `GET /api/pipeline/summary` returns aggregate scan/tracking counts
- `GET /api/pipeline/review-queue` returns the current manual-review queue

## Acceptance Criteria Met

Phase 1 is considered complete because all of the following are true:

- real inbox scans complete successfully
- relevant PDFs are downloaded and stored locally
- supplier and document type routing works for the majority of real cases
- filenames are materially useful and mostly correct
- rerunning scans does not create uncontrolled duplicate output
- uncertain files are surfaced in `Needs Review` instead of being silently misfiled
- review state can be inspected without opening raw JSON by hand

## Current Expected Operator Flow

1. Connect the Gmail inbox
2. Run a pipeline scan
3. Check `summary`
4. Check `review-queue`
5. Inspect files under `backend/Documents/`
6. Treat any `Needs Review` items as intentional manual checks

## Important Phase 1 Decision

`Needs Review` is accepted behavior, not a failure condition.

If the system is not confident about supplier or type, it should prefer review over guessing.
That is the intended trust model for the local pipeline.

## Intentionally Deferred to Later Phases

Phase 1 does not include:

- Google Drive sync
- database-backed document records as the main system of record
- AI extraction workflows
- Excel matching
- frontend review UI
- multi-user production hardening

## Phase 2 Start Point

Phase 2 should begin with Google Drive integration using the folder structure already proven locally.

The immediate handoff assumptions are:

- local folder structure is now the source pattern to mirror
- `Needs Review` should still exist in Drive, not be removed
- current summary and review endpoints remain useful for debugging during Drive rollout

## Validation Commands

```bash
curl -s -X POST http://localhost:8000/api/pipeline/scan-recent \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"days":30,"max_messages":50,"force":true}'

curl -s http://localhost:8000/api/pipeline/summary \
  -H "Authorization: Bearer $TOKEN"

curl -s http://localhost:8000/api/pipeline/review-queue \
  -H "Authorization: Bearer $TOKEN"

python3 -m unittest discover -s backend/tests
```
