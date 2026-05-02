# Invoice Auto-Organizer

Automatically extract invoices from Gmail and present them in a clean dashboard.

## Quick Start

```bash
# 1. Copy env file and fill in your values
cp .env.example .env

# 2. Start everything
docker compose up -d

# 3. Run database migrations
docker compose exec api alembic upgrade head

# 4. API is running at http://localhost:8000
# 5. Health check: http://localhost:8000/health
```

## Development

```bash
# View logs
docker compose logs -f api

# Restart after code changes (auto-reload is on)
docker compose restart api

# Run migrations after model changes
docker compose exec api alembic revision --autogenerate -m "description"
docker compose exec api alembic upgrade head
```

## API Docs

FastAPI auto-generates docs at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
