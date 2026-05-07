import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import Document, GmailConnection, User
from app.schemas import DocumentDriveSyncRequest, DocumentDriveSyncResponse, DocumentListResponse, DocumentResponse
from app.services.document_sync import sync_documents_to_drive

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    needs_review: bool | None = None,
    synced: bool | None = None,
    document_type: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Document).where(Document.user_id == user.id)
    count_query = select(func.count(Document.id)).where(Document.user_id == user.id)

    if needs_review is not None:
        query = query.where(Document.needs_review == needs_review)
        count_query = count_query.where(Document.needs_review == needs_review)

    if synced is True:
        query = query.where(Document.drive_file_id.is_not(None))
        count_query = count_query.where(Document.drive_file_id.is_not(None))
    elif synced is False:
        query = query.where(Document.drive_file_id.is_(None))
        count_query = count_query.where(Document.drive_file_id.is_(None))

    if document_type:
        query = query.where(Document.document_type == document_type)
        count_query = count_query.where(Document.document_type == document_type)

    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(Document.created_at.desc()).offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    documents = result.scalars().all()

    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(document, from_attributes=True) for document in documents],
        total=total,
        page=page,
        pages=math.ceil(total / limit) if total else 1,
    )


@router.post("/sync-drive", response_model=DocumentDriveSyncResponse)
async def sync_drive_documents(
    body: DocumentDriveSyncRequest,
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
        raise HTTPException(status_code=400, detail="Gmail is not connected")

    summary = await sync_documents_to_drive(
        user=user,
        connection=connection,
        db=db,
        limit=body.limit,
        document_ids=body.document_ids,
        force=body.force,
    )
    return DocumentDriveSyncResponse.model_validate(summary)
