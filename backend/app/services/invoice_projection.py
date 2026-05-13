from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, Invoice


def _document_projects_to_invoice(document: Document) -> bool:
    if document.document_type != "invoice":
        return False
    if document.extraction_status == "split":
        return False
    if "multiple_invoice_records" in (document.review_reasons or []):
        return False
    return True


def _derive_invoice_status(*, document: Document, existing_status: str | None) -> str:
    if existing_status == "rejected":
        return "rejected"
    if document.needs_review or document.extraction_status == "review":
        if existing_status not in {None, "", "pending", "ready"}:
            return existing_status
        return "pending"
    if existing_status in {None, "", "pending"}:
        return "ready"
    return existing_status


def _populate_invoice_from_document(invoice: Invoice, document: Document) -> None:
    invoice.user_id = document.user_id
    invoice.document_id = document.id
    invoice.supplier_name = document.supplier
    invoice.reference = document.reference
    invoice.amount = document.amount
    invoice.vat_amount = document.vat_amount
    invoice.currency = document.currency or invoice.currency or "GBP"
    invoice.invoice_date = document.document_date
    invoice.source_email_id = document.gmail_message_id
    invoice.source_email_subject = document.source_email_subject
    invoice.attachment_path = document.local_path
    invoice.extracted_text = document.extracted_text
    invoice.confidence_score = document.confidence_score
    invoice.status = _derive_invoice_status(document=document, existing_status=invoice.status)


async def _find_legacy_invoice_for_document(*, db: AsyncSession, document: Document) -> Invoice | None:
    query = select(Invoice).where(
        Invoice.user_id == document.user_id,
        Invoice.document_id.is_(None),
        Invoice.source_email_id == document.gmail_message_id,
        Invoice.attachment_path == document.local_path,
        Invoice.supplier_name == document.supplier,
    )
    if document.document_date is None:
        query = query.where(Invoice.invoice_date.is_(None))
    else:
        query = query.where(Invoice.invoice_date == document.document_date)

    if document.amount is None:
        query = query.where(Invoice.amount.is_(None))
    else:
        query = query.where(Invoice.amount == document.amount)

    result = await db.execute(query.order_by(Invoice.created_at.asc()).limit(1))
    return result.scalar_one_or_none()


async def sync_invoices_from_documents(
    *,
    db: AsyncSession,
    user_id,
    document_ids: Iterable | None = None,
) -> dict[str, int]:
    query = select(Document).where(Document.user_id == user_id)
    if document_ids:
        query = query.where(Document.id.in_(list(document_ids)))

    result = await db.execute(query.order_by(Document.created_at.asc()))
    documents = list(result.scalars().all())
    if not documents:
        return {"created": 0, "updated": 0, "deleted": 0}

    existing_invoice_result = await db.execute(
        select(Invoice).where(
            Invoice.user_id == user_id,
            Invoice.document_id.in_([document.id for document in documents]),
        )
    )
    existing_by_document_id = {
        invoice.document_id: invoice
        for invoice in existing_invoice_result.scalars().all()
        if invoice.document_id is not None
    }

    created = 0
    updated = 0
    deleted = 0

    for document in documents:
        invoice = existing_by_document_id.get(document.id)
        if not _document_projects_to_invoice(document):
            if invoice is not None:
                await db.delete(invoice)
                deleted += 1
            continue

        if invoice is None:
            invoice = await _find_legacy_invoice_for_document(db=db, document=document)
            if invoice is None:
                invoice = Invoice(
                    user_id=document.user_id,
                    document_id=document.id,
                    status="pending",
                )
                db.add(invoice)
                created += 1
            else:
                updated += 1
        else:
            updated += 1

        _populate_invoice_from_document(invoice, document)

    await db.flush()
    return {"created": created, "updated": updated, "deleted": deleted}
