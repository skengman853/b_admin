# 11 — Deployment & Infrastructure

## Current Priority

Production deployment is not the current bottleneck.

The current bottleneck is proving the document pipeline locally.

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

When the project reaches Phase 6, revisit:

- Railway
- ECS / Fargate
- Render
- VPS plus Docker Compose

But do not let production planning delay the local workflow proof.
