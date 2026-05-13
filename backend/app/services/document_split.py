from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document
from app.services.document_candidates import extract_multi_invoice_candidates
from app.services.document_extraction_rules import build_extraction_fields
from app.services.pdf_text import extract_pdf_text


def _child_attachment_name(parent_attachment_name: str, reference: str | None, derivation_index: int) -> str:
    if reference:
        return f"{parent_attachment_name} [{reference}]"
    return f"{parent_attachment_name} [split-{derivation_index}]"


async def sync_child_documents_from_parent(*, parent_document: Document, db: AsyncSession) -> None:
    result = await db.execute(
        select(Document).where(Document.parent_document_id == parent_document.id)
    )
    children = list(result.scalars().all())
    for child in children:
        child.local_path = parent_document.local_path
        child.drive_file_id = parent_document.drive_file_id
        child.drive_web_link = parent_document.drive_web_link
        child.drive_folder_path = parent_document.drive_folder_path
        child.synced_at = parent_document.synced_at


async def split_document_into_children(
    *,
    document: Document,
    db: AsyncSession,
) -> dict:
    if document.parent_document_id is not None:
        raise ValueError("Derived documents cannot be split again")

    extracted_text = document.extracted_text or ""
    if not extracted_text.strip():
        local_path = Path(document.local_path)
        if not local_path.exists():
            raise ValueError("Source file is missing")
        extracted_text = extract_pdf_text(local_path.read_bytes())
        if not extracted_text.strip():
            raise ValueError("Document text extraction failed")
        document.extracted_text = extracted_text

    candidates = extract_multi_invoice_candidates(
        text=extracted_text,
        document_type=document.document_type,
        subject=document.source_email_subject or "",
    )
    if len(candidates) < 2:
        raise ValueError("Document does not contain multiple invoice candidates")

    existing_result = await db.execute(
        select(Document)
        .where(Document.parent_document_id == document.id)
        .order_by(Document.derivation_index.asc())
    )
    existing_children = {child.derivation_index: child for child in existing_result.scalars().all()}

    created = 0
    updated = 0
    deleted = 0
    child_documents: list[Document] = []

    for candidate in candidates:
        derivation_index = int(candidate["candidate_index"])
        section_text = candidate.get("section_text") or ""
        extraction_fields = build_extraction_fields(
            extracted_text=section_text,
            supplier=document.supplier,
            document_type=document.document_type,
            subject=document.source_email_subject or "",
            attachment_name=document.attachment_name,
            existing_document_date=candidate.get("document_date"),
            existing_reference=candidate.get("reference"),
            existing_amount=candidate.get("amount"),
            existing_vat_amount=candidate.get("vat_amount"),
            existing_currency=candidate.get("currency"),
            existing_review_reasons=[],
            needs_review=False,
            prefer_existing_values=True,
        )

        child = existing_children.pop(derivation_index, None)
        if child is None:
            child = Document(
                user_id=document.user_id,
                parent_document_id=document.id,
                gmail_message_id=document.gmail_message_id,
                attachment_index=document.attachment_index,
                derivation_index=derivation_index,
                attachment_name=_child_attachment_name(
                    document.attachment_name,
                    extraction_fields.get("reference"),
                    derivation_index,
                ),
                supplier=document.supplier,
                document_type=document.document_type,
                local_path=document.local_path,
                source_email_sender=document.source_email_sender,
                source_email_subject=document.source_email_subject,
                source_received_at=document.source_received_at,
                drive_file_id=document.drive_file_id,
                drive_web_link=document.drive_web_link,
                drive_folder_path=document.drive_folder_path,
                synced_at=document.synced_at,
            )
            db.add(child)
            created += 1
        else:
            updated += 1

        child.parent_document_id = document.id
        child.gmail_message_id = document.gmail_message_id
        child.attachment_index = document.attachment_index
        child.derivation_index = derivation_index
        child.attachment_name = _child_attachment_name(
            document.attachment_name,
            extraction_fields.get("reference"),
            derivation_index,
        )
        child.supplier = document.supplier
        child.document_type = document.document_type
        child.document_date = extraction_fields.get("document_date")
        child.reference = extraction_fields.get("reference")
        child.amount = extraction_fields.get("amount")
        child.vat_amount = extraction_fields.get("vat_amount")
        child.currency = extraction_fields.get("currency")
        child.confidence_score = extraction_fields.get("confidence_score")
        child.extracted_text = section_text
        child.extraction_status = extraction_fields.get("extraction_status")
        child.extracted_at = extraction_fields.get("extracted_at")
        child.local_path = document.local_path
        child.needs_review = extraction_fields.get("needs_review", False)
        child.review_reasons = extraction_fields.get("review_reasons", [])
        child.source_email_sender = document.source_email_sender
        child.source_email_subject = document.source_email_subject
        child.source_received_at = document.source_received_at
        child.drive_file_id = document.drive_file_id
        child.drive_web_link = document.drive_web_link
        child.drive_folder_path = document.drive_folder_path
        child.synced_at = document.synced_at
        child_documents.append(child)

    for stale_child in existing_children.values():
        await db.delete(stale_child)
        deleted += 1

    document.needs_review = False
    document.review_reasons = []
    document.extraction_status = "split"

    await db.flush()
    return {
        "created": created,
        "updated": updated,
        "deleted": deleted,
        "child_documents": child_documents,
    }
