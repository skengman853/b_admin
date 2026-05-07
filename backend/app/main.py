from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api import auth, dashboard, documents, gmail, invoices, pipeline, webhooks

app = FastAPI(title="Invoice Organizer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(gmail.router)
app.include_router(pipeline.router)
app.include_router(documents.router)
app.include_router(invoices.router)
app.include_router(dashboard.router)
app.include_router(webhooks.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
