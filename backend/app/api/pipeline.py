from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models import GmailConnection, User
from app.schemas import (
    PipelineReviewQueueResponse,
    PipelineScanRequest,
    PipelineScanResponse,
    PipelineTrackingSummaryResponse,
)
from app.services.document_pipeline import scan_recent_documents
from app.services.tracking import build_review_queue, build_tracking_summary

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.get("/summary", response_model=PipelineTrackingSummaryResponse)
async def pipeline_summary(user: User = Depends(get_current_user)):
    summary = build_tracking_summary(str(user.id))
    return PipelineTrackingSummaryResponse.model_validate(summary)


@router.get("/review-queue", response_model=PipelineReviewQueueResponse)
async def pipeline_review_queue(user: User = Depends(get_current_user)):
    files = build_review_queue(str(user.id))
    return PipelineReviewQueueResponse(total=len(files), files=files)


@router.post("/scan-recent", response_model=PipelineScanResponse)
async def scan_recent_pipeline(
    body: PipelineScanRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(GmailConnection).where(
            GmailConnection.user_id == user.id,
            GmailConnection.is_active == True,
        )
    )
    connection = result.scalar_one_or_none()
    if not connection:
        raise HTTPException(status_code=400, detail="Gmail is not connected. Use Connect Gmail first.")

    try:
        summary = await scan_recent_documents(
            user=user,
            connection=connection,
            db=db,
            days=body.days,
            max_messages=body.max_messages,
            force=body.force,
            sync_drive=settings.pipeline_auto_sync_to_drive if body.sync_drive is None else body.sync_drive,
        )
    except HTTPException:
        raise
    except Exception as exc:  # surface a clean message instead of a raw 500
        raise HTTPException(status_code=502, detail=f"Gmail scan failed: {exc}") from exc
    return PipelineScanResponse.model_validate(summary)
