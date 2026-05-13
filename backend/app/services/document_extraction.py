from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, User
from app.services.document_extraction_rules import build_extraction_fields
from app.services.invoice_projection import sync_invoices_from_documents
from app.services.pdf_text import extract_pdf_text


async def extract_documents(
    *,
    user: User,
    db: AsyncSession,
    limit: int,
    document_ids: list | None = None,
    force: bool = False,
) -> dict:
    query = select(Document).where(Document.user_id == user.id)
    if document_ids:
        query = query.where(Document.id.in_(document_ids))
    elif not force:
        query = query.where(Document.derivation_index == 0)
        query = query.where(Document.extraction_status.not_in(["extracted", "reviewed", "split"]))
    else:
        query = query.where(Document.derivation_index == 0)
        query = query.where(Document.extraction_status != "split")

    query = query.order_by(Document.created_at.asc()).limit(limit)
    result = await db.execute(query)
    documents = list(result.scalars().all())

    extracted = 0
    skipped = 0
    response_results: list[dict] = []
    touched_document_ids: list = []

    for document in documents:
        if document.extraction_status == "split":
            skipped += 1
            response_results.append(
                {
                    "document_id": document.id,
                    "status": "skipped",
                    "reason": "split_source_document",
                    "document_type": document.document_type,
                    "supplier": document.supplier,
                    "amount": str(document.amount) if document.amount is not None else None,
                    "vat_amount": str(document.vat_amount) if document.vat_amount is not None else None,
                    "confidence_score": document.confidence_score,
                }
            )
            continue

        if document.derivation_index != 0:
            skipped += 1
            response_results.append(
                {
                    "document_id": document.id,
                    "status": "skipped",
                    "reason": "derived_document",
                    "document_type": document.document_type,
                    "supplier": document.supplier,
                    "amount": str(document.amount) if document.amount is not None else None,
                    "vat_amount": str(document.vat_amount) if document.vat_amount is not None else None,
                    "confidence_score": document.confidence_score,
                }
            )
            continue

        local_path = Path(document.local_path)
        if not local_path.exists():
            document.extraction_status = "failed"
            skipped += 1
            response_results.append(
                {
                    "document_id": document.id,
                    "status": "skipped",
                    "reason": "local_file_missing",
                    "document_type": document.document_type,
                    "supplier": document.supplier,
                    "amount": str(document.amount) if document.amount is not None else None,
                    "vat_amount": str(document.vat_amount) if document.vat_amount is not None else None,
                    "confidence_score": document.confidence_score,
                }
            )
            continue

        extracted_text = extract_pdf_text(local_path.read_bytes())
        if not extracted_text.strip():
            document.extraction_status = "failed"
            skipped += 1
            response_results.append(
                {
                    "document_id": document.id,
                    "status": "skipped",
                    "reason": "text_extraction_failed",
                    "document_type": document.document_type,
                    "supplier": document.supplier,
                    "amount": str(document.amount) if document.amount is not None else None,
                    "vat_amount": str(document.vat_amount) if document.vat_amount is not None else None,
                    "confidence_score": document.confidence_score,
                }
            )
            continue

        extraction_fields = build_extraction_fields(
            extracted_text=extracted_text,
            supplier=document.supplier,
            document_type=document.document_type,
            subject=document.source_email_subject or "",
            attachment_name=document.attachment_name,
            existing_document_date=document.document_date,
            existing_reference=document.reference,
            existing_amount=document.amount,
            existing_review_reasons=document.review_reasons,
            needs_review=document.needs_review,
        )
        for field, value in extraction_fields.items():
            setattr(document, field, value)

        extracted += 1
        touched_document_ids.append(document.id)
        response_results.append(
            {
                "document_id": document.id,
                "status": "extracted",
                "reason": None,
                "document_type": document.document_type,
                "supplier": document.supplier,
                "amount": str(document.amount) if document.amount is not None else None,
                "vat_amount": str(document.vat_amount) if document.vat_amount is not None else None,
                "confidence_score": document.confidence_score,
            }
        )

    if touched_document_ids:
        await sync_invoices_from_documents(
            db=db,
            user_id=user.id,
            document_ids=touched_document_ids,
        )
    await db.commit()
    return {
        "requested": len(documents),
        "extracted": extracted,
        "skipped": skipped,
        "results": response_results,
    }
