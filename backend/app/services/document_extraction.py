from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentExtractionRun, User
from app.services.ai_document_extraction import (
    AIDocumentExtractionResult,
    extract_document_with_ai,
    merge_ai_extraction,
    should_attempt_ai_extraction,
)
from app.services.document_extraction_rules import build_extraction_fields
from app.services.document_financial_state import sync_document_financial_state
from app.services.invoice_projection import sync_invoices_from_documents
from app.services.object_storage import ensure_local_document_file
from app.services.pdf_text import extract_pdf_text
from app.services.supplier_profiles import detect_statement_parser_family


EXTRACTION_VERSION = "document_extraction_v1"


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

        try:
            local_path = ensure_local_document_file(document)
        except FileNotFoundError:
            document.extraction_status = "failed"
            document.extracted_at = datetime.utcnow()
            document.review_reasons = _unique_reasons([*(document.review_reasons or []), "document_file_missing"])
            document.needs_review = True
            db.add(
                _build_extraction_run(
                    document=document,
                    extracted_text="",
                    source_kind="rules",
                    status="failed",
                    confidence_score=document.confidence_score,
                    review_reasons=document.review_reasons,
                    raw_payload_json={"failure_reason": "document_file_missing"},
                )
            )
            skipped += 1
            response_results.append(
                {
                    "document_id": document.id,
                    "status": "skipped",
                    "reason": "document_file_missing",
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
            document.extracted_at = datetime.utcnow()
            document.review_reasons = _unique_reasons([*(document.review_reasons or []), "text_extraction_failed"])
            document.needs_review = True
            db.add(
                _build_extraction_run(
                    document=document,
                    extracted_text="",
                    source_kind="rules",
                    status="failed",
                    confidence_score=document.confidence_score,
                    review_reasons=document.review_reasons,
                    raw_payload_json={"failure_reason": "text_extraction_failed"},
                )
            )
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

        extraction_fields = await _build_document_extraction_fields(
            document=document,
            extracted_text=extracted_text,
        )
        for field, value in extraction_fields.items():
            setattr(document, field, value)
        extraction_run = _build_extraction_run(
            document=document,
            extracted_text=extracted_text,
            source_kind=_extraction_source_kind(document),
            status=document.extraction_status,
            confidence_score=document.confidence_score,
            review_reasons=document.review_reasons or [],
            raw_payload_json=_build_run_payload(document=document, extraction_fields=extraction_fields),
        )
        db.add(extraction_run)
        await db.flush()
        await sync_document_financial_state(
            db=db,
            document=document,
            extraction_run=extraction_run,
        )

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


def _build_extraction_run(
    *,
    document: Document,
    extracted_text: str,
    source_kind: str,
    status: str,
    confidence_score: float | None,
    review_reasons: list[str],
    raw_payload_json: dict,
) -> DocumentExtractionRun:
    return DocumentExtractionRun(
        user_id=document.user_id,
        document_id=document.id,
        extractor_family=_extractor_family(document),
        extractor_profile=_extractor_profile(document=document, extracted_text=extracted_text),
        extractor_version=EXTRACTION_VERSION,
        source_kind=source_kind,
        status=status,
        confidence_score=confidence_score,
        review_reasons=_unique_reasons(review_reasons),
        raw_payload_json=_json_ready(raw_payload_json),
    )


def _extractor_family(document: Document) -> str:
    if document.document_type in {"invoice", "statement", "credit_note", "receipt"}:
        return document.document_type
    return "document"


def _extractor_profile(*, document: Document, extracted_text: str) -> str:
    if document.document_type == "statement":
        return detect_statement_parser_family(supplier=document.supplier, text=extracted_text) or "generic_statement"
    return document.document_type or "document"


def _extraction_source_kind(document: Document) -> str:
    if document.ai_extraction_status == "completed" and document.ai_extraction_payload:
        if document.document_type == "statement":
            return "ai_primary"
        return "hybrid"
    return "rules"


async def _build_document_extraction_fields(
    *,
    document: Document,
    extracted_text: str,
) -> dict:
    ai_attempted = False
    if document.document_type == "statement" and should_attempt_ai_extraction(document=document, extraction_fields={}):
        ai_attempted = True
        try:
            ai_result = await extract_document_with_ai(
                document=document,
                extracted_text=extracted_text,
            )
        except Exception:
            document.ai_extraction_status = "failed"
        else:
            if ai_result is not None:
                seeded_fields = _build_statement_ai_primary_fields(
                    document=document,
                    extracted_text=extracted_text,
                    ai_result=ai_result,
                )
                return merge_ai_extraction(
                    document=document,
                    extraction_fields=seeded_fields,
                    ai_result=ai_result,
                )
            document.ai_extraction_status = "skipped"

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
    if not ai_attempted and should_attempt_ai_extraction(document=document, extraction_fields=extraction_fields):
        try:
            ai_result = await extract_document_with_ai(
                document=document,
                extracted_text=extracted_text,
            )
        except Exception:
            document.ai_extraction_status = "failed"
        else:
            if ai_result is not None:
                extraction_fields = merge_ai_extraction(
                    document=document,
                    extraction_fields=extraction_fields,
                    ai_result=ai_result,
                )
            else:
                document.ai_extraction_status = "skipped"
    return extraction_fields


def _build_statement_ai_primary_fields(
    *,
    document: Document,
    extracted_text: str,
    ai_result: AIDocumentExtractionResult,
) -> dict:
    return build_extraction_fields(
        extracted_text=extracted_text,
        supplier=document.supplier,
        document_type=document.document_type,
        subject=document.source_email_subject or "",
        attachment_name=document.attachment_name,
        existing_document_date=ai_result.document_date or document.document_date,
        existing_reference=ai_result.reference or document.reference,
        existing_amount=ai_result.amount if ai_result.amount is not None else document.amount,
        existing_vat_amount=ai_result.vat_amount if ai_result.vat_amount is not None else document.vat_amount,
        existing_currency=ai_result.currency or document.currency,
        existing_review_reasons=document.review_reasons,
        needs_review=document.needs_review,
        prefer_existing_values=True,
    )


def _build_run_payload(*, document: Document, extraction_fields: dict) -> dict:
    return {
        "document_snapshot": {
            "supplier": document.supplier,
            "document_type": document.document_type,
            "document_date": document.document_date,
            "reference": document.reference,
            "amount": document.amount,
            "vat_amount": document.vat_amount,
            "currency": document.currency,
            "confidence_score": document.confidence_score,
            "extraction_status": document.extraction_status,
            "needs_review": document.needs_review,
            "review_reasons": list(document.review_reasons or []),
        },
        "extraction_fields": extraction_fields,
        "ai_extraction": {
            "status": document.ai_extraction_status,
            "provider": document.ai_extraction_provider,
            "model": document.ai_extraction_model,
            "payload": document.ai_extraction_payload,
        },
    }


def _json_ready(value):
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _unique_reasons(reasons: list[str]) -> list[str]:
    seen: list[str] = []
    for reason in reasons:
        if reason and reason not in seen:
            seen.append(reason)
    return seen
