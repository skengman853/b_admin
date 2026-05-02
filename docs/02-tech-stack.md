# 02 — Tech Stack

## Backend
- **Framework:** FastAPI (Python 3.11+)
- **Task Queue:** Celery + Redis
- **Database:** PostgreSQL
- **ORM:** SQLAlchemy (async)
- **Migrations:** Alembic
- **PDF Parsing:** pdfplumber + pdf2image
- **AI:** OpenAI API (gpt-4o-mini)
- **Email:** Gmail API + Google Pub/Sub (push notifications)

## Frontend
- **Framework:** React (Vite + TypeScript)
- **Styling:** Tailwind CSS (or similar — keep it simple)
- **HTTP Client:** Axios or fetch

## Infrastructure
- **Containerisation:** Docker + Docker Compose
- **Deployment:** AWS ECS / Railway / Render (decide at deploy time)
- **Object Storage:** AWS S3 or GCS (for raw PDF storage)
- **Secrets:** Environment variables → secrets manager in production
- **Monitoring:** Sentry (error tracking) + structured logging
- **SSL:** Let's Encrypt / managed via cloud provider

## Development Tools
- **Linting:** Ruff (Python), ESLint (TypeScript)
- **Formatting:** Black (Python), Prettier (TypeScript)
- **Testing:** pytest (backend), Vitest (frontend)

## Key Dependencies (Python)
```
fastapi
uvicorn
sqlalchemy[asyncio]
asyncpg
alembic
celery[redis]
pdfplumber
pdf2image
python-docx
openai
google-auth
google-api-python-client
python-jose[cryptography]
passlib[bcrypt]
httpx
sentry-sdk
pydantic-settings
```

## Key Dependencies (Frontend)
```
react
react-dom
react-router-dom
axios
```
