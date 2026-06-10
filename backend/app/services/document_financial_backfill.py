from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Document, DocumentExtractionRun, User
from app.services.document_extraction import EXTRACTION_VERSION
from app.services.document_financial_state import sync_document_financial_state
from app.services.supplier_profiles import detect_statement_parser_family


async def backfill_document_financial_state(
    *,
    user: User,
    db: AsyncSession,
    limit: int,
    document_ids: list | None = None,
    force: bool = False,
) -> dict:
    query = (
        select(Document)
        .options(selectinload(Document.financial_fact), selectinload(Document.financial_rows))
        .where(Document.user_id == user.id, Document.derivation_index == 0, Document.extraction_status != "split")
    )
    if document_ids:
        query = query.where(Document.id.in_(document_ids))
    query = query.order_by(Document.created_at.asc()).limit(limit)

    result = await db.execute(query)
    documents = list(result.scalars().all())

    backfilled = 0
    skipped = 0
    results: list[dict] = []

    for document in documents:
        if not force and document.financial_fact is not None:
            skipped += 1
            results.append(
                {
                    "document_id": document.id,
                    "status": "skipped",
                    "reason": "financial_state_already_present",
                    "document_type": document.document_type,
                    "supplier": document.supplier,
                }
            )
            continue

        latest_run = (
            await db.execute(
                select(DocumentExtractionRun)
                .where(DocumentExtractionRun.document_id == document.id)
                .order_by(desc(DocumentExtractionRun.created_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_run is None:
            latest_run = _build_backfill_run(document)
            db.add(latest_run)
            await db.flush()

        await sync_document_financial_state(
            db=db,
            document=document,
            extraction_run=latest_run,
        )
        backfilled += 1
        results.append(
            {
                "document_id": document.id,
                "status": "backfilled",
                "reason": None,
                "document_type": document.document_type,
                "supplier": document.supplier,
            }
        )

    await db.commit()
    return {
        "requested": len(documents),
        "backfilled": backfilled,
        "skipped": skipped,
        "results": results,
    }


def _build_backfill_run(document: Document) -> DocumentExtractionRun:
    extracted_text = document.extracted_text or ""
    if document.document_type == "statement":
        extractor_profile = detect_statement_parser_family(supplier=document.supplier, text=extracted_text) or "generic_statement"
    else:
        extractor_profile = document.document_type or "document"

    if document.ai_extraction_status == "completed" and document.ai_extraction_payload:
        source_kind = "ai_primary" if document.document_type == "statement" else "hybrid"
    else:
        source_kind = "rules"
    status = document.extraction_status or ("review" if document.needs_review else "extracted")
    return DocumentExtractionRun(
        user_id=document.user_id,
        document_id=document.id,
        extractor_family=document.document_type if document.document_type in {"invoice", "statement", "credit_note", "receipt"} else "document",
        extractor_profile=extractor_profile,
        extractor_version=EXTRACTION_VERSION,
        source_kind=source_kind,
        status=status,
        confidence_score=document.confidence_score,
        review_reasons=list(document.review_reasons or []),
        raw_payload_json={
            "backfill": True,
            "document_snapshot": {
                "supplier": document.supplier,
                "document_type": document.document_type,
                "document_date": document.document_date.isoformat() if document.document_date else None,
                "reference": document.reference,
                "amount": str(document.amount) if document.amount is not None else None,
                "vat_amount": str(document.vat_amount) if document.vat_amount is not None else None,
                "currency": document.currency,
                "confidence_score": document.confidence_score,
                "extraction_status": document.extraction_status,
                "needs_review": document.needs_review,
                "review_reasons": list(document.review_reasons or []),
            },
        },
        created_at=datetime.utcnow(),
    )
