# 11 — Deployment & Infrastructure

## Local Development

### Docker Compose
```yaml
services:
  api:
    build: ./backend
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [db, redis]
    volumes: ["./backend:/app"]
    command: uvicorn app.main:app --host 0.0.0.0 --reload

  worker:
    build: ./backend
    env_file: .env
    depends_on: [db, redis]
    volumes: ["./backend:/app"]
    command: celery -A app.tasks worker --loglevel=info

  beat:
    build: ./backend
    env_file: .env
    depends_on: [db, redis]
    volumes: ["./backend:/app"]
    command: celery -A app.tasks beat --loglevel=info

  db:
    image: postgres:16
    environment:
      POSTGRES_DB: invoice_organizer
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    volumes: ["./frontend/src:/app/src"]
    command: npm run dev

volumes:
  pgdata:
```

### Running Locally
```bash
docker compose up -d
docker compose exec api alembic upgrade head  # Run migrations
```

## Production Deployment

### Option A: Railway (Simplest)
- Deploy backend, worker, beat as separate services
- Managed Postgres + Redis add-ons
- Auto-deploy from GitHub
- ~£15-30/month at low scale

### Option B: AWS (More Control)
- ECS Fargate for API + workers
- RDS PostgreSQL
- ElastiCache Redis
- S3 for PDF storage
- ALB for load balancing
- ~£40-80/month at low scale

### Option C: VPS (Cheapest)
- Single VPS (Hetzner/DigitalOcean, £10-20/month)
- Docker Compose in production
- Managed Postgres (Supabase/Neon free tier)
- Fine for <100 users

## Production Checklist

### Before Launch
- [ ] HTTPS configured with valid certificate
- [ ] Environment variables in secrets manager (not .env file)
- [ ] Database backups configured (daily)
- [ ] Sentry error tracking connected
- [ ] CORS restricted to production domain
- [ ] Rate limiting enabled
- [ ] Gmail OAuth consent screen approved by Google
- [ ] Health check endpoint (`/health`) responding
- [ ] Logging structured (JSON format)
- [ ] Docker images built with production settings (no --reload)

### Monitoring
- [ ] Uptime monitoring (UptimeRobot or similar)
- [ ] Error alerting via Sentry (email/Slack)
- [ ] Database connection pool monitoring
- [ ] Celery queue depth monitoring
- [ ] Disk space alerts (if VPS)

## Scaling Considerations (Not Needed Yet)

| Users | Infrastructure |
|-------|---------------|
| 1-50 | Single VPS or Railway |
| 50-500 | Separate API + worker instances, managed DB |
| 500+ | Horizontal scaling, read replicas, CDN |

Don't over-engineer. Start with the simplest deployment that works.

## CI/CD

```
GitHub Push → GitHub Actions → Build Docker Image → Deploy
```

### GitHub Actions Workflow (Simple)
1. Run tests (pytest + vitest)
2. Build Docker images
3. Push to container registry
4. Deploy (Railway auto-deploys, or ECS service update)

## Domain & DNS
- Register domain
- Point to load balancer / Railway / VPS
- SSL via Let's Encrypt (auto-renewed) or managed by platform
- Subdomain structure:
  - `app.yourdomain.com` — frontend
  - `api.yourdomain.com` — backend API
