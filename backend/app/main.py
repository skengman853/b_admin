import sentry_sdk
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings, validate_runtime_settings
from app.api import auth, dashboard, documents, gmail, invoices, pipeline, review_ui, transactions, webhooks
from app.db import database_ready

try:
    from redis.asyncio import from_url as redis_from_url
except Exception:  # pragma: no cover - optional runtime import fallback
    redis_from_url = None

app = FastAPI(title="Invoice Organizer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(gmail.router)
app.include_router(pipeline.router)
app.include_router(documents.router)
app.include_router(transactions.router)
app.include_router(invoices.router)
app.include_router(dashboard.router)
app.include_router(webhooks.router)
app.include_router(review_ui.router)


@app.on_event("startup")
async def startup_checks() -> None:
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.app_env,
        )

    errors = validate_runtime_settings(settings)
    if errors:
        joined = "; ".join(errors)
        raise RuntimeError(f"Invalid runtime settings: {joined}")


@app.get("/health")
async def health():
    return {"status": "ok", "environment": settings.app_env}


@app.get("/ready")
async def ready():
    checks: dict[str, str] = {}

    checks["database"] = "ok" if await database_ready() else "error"

    if redis_from_url is None:
        checks["redis"] = "unknown"
    else:
        try:
            redis = redis_from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
            await redis.ping()
            await redis.aclose()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "error"

    if settings.document_storage_backend == "s3":
        object_storage_ready = all(
            [
                settings.s3_bucket,
                settings.s3_endpoint_url,
                settings.s3_access_key_id,
                settings.s3_secret_access_key,
            ]
        )
        checks["object_storage"] = "ok" if object_storage_ready else "error"
    else:
        checks["object_storage"] = "ok"

    ready_state = all(value == "ok" or value == "unknown" for value in checks.values())
    if not ready_state:
        raise HTTPException(status_code=503, detail={"status": "error", "checks": checks})
    return {"status": "ok", "checks": checks, "environment": settings.app_env}
