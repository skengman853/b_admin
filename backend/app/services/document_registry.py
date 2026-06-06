from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document
from app.services.document_dedupe import (
    build_duplicate_groups,
    document_duplicate_fingerprint,
    pick_canonical_document,
)
from app.services.document_serialization import normalize_document_record


def _merge_document_payload(document: Document, payload: dict[str, Any], *, preserve_identity: bool) -> None:
    protected_fields = {"gmail_message_id", "attachment_index"} if preserve_identity else set()
    for field, value in payload.items():
        if field in protected_fields:
            continue
        if field in {"source_email_sender", "source_email_subject", "source_received_at"} and getattr(document, field):
            continue
        setattr(document, field, value)


def _extraction_merge_rank(document: Document) -> tuple[int, int, float]:
    status = (document.extraction_status or "").lower()
    status_rank = {
        "reviewed": 0,
        "extracted": 0,
        "review": 1,
        "pending": 2,
        "failed": 3,
    }.get(status, 2)
    review_penalty = 1 if document.needs_review else 0
    confidence_rank = -(float(document.confidence_score) if document.confidence_score is not None else -1.0)
    return (status_rank, review_penalty, confidence_rank)


def _merge_duplicate_document(canonical: Document, duplicate: Document) -> None:
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
    if canonical.source_email_sender is None and duplicate.source_email_sender is not None:
        canonical.source_email_sender = duplicate.source_email_sender
    if canonical.source_email_subject is None and duplicate.source_email_subject is not None:
        canonical.source_email_subject = duplicate.source_email_subject
    if canonical.source_received_at is None and duplicate.source_received_at is not None:
        canonical.source_received_at = duplicate.source_received_at
    if canonical.document_date is None and duplicate.document_date is not None:
        canonical.document_date = duplicate.document_date
    if canonical.reference is None and duplicate.reference is not None:
        canonical.reference = duplicate.reference
    if canonical.amount is None and duplicate.amount is not None:
        canonical.amount = duplicate.amount
    if canonical.vat_amount is None and duplicate.vat_amount is not None:
        canonical.vat_amount = duplicate.vat_amount
    if canonical.currency is None and duplicate.currency is not None:
        canonical.currency = duplicate.currency

    if _extraction_merge_rank(duplicate) < _extraction_merge_rank(canonical):
        canonical.extracted_text = duplicate.extracted_text
        canonical.vat_amount = duplicate.vat_amount
        canonical.currency = duplicate.currency
        canonical.confidence_score = duplicate.confidence_score
        canonical.extraction_status = duplicate.extraction_status
        canonical.extracted_at = duplicate.extracted_at
        canonical.needs_review = duplicate.needs_review
        canonical.review_reasons = list(duplicate.review_reasons or [])
        canonical.ai_extraction_status = duplicate.ai_extraction_status
        canonical.ai_extraction_provider = duplicate.ai_extraction_provider
        canonical.ai_extraction_model = duplicate.ai_extraction_model
        canonical.ai_extraction_payload = duplicate.ai_extraction_payload
        canonical.ai_extracted_at = duplicate.ai_extracted_at
        if duplicate.document_date is not None:
            canonical.document_date = duplicate.document_date
        if duplicate.reference is not None:
            canonical.reference = duplicate.reference
        if duplicate.amount is not None:
            canonical.amount = duplicate.amount
    else:
        if canonical.extracted_text is None and duplicate.extracted_text is not None:
            canonical.extracted_text = duplicate.extracted_text
        if canonical.confidence_score is None and duplicate.confidence_score is not None:
            canonical.confidence_score = duplicate.confidence_score


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
                _merge_duplicate_document(document, duplicate)
                await db.delete(duplicate)
            return document

        fingerprint = document_duplicate_fingerprint(type("PayloadStub", (), payload))
        if fingerprint:
            signature_query = select(Document).where(
                Document.user_id == user_id,
                Document.derivation_index == 0,
                Document.document_type == payload["document_type"],
                Document.supplier == payload["supplier"],
            )
            if payload.get("document_date") is not None:
                signature_query = signature_query.where(Document.document_date == payload["document_date"])
            signature_result = await db.execute(signature_query)
            signature_matches = [
                candidate
                for candidate in signature_result.scalars().all()
                if document_duplicate_fingerprint(candidate) == fingerprint
            ]
            if signature_matches:
                document, duplicates = pick_canonical_document(signature_matches)
                _merge_document_payload(document, payload, preserve_identity=True)
                for duplicate in duplicates:
                    _merge_duplicate_document(document, duplicate)
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

    deduped = 0
    for group in build_duplicate_groups(documents):
        if len(group) < 2:
            continue

        canonical, duplicates = pick_canonical_document(group)
        for duplicate in duplicates:
            _merge_duplicate_document(canonical, duplicate)
            await db.delete(duplicate)
            deduped += 1

    if deduped:
        await db.flush()

    return {"deduped": deduped}
