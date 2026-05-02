from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/gmail")
async def gmail_webhook(request: Request):
    """Receives Gmail Pub/Sub push notifications. Implemented in Phase 3."""
    # TODO: Validate Pub/Sub signature, decode message, trigger incremental scan
    return {"status": "ok"}
