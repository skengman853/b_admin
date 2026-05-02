# 12 — Build Phases & Execution Order

## Phase 1 — Foundation (Week 1)

### Goals
- Project scaffolding with Docker Compose
- User auth working (signup, login, JWT)
- Gmail OAuth flow complete (connect, store tokens)
- Database set up with migrations

### Tasks
1. [ ] Create project structure (backend + frontend dirs)
2. [ ] Set up Docker Compose (Postgres, Redis, API, Worker)
3. [ ] FastAPI app with health check endpoint
4. [ ] SQLAlchemy models + Alembic migrations
5. [ ] User signup/login endpoints with JWT
6. [ ] Gmail OAuth flow (auth URL → callback → store encrypted tokens)
7. [ ] Basic test: can connect Gmail and see token stored

### Done When
- `docker compose up` starts everything
- Can create account, login, get JWT
- Can connect Gmail and tokens are stored encrypted in DB

---

## Phase 2 — Core Logic (Week 2)

### Goals
- Fetch emails from Gmail
- Detect invoices
- Extract data with AI
- Store invoices in DB

### Tasks
1. [ ] Gmail API client (fetch messages, get full email, get attachments)
2. [ ] Invoice detection logic (keyword matching on subject/body/filename)
3. [ ] PDF text extraction (pdfplumber)
4. [ ] OpenAI text-based extraction (email body + PDF text → JSON)
5. [ ] OpenAI Vision extraction (for scanned PDFs)
6. [ ] Celery task: process_single_email
7. [ ] Celery task: scan_inbox_initial (90-day backfill)
8. [ ] Store invoices in DB with confidence score
9. [ ] Upload raw PDFs to S3 (or local filesystem for dev)
10. [ ] Deduplication (skip already-processed emails)

### Done When
- Connect Gmail → system scans inbox → invoices appear in DB
- Can verify with `SELECT * FROM invoices` that data is correct
- Both digital and scanned PDFs are handled

---

## Phase 3 — Frontend + Polish (Week 3)

### Goals
- Working dashboard UI
- User can review and confirm invoices
- Push notifications set up

### Tasks
1. [ ] React app scaffolding (Vite + TypeScript)
2. [ ] Login/signup page
3. [ ] Auth state management (store JWT, redirect if expired)
4. [ ] Dashboard page with summary cards
5. [ ] Invoice table component
6. [ ] Month selector (navigate between months)
7. [ ] Invoice review/edit panel (confirm, edit, reject)
8. [ ] Gmail connect button + status indicator
9. [ ] Gmail Pub/Sub push notifications (webhook + watch setup)
10. [ ] Celery Beat periodic tasks (watch renewal, fallback scan)
11. [ ] Error handling in UI (loading states, error messages)

### Done When
- Full user flow works end-to-end in browser
- User signs up → connects Gmail → sees invoices → confirms them
- New emails trigger near-instant processing via push

---

## Phase 4 — Production Ready (Week 4)

### Goals
- Deployable to production
- Secure, monitored, reliable

### Tasks
1. [ ] Production Docker builds (multi-stage, no dev dependencies)
2. [ ] Environment-based config (dev vs production settings)
3. [ ] Structured logging (JSON format)
4. [ ] Sentry integration (backend + frontend)
5. [ ] Rate limiting on auth endpoints
6. [ ] CORS configuration (production domain only)
7. [ ] Health check endpoint with DB/Redis connectivity check
8. [ ] Deploy to chosen platform (Railway / AWS / VPS)
9. [ ] SSL + domain setup
10. [ ] Database backups configured
11. [ ] Gmail OAuth consent screen submitted for Google verification
12. [ ] Basic load testing (can handle 10 concurrent users)
13. [ ] README with setup instructions

### Done When
- App is live on a real domain with HTTPS
- Can sign up, connect Gmail, and see invoices — in production
- Errors are captured in Sentry
- System recovers from crashes (Docker restart policies)

---

## Key Principles During Build

1. **Get it working, then make it good.** Don't optimise prematurely.
2. **Test with real emails.** Use your own Gmail from day one.
3. **One feature at a time.** Don't start Phase 2 until Phase 1 is solid.
4. **Commit often.** Small, working commits. Never break main.
5. **If stuck for >30 minutes, simplify.** Cut scope, not corners.
