# 08 — Background Tasks & Execution Model

## Key Shift

Do not start with Celery-heavy automation.

Start with a run model that is easy to observe and debug:

- manual run
- API-triggered run
- one-shot worker command

## Phase 1 Execution Model

The first useful execution path can be synchronous or manually triggered.

Suggested sequence:

```text
1. Fetch recent Gmail messages
2. Filter likely document emails
3. Download PDF attachments
4. Detect supplier
5. Detect document type
6. Rename file
7. Save to local folder
8. Record processed message ID
```

## Suggested Local Tasks

These are logical tasks, not necessarily Celery tasks yet.

### `scan_recent_emails`

- read recent Gmail messages
- return message IDs for candidate processing

### `process_message`

- load one Gmail message
- inspect headers and attachments
- skip if already processed

### `download_pdf_attachments`

- pull attachment payloads
- save temp files locally

### `classify_document`

- determine supplier
- determine type
- determine output folder

### `store_document_locally`

- rename safely
- move into final local folder

### `record_processed_message`

- write local tracking data
- prevent duplicate work on later runs

## Current Repo Reality

The repo already includes Celery scaffolding and a `worker` container.

That is fine to keep, but Phase 1 should not depend on a complex async architecture to demonstrate value.

If a manual run and a worker-based run both exist, the manual path should remain the easier debugging path.

## Phase 2 and 3 Automation

Once the local pipeline is stable, background jobs become more useful for:

- Drive uploads
- extraction retries
- OCR retries
- periodic rescans

## Phase 6 Automation

Only later should the system grow into full background automation such as:

- Gmail push notification handling
- scheduled scans
- watch renewal
- multi-user queue orchestration
- alerting and retries at scale

## Done When

The execution model is good enough when:

- a run can be triggered reliably
- the output files appear where expected
- duplicate runs do not duplicate files
- failures are understandable without deep queue debugging
