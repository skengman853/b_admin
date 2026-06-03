from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document
from app.services.document_dedupe import pick_canonical_document
from app.services.document_serialization import normalize_document_record


def _merge_document_payload(document: Document, payload: dict[str, Any], *, preserve_identity: bool) -> None:
    protected_fields = {"gmail_message_id", "attachment_index"} if preserve_identity else set()
    for field, value in payload.items():
        if field in protected_fields:
            continue
        if field in {"source_email_sender", "source_email_subject", "source_received_at"} and getattr(document, field):
            continue
        setattr(document, field, value)


async def upsert_document_record(
    db: AsyncSession,
    *,
    user_id,
    gmail_message_id: str,
    attachment_index: int,
    source_email_sender: str,
    source_email_subject: str,
    source_received_at: datetime | None,
    stored_file: dict[str, Any],
    extraction_fields: dict[str, Any] | None = None,
) -> Document:
    payload = normalize_document_record(
        gmail_message_id=gmail_message_id,
        attachment_index=attachment_index,
        source_email_sender=source_email_sender,
        source_email_subject=source_email_subject,
        source_received_at=source_received_at,
        stored_file=stored_file,
    )
    if extraction_fields:
        payload.update(extraction_fields)

    result = await db.execute(
        select(Document).where(
            Document.user_id == user_id,
            Document.gmail_message_id == gmail_message_id,
            Document.attachment_index == attachment_index,
            Document.derivation_index == 0,
        )
    )
    document = result.scalar_one_or_none()

    if document is None:
        path_result = await db.execute(
            select(Document).where(
                Document.user_id == user_id,
                Document.local_path == payload["local_path"],
                Document.derivation_index == 0,
            )
        )
        path_matches = list(path_result.scalars().all())
        if path_matches:
            document, duplicates = pick_canonical_document(path_matches)
            _merge_document_payload(document, payload, preserve_identity=True)
            for duplicate in duplicates:
                if document.drive_file_id is None and duplicate.drive_file_id is not None:
                    document.drive_file_id = duplicate.drive_file_id
                    document.drive_web_link = duplicate.drive_web_link
                    document.drive_folder_path = duplicate.drive_folder_path
                    document.synced_at = duplicate.synced_at
                if document.storage_key is None and duplicate.storage_key is not None:
                    document.storage_provider = duplicate.storage_provider
                    document.storage_bucket = duplicate.storage_bucket
                    document.storage_key = duplicate.storage_key
                    document.storage_synced_at = duplicate.storage_synced_at
                if document.extracted_text is None and duplicate.extracted_text is not None:
                    document.extracted_text = duplicate.extracted_text
                    document.vat_amount = duplicate.vat_amount
                    document.currency = duplicate.currency
                    document.confidence_score = duplicate.confidence_score
                    document.extraction_status = duplicate.extraction_status
                    document.extracted_at = duplicate.extracted_at
                await db.delete(duplicate)
            return document

        document = Document(user_id=user_id, **payload)
        try:
            async with db.begin_nested():
                db.add(document)
                await db.flush()
            return document
        except IntegrityError:
            retry_result = await db.execute(
                select(Document).where(
                    Document.user_id == user_id,
                    Document.gmail_message_id == gmail_message_id,
                    Document.attachment_index == attachment_index,
                    Document.derivation_index == 0,
                )
            )
            existing_document = retry_result.scalar_one_or_none()
            if existing_document is None:
                raise
            _merge_document_payload(existing_document, payload, preserve_identity=False)
            return existing_document

    _merge_document_payload(document, payload, preserve_identity=False)
    return document


async def dedupe_documents_for_user(
    db: AsyncSession,
    *,
    user_id,
    local_paths: list[str] | None = None,
) -> dict[str, int]:
    query = select(Document).where(Document.user_id == user_id)
    query = query.where(Document.derivation_index == 0)
    if local_paths:
        query = query.where(Document.local_path.in_(local_paths))

    result = await db.execute(query.order_by(Document.local_path.asc(), Document.created_at.asc()))
    documents = list(result.scalars().all())

    groups_by_path: dict[str, list[Document]] = {}
    for document in documents:
        groups_by_path.setdefault(document.local_path, []).append(document)

    deduped = 0
    for group in groups_by_path.values():
        if len(group) < 2:
            continue

        canonical, duplicates = pick_canonical_document(group)
        for duplicate in duplicates:
            if canonical.drive_file_id is None and duplicate.drive_file_id is not None:
                canonical.drive_file_id = duplicate.drive_file_id
                canonical.drive_web_link = duplicate.drive_web_link
                canonical.drive_folder_path = duplicate.drive_folder_path
                canonical.synced_at = duplicate.synced_at
            if canonical.storage_key is None and duplicate.storage_key is not None:
                canonical.storage_provider = duplicate.storage_provider
                canonical.storage_bucket = duplicate.storage_bucket
                canonical.storage_key = duplicate.storage_key
                canonical.storage_synced_at = duplicate.storage_synced_at
            if canonical.extracted_text is None and duplicate.extracted_text is not None:
                canonical.extracted_text = duplicate.extracted_text
                canonical.vat_amount = duplicate.vat_amount
                canonical.currency = duplicate.currency
                canonical.confidence_score = duplicate.confidence_score
                canonical.extraction_status = duplicate.extraction_status
                canonical.extracted_at = duplicate.extracted_at
            if canonical.source_email_sender is None and duplicate.source_email_sender is not None:
                canonical.source_email_sender = duplicate.source_email_sender
            if canonical.source_email_subject is None and duplicate.source_email_subject is not None:
                canonical.source_email_subject = duplicate.source_email_subject
            if canonical.source_received_at is None and duplicate.source_received_at is not None:
                canonical.source_received_at = duplicate.source_received_at
            await db.delete(duplicate)
            deduped += 1

    if deduped:
        await db.flush()

    return {"deduped": deduped}
