from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID

from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, GmailConnection, User
from app.services.drive_client import ensure_drive_path, get_drive_service, upload_local_file
from app.services.drive_paths import drive_path_parts_for_local_path
from app.services.document_registry import dedupe_documents_for_user
from app.services.document_split import sync_child_documents_from_parent
from app.services.object_storage import ensure_local_document_file


def _sync_error_reason(exc: Exception) -> str:
    if isinstance(exc, HttpError):
        status = getattr(exc.resp, "status", "unknown")
        details = ""
        if exc.error_details:
            detail_parts: list[str] = []
            for item in exc.error_details:
                if isinstance(item, dict):
                    detail_parts.append(item.get("message") or item.get("reason") or str(item))
                else:
                    detail_parts.append(str(item))
            details = "; ".join(part for part in detail_parts if part)
        if not details:
            details = str(exc)
        details = " ".join(details.split())
        return f"sync_failed:HttpError:{status}:{details[:240]}"

    return f"sync_failed:{exc.__class__.__name__}"


async def sync_documents_to_drive(
    *,
    user: User,
    connection: GmailConnection,
    db: AsyncSession,
    limit: int,
    document_ids: list[UUID] | None = None,
    force: bool = False,
) -> dict:
    dedupe_summary = await dedupe_documents_for_user(db, user_id=user.id)

    query = select(Document).where(Document.user_id == user.id, Document.derivation_index == 0)
    if document_ids:
        query = query.where(Document.id.in_(document_ids))
    elif not force:
        query = query.where(Document.drive_file_id.is_(None))

    query = query.order_by(Document.created_at.asc()).limit(limit)
    result = await db.execute(query)
    documents = list(result.scalars().all())

    response_results: list[dict] = []
    if not documents:
        await db.commit()
        return {
            "requested": 0,
            "synced": 0,
            "skipped": 0,
            "deduped": dedupe_summary["deduped"],
            "results": response_results,
        }

    service = await get_drive_service(connection, db)
    synced = 0
    skipped = 0

    for document in documents:
        if document.drive_file_id and not force:
            skipped += 1
            response_results.append(
                {
                    "document_id": document.id,
                    "local_path": document.local_path,
                    "drive_file_id": document.drive_file_id,
                    "drive_web_link": document.drive_web_link,
                    "status": "skipped",
                    "reason": "already_synced",
                }
            )
            continue

        try:
            local_path = ensure_local_document_file(document)
        except FileNotFoundError:
            skipped += 1
            response_results.append(
                {
                    "document_id": document.id,
                    "local_path": document.local_path,
                    "drive_file_id": document.drive_file_id,
                    "drive_web_link": document.drive_web_link,
                    "status": "skipped",
                    "reason": "local_file_missing",
                }
            )
            continue

        try:
            folder_id, folder_path = ensure_drive_path(service, drive_path_parts_for_local_path(document.local_path))
            uploaded = upload_local_file(service, local_path=str(local_path), parent_id=folder_id)
        except Exception as exc:
            skipped += 1
            response_results.append(
                {
                    "document_id": document.id,
                    "local_path": document.local_path,
                    "drive_file_id": document.drive_file_id,
                    "drive_web_link": document.drive_web_link,
                    "status": "skipped",
                    "reason": _sync_error_reason(exc),
                }
            )
            continue

        document.drive_file_id = uploaded.get("id")
        document.drive_web_link = uploaded.get("webViewLink")
        document.drive_folder_path = folder_path
        document.synced_at = datetime.utcnow()
        await sync_child_documents_from_parent(parent_document=document, db=db)
        synced += 1
        response_results.append(
            {
                "document_id": document.id,
                "local_path": document.local_path,
                "drive_file_id": document.drive_file_id,
                "drive_web_link": document.drive_web_link,
                "status": "synced",
                "reason": None,
            }
        )

    await db.commit()

    return {
        "requested": len(documents),
        "synced": synced,
        "skipped": skipped,
        "deduped": dedupe_summary["deduped"],
        "results": response_results,
    }
