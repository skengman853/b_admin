# 11 — Deployment & Infrastructure

## Current Priority

The product now has enough operator flow and document handling that deployment hardening matters.

The immediate production baseline is:

- explicit runtime mode with `app_env`
- strong secrets validation at startup
- non-reload API command
- readiness checks for DB, Redis, and object storage config
- separate production compose shape

## Local Development Stack

This repo currently runs with:

- `api`
- `worker`
- `db`
- `redis`

### Compose Shape

```yaml
services:
  api:
    build: ./backend
    ports: ["8000:8000"]
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    volumes: ["./backend:/app"]

  worker:
    build: ./backend
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    volumes: ["./backend:/app"]

  db:
    image: postgres:16-alpine

  redis:
    image: redis:7-alpine
```

Postgres and Redis stay inside the Compose network by default, which avoids host-port conflicts.

## Running Locally

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
curl http://localhost:8000/health
```

## Production Runtime

Use the dedicated production compose file:

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
curl http://localhost:8000/ready
```

### Required Production Environment

```env
app_env=production
jwt_secret=<long-random-secret>
encryption_key=<long-random-secret>
frontend_url=https://your-frontend.example.com
google_redirect_uri=https://your-api.example.com/api/gmail/callback
```

If `document_storage_backend=s3`, production also requires:

```env
s3_bucket=...
s3_endpoint_url=...
s3_access_key_id=...
s3_secret_access_key=...
```

The API now refuses to start in `production` if these settings are unsafe or incomplete.

## Local Filesystem Expectations

As the document pipeline is built, expect local storage like:

```text
temp_pdfs/
Documents/
data/processed_emails.json
```

Those are product outputs, not disposable side effects.

## Recommendation for Phase 1

Keep infrastructure simple.

You do not need:

- frontend hosting
- cloud workers
- production-grade object storage
- pub/sub automation

You do need:

- stable Gmail auth
- working local folders
- repeatable runs
- observable logs

## Later Infrastructure by Phase

### Phase 2

- Google Drive API integration
- metadata persistence in SQLite or Postgres

### Phase 3

- deeper PDF and extraction processing
- optional OCR / AI services

### Phase 4

- spreadsheet import support

### Phase 5

- frontend hosting

### Phase 6

- production deployment
- backups
- alerts
- monitoring
- multi-user scaling

## Production Notes

The repo is now closest to a:

- VPS plus Docker Compose
- or small-container-host deployment

Recommended next infrastructure steps after this baseline:

- managed Postgres
- managed Redis
- object storage via R2/S3
- reverse proxy with HTTPS
- real secrets manager
- automated backups
- log aggregation / Sentry alerting
